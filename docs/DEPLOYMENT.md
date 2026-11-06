# Local deployment, rollback and recovery

This package supports **local hosting only**. All commands run from the repository
root and use only the `cryptolens` Compose project. Never operate on unrelated stacks.
PostgreSQL/Redis have no host ports. Migration head is `0002`.

## HTTP workspace

Copy `.env.example` to `.env`, set both database credentials consistently, and `chmod 600 .env`.
Use `DATA_MODE=live` for public providers or `fixture` for explicitly synthetic data.
`docker compose up -d --build` starts migrations before API/worker. HTTP ports are
127.0.0.1:3100 and 127.0.0.1:8100. `AUTH_MODE=local` is a single-operator browser-cookie
workspace; use the account/TLS package for shared access. `AI_ENABLED=true` enables
backend-grounded research without a provider key. Optional `AI_NARRATION=true` also
requires the backend-only key and uses the permanent budget ledger.

## Account-protected local HTTPS

Requires modern Docker Compose supporting [`!reset`](https://docs.docker.com/reference/compose-file/merge/).
The override removes both direct app ports and exposes only `127.0.0.1:8443`.
It requires accounts, secure cookies, a fixed HTTPS Origin, and grounded AI mode.

```bash
python3 scripts/deploy.py prepare
python3 scripts/deploy.py start
docker compose -f docker-compose.yml -f compose.local-tls.yml exec backend python -m app.auth researcher --role researcher
```

Provisioning prompts for the password twice; passwords never go in shell arguments.
Roles: `reader` can view/compare data, `researcher` can also create AI research,
`admin` can additionally read internal metrics. Accounts are administrator-provisioned;
there is no public signup. Sessions expire after 12 hours. Logout revokes the session.
Account disabling (`users.active=false`) invalidates subsequent HTTP and WebSocket checks.

Caddy uses a **local CA**, not a public certificate. Retrieve its public root for tools:

```bash
docker compose -f docker-compose.yml -f compose.local-tls.yml exec -T gateway cat /data/caddy/pki/authorities/local/root.crt > .local/caddy-root.crt
curl --cacert .local/caddy-root.crt https://localhost:8443/api/v1/health/ready
```

Open `https://localhost:8443`. For browser trust, deliberately import that local root into
your browser/OS trust store; the deployment script does not modify system trust. CA keys
stay in the dedicated Caddy volume. No public domain, tunnel, DNS, ACME or cloud resource
is created. Runtime `/api/v1/config` supplies the same-origin WebSocket path. SSE and
WebSocket traffic go directly through Caddy to FastAPI; page traffic goes to Next.js.
`/metrics` is blocked at the gateway and requires an admin session internally.

## API blue/green rehearsal

```bash
python3 scripts/deploy.py candidate
python3 scripts/deploy.py promote
python3 scripts/deploy.py rollback
```

The candidate has its own resource-limited API container and shares the current database.
Promotion checks readiness, validates Caddy config and reloads the upstream; reload
failure restores the previous config. Rollback selects the retained `backend` container.
This is an **API** deployment switch; frontend/worker updates still use Compose recreation.
Do not rebuild the old backend image until the rollback window closes. Apply only
backward-compatible migrations before promotion; these commands never downgrade schema.
Caddy reload follows its [documented configuration workflow](https://caddyserver.com/docs/command-line#caddy-reload).
Local candidate promotion and rollback were exercised with readiness checked after each.

## Backup and disaster recovery

Stop ingestion and AI activity before the exact-content recovery drill:

```bash
docker compose stop backend ingestion-worker
python3 scripts/recovery_drill.py
```

The drill creates a mode-0600 custom-format dump under ignored `.local/backups`, restores
into a generated `cryptolens_verify_*` database, compares per-table sorted-row SHA256
including the permanent token ledger, verifies the source is unchanged, and removes only
that generated database. It never restores over the live database. The drill writes a local, ignored `docs/recovery-drill.json` report. Keep encrypted off-device backups separately if
host-loss protection is required; local Docker volumes are not off-device backups.

Real recovery must retain every usage record accrued **after** a backup. Reconcile the
latest permanent ledger before enabling paid AI; otherwise keep AI disabled. Restoring
an old database is never permission to reset the cumulative 100,000-token allowance.
Migration downgrades intentionally refuse destructive deletion.

## Reproducible isolated verification

`scripts/prepare_verification.py` creates a dedicated `cryptolens_verify_work` database
inside this project's PostgreSQL, an ignored Compose overlay, and private test accounts.
It refuses reuse unless the database marker proves ownership. Paid calls are disabled
by blank credentials and `AI_NARRATION=false`; synthetic data never enters the live DB.

```bash
.venv/bin/python scripts/prepare_verification.py
python3 scripts/deploy.py start --overlay .local/verify.yml
.venv/bin/python scripts/prepare_verification.py --accounts
.venv/bin/python scripts/verify_local.py
docker compose stop ingestion-worker
docker compose exec -T backend python - < scripts/verify_leadership.py
CRYPTOLENS_BASE_URL=https://localhost:8443 CRYPTOLENS_TEST_CREDENTIALS="$PWD/.local/accounts.json" npm --prefix frontend run e2e
```

Do not run build/recreation concurrently with these checks. Browser tests allow the
self-signed certificate only in this explicit test configuration; `verify_local.py`
verifies the certificate against the extracted CA. The integration script briefly stops
and restarts **this project's Redis** and always restores it in a `finally` block.
It verifies account boundaries, real SSE, duplicate protection after restart and bounded
multi-user reads. Leader verification kills only its isolated DB's dedicated lock session.

## Stop and resume

```bash
docker compose -f docker-compose.yml -f compose.local-tls.yml --profile rollout stop
```

This preserves all volumes, backups and ledger data. Use the same Compose configuration
when restarting. `scripts/deploy.py start` without the verification overlay reconnects
the application to the original `.env` database. Recreate ingestion with the intended environment when wanted (plain `start` retains any
previous verification environment):

```bash
docker compose -f docker-compose.yml -f compose.local-tls.yml up -d --build ingestion-worker
```

 Never use `down -v` or global Docker prune.

Runtime image bases are digest-pinned; Python runtime dependencies exclude test/lint/audit
tooling. Resource ceilings are backend/worker 512 MiB each, frontend 384 MiB, PostgreSQL
256 MiB, Redis 96 MiB, gateway 128 MiB. These are limits, not measured consumption or
capacity guarantees. No GPU is required. Account/API horizontal replicas use PostgreSQL
admission; ingestion replicas elect a single owner. Redis is a recoverable cache, not a
replicated HA service; its restart drill does not prove Sentinel/cluster failover.
