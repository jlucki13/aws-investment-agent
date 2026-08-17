"""Tests for Twelve Data request pacing.

Real incident, in order: a live 9-ticker portfolio hit a 429 on Twelve
Data's "Basic 8" free plan (8 API credits/minute). The first fix batched
symbols into <=8-per-call chunks, assuming 1 credit/symbol as documented --
still failed. A second fix lowered the batch size to 5 for margin -- still
failed, with the exact same "9 credits used" message. Logging the literal
outgoing URL proved the request genuinely contained only 5 symbols, and a
single-symbol call made directly against the API (outside this Lambda)
succeeded cleanly. Conclusion: the batched /quote endpoint doesn't cost what
its docs say on this plan -- any batch size above 1 hits roughly the same
wall. fetch_quotes_paced fetches one symbol per request, paced.

Even that wasn't fully reliable: a live run with symbols spaced 12s apart
had its first four single-symbol calls succeed and its fifth get a 429 --
not obviously explained by the documented 8-credits/minute figure either.
Rather than continue guessing a pace that's "safe," fetch_quotes_paced now
catches a 429 and retries just that symbol after a long recovery pause,
bounded by MAX_RETRIES across the whole run.
"""

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "layers" / "common" / "python"))

os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "test-user")
os.environ.setdefault("TWELVEDATA_PARAM_NAME", "/test/param")

_spec = importlib.util.spec_from_file_location(
    "_test_fetch_prices_app", ROOT / "src" / "fetch_prices" / "app.py"
)
fp_app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fp_app)


def test_paced_fetch_calls_once_per_symbol_never_batched():
    """The core guarantee this module now exists to provide: fetch_quotes is
    never called with more than one symbol at a time."""
    symbols = ["GOOG", "JPM", "META", "MSFT", "NFLX", "SBUX", "TCEHY", "V", "WMT"]

    with patch.object(fp_app, "fetch_quotes") as mock_fetch, patch.object(
        fp_app.time, "sleep"
    ) as mock_sleep:
        mock_fetch.side_effect = lambda batch: {s: {"close": 1.0} for s in batch}

        result = fp_app.fetch_quotes_paced(symbols)

    assert set(result.keys()) == set(symbols)

    actual_calls = [c.args[0] for c in mock_fetch.call_args_list]
    assert actual_calls == [[s] for s in symbols]  # one symbol per call, in order


def test_paced_fetch_pauses_between_every_call_but_not_after_the_last():
    symbols = ["AAPL", "MSFT", "GOOG"]

    with patch.object(fp_app, "fetch_quotes") as mock_fetch, patch.object(
        fp_app.time, "sleep"
    ) as mock_sleep:
        mock_fetch.side_effect = lambda batch: {s: {"close": 1.0} for s in batch}

        fp_app.fetch_quotes_paced(symbols)

    assert mock_sleep.call_count == len(symbols) - 1
    assert all(
        call.args == (fp_app.REQUEST_PAUSE_SECONDS,)
        for call in mock_sleep.call_args_list
    )


def test_paced_fetch_single_symbol_never_pauses():
    with patch.object(fp_app, "fetch_quotes") as mock_fetch, patch.object(
        fp_app.time, "sleep"
    ) as mock_sleep:
        mock_fetch.side_effect = lambda batch: {s: {"close": 1.0} for s in batch}

        result = fp_app.fetch_quotes_paced(["AAPL"])

    assert result == {"AAPL": {"close": 1.0}}
    mock_fetch.assert_called_once_with(["AAPL"])
    mock_sleep.assert_not_called()


def test_paced_fetch_empty_list_does_nothing():
    with patch.object(fp_app, "fetch_quotes") as mock_fetch, patch.object(
        fp_app.time, "sleep"
    ) as mock_sleep:
        result = fp_app.fetch_quotes_paced([])

    assert result == {}
    mock_fetch.assert_not_called()
    mock_sleep.assert_not_called()


def test_request_pause_leaves_real_margin_under_the_confirmed_plan_ceiling():
    """At most 8 credits/minute is the confirmed real ceiling (account
    dashboard: "Basic 8"). A pause this short would allow >=8 single-symbol
    requests inside some rolling minute, sitting on the same fragile boundary
    that failed live twice already."""
    max_requests_per_minute = 60 / fp_app.REQUEST_PAUSE_SECONDS
    assert max_requests_per_minute < 8


# ----------------------------------------------------------------------
# 429 recovery
# ----------------------------------------------------------------------


def test_429_on_one_symbol_retries_and_recovers():
    """The exact live scenario: a mid-run 429 on symbol 3 of 5. It must
    retry only that symbol (not restart from the beginning, not skip it)
    and continue once it succeeds."""
    calls = []

    def flaky_fetch(batch):
        calls.append(batch[0])
        if batch[0] == "C" and calls.count("C") == 1:
            raise RuntimeError("Twelve Data HTTP 429: rate limited")
        return {batch[0]: {"close": 1.0}}

    with patch.object(
        fp_app, "fetch_quotes", side_effect=flaky_fetch
    ), patch.object(fp_app.time, "sleep") as mock_sleep:
        result = fp_app.fetch_quotes_paced(["A", "B", "C", "D", "E"])

    assert set(result.keys()) == {"A", "B", "C", "D", "E"}
    # C was attempted twice: the failure, then the successful retry.
    assert calls.count("C") == 2
    assert calls == ["A", "B", "C", "C", "D", "E"]
    # One recovery pause (RETRY_WAIT_SECONDS) plus the normal per-request
    # pauses in between every other pair of symbols.
    recovery_pauses = [
        c for c in mock_sleep.call_args_list if c.args == (fp_app.RETRY_WAIT_SECONDS,)
    ]
    assert len(recovery_pauses) == 1


def test_429_exhausting_retries_propagates():
    """A 429 that never clears must eventually raise, not retry forever --
    a persistently bad key or a real outage shouldn't hang the function
    until its timeout."""
    with patch.object(
        fp_app, "fetch_quotes", side_effect=RuntimeError("Twelve Data HTTP 429: x")
    ), patch.object(fp_app.time, "sleep"):
        import pytest

        with pytest.raises(RuntimeError, match="429"):
            fp_app.fetch_quotes_paced(["A"])


def test_non_429_error_is_not_retried():
    """A different failure (bad symbol, network error, etc.) must propagate
    immediately -- retrying is specifically a rate-limit recovery, not a
    general-purpose retry-everything policy."""
    with patch.object(
        fp_app, "fetch_quotes", side_effect=RuntimeError("Twelve Data unreachable: timeout")
    ), patch.object(fp_app.time, "sleep") as mock_sleep:
        import pytest

        with pytest.raises(RuntimeError, match="unreachable"):
            fp_app.fetch_quotes_paced(["A"])

    mock_sleep.assert_not_called()
