import asyncio
import json
import logging
import math
import random
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import websockets
from redis.asyncio import Redis
from sqlalchemy import delete, func, select

from app.config import settings
from app.db import (
    Asset,
    Candle,
    ChatMessage,
    ChatSession,
    DefiMetric,
    Exchange,
    Fundamental,
    HourlyCandle,
    IngestionRun,
    Mapping,
    MetadataHistory,
    QualityEvent,
    Session,
    Snapshot,
    UniverseAsset,
    now,
)
from app.market_extra import archive_snapshots, universe_poll
from app.providers import CandleInput, MarketInput, Provider, backfill
from app.registry import ASSETS, IDS, SYMBOLS

log = logging.getLogger("worker")


def seed_registry():
    with Session.begin() as db:
        db.merge(Exchange(id="binance", name="Binance spot, USDT quote"))
        for asset, symbol, name, pair, stable in ASSETS:
            db.merge(Asset(id=asset, symbol=symbol, name=name, stablecoin=stable))
        db.flush()
        for i, (asset, _, _, pair, _) in enumerate(ASSETS):
            for j, (provider, pid) in enumerate([("coingecko", asset), ("binance", pair)]):
                db.merge(
                    Mapping(id=i * 2 + j + 1, asset_id=asset, provider=provider, provider_id=pid)
                )


def save_candles(asset: str, rows: list[CandleInput], source: str):
    with Session.begin() as db:
        for row in rows:
            if row.finalized:
                previous = db.get(Candle, (asset, source, row.time - 86400))
                if previous and abs(row.close / previous.close - 1) > Decimal("0.5"):
                    db.add(QualityEvent(source=source, reason="daily_outlier:" + asset))
                db.merge(Candle(asset_id=asset, source=source, **row.model_dump()))


def event(provider: str, status: str, count: int = 0):
    with Session.begin() as db:
        db.add(IngestionRun(provider=provider, status=status, records=count))
        if status != "ok":
            db.add(QualityEvent(source=provider, reason=status))


def fixtures():
    """Synthetic deterministic data, explicitly segregated from live sources."""
    seed_registry()
    end = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
    for i, (asset, _, _, _, stable) in enumerate(ASSETS):
        rows = []
        for j in range(366):
            price = (
                1 + 0.001 * math.sin(j)
                if stable
                else (i + 1) * 100 * math.exp(0.0007 * j + 0.08 * math.sin(j / (5 + i)))
            )
            rows.append(
                CandleInput(
                    time=end - (365 - j) * 86400,
                    open=Decimal(str(price)),
                    high=Decimal(str(price * 1.01)),
                    low=Decimal(str(price * 0.99)),
                    close=Decimal(str(price)),
                    volume=Decimal(10000),
                )
            )
        save_candles(asset, rows, "synthetic-fixture")
        with Session.begin() as db:
            db.merge(
                Snapshot(
                    asset_id=asset,
                    source="synthetic-fixture",
                    price=rows[-1].close,
                    observed_at=datetime.fromtimestamp(end, timezone.utc),
                    ingested_at=now(),
                    data={
                        "market_cap": (i + 1) * 100000000,
                        "total_volume": 10000000,
                        "price_change_percentage_24h": None,
                    },
                )
            )
    with Session.begin() as db:
        for asset, symbol, name, _, _ in ASSETS:
            db.merge(
                UniverseAsset(
                    id=asset,
                    symbol=symbol,
                    name=name,
                    observed_at=datetime.fromtimestamp(end, timezone.utc),
                    data={
                        "source": "synthetic-fixture",
                        "current_price": 100,
                        "market_cap": 1000000,
                    },
                )
            )
            for hour in range(73):
                hour_price = Decimal(str(100 + math.sin(hour / 5)))
                db.merge(
                    HourlyCandle(
                        asset_id=asset,
                        source="synthetic-fixture",
                        time=end - (72 - hour) * 3600,
                        open=hour_price,
                        high=hour_price + 1,
                        low=hour_price - 1,
                        close=hour_price,
                        volume=Decimal(100),
                    )
                )
    event("synthetic-fixture", "ok", 3660)


async def poll(provider: Provider, redis: Redis):
    for name, operation in [
        ("coingecko", market_poll),
        ("defillama", defi_poll),
        ("binance", candle_poll),
        ("binance-book", book_poll),
    ]:
        try:
            count = await operation(provider)
            await asyncio.to_thread(event, name, "ok", count)
        except Exception as exc:
            await asyncio.to_thread(event, name, type(exc).__name__)
            log.warning(json.dumps({"provider": name, "error": type(exc).__name__}))
    try:
        await redis.set("worker:last_poll", now().isoformat(), ex=900)
    except Exception:
        log.warning('{"event":"redis_unavailable"}')
    await asyncio.to_thread(retain)
    await asyncio.to_thread(archive_snapshots)


async def market_poll(provider: Provider):
    raw = await provider.get(
        "https://api.coingecko.com/api/v3/coins/markets",
        {"vs_currency": "usd", "ids": ",".join(sorted(IDS))},
    )
    count = 0
    for item in raw:
        try:
            row = MarketInput.model_validate(item)
            if row.id not in IDS:
                continue
            observed = datetime.fromisoformat(row.last_updated.replace("Z", "+00:00"))
            if observed.tzinfo is None or observed > now() + timedelta(minutes=5):
                raise ValueError("invalid timestamp")
            data = row.model_dump(mode="json")

            def save():
                with Session.begin() as db:
                    old = db.get(Snapshot, (row.id, "coingecko"))
                    if old and old.observed_at.replace(tzinfo=timezone.utc) > observed:
                        return
                    db.merge(
                        Snapshot(
                            asset_id=row.id,
                            source="coingecko",
                            price=row.current_price,
                            observed_at=observed,
                            ingested_at=now(),
                            data=data,
                        )
                    )
                    db.merge(Fundamental(asset_id=row.id, observed_at=observed, data=data))
                    db.merge(
                        MetadataHistory(
                            asset_id=row.id,
                            source="coingecko",
                            observed_at=observed,
                            ingested_at=now(),
                            data=data,
                        )
                    )

            await asyncio.to_thread(save)
            count += 1
        except (ValueError, TypeError):
            await asyncio.to_thread(event, "coingecko", "invalid_record")
    global_data = await provider.get("https://api.coingecko.com/api/v3/global")

    def save_global():
        with Session.begin() as db:
            db.merge(DefiMetric(id="global-market", observed_at=now(), data=global_data["data"]))

    await asyncio.to_thread(save_global)
    return count


async def candle_poll(provider: Provider):
    count = 0
    end = int(now().timestamp()) // 86400 * 86400
    for asset, _, _, pair, _ in ASSETS:

        def latest(model):
            with Session() as db:
                return db.scalar(
                    select(func.max(model.time)).where(
                        model.asset_id == asset, model.source == "binance"
                    )
                )

        last = await asyncio.to_thread(latest, Candle)
        start = max(end - settings().daily_retention_days * 86400, (last or 0) - 86400)
        # First acquisition includes configured multi-year history; existing short histories
        # can be extended explicitly with scripts/backfill.py without repeated provider traffic.
        rows = await backfill(provider, pair, "1d", start, end)
        await asyncio.to_thread(save_candles, asset, rows, "binance")
        count += len(rows)
        hourly_end = int(now().timestamp()) // 3600 * 3600
        hourly_last = await asyncio.to_thread(latest, HourlyCandle)
        hourly_start = max(
            hourly_end - settings().hourly_retention_days * 86400, (hourly_last or 0) - 3600
        )
        hours = await backfill(provider, pair, "1h", hourly_start, hourly_end)

        def save_hours():
            with Session.begin() as db:
                for row in hours:
                    db.merge(
                        HourlyCandle(
                            asset_id=asset,
                            source="binance",
                            **row.model_dump(exclude={"finalized"}),
                        )
                    )

        await asyncio.to_thread(save_hours)
        count += len(hours)
        await asyncio.sleep(0.2)
    return count


async def defi_poll(provider: Provider):
    chains = await provider.get("https://api.llama.fi/v2/chains")

    def save():
        with Session.begin() as db:
            for row in chains:
                if (
                    row["name"] in ("Ethereum", "Solana", "BSC", "Avalanche")
                    and float(row["tvl"]) >= 0
                ):
                    db.merge(
                        DefiMetric(
                            id="chain:" + row["name"],
                            observed_at=now(),
                            data={
                                "tvl_usd": row["tvl"],
                                "scope": "chain, not token",
                                "source": "defillama",
                            },
                        )
                    )

    await asyncio.to_thread(save)
    # Explicit protocol/chain scope; never infer a relationship to token value.
    protocol = await provider.get("https://api.llama.fi/protocol/aave")
    history = await provider.get("https://api.llama.fi/v2/historicalChainTvl/Ethereum")
    stable = await provider.get(
        "https://stablecoins.llama.fi/stablecoins", {"includePrices": "true"}
    )
    tvl = protocol.get("tvl", [])[-365:]
    chain_history = history[-365:]
    total = sum(
        float(x.get("circulating", {}).get("peggedUSD", 0) or 0)
        for x in stable.get("peggedAssets", [])
    )
    if not math.isfinite(total) or total < 0:
        raise ValueError("Invalid stablecoin supply")

    def save_extended():
        with Session.begin() as db:
            db.merge(
                DefiMetric(
                    id="protocol:aave",
                    observed_at=now(),
                    data={
                        "source": "defillama",
                        "scope": "protocol",
                        "tvl_usd": float(tvl[-1]["totalLiquidityUSD"]) if tvl else None,
                        "history": tvl,
                    },
                )
            )
            db.merge(
                DefiMetric(
                    id="chain-history:Ethereum",
                    observed_at=now(),
                    data={"source": "defillama", "scope": "chain", "history": chain_history},
                )
            )
            db.merge(
                DefiMetric(
                    id="stablecoins:peggedUSD",
                    observed_at=now(),
                    data={
                        "source": "defillama",
                        "scope": "aggregate stablecoin circulating supply",
                        "circulating_usd": total,
                        "definition": "Sum of provider peggedUSD circulating fields; not proof of reserve backing",
                    },
                )
            )

    await asyncio.to_thread(save_extended)
    return len(chains)


def retain():
    with Session.begin() as db:
        cutoff = now() - timedelta(days=30)
        old_sessions = select(ChatSession.id).where(ChatSession.created_at < cutoff)
        db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(old_sessions)))
        db.execute(delete(ChatMessage).where(ChatMessage.created_at < cutoff))
        db.execute(delete(ChatSession).where(ChatSession.created_at < cutoff))
        db.execute(
            delete(HourlyCandle).where(
                HourlyCandle.time
                < int((now() - timedelta(days=settings().hourly_retention_days)).timestamp()),
                HourlyCandle.source != "synthetic-fixture",
            )
        )
        db.execute(delete(IngestionRun).where(IngestionRun.created_at < cutoff))
        db.execute(delete(QualityEvent).where(QualityEvent.created_at < cutoff))
        db.execute(
            delete(Candle).where(
                Candle.time
                < int((now() - timedelta(days=settings().daily_retention_days)).timestamp()),
                Candle.source != "synthetic-fixture",
            )
        )


async def live_feed(redis: Redis):
    streams = "/".join(a[3].lower() + "@kline_1d" for a in ASSETS)
    delay = 1
    while True:
        try:
            async with websockets.connect(
                "wss://stream.binance.com:9443/stream?streams=" + streams,
                ping_interval=20,
                ping_timeout=20,
                max_queue=16,
                max_size=65536,
            ) as ws:
                started = time.monotonic()
                last: dict[str, int] = {}
                delay = 1
                while time.monotonic() - started < settings().stream_rotation_seconds:
                    message = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))["data"]
                    asset = SYMBOLS.get(message.get("s"))
                    if not asset or message["E"] <= last.get(asset, 0):
                        continue
                    k = message["k"]
                    row = CandleInput(
                        time=k["t"] // 1000,
                        open=k["o"],
                        high=k["h"],
                        low=k["l"],
                        close=k["c"],
                        volume=k["v"],
                        finalized=k["x"],
                    )
                    last[asset] = message["E"]
                    if row.finalized:
                        await asyncio.to_thread(save_candles, asset, [row], "binance")
                    payload = {
                        "asset_id": asset,
                        "price": str(row.close),
                        "observed_at": message["E"],
                        "source": "binance",
                        "quote": "USDT",
                        "finalized": row.finalized,
                    }
                    await redis.set("tick:" + asset, json.dumps(payload), ex=120)
                    await redis.publish("market", json.dumps(payload))
        except Exception as exc:
            log.warning(json.dumps({"event": "feed_reconnect", "error": type(exc).__name__}))
            await asyncio.sleep(delay + random.random())
            delay = min(60, delay * 2)


async def worker_job():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    await asyncio.to_thread(seed_registry)
    if settings().data_mode == "fixture":
        await asyncio.to_thread(fixtures)
        while True:
            await asyncio.sleep(60)
    redis = Redis.from_url(settings().redis_url)
    async with httpx.AsyncClient() as client:
        provider = Provider(client)

        async def polling():
            while True:
                await poll(provider, redis)
                await asyncio.sleep(settings().poll_seconds)

        async def universe_loop():
            while True:
                try:
                    count = await universe_poll(provider)
                    await asyncio.to_thread(event, "coingecko-universe", "ok", count)
                except Exception as exc:
                    await asyncio.to_thread(event, "coingecko-universe", type(exc).__name__)
                await asyncio.sleep(settings().universe_poll_seconds)

        try:
            await asyncio.gather(polling(), live_feed(redis), universe_loop())
        finally:
            await redis.aclose()


async def book_poll(provider: Provider):
    raw = await provider.get(
        "https://api.binance.com/api/v3/ticker/bookTicker",
        {"symbols": json.dumps(list(SYMBOLS), separators=(",", ":"))},
    )
    count = 0
    for item in raw:
        asset = SYMBOLS.get(item.get("symbol"))
        if not asset:
            continue
        bid, ask = Decimal(item["bidPrice"]), Decimal(item["askPrice"])
        if not bid.is_finite() or not ask.is_finite() or bid <= 0 or ask < bid:
            raise ValueError("Invalid bid/ask")
        midpoint = (bid + ask) / 2

        def save():
            with Session.begin() as db:
                db.merge(
                    Snapshot(
                        asset_id=asset,
                        source="binance-book",
                        price=midpoint,
                        observed_at=now(),
                        ingested_at=now(),
                        data={
                            "bid": str(bid),
                            "ask": str(ask),
                            "spread_bps": float((ask - bid) / midpoint * 10000),
                            "quote": "USDT",
                            "timestamp_semantics": "backend retrieval time; endpoint has no observation time",
                        },
                    )
                )
                other = db.get(Snapshot, (asset, "coingecko"))
                if other and abs(midpoint / other.price - 1) > Decimal("0.05"):
                    db.add(
                        QualityEvent(
                            source="cross-provider",
                            reason="quote_basis_or_price_discrepancy:" + asset,
                        )
                    )

        await asyncio.to_thread(save)
        count += 1
    return count


if __name__ == "__main__":
    from app.leadership import run_owned

    asyncio.run(run_owned(worker_job))
