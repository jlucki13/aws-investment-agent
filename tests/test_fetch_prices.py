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
wall. fetch_quotes_paced now fetches one symbol per request, paced, which is
the only shape that's actually been proven to work.
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
