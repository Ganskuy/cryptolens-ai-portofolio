import hashlib
import json
from datetime import timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.analytics import VERSION, correlation, metrics
from app.config import settings
from app.db import AnalyticsSnapshot, Asset, Candle, DefiMetric, Fundamental, Session, Snapshot, now
from app.registry import IDS
from app.telemetry import traced


def source() -> str:
    return "synthetic-fixture" if settings().data_mode == "fixture" else "binance"


def candles(asset_id: str, days: int = 90) -> list[dict[str, Any]]:
    if asset_id not in IDS:
        raise ValueError("Unknown canonical asset ID")
    with Session() as db:
        rows = db.scalars(
            select(Candle)
            .where(
                Candle.asset_id == asset_id, Candle.source == source(), Candle.finalized.is_(True)
            )
            .order_by(Candle.time.desc())
            .limit(days + 1)
        ).all()
        return [
            {
                "time": r.time,
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": float(r.volume),
            }
            for r in reversed(rows)
        ]


def overview() -> dict[str, Any]:
    with Session() as db:
        assets = db.scalars(select(Asset).order_by(Asset.id)).all()
        items = []
        for asset in assets:
            row = db.get(
                Snapshot,
                (
                    asset.id,
                    "synthetic-fixture" if settings().data_mode == "fixture" else "coingecko",
                ),
            )
            data = dict(row.data) if row else {}
            book = (
                db.get(Snapshot, (asset.id, "binance-book"))
                if settings().data_mode == "live"
                else None
            )
            data["bid_ask"] = (
                {**book.data, "observed_at": book.observed_at.isoformat()} if book else None
            )
            observed = row.observed_at.replace(tzinfo=timezone.utc) if row else None
            age = (now() - observed).total_seconds() if observed else None
            items.append(
                {
                    "id": asset.id,
                    "symbol": asset.symbol,
                    "name": asset.name,
                    "stablecoin": asset.stablecoin,
                    **data,
                    "price": str(row.price) if row else None,
                    "source": row.source if row else None,
                    "observed_at": observed.isoformat() if observed else None,
                    "ingested_at": row.ingested_at.replace(tzinfo=timezone.utc).isoformat()
                    if row
                    else None,
                    "stale": age is None or age > 900,
                    "age_seconds": age,
                }
            )
        glob = db.get(DefiMetric, "global-market") if settings().data_mode == "live" else None
        return {
            "mode": settings().data_mode,
            "snapshot_at": now().isoformat(),
            "assets": items,
            "global": {
                "data": glob.data,
                "observed_at": glob.observed_at.isoformat(),
                "source": "coingecko",
            }
            if glob
            else None,
        }


def fundamentals(asset_id: str) -> dict[str, Any]:
    if asset_id not in IDS:
        raise ValueError("Unknown canonical asset ID")
    with Session() as db:
        row = db.get(Fundamental, asset_id) if settings().data_mode == "live" else None
        if not row:
            return {
                "asset_id": asset_id,
                "available": False,
                "reason": "No provider fundamentals available",
            }
        data = dict(row.data)
        cap, volume = data.get("market_cap"), data.get("total_volume")
        maximum, supply = data.get("max_supply"), data.get("circulating_supply")
        return {
            "asset_id": asset_id,
            "available": True,
            "source": "coingecko",
            "observed_at": row.observed_at.isoformat(),
            **data,
            "volume_to_market_cap": float(volume) / float(cap)
            if volume and cap and float(cap) > 0
            else None,
            "supply_ratio": float(supply) / float(maximum) if maximum and supply else None,
        }


@traced("risk")
def risk(asset_id: str, days: int, risk_free: float | None = None) -> dict[str, Any]:
    rows = candles(asset_id, days)
    result = metrics(rows, days, risk_free)
    digest = hashlib.sha256(
        json.dumps([asset_id, rows, days, risk_free, VERSION], sort_keys=True).encode()
    ).hexdigest()[:20]
    result = {
        "asset_id": asset_id,
        "dataset_id": digest,
        "source": source(),
        "quote": "USDT" if source() == "binance" else "synthetic",
        "snapshot_at": now().isoformat(),
        **result,
    }
    if asset_id == "usd-coin" and rows:
        deviations = [abs(float(r["close"]) - 1) for r in rows]
        result["stablecoin_analysis"] = {
            "reference": "1 USDT, not USD",
            "max_absolute_quote_deviation": max(deviations),
            "fraction_outside_half_percent": sum(d > 0.005 for d in deviations) / len(deviations),
            "limitations": "Daily closes miss intraday depegs. Issuer, reserves, custody and counterparty risks are not measured.",
        }
    result["stale"] = bool(
        rows
        and source() == "binance"
        and rows[-1]["time"] < int(now().timestamp()) // 86400 * 86400 - 86400
    )
    if result["stale"]:
        result["eligible"] = False
        result["reason"] = "Latest finalized daily candle is stale"
    with Session.begin() as db:
        insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
        db.execute(
            insert(AnalyticsSnapshot)
            .values(id=digest, data=result)
            .on_conflict_do_nothing(index_elements=["id"])
        )
    return result


@traced("rankings")
def rankings(
    days: int = 90,
    volatility_weight: float = 0.5,
    min_volume: float = 0,
    preset: str = "balanced",
    risk_free: float | None = None,
) -> dict[str, Any]:
    if preset not in {"balanced", "volatility", "drawdown", "liquidity", "sharpe"}:
        raise ValueError("Unknown ranking preset")
    if preset == "sharpe" and risk_free is None:
        raise ValueError("Sharpe ranking requires an explicit annual risk-free assumption")
    market = overview()
    included, excluded = [], []
    for asset in market["assets"]:
        if asset["stablecoin"]:
            excluded.append(
                {
                    "asset_id": asset["id"],
                    "reason": "Stablecoin: evaluate depeg, issuer and custody risk separately",
                }
            )
            continue
        data = risk(asset["id"], days, risk_free)
        data["reported_volume_usd"] = float(asset.get("total_volume") or 0)
        if preset in {"liquidity", "sharpe"} and (
            (preset == "liquidity" and asset["stale"] and settings().data_mode == "live")
            or (preset == "sharpe" and data.get("sharpe") is None)
        ):
            excluded.append(
                {"asset_id": asset["id"], "reason": "Required preset metric unavailable or stale"}
            )
            continue
        if not data["eligible"] or float(asset.get("total_volume") or 0) < min_volume:
            excluded.append(
                {
                    "asset_id": asset["id"],
                    "reason": data.get("reason") or "Below minimum quoted USD volume",
                }
            )
            continue
        included.append(
            {
                k: v
                for k, v in data.items()
                if k not in ("series", "rolling", "simple_returns", "log_returns")
            }
        )
    for key in ("annualized_volatility", "max_drawdown"):
        values = [abs(r[key]) for r in included]
        lo, hi = (min(values), max(values)) if values else (0, 0)
        for row in included:
            row[key + "_normalized"] = (abs(row[key]) - lo) / (hi - lo) if hi > lo else 0
    for row in included:
        row["score"] = 100 * (
            volatility_weight * row["annualized_volatility_normalized"]
            + (1 - volatility_weight) * row["max_drawdown_normalized"]
        )
    for row in included:
        if preset == "volatility":
            row["score"] = row["annualized_volatility"]
        elif preset == "drawdown":
            row["score"] = abs(row["max_drawdown"])
        elif preset == "liquidity":
            row["score"] = -row["reported_volume_usd"]
        elif preset == "sharpe":
            row["score"] = -row["sharpe"]
    return {
        "preset": preset,
        "score_units": "relative composite points"
        if preset == "balanced"
        else "decimal volatility/drawdown; negative USD volume or negative ratio for descending presets",
        "version": "rank-v2",
        "days": days,
        "volatility_weight": volatility_weight,
        "methodology": {
            "balanced": "Universe min-max volatility and absolute drawdown; lower is lower relative historical risk.",
            "volatility": "Annualized daily volatility ascending.",
            "drawdown": "Absolute maximum historical drawdown ascending.",
            "liquidity": "Negative fresh reported USD volume; descending volume is a liquidity proxy, not executable depth.",
            "sharpe": "Negative historical Sharpe with explicit annual risk-free assumption; descending Sharpe.",
        }[preset]
        + " Not a forecast.",
        "rankings": sorted(included, key=lambda r: (r["score"], r["asset_id"])),
        "excluded": excluded,
    }


@traced("compare")
def compare(asset_ids: list[str], days: int) -> dict[str, Any]:
    return {
        "results": [risk(a, days) for a in asset_ids],
        "correlation": correlation({a: candles(a, days) for a in asset_ids}),
    }


def defi() -> dict[str, Any]:
    with Session() as db:
        rows = db.scalars(select(DefiMetric).where(DefiMetric.id != "global-market")).all()
        return {
            "metrics": [
                {"id": r.id, "observed_at": r.observed_at.isoformat(), **r.data} for r in rows
            ],
            "limitation": "Chain TVL is not token value or protocol revenue.",
        }
