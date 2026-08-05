"""Positions CRUD and brief retrieval.

Deliberately framework-free -- no FastAPI, no Flask. At five routes a dict-based
router is less code than the framework's boilerplate, and it keeps the deployment
package to zero dependencies, which means fast cold starts and nothing to patch.
"""

import json
import os
import re
from decimal import Decimal
from typing import Any, Callable

from portfolio_common import db

USER_ID = os.environ["USER_ID"]


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


def upsert_position(event, params) -> Any:
    ticker = params["ticker"].upper()
    body = _parse_body(event)

    shares = _require_number(body, "shares")
    cost_basis = _require_number(body, "costBasis")

    if shares <= 0:
        raise HttpError(400, "shares must be greater than zero")
    if cost_basis < 0:
        raise HttpError(400, "costBasis cannot be negative")

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

    for route_method, pattern, fn in ROUTES:
        match = pattern.match(path)
        if not match:
            continue
        if route_method != method:
            return respond(405, {"error": f"{method} not allowed on {path}"})
        try:
            return respond(200, fn(event, match.groupdict()))
        except HttpError as exc:
            return respond(exc.status, {"error": exc.message})

    return respond(404, {"error": f"no route for {method} {path}"})
