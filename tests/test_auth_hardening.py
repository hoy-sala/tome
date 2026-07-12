"""Auth hardening: Quick Connect poll capability.

Covers the fixes from the 2026-07-03 auth surface review:
- Quick Connect: polling requires the poll_token issued at initiate, so the
  6-character display code can no longer be brute-forced into a login JWT.
"""
from datetime import datetime, timedelta

from starlette.testclient import TestClient

from backend.models.quick_connect import QuickConnectCode


# ---------------------------------------------------------------------------
# Quick Connect
# ---------------------------------------------------------------------------

class TestQuickConnectPollToken:
    def test_initiate_returns_poll_token(self, client: TestClient):
        resp = client.post("/api/auth/quick-connect/initiate")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["code"]) == 6
        assert len(data["poll_token"]) >= 32

    def test_full_flow_with_token(self, client: TestClient, admin_user):
        user, _ = admin_user
        init = client.post("/api/auth/quick-connect/initiate").json()

        # Pending until authorized
        pending = client.post("/api/auth/quick-connect/poll",
                              json={"code": init["code"], "poll_token": init["poll_token"]})
        assert pending.status_code == 200
        assert pending.json()["status"] == "pending"

        # Authorize from the logged-in device (client carries the admin JWT)
        auth = client.post("/api/auth/quick-connect/authorize", json={"code": init["code"]})
        assert auth.status_code == 200

        done = client.post("/api/auth/quick-connect/poll",
                           json={"code": init["code"], "poll_token": init["poll_token"]})
        assert done.status_code == 200
        body = done.json()
        assert body["status"] == "authorized"
        assert body["access_token"]

    def test_poll_with_wrong_token_is_indistinguishable_from_unknown_code(
        self, client: TestClient
    ):
        init = client.post("/api/auth/quick-connect/initiate").json()
        client.post("/api/auth/quick-connect/authorize", json={"code": init["code"]})

        # Correct code, wrong token: the brute-forcer's position. Must get the
        # same 410 as a nonexistent code — no oracle, no JWT.
        wrong = client.post("/api/auth/quick-connect/poll",
                            json={"code": init["code"], "poll_token": "A" * 43})
        unknown = client.post("/api/auth/quick-connect/poll",
                              json={"code": "ZZZZZZ", "poll_token": "A" * 43})
        assert wrong.status_code == 410
        assert unknown.status_code == 410
        assert wrong.json() == unknown.json()

        # The code is still consumable by the legitimate holder afterwards.
        ok = client.post("/api/auth/quick-connect/poll",
                         json={"code": init["code"], "poll_token": init["poll_token"]})
        assert ok.status_code == 200
        assert ok.json()["status"] == "authorized"

    def test_legacy_tokenless_rows_cannot_be_polled(self, client: TestClient, db, admin_user):
        user, _ = admin_user
        # A pre-migration row (poll_token NULL) that is already authorized.
        entry = QuickConnectCode(
            code="ABCDEF", poll_token=None, user_id=user.id,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(minutes=5),
            authorized_at=datetime.utcnow(),
        )
        db.add(entry)
        db.commit()

        resp = client.post("/api/auth/quick-connect/poll",
                           json={"code": "ABCDEF", "poll_token": ""})
        assert resp.status_code == 410

    def test_old_get_poll_route_yields_no_jwt(self, client: TestClient):
        # The tokenless GET route is removed; unmatched GETs fall through to
        # the SPA catch-all. Whatever comes back, it must never carry a JWT.
        init = client.post("/api/auth/quick-connect/initiate").json()
        client.post("/api/auth/quick-connect/authorize", json={"code": init["code"]})
        resp = client.get(f"/api/auth/quick-connect/poll/{init['code']}")
        assert "access_token" not in resp.text

    def test_expired_code_polls_410(self, client: TestClient, db):
        init = client.post("/api/auth/quick-connect/initiate").json()
        entry = db.query(QuickConnectCode).filter(QuickConnectCode.code == init["code"]).first()
        entry.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()

        resp = client.post("/api/auth/quick-connect/poll",
                           json={"code": init["code"], "poll_token": init["poll_token"]})
        assert resp.status_code == 410


