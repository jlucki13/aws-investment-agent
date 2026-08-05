"""DynamoDB access for the single-table portfolio model.

Table layout (pk / sk):

    Position   USER#<id>      POS#<ticker>       shares, costBasis, status
    Price bar  TICKER#<sym>   BAR#<yyyy-mm-dd>   close, prevClose, changePct, ttl
    Brief      USER#<id>      BRIEF#<yyyy-mm-dd> text, totalValue, dayChangePct
    Snapshot   USER#<id>      SNAP#<iso-ts>      s3Key, status, extractedJson

Positions and briefs share the user partition, so the dashboard loads with one
Query. Price bars partition by ticker and sort by date, which makes "last N bars
for NVDA" a single efficient range Query rather than a scan.
"""

import os
import time
from datetime import date, datetime, timezone
from typing import Any, Iterable

import boto3
from boto3.dynamodb.conditions import Key

from .money import to_decimal, to_float

_TABLE = None


def get_table():
    """Lazily create the table resource so imports stay cheap during cold start."""
    global _TABLE
    if _TABLE is None:
        _TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return _TABLE


class Keys:
    """Key construction in one place, so a typo is a test failure not a silent miss."""

    @staticmethod
    def user(user_id: str) -> str:
        return f"USER#{user_id}"

    @staticmethod
    def position(ticker: str) -> str:
        return f"POS#{ticker.upper()}"

    @staticmethod
    def ticker(symbol: str) -> str:
        return f"TICKER#{symbol.upper()}"

    @staticmethod
    def bar(day: date | str) -> str:
        d = day.isoformat() if isinstance(day, date) else day
        return f"BAR#{d}"

    @staticmethod
    def brief(day: date | str) -> str:
        d = day.isoformat() if isinstance(day, date) else day
        return f"BRIEF#{d}"

    @staticmethod
    def snapshot(ts: datetime | str) -> str:
        t = ts.isoformat() if isinstance(ts, datetime) else ts
        return f"SNAP#{t}"


# ----------------------------------------------------------------------
# Positions
# ----------------------------------------------------------------------


def read_positions(user_id: str, confirmed_only: bool = True) -> list[dict[str, Any]]:
    """All positions for a user.

    confirmed_only skips rows still awaiting human review after screenshot
    extraction -- unconfirmed numbers must never reach the analytics.
    """
    resp = get_table().query(
        KeyConditionExpression=Key("pk").eq(Keys.user(user_id))
        & Key("sk").begins_with("POS#")
    )
    items = [to_float(item) for item in resp.get("Items", [])]
    if confirmed_only:
        items = [i for i in items if i.get("status") == "CONFIRMED"]
    return items


def put_position(
    user_id: str,
    ticker: str,
    shares: float,
    cost_basis: float,
    status: str = "CONFIRMED",
) -> dict[str, Any]:
    item = to_decimal(
        {
            "pk": Keys.user(user_id),
            "sk": Keys.position(ticker),
            "ticker": ticker.upper(),
            "shares": shares,
            "costBasis": cost_basis,
            "status": status,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
    )
    get_table().put_item(Item=item)
    return to_float(item)


def delete_position(user_id: str, ticker: str) -> None:
    get_table().delete_item(
        Key={"pk": Keys.user(user_id), "sk": Keys.position(ticker)}
    )


# ----------------------------------------------------------------------
# Price history
# ----------------------------------------------------------------------


def put_price_bar(
    symbol: str,
    day: date | str,
    close: float,
    prev_close: float | None = None,
    ttl_days: int = 400,
) -> None:
    """Write one daily bar.

    The TTL keeps history bounded so storage stays inside the free 25 GB
    indefinitely. DynamoDB deletes expired items on its own schedule (usually
    within 48 hours) at no cost.
    """
    change_pct = None
    if prev_close:
        change_pct = (close - prev_close) / prev_close * 100

    item = to_decimal(
        {
            "pk": Keys.ticker(symbol),
            "sk": Keys.bar(day),
            "symbol": symbol.upper(),
            "date": day.isoformat() if isinstance(day, date) else day,
            "close": close,
            "prevClose": prev_close,
            "changePct": change_pct,
            "ttl": int(time.time()) + ttl_days * 86400,
        }
    )
    get_table().put_item(Item=item)


def query_price_history(symbol: str, limit: int = 30) -> list[dict[str, Any]]:
    """Most recent `limit` bars for a symbol, oldest first."""
    resp = get_table().query(
        KeyConditionExpression=Key("pk").eq(Keys.ticker(symbol))
        & Key("sk").begins_with("BAR#"),
        ScanIndexForward=False,  # newest first, so Limit takes the recent ones
        Limit=limit,
    )
    bars = [to_float(item) for item in resp.get("Items", [])]
    return list(reversed(bars))


def latest_close(symbol: str) -> dict[str, Any] | None:
    bars = query_price_history(symbol, limit=1)
    return bars[-1] if bars else None


# ----------------------------------------------------------------------
# Briefs
# ----------------------------------------------------------------------


def write_brief(user_id: str, day: date | str, brief: dict[str, Any]) -> None:
    item = to_decimal(
        {
            "pk": Keys.user(user_id),
            "sk": Keys.brief(day),
            "date": day.isoformat() if isinstance(day, date) else day,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            **brief,
        }
    )
    get_table().put_item(Item=item)


def read_briefs(user_id: str, limit: int = 30) -> list[dict[str, Any]]:
    resp = get_table().query(
        KeyConditionExpression=Key("pk").eq(Keys.user(user_id))
        & Key("sk").begins_with("BRIEF#"),
        ScanIndexForward=False,
        Limit=limit,
    )
    return [to_float(item) for item in resp.get("Items", [])]


def batch_put(items: Iterable[dict[str, Any]]) -> None:
    """Write many items efficiently. boto3 handles batching and retries."""
    table = get_table()
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=to_decimal(item))
