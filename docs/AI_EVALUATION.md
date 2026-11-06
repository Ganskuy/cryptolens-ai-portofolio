# AI evaluation

The default grounded-v2 policy routes bounded English/Indonesian requests, clarifies ambiguity,
refuses unsupported intent and constructs approved claims from backend evidence. Optional
model selection cannot introduce displayed prose, numbers or unknown claim IDs.

The checked-in `backend/tests/evals/golden.json` contains 30 authored regression prompts,
including adversarial inputs. They are synthetic test cases, not captured user conversations.
`python scripts/evaluate_grounded.py` uses a temporary synthetic SQLite database and disables
external inference. It checks operation selection, numerical evidence equality, eligible claims
and fixture disclosure. The generated report is ignored by Git.

Additional tests cover stale evidence, malformed/adversarial model outputs and preservation
of reservations after cancellation. Passing known cases does not establish held-out accuracy,
human usefulness, live provider reliability or investment performance.

Paid comparison and smoke scripts require `--run-paid`. Do not run them as part of ordinary
verification. They use the application's persistent admission ledger; never reset it or create
a fresh ledger to evade an existing evaluation allowance. Model availability and pricing must
be revalidated before enabling inference. No paid calls are needed for this public release.
