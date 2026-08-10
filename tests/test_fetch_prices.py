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


def test_paced_fetch_splits_nine_symbols_into_two_chunks_with_one_pause():
    """The exact scenario that failed live: 9 symbols against an 8/min cap."""
    symbols = [f"SYM{i}" for i in range(9)]

    with patch.object(fp_app, "fetch_quotes") as mock_fetch, patch.object(
        fp_app.time, "sleep"
    ) as mock_sleep:
        mock_fetch.side_effect = lambda batch: {s: {"close": 1.0} for s in batch}

        result = fp_app.fetch_quotes_paced(symbols)

    assert set(result.keys()) == set(symbols)
    assert mock_fetch.call_count == 2
    first_batch, second_batch = (c.args[0] for c in mock_fetch.call_args_list)
    assert len(first_batch) == 8
    assert len(second_batch) == 1
    # Exactly one pause -- between the two chunks, never after the last one.
    mock_sleep.assert_called_once_with(fp_app.BATCH_PAUSE_SECONDS)


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
