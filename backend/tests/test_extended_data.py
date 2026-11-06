import math

import httpx
import pytest

from app import services
from app.indicators import indicators
from app.market_extra import hourly, universe
from app.providers import HourlyInput, Provider, backfill


def rows(prices):
    return [{"time": i * 86400, "close": v} for i, v in enumerate(prices)]


def test_indicator_warmup_values_and_no_lookahead():
    data = rows(list(range(1, 61)))
    first = indicators(data[:30])["series"]
    full = indicators(data)["series"]
    assert first == full[:30]
    assert full[12]["sma"] is None
    assert full[13]["sma"] == 7.5
    assert full[13]["ema"] == 7.5
    assert full[14]["ema"] == 8.5
    assert full[14]["rsi"] == 100
    assert full[25]["macd"] == pytest.approx(7)
    flat = indicators(rows([10] * 50))["series"][-1]
    assert flat["rsi"] == 50 and flat["macd"] == 0


def test_gaps_reset_indicator_state():
    data = rows(list(range(1, 51)))
    del data[20]
    result = indicators(data)["series"]
    assert result[20]["rsi"] is None and result[20]["sma"] is None


async def test_paginated_backfill_and_provisional_exclusion():
    requests = []

    def handle(request):
        requests.append(request)
        start = int(request.url.params["startTime"]) // 1000
        count = 1000 if start == 0 else 200
        return httpx.Response(
            200,
            json=[
                [
                    1000 * (start + i * 86400),
                    "100",
                    "101",
                    "99",
                    "100",
                    "2",
                    1000 * (start + (i + 1) * 86400) - 1,
                ]
                for i in range(count)
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await backfill(Provider(client), "BTCUSDT", "1d", 0, 1200 * 86400)
    assert len(result) == 1200 and len(requests) == 2
    assert len({r.time for r in result}) == 1200


def test_hourly_contract_and_fixture():
    data = HourlyInput(time=3600, open=100, high=101, low=99, close=100, volume=0)
    assert data.time == 3600
    assert len(hourly("bitcoin", 48)) == 49
    assert universe("bitcoin", 0, 20)["items"][0]["analytics_supported"]


def test_ranking_presets_and_risk_free_gate():
    with pytest.raises(ValueError, match="risk-free"):
        services.rankings(preset="sharpe")
    data = services.rankings(preset="volatility")["rankings"]
    assert [r["annualized_volatility"] for r in data] == sorted(
        r["annualized_volatility"] for r in data
    )
    data = services.rankings(preset="sharpe", risk_free=0)["rankings"]
    assert all(math.isfinite(r["score"]) for r in data)


def test_protocol_ratio_uses_tvl_observation_not_retrieval_time():
    from app.db import DefiMetric, Session, UniverseAsset, now
    from app.market_extra import protocol_valuation

    with Session.begin() as db:
        db.merge(
            UniverseAsset(
                id="aave", symbol="AAVE", name="Aave", observed_at=now(), data={"market_cap": 100}
            )
        )
        db.merge(
            DefiMetric(
                id="protocol:aave",
                observed_at=now(),
                data={"tvl_usd": 200, "history": [{"date": 0}]},
            )
        )
    assert protocol_valuation()["tvl_to_market_cap"] is None
    with Session.begin() as db:
        row = db.get(DefiMetric, "protocol:aave")
        row.data = {"tvl_usd": 200, "history": [{"date": now().timestamp()}]}
    assert protocol_valuation()["tvl_to_market_cap"] == 2
