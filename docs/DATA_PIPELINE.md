# Pipeline and quality

1. Seed reviewed asset/exchange identities idempotently.
2. Fetch metadata in batches and candles by explicit Binance pair. Concurrent WebSocket task listens to a single multiplexed stream.
3. Validate numeric finiteness, positive prices, nonnegative volume, candle OHLC bounds, UTC midnight, canonical IDs and metadata timestamps.
4. Ignore out-of-order stream event timestamps; finalized candle compound keys make replay idempotent. Provisional candles remain only in expiring latest-price cache.
5. Preserve provider-specific prices and separate observation/ingestion/snapshot timestamps. Metadata cannot overwrite a newer observation.
6. Flag daily close jumps above 50% for investigation. Flag large cross-provider discrepancies with an explicit USD/USDT quote-basis caveat; do not automatically correct prices.
7. Compute analytics only over contiguous daily returns. Coverage reflects excluded missing intervals, with a 95% gate for ranking and annualized metrics. Never interpolate.
8. Retain last successful snapshots on provider outage and expose stale flags/coverage rather than fabricated replacements.

Daily backfill supports up to 1,826 requested days, paginated in 1,000-row provider batches; the acquisition helper rejects more than 9,000 observations or non-advancing pages. Existing shorter histories extend through `scripts/backfill.py`. Hourly history defaults to 90 days and is separate from daily annualization. No tick archive is maintained. Polling frequency is configurable but has a conservative minimum of 120 seconds. Ingestion and numerical work use bounded asset universes and thread offloading.

Retention: live daily candles default to 1,826 days and hourly candles to 90 days;
quality/ingestion/chat records retain 30 days. Fixture data remains fixed. Metadata history
is captured idempotently at source observation timestamps and starts at first capture.
Analytical snapshots expire after configurable 30 days, except datasets referenced by retained
chat charts. The worker runs this archival step. AI usage/request admission records remain
durable; the usage ledger is never deleted to reset budget. Backups are private local artifacts.

The discovery poll captures configurable pages of 250 provider assets (default four pages,
hourly). Canonical provider IDs remain separate from the ten reviewed exchange mappings.
Partial provider responses or page/rate limits can yield less than the configured cap.
Issuer/protocol research is a reviewed qualitative inventory with links and dates, not a
fabricated solvency score. Aave TVL/cap requires both source observations within two hours;
missing/stale values withhold the ratio. TVL is not revenue or a token-holder ownership claim.

Quality validation does not prove economic accuracy, eliminate exchange manipulation or assess asset issuer solvency. A valid schema can still contain wrong provider data.

## Explicit existing-history extension

With the intended live backend running and its worker temporarily stopped, extend only
the chosen canonical asset without exposing PostgreSQL on the host:

```bash
docker compose stop ingestion-worker
docker compose exec -T backend python - --asset bitcoin --days 730 < scripts/backfill.py
```

The CLI fetches public finalized bars and idempotently writes the configured market database;
it does not call a model or change the usage ledger. Recreate/start ingestion with the intended
Compose environment afterward. Do not accidentally use the isolated verification overlay
when intending to extend the original live database.
