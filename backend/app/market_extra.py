"""Bounded history, provider-wide discovery and explicitly scoped fundamental research."""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.config import settings
from app.db import AnalyticsSnapshot, HourlyCandle, MetadataHistory, Session, UniverseAsset, now
from app.providers import MarketInput, Provider
from app.registry import IDS


async def universe_poll(provider: Provider) -> int:
    count = 0
    for page in range(1, settings().universe_pages + 1):
        rows = await provider.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 250,
                "page": page,
                "sparkline": "false",
            },
        )
        if not isinstance(rows, list):
            raise ValueError("Invalid market universe response")

        def save():
            with Session.begin() as db:
                for row in rows:
                    try:
                        valid = MarketInput.model_validate(row)
                    except ValueError:
                        continue
                    if not 1 <= len(valid.id) <= 100:
                        continue
                    observed = datetime.fromisoformat(row["last_updated"].replace("Z", "+00:00"))
                    if observed.tzinfo is None or observed > now() + timedelta(minutes=5):
                        continue
                    data = {
                        k: row.get(k)
                        for k in (
                            "current_price",
                            "market_cap",
                            "market_cap_rank",
                            "total_volume",
                            "price_change_percentage_24h",
                        )
                    }
                    db.merge(
                        UniverseAsset(
                            id=row["id"],
                            symbol=str(row.get("symbol", ""))[:40],
                            name=str(row.get("name", ""))[:160],
                            observed_at=observed,
                            data=data,
                        )
                    )

        await asyncio.to_thread(save)
        count += len(rows)
        if len(rows) < 250:
            break
        await asyncio.sleep(2)
    return count


def universe(q: str, offset: int, limit: int) -> dict:
    with Session() as db:
        query = select(UniverseAsset)
        if q:
            # Escape LIKE wildcards: search is literal, not a query language.
            pattern = (
                "%" + q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            )
            query = query.where(
                (func.lower(UniverseAsset.name).like(pattern, escape="\\"))
                | (func.lower(UniverseAsset.symbol).like(pattern, escape="\\"))
                | (UniverseAsset.id.like(pattern, escape="\\"))
            )
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.scalars(query.order_by(UniverseAsset.id).offset(offset).limit(limit)).all()
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "source": "synthetic-fixture" if settings().data_mode == "fixture" else "coingecko",
            "mode": settings().data_mode,
            "coverage_limit": settings().universe_pages * 250,
            "items": [
                {
                    "id": r.id,
                    "symbol": r.symbol,
                    "name": r.name,
                    "observed_at": r.observed_at.isoformat(),
                    "stale": r.observed_at.replace(tzinfo=timezone.utc)
                    < now() - timedelta(hours=2),
                    "analytics_supported": r.id in IDS,
                    **r.data,
                }
                for r in rows
            ],
        }


def metadata_history(asset_id: str, days: int) -> dict:
    if asset_id not in IDS:
        raise ValueError("Unknown canonical asset")
    with Session() as db:
        rows = db.scalars(
            select(MetadataHistory)
            .where(
                MetadataHistory.asset_id == asset_id,
                MetadataHistory.observed_at >= now() - timedelta(days=days),
            )
            .order_by(MetadataHistory.observed_at)
            .limit(5000)
        ).all()
        return {
            "asset_id": asset_id,
            "source": "coingecko",
            "rows": [{"observed_at": r.observed_at.isoformat(), **r.data} for r in rows],
            "limitation": "History starts at first successful capture; pre-capture supply/rank metadata is unavailable.",
        }


def hourly(asset_id: str, hours: int) -> list[dict]:
    if asset_id not in IDS:
        raise ValueError("Unknown canonical asset")
    src = "synthetic-fixture" if settings().data_mode == "fixture" else "binance"
    with Session() as db:
        rows = db.scalars(
            select(HourlyCandle)
            .where(HourlyCandle.asset_id == asset_id, HourlyCandle.source == src)
            .order_by(HourlyCandle.time.desc())
            .limit(hours + 1)
        ).all()
        return [
            {
                "time": r.time,
                **{
                    key: float(getattr(r, key))
                    for key in ("open", "high", "low", "close", "volume")
                },
            }
            for r in reversed(rows)
        ]


def archive_snapshots() -> dict:
    """Delete expired reproducible snapshots, preserving datasets cited by retained chats."""

    from sqlalchemy import delete

    from app.db import ChatMessage

    with Session.begin() as db:
        # Chart references are explicit allowlisted IDs. Retained chat count is bounded by retention.
        referenced = set()
        for data in db.scalars(select(ChatMessage.data).where(ChatMessage.role == "assistant")):
            for chart in data.get("charts", []):
                if isinstance(chart, dict) and isinstance(chart.get("dataset_id"), str):
                    referenced.add(chart["dataset_id"])
        query = delete(AnalyticsSnapshot).where(
            AnalyticsSnapshot.created_at
            < now() - timedelta(days=settings().analytics_retention_days)
        )
        if referenced:
            query = query.where(AnalyticsSnapshot.id.not_in(referenced))
        removed = len(db.execute(query.returning(AnalyticsSnapshot.id)).all())
        return {"removed": removed, "preserved_referenced": len(referenced)}


# Reviewed qualitative risk dimensions, not fabricated issuer scores or solvency attestations.
RESEARCH = {
    "usd-coin": {
        "scope": "issuer-backed stablecoin",
        "reviewed_at": "2026-10-27",
        "dimensions": [
            {
                "risk": "issuer and redemption",
                "assessment": "Redemption depends on issuer terms and access; a market peg is not a redemption guarantee.",
            },
            {
                "risk": "reserve custody and counterparties",
                "assessment": "Reserve composition and banking/custody exposures require current issuer disclosures; no solvency score is inferred.",
            },
            {
                "risk": "concentration and chain",
                "assessment": "Issuer concentration and the security of the selected chain/bridge affect risk independently of historical volatility.",
            },
        ],
        "sources": ["https://www.circle.com/transparency"],
        "status": "qualitative research; reserve composition not independently audited by this application",
    },
    "aave": {
        "scope": "lending protocol and governance token",
        "reviewed_at": "2026-10-27",
        "dimensions": [
            {
                "risk": "smart contracts and oracle",
                "assessment": "Contract, oracle and liquidation failures can affect supplied capital.",
            },
            {
                "risk": "governance and counterparties",
                "assessment": "Parameter changes, collateral concentration and connected infrastructure affect protocol risk.",
            },
        ],
        "sources": ["https://www.aave.com/docs/resources/risks", "https://aave.com/faq"],
        "status": "qualitative risk inventory; not a numeric rating",
    },
}


def research(asset_id: str) -> dict:
    return {
        "asset_id": asset_id,
        **RESEARCH.get(
            asset_id,
            {
                "status": "No reviewed issuer/protocol assessment available",
                "dimensions": [],
                "sources": [],
            },
        ),
    }


def protocol_valuation() -> dict:
    from app.db import DefiMetric

    with Session() as db:
        tvl = db.get(DefiMetric, "protocol:aave")
        token = db.get(UniverseAsset, "aave")
        cap = float(token.data.get("market_cap") or 0) if token else 0
        history = tvl.data.get("history", []) if tvl else []
        # TVL is a historical observation; retrieval time cannot make it current.
        observed = history[-1].get("date") if history else None
        tvl_current = (
            isinstance(observed, (int, float))
            and now().timestamp() - 7200 < observed <= now().timestamp() + 300
        )
        fresh = bool(
            tvl_current
            and token
            and tvl
            and token.observed_at.replace(tzinfo=timezone.utc) > now() - timedelta(hours=2)
            and tvl.observed_at.replace(tzinfo=timezone.utc) > now() - timedelta(hours=2)
        )
        value = tvl.data.get("tvl_usd") if tvl else None
        return {
            "protocol_id": "aave",
            "token_id": "aave",
            "mapping_version": "reviewed-aave-v1",
            "mapping_source": "https://aave.com/faq",
            "tvl_to_market_cap": float(value) / cap
            if fresh and value is not None and float(value) >= 0 and cap > 0
            else None,
            "fresh": fresh,
            "tvl_observed_at": observed,
            "meaning": "Protocol TVL divided by governance-token market cap; TVL is not token-holder revenue or an ownership claim.",
            "research": research("aave"),
        }
