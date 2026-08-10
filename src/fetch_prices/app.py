"""Pull daily closes from Twelve Data into the price history.

Runs first in the daily Step Functions pipeline. Writes bars to DynamoDB and
returns a summary; the analyze step reads from DynamoDB rather than taking the
quotes as input, so each function can be invoked and debugged on its own:

    sam remote invoke FetchPricesFunction --stack-name portfolio-monitor
"""

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import boto3

from portfolio_common import db

log = logging.getLogger()
log.setLevel(logging.INFO)

USER_ID = os.environ["USER_ID"]
PARAM_NAME = os.environ["TWELVEDATA_PARAM_NAME"]
TTL_DAYS = int(os.environ.get("PRICE_TTL_DAYS", "400"))

QUOTE_URL = "https://api.twelvedata.com/quote"
TIMEOUT_SECONDS = 20

# Twelve Data's free tier caps at 8 API credits/minute, and a batched /quote
# call costs one credit per symbol -- confirmed directly from a live 429:
# "9 API credits were used, with the current limit being 8." A portfolio
# bigger than this must be split across multiple one-minute windows. This
# runs once a day on a schedule, so the added latency costs nothing real.
BATCH_SIZE = int(os.environ.get("TWELVEDATA_BATCH_SIZE", "8"))
BATCH_PAUSE_SECONDS = 61

_api_key: str | None = None


def get_api_key() -> str:
    """Read the key from Parameter Store once per container.

    Cached at module scope so a warm Lambda doesn't re-hit SSM on every run --
    Parameter Store is free but rate-limited, and the value never changes
    mid-execution.
    """
    global _api_key
    if _api_key is None:
        ssm = boto3.client("ssm")
        resp = ssm.get_parameter(Name=PARAM_NAME, WithDecryption=True)
        _api_key = resp["Parameter"]["Value"]
    return _api_key


def fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    """One batched call for the whole portfolio.

    Twelve Data returns a bare object for a single symbol and a symbol-keyed map
    for several, which is an easy thing to get caught by when your portfolio
    happens to drop to one holding.
    """
    if not symbols:
        return {}

    params = urllib.parse.urlencode(
        {"symbol": ",".join(symbols), "apikey": get_api_key()}
    )
    url = f"{QUOTE_URL}?{params}"

    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Twelve Data HTTP {exc.code}: {exc.read()[:200]!r}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Twelve Data unreachable: {exc.reason}") from exc

    # A rate-limit or bad-key response is a 200 with an error body.
    if isinstance(payload, dict) and payload.get("status") == "error":
        raise RuntimeError(
            f"Twelve Data error {payload.get('code')}: {payload.get('message')}"
        )

    if len(symbols) == 1:
        payload = {symbols[0]: payload}

    return payload


def _chunk(items: list[str], size: int) -> list[list[str]]:
    """Split into groups of at most `size`, preserving order. Pure -- no I/O."""
    if size <= 0:
        raise ValueError("size must be positive")
    return [items[i : i + size] for i in range(0, len(items), size)]


def fetch_quotes_paced(symbols: list[str]) -> dict[str, dict]:
    """fetch_quotes across as many one-minute windows as the symbol count needs."""
    batches = _chunk(symbols, BATCH_SIZE)
    quotes: dict[str, dict] = {}

    for i, batch in enumerate(batches):
        quotes.update(fetch_quotes(batch))
        is_last = i == len(batches) - 1
        if not is_last:
            log.info(
                "fetched %d/%d symbols; pausing %ds for Twelve Data's per-minute limit",
                (i + 1) * BATCH_SIZE,
                len(symbols),
                BATCH_PAUSE_SECONDS,
            )
            time.sleep(BATCH_PAUSE_SECONDS)

    return quotes


def _to_float(value) -> float | None:
    if value in (None, "", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def handler(_event, _context):
    positions = db.read_positions(USER_ID, confirmed_only=True)
    symbols = sorted({str(p["ticker"]).upper() for p in positions})

    if not symbols:
        log.info("no confirmed positions - nothing to fetch")
        return {"fetched": 0, "symbols": [], "errors": []}

    log.info("fetching quotes for %d symbols: %s", len(symbols), symbols)
    quotes = fetch_quotes_paced(symbols)

    written, errors = 0, []

    for symbol in symbols:
        quote = quotes.get(symbol)

        if not isinstance(quote, dict) or quote.get("status") == "error":
            msg = (quote or {}).get("message", "no quote returned")
            log.warning("no usable quote for %s: %s", symbol, msg)
            errors.append({"symbol": symbol, "error": msg})
            continue

        close = _to_float(quote.get("close"))
        prev_close = _to_float(quote.get("previous_close"))

        if close is None:
            log.warning("quote for %s had no close price", symbol)
            errors.append({"symbol": symbol, "error": "missing close"})
            continue

        # Prefer the exchange's own bar date over "today" -- they differ on
        # holidays and around the date line.
        bar_date = (quote.get("datetime") or "")[:10]
        if not bar_date:
            bar_date = datetime.now(timezone.utc).date().isoformat()

        db.put_price_bar(
            symbol=symbol,
            day=bar_date,
            close=close,
            prev_close=prev_close,
            ttl_days=TTL_DAYS,
        )
        written += 1

    log.info("wrote %d bars, %d errors", written, len(errors))

    # Surface partial failure without failing the run -- one dead ticker
    # shouldn't cost you the whole brief. The analyze step reports missing
    # quotes explicitly.
    return {"fetched": written, "symbols": symbols, "errors": errors}
