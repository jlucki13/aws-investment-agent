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

# Twelve Data's "Basic 8" free plan (confirmed on the account dashboard) caps
# at 8 API credits/minute. It does NOT cost 1 credit/symbol for a batched
# /quote call the way the docs suggested -- proven live: a genuine 5-symbol
# batch (confirmed via logging the literal outgoing URL) was still rejected
# as "9 credits used, limit 8," identical to what a 9-symbol batch produced,
# while a single-symbol call succeeded cleanly outside this Lambda entirely.
# That pattern -- any batch size >1 hitting roughly the same wall, one
# symbol going through fine -- means the batched endpoint's real credit cost
# on this plan doesn't scale the way it's documented. Fetching one symbol
# per request, paced, is what's actually been proven to work.
#
# 12s between requests allows at most 5 requests/minute at exact intervals,
# ~6 in the worst-case window alignment -- real margin under the 8/minute
# ceiling rather than the 7.5/minute a bare-minimum 8s pause would allow,
# which would again sit close enough to the limit to risk the same fragile
# boundary problem this whole fix exists to get away from.
REQUEST_PAUSE_SECONDS = int(os.environ.get("TWELVEDATA_REQUEST_PAUSE_SECONDS", "12"))

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
    """One /quote call. fetch_quotes_paced always passes a single symbol (see
    its docstring for why), but this itself still accepts a list and handles
    both response shapes: Twelve Data returns a bare object for one symbol
    and a symbol-keyed map for several.
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


RETRY_WAIT_SECONDS = int(os.environ.get("TWELVEDATA_RETRY_WAIT_SECONDS", "65"))
MAX_RETRIES = int(os.environ.get("TWELVEDATA_MAX_RETRIES", "2"))


def fetch_quotes_paced(symbols: list[str]) -> dict[str, dict]:
    """One symbol per request, paced -- see the comment above REQUEST_PAUSE_SECONDS
    for why batching isn't used here. Even lone single-symbol requests have still
    hit a 429 partway through a run in practice, for reasons this project hasn't
    been able to fully pin down against Twelve Data's real throttling behavior
    (four single-symbol calls, each 12s apart, succeeded before a fifth was
    rejected -- not obviously explained by the documented 8-credits/minute
    figure). Rather than continuing to guess a "safe" pace, a 429 here triggers
    a long recovery pause and a retry of just that one symbol, bounded by
    MAX_RETRIES across the whole run (not per-symbol) so a persistently bad
    connection can't run the function past its timeout.
    """
    quotes: dict[str, dict] = {}
    retries_used = 0

    i = 0
    while i < len(symbols):
        symbol = symbols[i]
        try:
            quotes.update(fetch_quotes([symbol]))
        except RuntimeError as exc:
            if "429" in str(exc) and retries_used < MAX_RETRIES:
                retries_used += 1
                log.warning(
                    "rate limited on %s (recovery %d/%d) -- pausing %ds before retry",
                    symbol,
                    retries_used,
                    MAX_RETRIES,
                    RETRY_WAIT_SECONDS,
                )
                time.sleep(RETRY_WAIT_SECONDS)
                continue  # retry the same symbol; don't advance
            raise

        i += 1
        if i < len(symbols):
            time.sleep(REQUEST_PAUSE_SECONDS)

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
