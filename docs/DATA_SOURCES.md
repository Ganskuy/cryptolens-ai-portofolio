# Data sources and contracts

| Source | Data | Default cadence | Units and caveats |
|---|---|---|---|
| Binance public REST `/api/v3/klines` | Daily finalized OHLCV, up to 367 requested rows | 300 seconds, ten symbols | USDT quote; volume in base asset units; incomplete current candle excluded |
| Binance multiplexed `@kline_1d` | Provisional latest price and finalized daily close | Provider events; dashboard coalesces to 2 seconds | One shared connection; bounded receive queue; reconnect jitter; rotate before 24 hours |
| Binance `/api/v3/ticker/bookTicker` | Bid/ask and spread | 300 seconds | USDT; retrieval timestamp because endpoint has no observation timestamp |
| CoinGecko `/coins/markets` | USD price, cap, rank, volume, supply | Batched every 300 seconds | `last_updated` is observation time; ingestion timestamp is separate |
| CoinGecko `/global` | Global cap, volume, BTC dominance | 300 seconds | Global aggregate, not the curated ten-asset universe |
| DefiLlama `/protocol/aave`, `/v2/historicalChainTvl/Ethereum`, stablecoins `/stablecoins` | Protocol/chain history, aggregate peggedUSD supply | 300 seconds | Bounded retained history, explicit scope, no inferred token valuation |
| DefiLlama `/v2/chains` | Chain TVL | 300 seconds | Chain metric, never silently assigned to a token |

All endpoints are fixed in code. No user-controlled URLs. No exchange API keys. Conservative centralized requests and bounded retry/backoff reduce load, but provider access and rate limits can change. A 429/418 opens a circuit using bounded Retry-After; API errors retain previous data. CoinGecko requests currently work without a Demo key; authenticated Demo usage is not configured and requires a separate adapter setting if anonymous access changes.

The canonical IDs are CoinGecko identities with explicit Binance pairs. No dynamic ticker matching. Wrapped/renamed/unsupported assets are excluded until reviewed. USDC is flagged as a stablecoin; USDT is a quote currency, not an implied USD equivalence.

Offline fixtures are deterministic mathematical series ending 2026-01-01 under `synthetic-fixture`, not captured or purported live data. Global aggregates and fundamentals are unavailable in fixture mode. Live mode never falls back silently to fixtures.


## 2026-10-27 extensions

CoinGecko markets discovery uses canonical IDs, configurable 250-item pages and hourly polling;
only reviewed IDs can enter exchange analytics. Metadata archives start at successful local
capture, not before. Binance paginated daily/hourly REST accepts only finalized, validated OHLCV.
Use `scripts/probe_history.py` for an explicit read-only provider probe; its generated report
is local evidence and is excluded from the public snapshot. Provider coverage is not guaranteed.
Aave token/protocol mapping links the provider's `aave` token identity to DefiLlama's Aave
protocol; the mapping source and review date are explicit in the research response. Circle/Aave
research links provide qualitative risk context and are not independently verified reserve
attestations. Source limits and missing observations remain visible.
