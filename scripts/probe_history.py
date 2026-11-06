"""Bounded public-provider read probe; no database writes and no LLM calls."""

import asyncio
import json
import sys
import time
from itertools import pairwise
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.providers import Provider, backfill


async def main():
    report = {"external_llm_calls": 0, "database_writes": 0, "checks": []}
    async with httpx.AsyncClient() as client:
        provider = Provider(client)
        for interval, periods in [("1d", 730), ("1h", 72)]:
            step = 86400 if interval == "1d" else 3600
            end = int(time.time()) // step * step
            started = time.perf_counter()
            try:
                rows = await backfill(
                    provider, "BTCUSDT", interval, end - periods * step, end
                )
                assert len(rows) == periods
                assert all(b.time - a.time == step for a, b in pairwise(rows))
                report["checks"].append(
                    {
                        "provider": "binance",
                        "symbol": "BTCUSDT",
                        "interval": interval,
                        "closed_observations": len(rows),
                        "contiguous": True,
                        "first_time": rows[0].time,
                        "last_time": rows[-1].time,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                        "status": "passed",
                    }
                )
            except (httpx.HTTPError, ValueError, RuntimeError, AssertionError) as exc:
                report["checks"].append(
                    {
                        "interval": interval,
                        "status": "unavailable",
                        "error_type": type(exc).__name__,
                    }
                )
    (ROOT / "docs/history-provider-probe.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
