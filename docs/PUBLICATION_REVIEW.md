# Public publication review — 2026-11-06

## Decision

Publish the complete first-party application and reproducible verification tooling as a fresh
Git snapshot. Preserve the private development repository and its remote. Public source
availability does not imply public deployment, production certification or a new software license.
No license grant has been added; dependency licenses remain applicable to their components.

## Content disposition

| Content | Decision | Rationale |
|---|---|---|
| FastAPI services, worker, analytics, bounded AI and auth | Include | Implementation demonstrates engineering; secrets are runtime configuration |
| Next.js dashboard and frontend tooling | Include | First-party UI source, no embedded account/session data |
| Alembic schema/migrations | Include | Schema definitions, no database records or dumps |
| Unit/E2E tests and authored golden fixtures | Include | Reproducible synthetic tests, no captured conversations |
| Dependency locks, Dockerfiles, Compose, Caddy, CI | Include | Reproducible local package; internal data services and loopback app ports |
| Scripts including opt-in paid evaluation | Include | Source tooling; generated outputs and credentials excluded |
| Architecture, methodology, API and operations docs | Include with edits | Remove private delivery references and unavailable report links |
| Private history, checkpoints and delivery logs | Exclude/rewrite | Not needed to inspect or run the public project |
| Runtime JSON reports, usage summaries and model captures | Exclude | Private operational evidence, not source assets |
| Existing screenshots | Exclude | Captured runtime state; no need to redistribute provider observations |
| Agent instructions, local environment, caches and backups | Exclude | Workspace-specific policy or private/generated state |

All 117 tracked source paths were inventoried. The private six-commit history was scanned
with Gitleaks (no findings) but is not included. The public snapshot contains only explicitly
selected files; `PUBLIC_MANIFEST.sha256` records the reviewed payload (excluding itself).
A hash manifest detects changes; it is not a signature or proof of security.

Review covered credential patterns, local/private references, generated/binary artifacts,
outbound endpoints, configuration boundaries, synthetic fixtures, dependency provenance and
publication claims. This is a publication suitability review with automated regression checks,
not an independent line-by-line security certification. The original application code is preserved.

## Runtime and data boundaries

No private environment, application database or AI usage ledger is copied, reset or modified.
No external LLM call is required. Never launch this export alongside another checkout using
the same `cryptolens` Compose project. Provider responses are not redistributed; live use
remains subject to each provider's terms and access restrictions. Dependency source bundles
and node_modules are excluded; lockfiles describe installation inputs.

The local configuration is for a trusted operator. Public network hosting requires a separate
security/deployment review. Legacy model mode remains for regression comparison and is
rejected by production configuration. Provider pricing assumptions are not billing guarantees.
