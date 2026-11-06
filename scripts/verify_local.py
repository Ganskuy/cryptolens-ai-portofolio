"""Bounded HTTPS, account isolation, Redis recovery and concurrent-read verification.

Requires the isolated fixture deployment described in docs/DEPLOYMENT.md. Never
invokes external LLMs. Credentials and local CA are read from ignored .local files.
"""

import asyncio
import json
import ssl
import statistics
import subprocess
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://localhost:8443"
COMPOSE = [
    "docker",
    "compose",
    "-p",
    "cryptolens",
    "-f",
    str(ROOT / "docker-compose.yml"),
    "-f",
    str(ROOT / "compose.local-tls.yml"),
    "-f",
    str(ROOT / ".local/verify.yml"),
]


def command(*args, data=None):
    return subprocess.run(
        [*COMPOSE, *args],
        cwd=ROOT,
        input=data,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


async def main():
    # Fail closed before any fixture writes or service fault injection.
    check = command(
        "exec",
        "-T",
        "backend",
        "python",
        "-c",
        "from app.config import settings; c=settings(); assert c.database_url.rsplit('/',1)[-1].startswith('cryptolens_verify_'); assert c.data_mode=='fixture' and not c.ai_narration and not c.openrouter_api_key.get_secret_value(); print('isolated')",
    )
    assert check.strip() == "isolated"
    tls = ssl.create_default_context(cafile=str(ROOT / ".local/caddy-root.crt"))
    accounts = json.loads((ROOT / ".local/accounts.json").read_text())
    clients = [
        httpx.AsyncClient(base_url=BASE, verify=tls, timeout=20) for _ in accounts
    ]
    anonymous = httpx.AsyncClient(base_url=BASE, verify=tls, timeout=20)
    results = {}
    try:
        assert (await anonymous.get("/api/v1/market/overview")).status_code == 401
        assert (await anonymous.get("/metrics")).status_code == 404
        for client, account in zip(clients, accounts):
            response = await client.post(
                "/api/v1/auth/login",
                headers={"Origin": BASE},
                json={"username": account["username"], "password": account["password"]},
            )
            assert response.status_code == 200, response.status_code
            assert "HttpOnly" in response.headers.get_list("set-cookie")[0]
            assert "Secure" in response.headers.get_list("set-cookie")[0]
            client.headers.update(
                {"Origin": BASE, "X-CSRF-Token": client.cookies["cryptolens_csrf"]}
            )
        admin, researcher, reader = clients
        body = {
            "message": "Analyze Bitcoin historical risk",
            "request_id": str(uuid.uuid4()),
        }
        assert (
            await reader.post("/api/v1/ai/chat/stream", json=body)
        ).status_code == 403
        assert (
            await researcher.post(
                "/api/v1/analytics/compare",
                headers={"X-CSRF-Token": "invalid"},
                json={"asset_ids": ["bitcoin", "ethereum"], "days": 90},
            )
        ).status_code == 403
        assert (
            await researcher.post(
                "/api/v1/analytics/compare",
                headers={"Origin": "https://untrusted.invalid"},
                json={},
            )
        ).status_code == 403
        assert (
            await researcher.post("/api/v1/ai/chat/stream", content="x" * 17000)
        ).status_code == 413
        response = await researcher.post("/api/v1/ai/chat/stream", json=body)
        assert response.status_code == 200
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        final = events[-1]
        assert final["stage"] == "completed", final.get("error")
        assert final["result"]["freshness"] == "fixture"
        assert "".join(e.get("chunk", "") for e in events) == final["result"]["answer"]
        session = final["session_id"]
        assert (await admin.get(f"/api/v1/ai/sessions/{session}")).status_code == 404
        assert (
            await researcher.get(f"/api/v1/ai/sessions/{session}")
        ).status_code == 200
        results["accounts_csrf_roles_isolation_validated_sse"] = "passed"

        # Real Redis stop/start, with bounded restoration even if an assertion fails.
        await asyncio.to_thread(command, "stop", "redis")
        try:
            assert (await researcher.get("/api/v1/health/ready")).status_code == 503
            assert (
                await researcher.post("/api/v1/ai/chat/stream", json=body)
            ).status_code == 503
            fallback = await researcher.get("/api/v1/market/overview")
            assert fallback.status_code == 200
        finally:
            await asyncio.to_thread(command, "start", "redis")
        for _ in range(20):
            if (await anonymous.get("/api/v1/health/ready")).status_code == 200:
                break
            await asyncio.sleep(1)
        assert (
            await researcher.post("/api/v1/ai/chat/stream", json=body)
        ).status_code == 409
        results["redis_restart_durable_idempotency_read_fallback"] = "passed"

        latencies, statuses = [], []
        semaphore = asyncio.Semaphore(6)

        async def read(client, path):
            async with semaphore:
                started = time.perf_counter()
                response = await client.get(path)
                latencies.append((time.perf_counter() - started) * 1000)
                statuses.append(response.status_code)

        paths = [
            "/api/v1/market/overview",
            "/api/v1/analytics/risk?asset_id=bitcoin&days=90",
            "/api/v1/universe?limit=100",
        ]
        await asyncio.gather(*(read(clients[i % 3], paths[i % 3]) for i in range(90)))
        assert all(status == 200 for status in statuses), {
            s: statuses.count(s) for s in set(statuses)
        }
        results["load"] = {
            "users": 3,
            "concurrency": 6,
            "requests": 90,
            "errors": 0,
            "median_ms": round(statistics.median(latencies), 2),
            "p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 2),
            "max_ms": round(max(latencies), 2),
            "scope": "Local fixture HTTPS, cached overview, analytical DB reads and discovery; not production capacity",
        }
        assert (await researcher.post("/api/v1/auth/logout")).status_code == 204
        assert (await researcher.get("/api/v1/market/overview")).status_code == 401
        results["logout_revocation"] = "passed"
        result = command(
            "exec",
            "-T",
            "backend",
            "python",
            "-c",
            "from sqlalchemy import select,func; from app.db import Session,AIUsage; s=Session(); assert s.scalar(select(func.count()).select_from(AIUsage))==0; print('zero')",
        )
        assert result.strip() == "zero"
        results["external_llm_calls"] = 0
        (ROOT / "docs/local-integration-results.json").write_text(
            json.dumps(results, indent=2) + "\n"
        )
        print(json.dumps(results, indent=2))
    finally:
        await asyncio.gather(*(c.aclose() for c in [*clients, anonymous]))


if __name__ == "__main__":
    asyncio.run(main())
