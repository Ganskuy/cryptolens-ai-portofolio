# Data dictionary

| Table | Keys and important fields | Meaning/source |
|---|---|---|
| assets | id PK, symbol, name, stablecoin | Reviewed canonical registry; ticker is display-only |
| asset_provider_mappings | id PK; provider/provider_id unique; asset_id FK | Explicit identity join, not fuzzy ticker matching |
| exchanges | id PK, name | Exchange registry; Binance spot USDT context |
| market_snapshots | asset_id/source composite PK; price NUMERIC(30,12), observed_at, ingested_at, data JSON | Latest per-provider snapshot; provider observation and backend receipt kept separate |
| ohlcv_candles | asset_id/source/time composite PK; OHLC NUMERIC(30,12), volume NUMERIC(36,12), finalized | Daily UTC start epoch seconds; only finalized records persist |
| asset_fundamentals | asset_id PK; observed_at; data | Latest CoinGecko supply/cap/volume metadata |
| defi_metrics | id PK; observed_at; data | Chain-scoped TVL and separately named global-market snapshot |
| analytics_snapshots | content-derived id PK, created_at, data | Immutable numerical dataset used by grounded chart references |
| ingestion_runs | id, created_at index, provider, status, records | Operational audit without response bodies or secrets |
| data_quality_events | id, created_at index, source, reason | Rejected records, provider failures, outliers/discrepancies |
| chat_sessions | id UUID PK, owner index (account UUID or SHA-256), created_at | Account ID or hash of local browser capability; session UUID alone grants no access |
| chat_messages | id UUID PK, session_id FK/index, role, data, created_at | User question or validated assistant output; private to session owner |
| ai_usage_records | id UUID PK; model; reserved_tokens; actual_tokens nullable; estimated_cost; confirmed_cost nullable; data | Persistent request admission and observed provider usage; never delete to reset task budget |

| users | id UUID PK, username unique, password_hash, role, active | Administrator-provisioned local accounts |
| auth_sessions | token_hash PK, user_id FK/index, csrf_hash, expires_at index | Hashed expiring session and CSRF capabilities |
| ai_requests | id SHA-256 PK, owner, state, created_at, expires_at | Durable per-owner request-ID admission; Redis is not authoritative |
| service_leases | name PK, token, expires_at | Expiring global AI lease; worker uses a PostgreSQL session lock separately |
| metadata_history | asset_id/source/observed_at composite PK, ingested_at, data | Source metadata captured from first successful observation |
| hourly_candles | asset_id/source/time composite PK, OHLC/volume | Finalized hourly exchange candles, source-separated fixtures |
| universe_assets | id canonical provider PK, symbol, name, observed_at, data | Bounded discovery registry; no implicit ticker-to-exchange mapping |

All database datetimes use UTC-aware application values; PostgreSQL uses timestamptz. Candle timestamps are UTC integer seconds. Currency decimals are persisted exactly from strings; numerical analytics convert bounded arrays to float64. JSON monetary metadata may use decimal strings and must be parsed explicitly. Null means unknown, never zero.

Query indexes follow actual access: candle composite PK supports asset/source/time bounds, owner index supports session listing, message session index supports ownership-scoped history, timestamp indexes support operational retention. No partitioning or speculative indexes.
