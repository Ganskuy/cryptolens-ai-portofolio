import asyncio
import hashlib
import json
import logging
import secrets
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import delete, select, text

from app import admission, ai, auth, services
from app import telemetry as tm
from app.config import settings
from app.db import AnalyticsSnapshot, ChatMessage, ChatSession, Session, engine

log = logging.getLogger("cryptolens")
logging.basicConfig(level=logging.INFO, format="%(message)s")
redis = Redis.from_url(
    settings().redis_url, decode_responses=True, socket_connect_timeout=1, socket_timeout=2
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await redis.aclose()
    engine.dispose()


app = FastAPI(title="CryptoLens AI", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings().allowed_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)


@app.middleware("http")
async def boundary(request: Request, call_next):
    ident = str(uuid.uuid4())
    if request.method in ("POST", "DELETE"):
        origin = request.headers.get("origin")
        if origin and origin != settings().allowed_origin:
            return JSONResponse({"error": "Origin rejected", "request_id": ident}, status_code=403)
    # Read bounded bodies including chunked transfer encoding.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            return JSONResponse(
                {"error": "Request too large", "request_id": ident}, status_code=413
            )
    request._body = bytes(body)
    token = request.cookies.get("cryptolens_owner")
    if token is None or len(token) != 64:
        token = secrets.token_hex(32)
    request.state.owner = hashlib.sha256(token.encode()).hexdigest()
    request.state.request_id = ident
    request.state.user = None
    public_paths = {
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/config",
    }
    if settings().auth_mode == "required":
        try:
            principal = await asyncio.to_thread(
                auth.principal, request.cookies.get("cryptolens_session")
            )
        except Exception:
            return JSONResponse({"error": "Authentication unavailable"}, status_code=503)
        request.state.user = principal
        if request.url.path not in public_paths:
            if principal is None:
                return JSONResponse({"error": "Authentication required"}, status_code=401)
            request.state.owner = principal["id"]
            if request.method in ("POST", "DELETE", "PUT", "PATCH"):
                csrf = request.headers.get("X-CSRF-Token", "")
                try:
                    verified = await asyncio.to_thread(
                        auth.principal, request.cookies.get("cryptolens_session"), csrf
                    )
                    if verified is None:
                        raise auth.AuthError("Session expired")
                except auth.AuthError:
                    return JSONResponse({"error": "CSRF verification failed"}, status_code=403)
            if "/ai/chat" in request.url.path and principal["role"] == "reader":
                return JSONResponse({"error": "Researcher role required"}, status_code=403)
            if request.url.path == "/metrics" and principal["role"] != "admin":
                return JSONResponse({"error": "Administrator role required"}, status_code=403)
    try:
        # Do not trust forwarded IP headers; local MVP uses direct client address.
        ip = (
            request.state.user["id"]
            if request.state.user
            else (request.client.host if request.client else "unknown")
        )
        key = f"rate:{hashlib.sha256(ip.encode()).hexdigest()}:{int(time.time()) // 60}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 65)
        if count > 120:
            return JSONResponse(
                {"error": "Rate limit exceeded", "request_id": ident}, status_code=429
            )
    except Exception:
        if "/ai/chat" in request.url.path:
            return JSONResponse(
                {"error": "AI admission unavailable", "request_id": ident}, status_code=503
            )
    try:
        response = await call_next(request)
    except Exception as exc:
        log.error(json.dumps({"request_id": ident, "error_type": type(exc).__name__}))
        response = JSONResponse(
            {"error": "Service temporarily unavailable", "request_id": ident}, status_code=503
        )
    if settings().auth_mode == "local" and request.cookies.get("cryptolens_owner") != token:
        response.set_cookie(
            "cryptolens_owner",
            token,
            httponly=True,
            secure=settings().cookie_secure,
            samesite="strict",
            max_age=2592000,
        )
    return response


@app.middleware("http")
async def observe(request: Request, call_next):
    started = time.perf_counter()
    trace_token = tm.trace_id.set(uuid.uuid4().hex)
    try:
        response = await call_next(request)
        route = getattr(request.scope.get("route"), "path", "unmatched")
        tm.REQUESTS.labels(
            route,
            request.method
            if request.method in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
            else "OTHER",
            str(response.status_code),
        ).inc()
        tm.LATENCY.labels(route).observe(time.perf_counter() - started)
        response.headers["traceparent"] = (
            "00-" + tm.trace_id.get() + "-" + secrets.token_hex(8) + "-01"
        )
        response.headers["X-Request-ID"] = getattr(request.state, "request_id", str(uuid.uuid4()))
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        log.info(
            json.dumps(
                {
                    "request_id": response.headers["X-Request-ID"],
                    "trace_id": tm.trace_id.get(),
                    "method": request.method,
                    "route": route,
                    "status": response.status_code,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            )
        )
        return response
    finally:
        tm.trace_id.reset(trace_token)


@app.exception_handler(ValueError)
async def invalid(request: Request, exc: ValueError):
    return JSONResponse(
        {"error": str(exc)[:200], "request_id": request.state.request_id}, status_code=422
    )


@app.get("/api/v1/health/live")
def live():
    return {"status": "alive"}


@app.get("/api/v1/health/ready")
async def ready():
    def db_check():
        with engine.connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0002"

    try:
        database, cache = await asyncio.gather(asyncio.to_thread(db_check), redis.ping())
        if not database or not cache:
            raise RuntimeError("not ready")
        return {
            "status": "ready",
            "mode": settings().data_mode,
            "ai_enabled": settings().ai_enabled,
            "worker_last_poll": await redis.get("worker:last_poll"),
        }
    except Exception:
        raise HTTPException(503, "Database or Redis unavailable") from None


@app.get("/api/v1/market/overview")
async def market():
    key = "overview:" + settings().data_mode
    try:
        cached = await redis.get(key)
        if cached:
            tm.CACHE.labels("hit").inc()
            return json.loads(cached)
        tm.CACHE.labels("miss").inc()
    except Exception:
        tm.CACHE.labels("error").inc()
    result = await asyncio.to_thread(services.overview)
    try:
        await redis.set(key, json.dumps(result), ex=15)
    except Exception:
        pass
    return result


@app.get("/api/v1/assets")
def assets(
    q: str = Query("", max_length=100),
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
):
    rows = services.overview()["assets"]
    filtered = [
        r for r in rows if q.lower() in (r["name"] + " " + r["symbol"] + " " + r["id"]).lower()
    ]
    return {"items": filtered[offset : offset + limit], "total": len(filtered)}


@app.get("/api/v1/assets/{asset_id}")
def asset(asset_id: str):
    found = next((a for a in services.overview()["assets"] if a["id"] == asset_id), None)
    if found is None:
        raise HTTPException(404, "Unknown asset")
    return found


@app.get("/api/v1/assets/{asset_id}/candles")
def candle_data(asset_id: str, days: int = Query(90, ge=1, le=1826)):
    return {
        "asset_id": asset_id,
        "source": services.source(),
        "interval": "1d",
        "quote": "USDT" if settings().data_mode == "live" else "synthetic",
        "candles": services.candles(asset_id, days),
    }


@app.get("/api/v1/assets/{asset_id}/fundamentals")
def fundamental_data(asset_id: str):
    return services.fundamentals(asset_id)


@app.get("/api/v1/analytics/risk")
def risk(
    asset_id: str = "bitcoin",
    days: int = Query(90, ge=30, le=1826),
    risk_free: float | None = Query(None, ge=0, le=1),
):
    return services.risk(asset_id, days, risk_free)


@app.get("/api/v1/analytics/rankings")
def rankings(
    days: int = Query(90, ge=30, le=1826),
    volatility_weight: float = Query(0.5, ge=0, le=1),
    min_volume: float = Query(0, ge=0),
    preset: str = Query("balanced", pattern="^(balanced|volatility|drawdown|liquidity|sharpe)$"),
    risk_free: float | None = Query(None, ge=0, le=1),
):
    return services.rankings(days, volatility_weight, min_volume, preset, risk_free)


class CompareRequest(BaseModel):
    asset_ids: list[str] = Field(min_length=2, max_length=5)
    days: int = Field(90, ge=30, le=1826)


@app.post("/api/v1/analytics/compare")
def compare(body: CompareRequest):
    if len(set(body.asset_ids)) != len(body.asset_ids):
        raise ValueError("Duplicate assets")
    return services.compare(body.asset_ids, body.days)


@app.get("/api/v1/defi")
def defi():
    return services.defi()


@app.get("/api/v1/ai/sessions")
def sessions(request: Request):
    with Session() as db:
        rows = db.scalars(
            select(ChatSession)
            .where(ChatSession.owner == request.state.owner)
            .order_by(ChatSession.created_at.desc())
            .limit(50)
        ).all()
        return {"sessions": [{"id": s.id, "created_at": s.created_at.isoformat()} for s in rows]}


def owned(db, session_id: str, owner: str):
    session = db.get(ChatSession, session_id)
    if not session or session.owner != owner:
        raise HTTPException(404, "Session not found")
    return session


@app.get("/api/v1/ai/sessions/{session_id}")
def history(session_id: str, request: Request):
    with Session() as db:
        owned(db, session_id, request.state.owner)
        rows = db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
            .limit(100)
        ).all()
        return {
            "messages": [
                {"role": r.role, "data": r.data, "created_at": r.created_at.isoformat()}
                for r in rows
            ]
        }


@app.delete("/api/v1/ai/sessions/{session_id}", status_code=204)
def remove_session(session_id: str, request: Request):
    with Session.begin() as db:
        session = owned(db, session_id, request.state.owner)
        db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
        db.delete(session)
    return Response(status_code=204)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1500)
    session_id: str | None = Field(None, max_length=36)
    request_id: str = Field(min_length=16, max_length=64)


def prepare_chat(body: ChatRequest, owner: str):
    with Session.begin() as db:
        sid = body.session_id or str(uuid.uuid4())
        if body.session_id:
            owned(db, sid, owner)
        else:
            db.add(ChatSession(id=sid, owner=owner))
            db.flush()
        prior = db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == sid)
            .order_by(ChatMessage.created_at.desc())
            .limit(4)
        ).all()
        history = [
            {
                "role": m.role,
                "content": str(m.data.get("message") or m.data.get("answer") or "")[:800],
            }
            for m in reversed(prior)
        ]
        db.add(
            ChatMessage(
                id=str(uuid.uuid4()), session_id=sid, role="user", data={"message": body.message}
            )
        )
        return sid, history


@app.post("/api/v1/ai/chat/stream")
async def chat(body: ChatRequest, request: Request):
    if not settings().ai_enabled:
        raise HTTPException(503, "AI disabled; configure backend credentials and AI_ENABLED")
    owner = request.state.owner
    lock_token = str(uuid.uuid4())
    try:
        request_key = await asyncio.to_thread(admission.claim, owner, body.request_id, lock_token)
    except admission.AdmissionError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    try:
        sid, prior = await asyncio.to_thread(prepare_chat, body, owner)
    except Exception:
        await asyncio.to_thread(admission.finish, request_key, lock_token, "failed")
        raise

    async def stream():
        queue: asyncio.Queue = asyncio.Queue(maxsize=16)

        async def progress(stage: str):
            await queue.put({"stage": stage, "session_id": sid})

        async def run():
            try:
                async with asyncio.timeout(110):
                    result = await ai.analyze(body.message, progress, prior)

                    def save():
                        with Session.begin() as db:
                            db.add(
                                ChatMessage(
                                    id=str(uuid.uuid4()),
                                    session_id=sid,
                                    role="assistant",
                                    data=result,
                                )
                            )

                    await asyncio.to_thread(save)
                    # Only backend-approved prose is streamed, after full validation.
                    for start in range(0, len(result["answer"]), 80):
                        await queue.put(
                            {
                                "stage": "validated_text",
                                "chunk": result["answer"][start : start + 80],
                                "session_id": sid,
                            }
                        )
                    tm.AI_EVENTS.labels("completed").inc()
                    await queue.put({"stage": "completed", "result": result, "session_id": sid})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning(
                    json.dumps(
                        {
                            "event": "ai_failed",
                            "request_id": request.state.request_id,
                            "type": type(exc).__name__,
                        }
                    )
                )
                await queue.put(
                    {
                        "stage": "failed",
                        "error": str(exc)[:150]
                        if isinstance(exc, ValueError)
                        else "AI request failed; check provider availability or budget",
                        "session_id": sid,
                    }
                )

        task = asyncio.create_task(run())
        try:
            yield "data: " + json.dumps({"stage": "received", "session_id": sid}) + "\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), 1)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                yield "data: " + json.dumps(event, default=str) + "\n\n"
                if event["stage"] in ("completed", "failed"):
                    break
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await asyncio.to_thread(admission.finish, request_key, lock_token, "finished")

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.websocket("/api/v1/stream/market")
async def market_stream(ws: WebSocket):
    if ws.headers.get("origin") not in (None, settings().allowed_origin):
        await ws.close(code=1008)
        return
    if settings().auth_mode == "required" and not await asyncio.to_thread(
        auth.principal, ws.cookies.get("cryptolens_session")
    ):
        await ws.close(code=1008)
        return
    await ws.accept()
    try:
        # Poll bounded latest-value cache: slow consumers cannot accumulate ticks.
        while True:
            if settings().auth_mode == "required" and not await asyncio.to_thread(
                auth.principal, ws.cookies.get("cryptolens_session")
            ):
                await ws.close(code=1008)
                return
            data = await redis.mget(["tick:" + a for a in sorted(services.IDS)])
            await asyncio.wait_for(
                ws.send_json(
                    {"ticks": [json.loads(d) for d in data if d], "mode": settings().data_mode}
                ),
                5,
            )
            await asyncio.sleep(2)
    except (WebSocketDisconnect, TimeoutError):
        pass
    except Exception:
        await ws.close(code=1013)


@app.get("/api/v1/datasets/{dataset_id}")
def dataset(dataset_id: str):
    if len(dataset_id) != 20 or any(c not in "0123456789abcdef" for c in dataset_id):
        raise HTTPException(404, "Dataset not found")
    with Session() as db:
        row = db.get(AnalyticsSnapshot, dataset_id)
        if row is None:
            raise HTTPException(404, "Dataset not found")
        return row.data


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=1, max_length=256)


login_semaphore = asyncio.Semaphore(1)


@app.post("/api/v1/auth/login")
async def login(body: LoginRequest, request: Request, response: Response):
    if request.headers.get("origin") != settings().allowed_origin:
        raise HTTPException(403, "Origin required")
    ip = request.client.host if request.client else "unknown"
    key = "login:" + auth.digest(ip) + ":" + str(int(time.time()) // 60)
    try:
        attempts = await redis.incr(key)
        if attempts == 1:
            await redis.expire(key, 65)
        if attempts > 5:
            raise HTTPException(429, "Login rate limit exceeded")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Login admission unavailable") from None
    try:
        async with login_semaphore:
            token, csrf, user = await asyncio.to_thread(auth.login, body.username, body.password)
    except auth.AuthError:
        raise HTTPException(401, "Invalid username or password") from None
    response.set_cookie(
        "cryptolens_session",
        token,
        httponly=True,
        secure=settings().cookie_secure,
        samesite="strict",
        max_age=43200,
    )
    response.set_cookie(
        "cryptolens_csrf",
        csrf,
        httponly=False,
        secure=settings().cookie_secure,
        samesite="strict",
        max_age=43200,
    )
    return {"user": user}


@app.get("/api/v1/auth/me")
async def me(request: Request):
    return {
        "mode": settings().auth_mode,
        "user": await asyncio.to_thread(auth.principal, request.cookies.get("cryptolens_session")),
    }


@app.post("/api/v1/auth/logout", status_code=204)
async def logout(request: Request):
    await asyncio.to_thread(auth.logout, request.cookies.get("cryptolens_session"))
    response = Response(status_code=204)
    response.delete_cookie("cryptolens_session")
    response.delete_cookie("cryptolens_csrf")
    return response


@app.get("/api/v1/config")
def public_config():
    return {
        "auth_mode": settings().auth_mode,
        "market_ws_url": settings().market_ws_url,
        "ai_mode": settings().ai_mode,
        "ai_enabled": settings().ai_enabled,
    }


@app.get("/metrics")
def metrics_endpoint():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/v1/universe")
def universe(
    q: str = Query("", max_length=100),
    offset: int = Query(0, ge=0, le=20000),
    limit: int = Query(100, ge=1, le=500),
):
    from app.market_extra import universe

    return universe(q, offset, limit)


@app.get("/api/v1/assets/{asset_id}/metadata-history")
def metadata_archive(asset_id: str, days: int = Query(90, ge=1, le=1826)):
    from app.market_extra import metadata_history

    return metadata_history(asset_id, days)


@app.get("/api/v1/assets/{asset_id}/hourly")
def hourly_data(asset_id: str, hours: int = Query(72, ge=2, le=2160)):
    from app.market_extra import hourly

    rows = hourly(asset_id, hours)
    # Return observations and technical indicators. Daily annualization is never
    # applied to hourly returns by pretending their timestamps are daily.
    from app.indicators import indicators

    returns = [
        {"time": b["time"], "return": b["close"] / a["close"] - 1}
        for a, b in zip(rows, rows[1:])
        if b["time"] - a["time"] == 3600
    ]
    return {
        "asset_id": asset_id,
        "source": services.source(),
        "interval": "1h",
        "candles": rows,
        "returns": returns,
        "coverage": len(returns) / hours,
        "indicators": indicators(rows, interval_seconds=3600),
    }


@app.get("/api/v1/assets/{asset_id}/indicators")
def technical_data(
    asset_id: str, days: int = Query(90, ge=30, le=1826), period: int = Query(14, ge=2, le=200)
):
    from app.indicators import indicators

    return {
        "asset_id": asset_id,
        "source": services.source(),
        **indicators(services.candles(asset_id, days), period),
    }


@app.get("/api/v1/research/{asset_id}")
def asset_research(asset_id: str):
    from app.market_extra import research

    return research(asset_id)


@app.get("/api/v1/defi/aave")
def aave_research():
    from app.market_extra import protocol_valuation

    return protocol_valuation()
