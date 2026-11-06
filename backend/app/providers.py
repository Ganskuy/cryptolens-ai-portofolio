import asyncio
import random
import time
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app import telemetry as tm


class CandleInput(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    time: int = Field(ge=0)
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: Decimal = Field(ge=0)
    finalized: bool = True

    @model_validator(mode="after")
    def valid_range(self):
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("invalid OHLC range")
        if self.time % 86400:
            raise ValueError("daily candle must start at UTC midnight")
        return self


class MarketInput(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    id: str
    current_price: Decimal = Field(gt=0)
    market_cap: Decimal | None = Field(None, ge=0)
    total_volume: Decimal | None = Field(None, ge=0)
    market_cap_rank: int | None = Field(None, gt=0)
    circulating_supply: Decimal | None = Field(None, ge=0)
    total_supply: Decimal | None = Field(None, ge=0)
    max_supply: Decimal | None = Field(None, gt=0)
    price_change_percentage_24h: float | None = None
    last_updated: str


class Provider:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.failures: dict[str, int] = {}
        self.blocked_until: dict[str, float] = {}

    async def get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        host = httpx.URL(url).host
        if self.blocked_until.get(host, 0) > time.monotonic():
            raise RuntimeError("provider circuit open")
        for attempt in range(3):
            started = time.perf_counter()
            try:
                with tm.span("provider." + host):
                    response = await self.client.get(url, params=params, timeout=20)
                response.raise_for_status()
                result = response.json()
                tm.PROVIDER.labels(host, "ok").observe(time.perf_counter() - started)
                self.failures[host] = 0
                return result
            except (httpx.HTTPError, ValueError) as exc:
                tm.PROVIDER.labels(host, "error").observe(time.perf_counter() - started)
                self.failures[host] = self.failures.get(host, 0) + 1
                if self.failures[host] >= 5:
                    self.blocked_until[host] = time.monotonic() + 120
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (
                    418,
                    429,
                ):
                    try:
                        delay = min(300, max(1, int(exc.response.headers.get("retry-after", "60"))))
                    except ValueError:
                        delay = 60
                    self.blocked_until[host] = time.monotonic() + delay
                    raise
                if attempt == 2:
                    raise
                await asyncio.sleep(2**attempt + random.random())

    async def candles(self, symbol: str) -> list[CandleInput]:
        rows = await self.get(
            "https://api.binance.com/api/v3/klines",
            {"symbol": symbol, "interval": "1d", "limit": 367},
        )
        return [
            CandleInput(time=r[0] // 1000, open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
            for r in rows
            if r[6] < time.time() * 1000
        ]


class HourlyInput(CandleInput):
    @model_validator(mode="after")
    def valid_range(self):
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("invalid OHLC range")
        if self.time % 3600:
            raise ValueError("hourly candle must start at UTC hour")
        return self


async def backfill(
    provider: Provider, symbol: str, interval: str, start: int, end: int
) -> list[CandleInput]:
    if interval not in {"1d", "1h"} or start < 0 or end <= start:
        raise ValueError("Invalid history range")
    step = 86400 if interval == "1d" else 3600
    if (end - start) // step > 9000:
        raise ValueError("History request exceeds bounded observations")
    model = CandleInput if interval == "1d" else HourlyInput
    cursor = start
    result = {}
    for _ in range(10):
        raw = await provider.get(
            "https://api.binance.com/api/v3/klines",
            {
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor * 1000,
                "endTime": end * 1000 - 1,
                "limit": 1000,
            },
        )
        if not raw:
            break
        for r in raw:
            timestamp = int(r[0]) // 1000
            if cursor <= timestamp < end and r[6] < time.time() * 1000:
                result[timestamp] = model(
                    time=timestamp, open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]
                )
        next_cursor = max(int(r[0]) // 1000 for r in raw) + step
        if next_cursor <= cursor:
            raise ValueError("Provider history pagination did not advance")
        cursor = next_cursor
        if cursor >= end or len(raw) < 1000:
            break
        await asyncio.sleep(0.2)
    return [result[t] for t in sorted(result)]
