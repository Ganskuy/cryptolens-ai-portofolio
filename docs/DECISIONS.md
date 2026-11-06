# Decisions

- 2026-10-25: isolated ~/Documents/cryptolens-ai per task requirement; original crypto_analysis workspace and Financial Assistant unchanged.
- Modular monolith with separate ingestion process: enough separation for shared provider connections without distributed infrastructure overhead.
- Canonical ten-asset registry: deliberate bounded universe and reviewed cross-provider identities instead of unsafe ticker joins.
- Daily-only analytics and one-year bounded history: reproducible methods on limited memory; intraday risk is out of scope.
- PostgreSQL numeric persistence and float64 analytical arrays: exact source storage with conventional numerical methods.
- NumPy/Polars and plain HTTPX tool orchestration: no unneeded SciPy/agent framework or vector database.
- Custom CSS tokens rather than Tailwind: smaller style toolchain, explicit accessible UI states.
- Strict numerical evidence references and correction: initial live model test demonstrated why successful tool calling alone is insufficient.
- Permanent usage ledger with pre-dispatch reservation: cumulative 100,000-token cap and USD 2/day guardrail; no automatic usage reset.
- Local anonymous capability cookies: suitable for personal loopback deployment, not a claim of public SaaS authentication readiness.
- Model selection remains provisional: small tool-selection benchmark and smoke responses do not validate broad analytical quality.
