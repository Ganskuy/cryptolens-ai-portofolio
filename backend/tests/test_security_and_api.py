import json
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app import ai, main, services
from app.ai import Finding, ModelAnswer, ToolArgs, validate_answer
from app.db import Candle, ChatSession, Session
from app.providers import CandleInput, MarketInput, Provider
from app.worker import save_candles


@pytest.fixture
def cache(monkeypatch):
    fake = AsyncMock()
    fake.incr.return_value = 1
    fake.get.return_value = None
    fake.set.return_value = True
    monkeypatch.setattr(main, "redis", fake)
    return fake


@pytest.mark.parametrize(
    "update",
    [{"close": -1}, {"volume": -1}, {"high": 50}, {"low": 200}, {"time": 1}, {"close": "NaN"}],
)
def test_bad_candles(update):
    with pytest.raises(ValidationError):
        CandleInput.model_validate(
            {"time": 0, "open": 100, "high": 110, "low": 90, "close": 100, "volume": 1, **update}
        )


def test_missing_market_price():
    with pytest.raises(ValidationError):
        MarketInput.model_validate({"id": "bitcoin", "last_updated": "2026-01-01"})


def test_idempotent_persistence():
    c = CandleInput(
        time=0,
        open=Decimal(100),
        high=Decimal(100),
        low=Decimal(100),
        close=Decimal(100),
        volume=Decimal(0),
    )
    save_candles("bitcoin", [c, c], "test")
    with Session() as db:
        assert (
            db.scalar(select(func.count()).select_from(Candle).where(Candle.source == "test")) == 1
        )


def test_provisional_not_persisted():
    c = CandleInput(
        time=86400,
        open=Decimal(100),
        high=Decimal(100),
        low=Decimal(100),
        close=Decimal(100),
        volume=Decimal(0),
        finalized=False,
    )
    save_candles("bitcoin", [c], "test")
    with Session() as db:
        assert db.get(Candle, ("bitcoin", "test", 86400)) is None


def test_rankings_deterministic_and_stablecoin_exclusion():
    a, b = services.rankings(), services.rankings()
    assert [(r["asset_id"], r["score"]) for r in a["rankings"]] == [
        (r["asset_id"], r["score"]) for r in b["rankings"]
    ]
    assert "usd-coin" not in [r["asset_id"] for r in a["rankings"]]
    assert len(a["rankings"]) == 9


@pytest.mark.parametrize(
    "args",
    [
        {"operation": "shell"},
        {"operation": "risk", "days": 10000},
        {"operation": "overview", "url": "https://evil.test"},
    ],
)
def test_tool_schema_blocks_injection(args):
    with pytest.raises(ValidationError):
        ToolArgs.model_validate(args)


def test_invalid_tool_asset():
    with pytest.raises(ValueError):
        ai.execute_tool(ToolArgs(operation="risk", asset_ids=["BTC"]))


def test_grounding_copies_values():
    result = validate_answer(
        ModelAnswer(
            answer="Historical volatility is elevated.",
            findings=[Finding(evidence_id="ev-1", field="risk")],
        ),
        {"ev-1": {"risk": 0.25}},
    )
    assert result[0]["value"] == 0.25


@pytest.mark.parametrize("answer", ["Return is 50%", "Price is $100", "up twenty percent"])
def test_ungrounded_numerical_prose_rejected(answer):
    with pytest.raises(ValueError):
        validate_answer(ModelAnswer(answer=answer, findings=[]), {})


def test_fake_reference_rejected():
    with pytest.raises(ValueError):
        validate_answer(
            ModelAnswer(
                answer="Historical risk.", findings=[Finding(evidence_id="fake", field="x")]
            ),
            {},
        )


async def test_provider_rate_limit_circuit():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(429, headers={"retry-after": "120"})
        )
    )
    p = Provider(client)
    with pytest.raises(httpx.HTTPStatusError):
        await p.get("https://api.binance.com/api/v3/time")
    with pytest.raises(RuntimeError, match="circuit"):
        await p.get("https://api.binance.com/api/v3/time")
    await client.aclose()


async def test_api_contracts_and_limits(cache):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as c:
        assert (await c.get("/api/v1/health/live")).status_code == 200
        r = await c.get("/api/v1/market/overview")
        assert r.json()["mode"] == "fixture" and len(r.json()["assets"]) == 10
        assert "HttpOnly" in r.headers.get("set-cookie", "") or "cryptolens_owner" in c.cookies
        assert (await c.get("/api/v1/assets/unknown/candles")).status_code == 422
        assert (await c.get("/api/v1/assets/bitcoin/candles?days=10000")).status_code == 422
        assert (
            await c.post("/api/v1/analytics/compare", json={"asset_ids": ["bitcoin", "ethereum"]})
        ).status_code == 200
        assert (await c.post("/api/v1/analytics/compare", content="x" * 17000)).status_code == 413
        assert (
            await c.post(
                "/api/v1/analytics/compare",
                json={"asset_ids": ["bitcoin", "ethereum"]},
                headers={"Origin": "https://evil.test"},
            )
        ).status_code == 403
        assert (
            await c.post(
                "/api/v1/ai/chat/stream", json={"message": "hello", "request_id": "a" * 32}
            )
        ).status_code == 503


async def test_session_owner_isolation(cache):
    with Session.begin() as db:
        db.merge(ChatSession(id="private-session", owner="another-user"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as c:
        assert (await c.get("/api/v1/ai/sessions/private-session")).status_code == 404
        assert (await c.delete("/api/v1/ai/sessions/private-session")).status_code == 404


async def test_mock_tool_orchestration(monkeypatch):
    from app.config import settings

    cfg = settings()
    monkeypatch.setattr(cfg, "ai_enabled", True)
    monkeypatch.setattr(cfg, "ai_mode", "legacy")
    from pydantic import SecretStr

    monkeypatch.setattr(cfg, "openrouter_api_key", SecretStr("test-only"))
    mock = AsyncMock(
        side_effect=[
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call1",
                        "type": "function",
                        "function": {
                            "name": "analytics",
                            "arguments": json.dumps(
                                {"operation": "risk", "asset_ids": ["bitcoin"]}
                            ),
                        },
                    }
                ],
            },
            {
                "content": json.dumps(
                    {
                        "answer": "Risiko historis perlu ditafsirkan dengan hati-hati.",
                        "findings": [{"evidence_id": "ev-1", "field": "max_drawdown"}],
                    }
                )
            },
        ]
    )
    monkeypatch.setattr(ai, "completion", mock)
    progress = AsyncMock()
    result = await ai.analyze("Analisis risiko Bitcoin", progress)
    assert result["key_findings"][0]["value"] < 0
    assert mock.await_count == 2
    assert progress.await_args_list[-1].args == ("validating_response",)


async def test_redis_outage_fails_closed_for_ai(cache):
    cache.incr.side_effect = ConnectionError("cache unavailable")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as c:
        assert (await c.get("/api/v1/market/overview")).status_code == 200
        assert (
            await c.post(
                "/api/v1/ai/chat/stream", json={"message": "hello", "request_id": "b" * 32}
            )
        ).status_code == 503


async def test_database_outage_readiness(cache, monkeypatch):
    from unittest.mock import Mock

    monkeypatch.setattr(main.engine, "connect", Mock(side_effect=ConnectionError()))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as c:
        assert (await c.get("/api/v1/health/ready")).status_code == 503


def test_budget_rejects_before_paid_dispatch(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings(), "ai_total_token_limit", 0)
    with pytest.raises(ValueError, match="budget"):
        ai.reserve("deepseek/deepseek-v3.2")


def test_dataset_reproducibility():
    from app.db import AnalyticsSnapshot

    result = services.risk("bitcoin", 90)
    with Session() as db:
        saved = db.get(AnalyticsSnapshot, result["dataset_id"])
        assert saved.data["series"] == result["series"]


async def test_book_ticker_contract():
    from app.worker import book_poll

    def handle(request):
        symbols = request.url.params["symbols"]
        assert " " not in symbols
        assert json.loads(symbols)[0] == "BTCUSDT"
        return httpx.Response(
            200, json=[{"symbol": "BTCUSDT", "bidPrice": "100", "askPrice": "102"}]
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        assert await book_poll(Provider(client)) == 1


async def test_sse_persists_owned_session_and_final_result(cache, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings(), "ai_enabled", True)

    async def fake_analyze(message, progress, history):
        await progress("calculating_metrics")
        return {
            "answer": "Verified research result",
            "key_findings": [],
            "evidence": {},
            "charts": [],
        }

    monkeypatch.setattr(ai, "analyze", fake_analyze)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/ai/chat/stream",
            json={"message": "test bounded stream", "request_id": "stream-test-unique-123"},
        )
        assert response.status_code == 200
        events = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        assert [e["stage"] for e in events] == [
            "received",
            "calculating_metrics",
            "validated_text",
            "completed",
        ]
        sid = events[-1]["session_id"]
        history = await client.get("/api/v1/ai/sessions/" + sid)
        assert [m["role"] for m in history.json()["messages"]] == ["user", "assistant"]
        assert (await client.delete("/api/v1/ai/sessions/" + sid)).status_code == 204
        assert (await client.get("/api/v1/ai/sessions/" + sid)).status_code == 404


async def test_provider_malformed_json_retries_are_bounded(monkeypatch):
    import app.providers as providers

    sleep = AsyncMock()
    monkeypatch.setattr(providers.asyncio, "sleep", sleep)
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, content=b"not-json")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError):
            await Provider(client).get("https://api.binance.com/api/v3/time")
    assert len(requests) == 3 and sleep.await_count == 2
