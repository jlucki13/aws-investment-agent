"""Router method-dispatch tests.

Regression coverage for a real bug: the handler used to return as soon as any
route's PATH matched, even when the METHOD didn't -- so two routes sharing a
path (PUT and DELETE both on /positions/{ticker}) meant only whichever was
listed first in ROUTES ever actually worked. DELETE returned a false 405 in
production until this was caught.

Loads src/api/app.py under a private module name (not "app") so it can never
collide with sys.modules["app"] if another test elsewhere imports a sibling
Lambda's app.py under the same generic name.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "layers" / "common" / "python"))

os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "test-user")
os.environ.setdefault("SCREENSHOT_BUCKET_NAME", "test-bucket")

_spec = importlib.util.spec_from_file_location(
    "_test_api_app", ROOT / "src" / "api" / "app.py"
)
api_app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api_app)


def _event(method, path, body=None):
    return {
        "requestContext": {"http": {"method": method}, "stage": "v1"},
        "rawPath": path,
        "body": json.dumps(body) if body is not None else None,
    }


def test_delete_reaches_delete_handler_not_put():
    """The exact bug: DELETE must not be shadowed by the earlier PUT route."""
    with patch.object(api_app.db, "delete_position") as mock_delete:
        resp = api_app.handler(_event("DELETE", "/positions/AAPL"), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"deleted": "AAPL"}
    mock_delete.assert_called_once_with("test-user", "AAPL")


def test_put_still_works_on_the_shared_path():
    with patch.object(api_app.db, "put_position") as mock_put:
        mock_put.return_value = {"ticker": "AAPL", "shares": 10.0, "costBasis": 100.0}
        resp = api_app.handler(
            _event("PUT", "/positions/AAPL", {"shares": 10, "costBasis": 100}), None
        )

    assert resp["statusCode"] == 200
    mock_put.assert_called_once()


def test_method_not_allowed_on_a_known_path_returns_405():
    """PATCH isn't defined for /positions/{ticker}; both PUT and DELETE routes
    match the path, so this must fall through both and land on 405, not 200."""
    resp = api_app.handler(_event("PATCH", "/positions/AAPL"), None)
    assert resp["statusCode"] == 405


def test_unknown_path_returns_404():
    resp = api_app.handler(_event("GET", "/nonexistent"), None)
    assert resp["statusCode"] == 404


def test_snapshot_confirm_and_get_do_not_collide():
    """GET /snapshots/{id} and POST /snapshots/{id}/confirm share a prefix;
    make sure the confirm path never falls into the plain get_snapshot route."""
    snap_id = "a" * 32
    with patch.object(api_app.db, "get_snapshot") as mock_get, patch.object(
        api_app.db, "put_position"
    ) as mock_put, patch.object(api_app.db, "update_snapshot") as mock_update:
        mock_get.return_value = {"status": "PENDING_REVIEW"}
        resp = api_app.handler(
            _event(
                "POST",
                f"/snapshots/{snap_id}/confirm",
                {"positions": [{"ticker": "AAPL", "shares": 5, "costBasis": 100}]},
            ),
            None,
        )

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body == {"confirmed": 1, "snapshotId": snap_id}
    mock_put.assert_called_once_with("test-user", "AAPL", 5.0, 100.0, "CONFIRMED")
    mock_update.assert_called_once_with("test-user", snap_id, status="CONFIRMED")
