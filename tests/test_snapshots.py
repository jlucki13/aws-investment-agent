"""Tests for screenshot key handling and Bedrock response parsing.

parse_extraction_response is the one piece of this module handling
model-authored text, so it gets the most coverage: fenced output, mixed
good/bad rows, and outright garbage all have to resolve to *something* sane
rather than raising, since one malformed extraction shouldn't take down the
whole upload flow.
"""

import pytest

from portfolio_common import snapshots


# ----------------------------------------------------------------------
# build_upload_key / parse_upload_key
# ----------------------------------------------------------------------


def test_build_upload_key_shape():
    key = snapshots.build_upload_key("me", "abc123", "holdings.png")
    assert key == "uploads/me/abc123/holdings.png"


def test_build_upload_key_strips_path_separators():
    key = snapshots.build_upload_key("me", "abc123", "../../etc/passwd")
    assert key == "uploads/me/abc123/passwd"

    key = snapshots.build_upload_key("me", "abc123", "C:\\Users\\me\\shot.jpg")
    assert key == "uploads/me/abc123/shot.jpg"


def test_build_upload_key_falls_back_on_empty_filename():
    key = snapshots.build_upload_key("me", "abc123", "   ")
    assert key == "uploads/me/abc123/screenshot"


def test_parse_upload_key_round_trips():
    key = snapshots.build_upload_key("me", "abc123", "holdings.png")
    user_id, snapshot_id = snapshots.parse_upload_key(key)
    assert user_id == "me"
    assert snapshot_id == "abc123"


def test_parse_upload_key_rejects_wrong_shape():
    with pytest.raises(ValueError):
        snapshots.parse_upload_key("not/an/upload/key")
    with pytest.raises(ValueError):
        snapshots.parse_upload_key("uploads/only-user-id")


# ----------------------------------------------------------------------
# parse_extraction_response
# ----------------------------------------------------------------------


def test_parse_extraction_response_normal_case():
    raw = """[
        {"ticker": "AAPL", "shares": 10, "costBasis": 150.5, "confidence": "high"},
        {"ticker": "msft", "shares": 5.5, "costBasis": 300, "confidence": "medium"}
    ]"""
    rows = snapshots.parse_extraction_response(raw)
    assert rows == [
        {"ticker": "AAPL", "shares": 10, "costBasis": 150.5, "confidence": "high"},
        {"ticker": "MSFT", "shares": 5.5, "costBasis": 300, "confidence": "medium"},
    ]


def test_parse_extraction_response_strips_markdown_fences():
    raw = '```json\n[{"ticker": "NVDA", "shares": 2, "costBasis": 900, "confidence": "low"}]\n```'
    rows = snapshots.parse_extraction_response(raw)
    assert rows == [
        {"ticker": "NVDA", "shares": 2, "costBasis": 900, "confidence": "low"}
    ]


def test_parse_extraction_response_bare_fence_no_language_tag():
    raw = '```\n[{"ticker": "TSLA", "shares": 1, "costBasis": 200}]\n```'
    rows = snapshots.parse_extraction_response(raw)
    assert rows[0]["ticker"] == "TSLA"
    # confidence defaults when missing
    assert rows[0]["confidence"] == "medium"


def test_parse_extraction_response_drops_bad_entries_keeps_good():
    raw = """[
        {"ticker": "AAPL", "shares": 10, "costBasis": 150.5, "confidence": "high"},
        {"ticker": "", "shares": 10, "costBasis": 150.5},
        {"ticker": "BAD_SHARES", "shares": "not a number", "costBasis": 10},
        {"ticker": "BAD_COST", "shares": 10, "costBasis": null},
        "not even an object",
        {"ticker": "GOOD2", "shares": 3, "costBasis": 20, "confidence": "bogus"}
    ]"""
    rows = snapshots.parse_extraction_response(raw)
    tickers = [r["ticker"] for r in rows]
    assert tickers == ["AAPL", "GOOD2"]
    # invalid confidence value falls back to medium rather than being dropped
    assert rows[1]["confidence"] == "medium"


def test_parse_extraction_response_garbage_input_returns_empty():
    assert snapshots.parse_extraction_response("not json at all") == []
    assert snapshots.parse_extraction_response("") == []
    assert snapshots.parse_extraction_response("{}") == []  # object, not array
    assert snapshots.parse_extraction_response('{"ticker": "AAPL"}') == []


def test_parse_extraction_response_coerces_numeric_strings():
    raw = '[{"ticker": "AAPL", "shares": "10", "costBasis": "150.5", "confidence": "high"}]'
    rows = snapshots.parse_extraction_response(raw)
    assert rows[0]["shares"] == 10.0
    assert rows[0]["costBasis"] == 150.5
