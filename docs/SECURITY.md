# Security boundaries

Deployment is local-only. PostgreSQL/Redis have no host ports; HTTP app ports are loopback.
The TLS override removes direct app ports and exposes localhost:8443 through Caddy's local
CA. App containers run as non-root. No trading, wallet signing, exchange credentials or
arbitrary model tools exist.

Secrets remain in ignored mode-0600 files and backend environment only. No `NEXT_PUBLIC_*`
credential, raw prompt, SQL parameter, password, cookie or authorization header is logged.
Tracked/staged content and history are scanned with redaction before publication.

## Identity and request boundaries

`AUTH_MODE=required` uses administrator-provisioned accounts. Passwords use salted scrypt
(N=131072, r=8, p=1), following the [OWASP password storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).
Unknown usernames perform equivalent password work. Hash work is serialized per process
to bound memory; logins are additionally limited to five/IP/minute. Behind the local proxy,
unauthenticated clients share its network address, deliberately conservative for this scope.

Sessions are 256-bit random capabilities, hashed at rest, expiring after 12 hours. Cookies
are HttpOnly/SameSite=Strict and Secure in TLS mode; the separate random CSRF cookie is
readable by the frontend and matched to the stored session hash for mutations. Login
requires the exact allowed Origin; all supplied mutation Origins are checked. Roles enforce
read-only versus research access and internal admin metrics. Account disable/logout/expiry
are checked for HTTP and each WebSocket polling iteration. Sessions and deletion are owner-scoped.
Local anonymous mode retains its original hashed browser capability; a shared browser profile
is a shared identity and clearing that cookie loses anonymous-history access.

## AI and data boundaries

Typed fixed provider identities/URLs and parameterized SQL prevent model-selected network
or database commands. Default reports use backend-approved claim predicates and copied
numerical evidence. Optional model output can select only approved claim IDs, never introduce
prose or numbers. Adversarial or malformed selection falls back deterministically. Prompt
instructions are supplementary; backend capability restrictions enforce the boundary.

16-KiB bodies, bounded prompts/windows/tool outputs, per-account or local-IP 120/minute
requests, one durable global AI lease, persistent request IDs and pre-dispatch budget
reservation bound work. Redis failure blocks new AI requests; ordinary data reads fall back
to PostgreSQL. Requests interrupted after dispatch retain unknown token reservations.

The worker holds a dedicated PostgreSQL session advisory lock; loss cancels its tasks and
permits a standby to take ownership. Candle writes remain idempotent. This is coordination
and failure detection, not a claim of perfectly instantaneous fencing under every partition.
See [PostgreSQL lock semantics](https://www.postgresql.org/docs/16/explicit-locking.html#ADVISORY-LOCKS).

## Verified scope and residual conditions

Automated tests exercise authentication, CSRF, role/session isolation, size/origin rejection,
malicious model output, source freshness, worker lock loss, Redis recovery, and TLS routing.
Dependency audits and source/history secret scans are point-in-time checks. The local load
and security checks are not an independent penetration test. No public deployment, external
auditor, market-manipulation detection, issuer solvency certification, MFA/SSO, or general
model-quality certification is claimed. Public service hosting is outside this release scope.

Never reset the permanent usage ledger, publish `.env`/test credentials/backups, expose DB
ports, or use destructive/global Docker cleanup. Public export manifests and exact remote
commit/CI must be verified at delivery. CI has read-only contents permissions and no runtime keys.
