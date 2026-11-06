# Public snapshot verification — 2026-11-06

Checks run against the exported source before publication:

| Check | Result |
|---|---|
| Backend Ruff lint and formatting | Passed, 28 formatted files |
| mypy | Passed, 17 application modules |
| pytest | 93 passed; isolated temporary SQLite |
| Grounded report evaluation | 30/30 known synthetic cases, zero external tokens |
| Frontend clean npm install, ESLint, production build, TypeScript | Passed |
| Frontend Vitest | 4 passed |
| pip-audit development and runtime locks | No known vulnerabilities reported |
| npm audit production dependencies | Zero vulnerabilities reported |
| npm audit all dependencies | 8 moderate findings in the development lint dependency chain; no high/critical findings |
| Exact export manifest, credential scan, fresh Git history scan | Required publication gates |

The npm findings derive from minimatch globparts amplification
([GHSA-g3hv-75wg-m249](https://github.com/advisories/GHSA-g3hv-75wg-m249)) through
TypeScript ESLint tooling. npm's proposed force fix changes the pinned eslint-config-next
major version. That dependency migration is deferred; do not interpret the high-severity CI
gate as a clean full audit. ESLint 9 also emitted an unsupported-version warning. Review and
upgrade the lint stack before relying on it for untrusted source processing.

The exported workflow runs backend/frontend checks, dependency scans, full-history Gitleaks,
Docker builds, PostgreSQL migration drift checks, fixture HTTP browser tests, TLS account
browser tests, Redis recovery, worker leadership, API promotion/rollback and backup restore.
Check the [public Actions runs](https://github.com/Ganskuy/cryptolens-ai-portofolio/actions)
for the status of the exact commit; this document does not predeclare their result.

Local verification did not start Docker services or access the original application database.
Integrated checks are delegated to the isolated GitHub Actions runner. No live provider or
paid model evaluation, public-host deployment, independent penetration test, held-out model
quality review or long-duration capacity/HA certification is claimed.
