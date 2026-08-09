"""Screenshot -> position extraction: key layout and Bedrock response parsing.

Pure Python, no boto3 -- the S3 key helpers are used by both the API (to build
the upload key) and the extraction Lambda (to parse it back out of the S3
event, without a DynamoDB lookup), and the response parser needs to be
unit-testable against arbitrary Bedrock output without mocking anything.

Vision extraction is a guess, not a fact. Nothing this module produces is
trusted until a human confirms it -- see the CONFIRMED/PENDING_REVIEW split in
db.py. Malformed rows are dropped rather than raised, on the same reasoning
`value_positions` in analytics.py surfaces missing quotes instead of failing
outright: one bad row from the model shouldn't cost you the rest of the read.
"""

from __future__ import annotations

import json
import re
from typing import Any

_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)

_VALID_CONFIDENCE = {"high", "medium", "low"}


def build_upload_key(user_id: str, snapshot_id: str, filename: str) -> str:
    """uploads/<user_id>/<snapshot_id>/<sanitized filename>

    The uploads/ prefix is also what the S3 event source filters on, so
    changing it here means changing template.yaml too.
    """
    safe_name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not safe_name:
        safe_name = "screenshot"
    return f"uploads/{user_id}/{snapshot_id}/{safe_name}"


def parse_upload_key(key: str) -> tuple[str, str]:
    """Inverse of build_upload_key -- how the S3-triggered Lambda finds its item."""
    parts = key.split("/")
    if len(parts) < 4 or parts[0] != "uploads":
        raise ValueError(f"not an upload key: {key!r}")
    return parts[1], parts[2]


def parse_extraction_response(raw_text: str) -> list[dict[str, Any]]:
    """Bedrock's raw text -> validated {ticker, shares, costBasis, confidence} rows.

    Returns [] if the response isn't parseable at all, which the caller treats
    as EXTRACTION_FAILED. A single bad entry inside an otherwise good array is
    dropped rather than failing the whole extraction.
    """
    stripped = _CODE_FENCE.sub("", raw_text.strip()).strip()

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return []

    if not isinstance(parsed, list):
        return []

    rows: list[dict[str, Any]] = []
    for entry in parsed:
        row = _validate_row(entry)
        if row is not None:
            rows.append(row)
    return rows


def _validate_row(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None

    ticker = entry.get("ticker")
    if not isinstance(ticker, str) or not ticker.strip():
        return None

    shares = _coerce_number(entry.get("shares"))
    if shares is None:
        return None

    # costBasis is allowed to be missing/null -- the model is instructed to
    # report null rather than substitute price or market value when a
    # screenshot's holdings view doesn't show average cost at all (it often
    # lives on a separate tab). The review screen renders that as a blank
    # field for the user to fill in, instead of silently carrying a
    # plausible-looking but wrong number into the portfolio.
    cost_basis = _coerce_number(entry.get("costBasis"))

    confidence = entry.get("confidence")
    if confidence not in _VALID_CONFIDENCE:
        confidence = "medium"

    return {
        "ticker": ticker.strip().upper(),
        "shares": shares,
        "costBasis": cost_basis,
        "confidence": confidence,
    }


def _coerce_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
