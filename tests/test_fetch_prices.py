"""Tests for Twelve Data batching/pacing.

Real incident: a live 9-ticker portfolio hit Twelve Data's free-tier limit of
8 API credits/minute on the very first fetch after crossing 8 holdings (a
batched /quote call costs one credit per symbol, confirmed from the actual
429 body). fetch_quotes_paced splits the symbol list into <=8-symbol chunks
and pauses ~61s between them; these tests cover the chunking and orchestration
without ever actually sleeping or hitting the network.
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


# ----------------------------------------------------------------------
# _chunk
# ----------------------------------------------------------------------


def test_chunk_splits_into_groups_of_size():
    assert fp_app._chunk(["A", "B", "C", "D", "E"], 2) == [
        ["A", "B"],
        ["C", "D"],
        ["E"],
    ]


def test_chunk_exact_multiple():
    assert fp_app._chunk(["A", "B", "C", "D"], 2) == [["A", "B"], ["C", "D"]]


def test_chunk_size_larger_than_list_returns_one_group():
    assert fp_app._chunk(["A", "B"], 8) == [["A", "B"]]


def test_chunk_empty_list():
    assert fp_app._chunk([], 8) == []


def test_chunk_rejects_non_positive_size():
    import pytest

    with pytest.raises(ValueError):
        fp_app._chunk(["A"], 0)


# ----------------------------------------------------------------------
# fetch_quotes_paced
# ----------------------------------------------------------------------


def test_paced_fetch_splits_nine_symbols_with_a_pause_between_chunks():
    """The exact scenario that failed live: a 9-symbol portfolio against
    Twelve Data's Basic 8 plan. Derives expected chunk sizes from BATCH_SIZE
    rather than hardcoding them, since that constant is deliberately kept
    below the plan's 8/minute ceiling for margin and may be retuned."""
    symbols = [f"SYM{i}" for i in range(9)]

    with patch.object(fp_app, "fetch_quotes") as mock_fetch, patch.object(
        fp_app.time, "sleep"
    ) as mock_sleep:
        mock_fetch.side_effect = lambda batch: {s: {"close": 1.0} for s in batch}

        result = fp_app.fetch_quotes_paced(symbols)

    assert set(result.keys()) == set(symbols)

    expected_batches = fp_app._chunk(symbols, fp_app.BATCH_SIZE)
    assert mock_fetch.call_count == len(expected_batches)
    actual_batches = [c.args[0] for c in mock_fetch.call_args_list]
    assert actual_batches == expected_batches

    # One pause between each pair of chunks, never a trailing one after the last.
    assert mock_sleep.call_count == len(expected_batches) - 1
    assert all(
        call.args == (fp_app.BATCH_PAUSE_SECONDS,)
        for call in mock_sleep.call_args_list
    )

    # BATCH_SIZE must stay strictly under Twelve Data's confirmed 8/minute
    # plan ceiling -- sitting exactly on it left zero margin and failed live.
    assert fp_app.BATCH_SIZE < 8


def test_paced_fetch_under_the_limit_never_pauses():
    symbols = ["AAPL", "MSFT"]

    with patch.object(fp_app, "fetch_quotes") as mock_fetch, patch.object(
        fp_app.time, "sleep"
    ) as mock_sleep:
        mock_fetch.side_effect = lambda batch: {s: {"close": 1.0} for s in batch}

        result = fp_app.fetch_quotes_paced(symbols)

    assert set(result.keys()) == {"AAPL", "MSFT"}
    mock_fetch.assert_called_once_with(symbols)
    mock_sleep.assert_not_called()
