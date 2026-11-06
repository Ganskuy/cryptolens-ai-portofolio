# Selected technology

Verified on macOS Apple Silicon with Python 3.13, Node 24 and Docker Engine 29.8.2. Backend transitive versions are fully captured in `backend/requirements.lock`; frontend direct versions and complete integrity hashes are captured in package.json/package-lock.json. Run `pip install -r` and `npm ci`, not unbounded upgrades.

Next.js 16.4.3 and React 19.3.1 were resolved from the package registry and successfully built. Python, Node, PostgreSQL, Redis and Caddy base images are now pinned to registry manifest digests in Dockerfiles/Compose. The separately locked `backend/requirements.runtime.lock` excludes test/lint/audit tools from installed runtime dependencies; the full lock remains for development/CI. Refresh digests deliberately with rebuild, audit and rollback verification.

Deviations from the preferred stack: CSS tokens replace Tailwind because this small application needs no extra style build dependency. NumPy and Polars cover current statistics; SciPy adds no required functionality and is omitted. No LangGraph, vector store, agent framework, Kafka, Celery or Kubernetes. HTTPX talks directly to OpenRouter. Vitest covers frontend formatting and Playwright covers integrated user flows.

Official references inspected: [Binance stream contract](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md), [CoinGecko markets](https://docs.coingecko.com/reference/coins-markets), [DefiLlama API](https://api-docs.defillama.com/), [OpenRouter tool calling](https://openrouter.ai/docs/guides/features/tool-calling), [Next.js installation](https://nextjs.org/docs/app/getting-started/installation). Live REST and model catalog probes supplemented documentation review.
