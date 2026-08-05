"""Compute the day's portfolio facts, narrate them, store and email the brief.

Second step of the daily pipeline. Reads from DynamoDB rather than taking the
fetch step's output as input, so it can be invoked on its own:

    sam remote invoke AnalyzeFunction --stack-name portfolio-monitor
"""

import logging
import os
from datetime import datetime, timezone

import boto3

import brief as narrator
from portfolio_common import analytics, db

log = logging.getLogger()
log.setLevel(logging.INFO)

USER_ID = os.environ["USER_ID"]
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "").strip()
HISTORY_BARS = 31  # 30 prior bars plus today, for the z-score baseline


def _load_market_data(tickers: list[str]):
    """Latest quote and recent history per ticker.

    One Query per ticker. At portfolio scale that's ~20 round trips of a few ms
    each -- not worth the complexity of BatchGetItem, which can't do range
    queries anyway.
    """
    quotes, history = {}, {}

    for ticker in tickers:
        bars = db.query_price_history(ticker, limit=HISTORY_BARS)
        if not bars:
            log.warning("no price history for %s", ticker)
            continue
        history[ticker] = bars
        latest = bars[-1]
        quotes[ticker] = {
            "close": latest.get("close"),
            "prevClose": latest.get("prevClose"),
            "date": latest.get("date"),
        }

    return quotes, history


def _previous_weights() -> dict[str, float]:
    """Weights from the last brief, for drift comparison.

    Stored on each brief rather than recomputed, so drift is measured against
    what was actually reported last time.
    """
    briefs = db.read_briefs(USER_ID, limit=1)
    if not briefs:
        return {}
    return {
        w["ticker"]: float(w["weight_pct"])
        for w in briefs[0].get("weights", [])
    }


def _send_email(subject: str, body: str) -> None:
    if not ALERT_EMAIL:
        log.info("ALERT_EMAIL unset - skipping email")
        return
    try:
        boto3.client("ses").send_email(
            Source=ALERT_EMAIL,  # self-send: one verified identity covers both ends
            Destination={"ToAddresses": [ALERT_EMAIL]},
            Message={
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": body}},
            },
        )
        log.info("brief emailed to %s", ALERT_EMAIL)
    except Exception:
        # The brief is already in DynamoDB; a mail failure isn't worth failing on.
        log.exception("SES send failed")


def handler(_event, _context):
    positions = db.read_positions(USER_ID, confirmed_only=True)
    if not positions:
        log.info("no confirmed positions")
        return {"status": "no_positions"}

    tickers = sorted({str(p["ticker"]).upper() for p in positions})
    quotes, history = _load_market_data(tickers)

    if not quotes:
        log.error("no market data for any holding - has fetch_prices run?")
        return {"status": "no_market_data", "tickers": tickers}

    as_of = max(
        (q.get("date") for q in quotes.values() if q.get("date")),
        default=datetime.now(timezone.utc).date().isoformat(),
    )

    facts = analytics.build_facts(
        as_of=as_of,
        positions=positions,
        quotes=quotes,
        history=history,
        previous_weights=_previous_weights(),
    )

    if facts.missing_quotes:
        log.warning("no quote for: %s", facts.missing_quotes)

    # Short-circuit quiet days rather than asking the model to be restrained
    # about them. A skipped call can't invent significance; a prompt instruction
    # only usually prevents it. Also saves the inference cost.
    if analytics.is_quiet_day(facts):
        text = (
            f"Quiet day. Portfolio at ${facts.total_value:,.2f}, "
            f"{facts.day_change_pct:+.2f}%. Nothing notable."
        )
        log.info("quiet day - skipped Bedrock")
    else:
        text = narrator.generate(facts.to_dict())

    weights = [
        {"ticker": p.ticker, "weight_pct": round(p.weight_pct, 4)}
        for p in facts.positions
    ]

    db.write_brief(
        USER_ID,
        as_of,
        {
            "text": text,
            "totalValue": facts.total_value,
            "dayChangePct": facts.day_change_pct,
            "dayChangeValue": facts.day_change_value,
            "unrealizedPct": facts.unrealized_pct,
            "positionCount": facts.position_count,
            "effectiveHoldings": round(facts.concentration.effective_holdings, 2),
            "weights": weights,
            "missingQuotes": facts.missing_quotes,
        },
    )

    subject = (
        f"Portfolio {facts.day_change_pct:+.2f}% - ${facts.total_value:,.0f}"
    )
    _send_email(subject, text)

    return {
        "status": "ok",
        "as_of": as_of,
        "totalValue": facts.total_value,
        "dayChangePct": facts.day_change_pct,
        "brief": text,
    }
