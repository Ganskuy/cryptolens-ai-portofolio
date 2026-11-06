# Observability

HTTP requests emit JSON request/trace IDs, route template, method, status and latency.
All responses, including rejected authentication/origin/body requests, carry a generated
`traceparent` and `X-Request-ID`. Incoming trace headers are not trusted. Analytics and
provider work emit local structured spans sharing request context where applicable.
No raw SQL, query parameters, passwords, chat prompts or authorization headers are logged.
These are **local correlated spans**, not an OTLP collector or cross-service tracing system.

`GET /metrics` exposes Prometheus text internally. Account mode requires an admin session;
the local TLS gateway deliberately blocks this route. Metric families:

| Metric | Meaning |
|---|---|
| `cryptolens_http_requests_total` | Route/method/status counts, including rejected requests |
| `cryptolens_http_duration_seconds` | Time to response headers; SSE completion is separately staged |
| `cryptolens_db_duration_seconds` | SQL execution histogram, without SQL/parameters |
| `cryptolens_cache_total` | Overview hit/miss/error counts |
| `cryptolens_provider_duration_seconds` | Provider attempt latency/outcome |
| `cryptolens_analytics_duration_seconds` | Risk/ranking/compare computation |
| `cryptolens_ai_events_total` | Completed research requests |

Metrics are per API process and reset on restart. Scrape each replica separately; this
package runs one Uvicorn process per container. Worker/provider spans and operational
records remain available independently of API process metrics. Counters are diagnostic,
not the billing authority: `ai_usage_records` is permanent and authoritative.

Readiness checks PostgreSQL migration **0002** and Redis connectivity. A ready API may
still have stale provider observations; inspect per-asset timestamps, coverage, and
`worker_last_poll`. Fixture workers do not claim live polling. Redis tick keys expire
at 120 seconds. Metadata/snapshot freshness uses source observations, not report creation.

```bash
docker compose logs --tail 100 backend ingestion-worker
docker compose exec -T postgres psql -U cryptolens -d cryptolens -c 'SELECT provider,status,records,created_at FROM ingestion_runs ORDER BY id DESC LIMIT 20;'
docker compose exec -T postgres psql -U cryptolens -d cryptolens -c 'SELECT count(*),sum(actual_tokens),sum(coalesce(actual_tokens,reserved_tokens)) FROM ai_usage_records;'
```

Operational response thresholds: investigate readiness failure immediately; stale daily
candles after the latest expected closed UTC bar; metadata older than 15 minutes; any
unexpected AI reservation growth; sustained API 5xx above 1% or p95 above one second under
the intended load. These are operator thresholds, not measured production SLOs. No external
alert delivery or hosted monitoring service is configured. Verification scripts generate ignored local reports; private runtime measurements
are not distributed with this source snapshot. Use targeted `docker stats --no-stream` service IDs to inspect this project.
