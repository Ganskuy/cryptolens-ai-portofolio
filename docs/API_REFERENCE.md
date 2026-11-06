# API reference

REST prefix `/api/v1`. HTTP development OpenAPI: `http://localhost:8100/docs`.
The local TLS gateway exposes only the application and `/api/*`, not OpenAPI or metrics.

| Method/path | Purpose and limits |
|---|---|
| GET /health/live, /health/ready | Process liveness; PostgreSQL revision 0002 plus Redis readiness |
| GET /config | Auth/AI modes, enabled flag and runtime WebSocket URL; no secrets |
| POST /auth/login | Username/password, mandatory exact Origin, five attempts/IP/minute |
| GET /auth/me | Current account or null, auth mode |
| POST /auth/logout | Revoke session, clear cookies; CSRF required in account mode |
| GET /market/overview | Curated market/global data, timestamps, mode; 15-second cache |
| GET /assets, /assets/{id} | Reviewed analytic identities; search/pagination on collection |
| GET /universe | Captured provider discovery: q <=100 chars, offset <=20000, limit 1–500, coverage limit and analytic-support flags |
| GET /assets/{id}/candles | Finalized daily data, days 1–1826 |
| GET /assets/{id}/hourly | Finalized hourly data, hours 2–2160, contiguous returns/coverage and indicators |
| GET /assets/{id}/indicators | Daily SMA/EMA/RSI/MACD, days 30–1826, period 2–200, null warm-up values |
| GET /assets/{id}/metadata-history | Captured CoinGecko history, days 1–1826, bounded to 5000 observations; no invented earlier metadata |
| GET /assets/{id}/fundamentals | Source supply/cap/volume and deterministic ratios |
| GET /analytics/risk | asset_id, days 30–1826, optional risk_free 0–1 annual decimal |
| GET /analytics/rankings | Same period, volatility_weight 0–1, min_volume >=0, balanced/volatility/drawdown/liquidity/sharpe preset; Sharpe requires risk_free |
| POST /analytics/compare | 2–5 distinct canonical IDs, days 30–1826 |
| GET /datasets/{id} | Content-addressed numerical chart dataset |
| GET /defi, /defi/aave | Explicit chain/protocol observations; reviewed Aave token mapping and freshness-gated TVL/cap ratio |
| GET /research/{id} | Reviewed qualitative issuer/protocol dimensions or explicit unavailable assessment |
| GET /ai/sessions, /ai/sessions/{id} | Current owner's latest 50 sessions; at most 100 messages per session |
| DELETE /ai/sessions/{id} | Owner-scoped deletion |
| POST /ai/chat/stream | message 1–1500 chars, optional session_id, unique request_id 16–64 chars |
| WS /stream/market | Latest cached prices every two seconds; account revalidation and bounded send timeout |
| GET /metrics (no REST prefix) | Internal Prometheus endpoint; admin session in account mode |

Mutation requests in account mode need `X-CSRF-Token` from the CSRF cookie. `reader` cannot
start AI requests. Authenticated rate limits are per account; anonymous mode uses direct
client IP. Reverse-proxy forwarded identity headers are not trusted.

SSE `data:` JSON has stage/session_id; `validated_text` adds an approved `chunk` and
`completed` adds the complete report. Heartbeats are comments. Cancellation uses browser
AbortController. Previously admitted IDs return 409 even after Redis restarts; a new request
needs a new ID. Disabled/unavailable admission returns 503; active global lease returns 429.

Every middleware response carries request/trace IDs. Application errors use `error`; framework
HTTP/validation errors use `detail`. Clients handle both shapes. The global body limit is
16 KiB including chunked transfers. Readiness alone does not prove fresh provider data.
