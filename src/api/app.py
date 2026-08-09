"""Positions CRUD and brief retrieval.

Deliberately framework-free -- no FastAPI, no Flask. At five routes a dict-based
router is less code than the framework's boilerplate, and it keeps the deployment
package to zero dependencies, which means fast cold starts and nothing to patch.
"""

import json
import os
import re
import uuid
from decimal import Decimal
from typing import Any, Callable

import boto3

from portfolio_common import db, snapshots

USER_ID = os.environ["USER_ID"]
SCREENSHOT_BUCKET_NAME = os.environ["SCREENSHOT_BUCKET_NAME"]
PRESIGNED_URL_TTL_SECONDS = 300

_UPLOAD_CONTENT_TYPES = {"image/png", "image/jpeg"}

_s3 = None


def _s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _json_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"not JSON serializable: {type(obj)}")


def respond(status: int, body: Any) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, default=_json_default),
    }


# ----------------------------------------------------------------------
# Handlers
# ----------------------------------------------------------------------


def list_positions(_event, _params) -> Any:
    # Include unconfirmed rows here so the review UI can see what's pending.
    return {"positions": db.read_positions(USER_ID, confirmed_only=False)}


def _validate_position_numbers(shares: float, cost_basis: float) -> None:
    if shares <= 0:
        raise HttpError(400, "shares must be greater than zero")
    if cost_basis < 0:
        raise HttpError(400, "costBasis cannot be negative")


def upsert_position(event, params) -> Any:
    ticker = params["ticker"].upper()
    body = _parse_body(event)

    shares = _require_number(body, "shares")
    cost_basis = _require_number(body, "costBasis")
    _validate_position_numbers(shares, cost_basis)

    status = body.get("status", "CONFIRMED")
    if status not in ("CONFIRMED", "PENDING_REVIEW"):
        raise HttpError(400, "status must be CONFIRMED or PENDING_REVIEW")

    return db.put_position(USER_ID, ticker, shares, cost_basis, status)


def delete_position(_event, params) -> Any:
    db.delete_position(USER_ID, params["ticker"].upper())
    return {"deleted": params["ticker"].upper()}


def list_briefs(_event, _params) -> Any:
    return {"briefs": db.read_briefs(USER_ID, limit=30)}


def latest_brief(_event, _params) -> Any:
    briefs = db.read_briefs(USER_ID, limit=1)
    if not briefs:
        raise HttpError(404, "no briefs yet - the daily job may not have run")
    return briefs[0]


def request_upload_url(event, _params) -> Any:
    body = _parse_body(event)

    filename = body.get("filename")
    content_type = body.get("contentType")
    if not filename or not isinstance(filename, str):
        raise HttpError(400, "missing required field: filename")
    if content_type not in _UPLOAD_CONTENT_TYPES:
        raise HttpError(400, "contentType must be image/png or image/jpeg")

    snapshot_id = uuid.uuid4().hex
    s3_key = snapshots.build_upload_key(USER_ID, snapshot_id, filename)
    db.put_snapshot(USER_ID, snapshot_id, s3_key)

    upload_url = _s3_client().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": SCREENSHOT_BUCKET_NAME,
            "Key": s3_key,
            "ContentType": content_type,
        },
        ExpiresIn=PRESIGNED_URL_TTL_SECONDS,
    )

    return {"snapshotId": snapshot_id, "uploadUrl": upload_url, "s3Key": s3_key}


def list_snapshots(_event, _params) -> Any:
    return {"snapshots": db.read_snapshots(USER_ID, limit=20)}


def get_snapshot(_event, params) -> Any:
    snapshot = db.get_snapshot(USER_ID, params["id"])
    if not snapshot:
        raise HttpError(404, "no such snapshot")

    snapshot["imageUrl"] = _s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": SCREENSHOT_BUCKET_NAME, "Key": snapshot["s3Key"]},
        ExpiresIn=PRESIGNED_URL_TTL_SECONDS,
    )
    return snapshot


def confirm_snapshot(event, params) -> Any:
    snapshot_id = params["id"]
    snapshot = db.get_snapshot(USER_ID, snapshot_id)
    if not snapshot:
        raise HttpError(404, "no such snapshot")
    if snapshot.get("status") != "PENDING_REVIEW":
        raise HttpError(409, "snapshot is not pending review")

    body = _parse_body(event)
    rows = body.get("positions")
    if not isinstance(rows, list) or not rows:
        raise HttpError(400, "positions must be a non-empty array")

    confirmed = 0
    for row in rows:
        if not isinstance(row, dict):
            raise HttpError(400, "each position must be an object")

        ticker = row.get("ticker")
        if not ticker or not isinstance(ticker, str):
            raise HttpError(400, "missing required field: ticker")

        shares = _require_number(row, "shares")
        cost_basis = _require_number(row, "costBasis")
        _validate_position_numbers(shares, cost_basis)

        db.put_position(USER_ID, ticker.upper(), shares, cost_basis, "CONFIRMED")
        confirmed += 1

    db.update_snapshot(USER_ID, snapshot_id, status="CONFIRMED")
    return {"confirmed": confirmed, "snapshotId": snapshot_id}


def reject_snapshot(_event, params) -> Any:
    snapshot_id = params["id"]
    if not db.get_snapshot(USER_ID, snapshot_id):
        raise HttpError(404, "no such snapshot")

    db.update_snapshot(USER_ID, snapshot_id, status="REJECTED")
    return {"snapshotId": snapshot_id, "status": "REJECTED"}


# ----------------------------------------------------------------------
# Routing
# ----------------------------------------------------------------------

Route = tuple[str, re.Pattern, Callable]

ROUTES: list[Route] = [
    ("GET", re.compile(r"^/positions/?$"), list_positions),
    ("PUT", re.compile(r"^/positions/(?P<ticker>[A-Za-z.\-]{1,10})/?$"), upsert_position),
    ("DELETE", re.compile(r"^/positions/(?P<ticker>[A-Za-z.\-]{1,10})/?$"), delete_position),
    ("GET", re.compile(r"^/briefs/latest/?$"), latest_brief),
    ("GET", re.compile(r"^/briefs/?$"), list_briefs),
    ("POST", re.compile(r"^/snapshots/upload-url/?$"), request_upload_url),
    ("GET", re.compile(r"^/snapshots/?$"), list_snapshots),
    ("GET", re.compile(r"^/snapshots/(?P<id>[0-9a-f]{32})/?$"), get_snapshot),
    ("POST", re.compile(r"^/snapshots/(?P<id>[0-9a-f]{32})/confirm/?$"), confirm_snapshot),
    ("POST", re.compile(r"^/snapshots/(?P<id>[0-9a-f]{32})/reject/?$"), reject_snapshot),
]


def _parse_body(event) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HttpError(400, "body must be valid JSON")
    if not isinstance(parsed, dict):
        raise HttpError(400, "body must be a JSON object")
    return parsed


def _require_number(body: dict, key: str) -> float:
    if key not in body:
        raise HttpError(400, f"missing required field: {key}")
    try:
        return float(body[key])
    except (TypeError, ValueError):
        raise HttpError(400, f"{key} must be a number")


def handler(event, _context):
    method = event["requestContext"]["http"]["method"]
    path = event.get("rawPath", "/")

    # The stage prefix is present on the default execute-api domain but not on a
    # custom domain, so strip it rather than baking it into every route.
    stage = event["requestContext"].get("stage")
    if stage and stage != "$default" and path.startswith(f"/{stage}"):
        path = path[len(stage) + 1 :] or "/"

    if method == "OPTIONS":
        return respond(204, "")

    # Two routes commonly share a path with different methods (PUT/DELETE on
    # the same /positions/{ticker}), so a method mismatch on one candidate
    # must not stop the search -- keep looking for the route that actually
    # matches both path and method before falling back to 405.
    path_matched = False
    for route_method, pattern, fn in ROUTES:
        match = pattern.match(path)
        if not match:
            continue
        path_matched = True
        if route_method != method:
            continue
        try:
            return respond(200, fn(event, match.groupdict()))
        except HttpError as exc:
            return respond(exc.status, {"error": exc.message})

    if path_matched:
        return respond(405, {"error": f"{method} not allowed on {path}"})
    return respond(404, {"error": f"no route for {method} {path}"})
