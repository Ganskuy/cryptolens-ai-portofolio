# Troubleshooting

- Empty markets: inspect worker logs and ingestion_runs, DATA_MODE and outbound provider reachability. Never relabel fixtures as live or bypass regional/provider restrictions.
- Stale metadata: inspect observation timestamps rather than refresh-animation activity. The dashboard marks snapshots older than fifteen minutes delayed. Daily analytical eligibility checks the latest finalized daily boundary.
- API 503: inspect database migration head and Redis health. Ordinary reads can bypass failed cache, but AI deliberately fails closed.
- AI 422/failed: tool arguments, context length, response grounding or budget may be invalid. Read sanitized failure type and usage rows. Grounded-v2 rejects unauthorized claim selections and uses a deterministic fallback; legacy correction behavior applies only to explicit legacy mode.
- AI 429: a request is running or the local rate limit was exceeded. Cancel from the original client or wait for the bounded request deadline. Never remove usage rows.
- AI 409: request_id was admitted previously. Review the owned session before intentionally retrying with a new ID.
- Lost chat access: sign back into the same account; local anonymous history instead depends on its browser cookie. Session UUIDs cannot bypass ownership.
- Charts empty: check finalized candles, source mode and minimum observations. Binance USDT charts are not CoinGecko USD price charts.
- Frontend connects natively but fails in Docker: verify BACKEND_URL is set during the Next.js build, not just runtime.
- Feed connected but price unavailable: WebSocket transport health is distinct from upstream freshness; Redis tick keys expire after two minutes. Inspect worker connection/reconnect logs.
- Port conflict: choose other app loopback ports and update allowed origin, proxy and WebSocket configuration together. Do not kill unrelated applications.

- HTTPS certificate warning: Caddy uses a dedicated local CA. Export its public root and trust it deliberately; do not disable TLS verification for normal clients.
- Login 429: five attempts/IP/minute; local proxy clients share its IP. Wait for the next minute, do not disable the guardrail.
- Account 403: verify role, current CSRF cookie/header, and exact configured Origin.
- Candidate promotion rejected: inspect readiness and migration revision before reload; do not downgrade schema to force a rollback.
- Worker standby: another worker owns PostgreSQL lock 712906. Do not remove unrelated locks; stop only the owning CryptoLens worker if intentionally replacing it.
- Sharpe preset requests an assumption: enter an annual percentage explicitly; blank is not silently treated as zero.
- Indicator chart gaps: warm-up observations are insufficient or a missing timestamp reset the window; no gap filling occurs.
- Fixture browser tests cannot connect: wait for frontend/gateway readiness before running them; HTTP and TLS profiles use different ports.
