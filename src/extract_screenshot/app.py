"""Bedrock vision extraction of holdings from a brokerage screenshot.

Triggered by S3 ObjectCreated under uploads/. Every path through this handler
ends with the snapshot landing in PENDING_REVIEW or EXTRACTION_FAILED -- never
stuck at PENDING_EXTRACTION -- because the browser is polling for one of those
two terminal states.

Nothing this Lambda writes is trusted on its own: extraction only ever
produces PENDING_REVIEW rows, and the API layer requires a human to confirm
them before they become real positions. See snapshots.py and the
CONFIRMED/PENDING_REVIEW split in db.py.
"""

import logging
import os
import urllib.parse

import boto3

from portfolio_common import db, snapshots

log = logging.getLogger()
log.setLevel(logging.INFO)

MODEL_ID = os.environ["BEDROCK_MODEL_ID"]
MAX_TOKENS = 1500

# Bedrock's image content block wants its own format name, not a file extension.
_FORMAT_BY_EXT = {"png": "png", "jpg": "jpeg", "jpeg": "jpeg"}

SYSTEM_PROMPT = """\
You read a screenshot of a brokerage holdings screen and extract each position
into structured data.

Output ONLY a JSON array, no prose, no markdown code fences. Each element:

    {"ticker": str, "shares": number, "costBasis": number|null, "confidence": "high"|"medium"|"low"}

Rules:
1. ticker is the exchange ticker symbol only, uppercase -- never the company
   name. A row showing "Apple Inc AAPL" extracts as "AAPL", not "Apple Inc".
2. costBasis is the per-share AVERAGE COST -- a field the screenshot must
   itself label as cost, avg cost, cost basis, or similar. It is a different
   number from the current share price and from the position's market value.
   Many brokerage "positions"/"holdings" views show price and market value
   but never show cost basis at all (that often lives on a separate
   "gain/loss" or "performance" screen). If no field is specifically labeled
   as cost/average cost, set costBasis to null. Do NOT substitute the current
   price, the market value, or any other visible number as a guess -- a wrong
   cost basis silently corrupts every profit/loss calculation downstream,
   which is worse than leaving it blank for a human to fill in.
3. ticker and shares are required; omit the row entirely if either is
   illegible. costBasis may legitimately be null per rule 2 -- that alone is
   never a reason to omit the row.
4. confidence reflects how legible the row was in the image, not how sure you
   are that it represents a real holding.
"""

_s3 = None
_bedrock = None


def _s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def _bedrock_client():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client("bedrock-runtime")
    return _bedrock


def _image_format(key: str) -> str:
    ext = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    fmt = _FORMAT_BY_EXT.get(ext)
    if fmt is None:
        raise ValueError(f"unsupported image type: {ext!r} (png/jpeg only)")
    return fmt


def _extract(bucket: str, key: str) -> list[dict]:
    image_format = _image_format(key)
    obj = _s3_client().get_object(Bucket=bucket, Key=key)
    image_bytes = obj["Body"].read()

    resp = _bedrock_client().converse(
        modelId=MODEL_ID,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "image": {
                            "format": image_format,
                            "source": {"bytes": image_bytes},
                        }
                    },
                    {"text": "Extract the holdings from this screenshot."},
                ],
            }
        ],
        inferenceConfig={
            "maxTokens": MAX_TOKENS,
            # Zero: this is transcription, not composition.
            "temperature": 0.0,
        },
    )

    usage = resp.get("usage", {})
    log.info(
        "bedrock tokens in=%s out=%s",
        usage.get("inputTokens"),
        usage.get("outputTokens"),
    )

    raw_text = resp["output"]["message"]["content"][0]["text"]
    return snapshots.parse_extraction_response(raw_text)


def _handle_record(record: dict) -> None:
    bucket = record["s3"]["bucket"]["name"]
    # S3 event keys are URL-encoded, and a literal '+' round-trips as a space.
    key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])

    try:
        user_id, snapshot_id = snapshots.parse_upload_key(key)
    except ValueError:
        # No snapshot to attribute this to -- nothing we can update.
        log.exception("could not parse upload key %r", key)
        return

    try:
        db.update_snapshot(user_id, snapshot_id, status="PENDING_EXTRACTION")
        positions = _extract(bucket, key)

        if not positions:
            db.update_snapshot(
                user_id,
                snapshot_id,
                status="EXTRACTION_FAILED",
                error="model returned no readable positions",
            )
            return

        db.update_snapshot(
            user_id,
            snapshot_id,
            status="PENDING_REVIEW",
            extractedPositions=positions,
        )
    except Exception as exc:
        log.exception("extraction failed for %s", key)
        db.update_snapshot(
            user_id, snapshot_id, status="EXTRACTION_FAILED", error=str(exc)
        )


def handler(event, _context):
    for record in event.get("Records", []):
        _handle_record(record)
