"""Deterministic failures, archival and cancellation; no external calls."""

import asyncio
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app import admission, ai, providers
from app.config import Settings, settings
from app.db import (
    AIRequest,
    AnalyticsSnapshot,
    ChatMessage,
    ChatSession,
    ServiceLease,
    Session,
    now,
)
from app.market_extra import archive_snapshots


def test_production_configuration_fails_closed():
    with pytest.raises(ValueError):
        Settings(deployment_mode="production", _env_file=None)
    cfg = Settings(
        deployment_mode="production",
        auth_mode="required",
        cookie_secure=True,
        allowed_origin="https://localhost:8443",
        _env_file=None,
    )
    assert cfg.ai_mode == "grounded"


@pytest.mark.asyncio
async def test_outage_opens_circuit_and_recovers(monkeypatch):
    calls = 0
    clock = [100.0]

    async def respond(request):
        nonlocal calls
        calls += 1
        return httpx.Response(503 if calls <= 6 else 200, json={"ok": True})

    async def no_sleep(_):
        pass

    monkeypatch.setattr(providers.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(providers.asyncio, "sleep", no_sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = providers.Provider(client)
        for _ in range(2):
            with pytest.raises(httpx.HTTPStatusError):
                await provider.get("https://api.binance.com/api/v3/time")
        with pytest.raises(RuntimeError, match="circuit"):
            await provider.get("https://api.binance.com/api/v3/time")
        assert calls == 6
        clock[0] += 121
        assert await provider.get("https://api.binance.com/api/v3/time") == {"ok": True}


def test_archive_preserves_retained_chat_datasets():
    with Session.begin() as db:
        db.add(ChatSession(id="archive-session", owner="archive-owner"))
        for ident in ("archive-keep", "archive-delete"):
            db.add(AnalyticsSnapshot(id=ident, data={}, created_at=now() - timedelta(days=40)))
        db.add(
            ChatMessage(
                id="archive-message",
                session_id="archive-session",
                role="assistant",
                data={"charts": [{"dataset_id": "archive-keep"}]},
            )
        )
    assert archive_snapshots()["removed"] >= 1
    with Session() as db:
        assert db.get(AnalyticsSnapshot, "archive-keep")
        assert not db.get(AnalyticsSnapshot, "archive-delete")


def test_expired_owner_cannot_release_replacement_lease():
    with Session.begin() as db:
        db.query(ServiceLease).delete()
    first = admission.claim("owner", "expired-first", "old")
    with Session.begin() as db:
        db.get(ServiceLease, "ai").expires_at = now() - timedelta(seconds=1)
    second = admission.claim("owner", "replacement", "new")
    admission.finish(first, "old", "cancelled")
    with Session() as db:
        assert db.get(ServiceLease, "ai").token == "new"
        assert db.get(AIRequest, second).state == "admitted"
    admission.finish(second, "new", "finished")


@pytest.mark.asyncio
async def test_cancelled_model_request_keeps_reservation(monkeypatch):
    from app.db import AIUsage

    monkeypatch.setattr(settings(), "ai_enabled", True)
    monkeypatch.setattr(settings(), "openrouter_api_key", __import__("pydantic").SecretStr("mock"))
    started = asyncio.Event()

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            started.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(ai.httpx, "AsyncClient", lambda **kw: Client())
    with Session() as db:
        before = set(db.scalars(select(AIUsage.id)))
    task = asyncio.create_task(
        ai.completion([{"role": "user", "content": "test"}], False, max_output_tokens=160)
    )
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with Session() as db:
        added = [r for r in db.scalars(select(AIUsage)) if r.id not in before]
        assert len(added) == 1
        assert added[0].reserved_tokens > 0
        assert added[0].actual_tokens is None


@pytest.mark.asyncio
async def test_websocket_23_hour_rotation_with_virtual_clock(monkeypatch):
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app import worker

    clock = [0]
    connections = []

    class Socket:
        async def __aenter__(self):
            connections.append(clock[0])
            if len(connections) == 2:
                raise asyncio.CancelledError()
            return self

        async def __aexit__(self, *args):
            pass

        async def recv(self):
            clock[0] += 82801
            return json.dumps(
                {
                    "data": {
                        "s": "BTCUSDT",
                        "E": 100,
                        "k": {
                            "t": 0,
                            "o": "10",
                            "h": "11",
                            "l": "9",
                            "c": "10",
                            "v": "1",
                            "x": False,
                        },
                    }
                }
            )

    monkeypatch.setattr(worker, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(worker.websockets, "connect", lambda *a, **kw: Socket())
    cache = AsyncMock()
    with pytest.raises(asyncio.CancelledError):
        await worker.live_feed(cache)
    assert connections == [0, 82801]
    cache.set.assert_awaited_once()
    assert json.loads(cache.set.call_args.args[1])["finalized"] is False
