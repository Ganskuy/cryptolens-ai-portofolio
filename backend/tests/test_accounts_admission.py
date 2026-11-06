import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select
from test_security_and_api import cache  # noqa: F401

from app import admission, auth, main
from app.config import settings
from app.db import AIRequest, AuthSession, ServiceLease, Session, now


@pytest.fixture
def account():
    username = "user-" + uuid.uuid4().hex[:8]
    ident = auth.create_user(username, "a long test password", "researcher")
    return username, ident


def test_password_hash_and_disabled_expired_sessions(account):
    username, ident = account
    token, csrf, user = auth.login(username, "a long test password")
    assert user["id"] == ident
    assert auth.principal(token, csrf)["id"] == ident
    with pytest.raises(auth.AuthError):
        auth.principal(token, "forged")
    with Session.begin() as db:
        session = db.get(AuthSession, auth.digest(token))
        session.expires_at = now() - timedelta(seconds=1)
    assert auth.principal(token) is None
    with pytest.raises(auth.AuthError):
        auth.login(username, "wrong password")


async def test_required_auth_csrf_and_revocation(cache, monkeypatch, account):  # noqa: F811
    monkeypatch.setattr(settings(), "auth_mode", "required")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/v1/market/overview")).status_code == 401
        response = await client.post(
            "/api/v1/auth/login",
            headers={"Origin": settings().allowed_origin},
            json={"username": account[0], "password": "a long test password"},
        )
        assert response.status_code == 200
        assert "HttpOnly" in response.headers["set-cookie"]
        assert (await client.get("/api/v1/market/overview")).status_code == 200
        body = {"asset_ids": ["bitcoin", "ethereum"]}
        assert (await client.post("/api/v1/analytics/compare", json=body)).status_code == 403
        headers = {
            "X-CSRF-Token": client.cookies["cryptolens_csrf"],
            "Origin": settings().allowed_origin,
        }
        assert (
            await client.post("/api/v1/analytics/compare", json=body, headers=headers)
        ).status_code == 200
        assert (await client.get("/metrics")).status_code == 403
        assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 204
        assert (await client.get("/api/v1/market/overview")).status_code == 401


def test_durable_idempotency_and_lease_owner():
    ident = uuid.uuid4().hex
    key = admission.claim("owner", ident, "token-a")
    with pytest.raises(admission.AdmissionError) as duplicate:
        admission.claim("owner", ident, "token-b")
    assert duplicate.value.status == 409
    with pytest.raises(admission.AdmissionError) as concurrent:
        admission.claim("owner", "another-" + ident, "token-b")
    assert concurrent.value.status == 429
    admission.finish(key, "wrong-token", "cancelled")
    with Session() as db:
        assert db.get(ServiceLease, "ai").token == "token-a"
    admission.finish(key, "token-a", "cancelled")
    # No cache dependency: a new process/cache restart still sees the durable record.
    with pytest.raises(admission.AdmissionError):
        admission.claim("owner", ident, "token-c")
    with Session() as db:
        assert db.scalar(select(AIRequest).where(AIRequest.id == key)).state == "cancelled"


async def test_metrics_no_query_text_or_secrets(cache):  # noqa: F811
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/market/overview")
        assert len(response.headers["traceparent"].split("-")[1]) == 32
        metrics = await client.get("/metrics")
        assert "cryptolens_http_duration_seconds_bucket" in metrics.text
        assert "cryptolens_db_duration_seconds_bucket" in metrics.text
        assert "SELECT " not in metrics.text
