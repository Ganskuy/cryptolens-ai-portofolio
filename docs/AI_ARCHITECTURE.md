# Grounded research architecture

The default `AI_MODE=grounded` uses `research_policy.py` to classify bounded English/Indonesian
requests, clarify ambiguity, refuse unauthorized intent, and invoke one typed analytics
operation. Unsupported assets never gain exchange mappings from a model. Questions beyond
this bounded policy may need rephrasing; no general natural-language understanding claim is made.

A report contains schema version 2, policy/operation, freshness, approved claims with evidence
IDs, numerical findings copied directly from allowlisted scalar fields, chart dataset IDs,
limitations, timestamps, and model-selection status. Claim predicates are deterministic.
Stale source observations cannot become fresh because a report was just created. Synthetic
fixtures always carry a disclosure. Daily analytics are historical, never forecasts.

By default there is no provider call. With `AI_NARRATION=true` and a backend key, OpenRouter
receives a bounded request and available claim IDs, and can select at most four. Output is
strict JSON with no extra fields; unknown IDs or prose trigger the deterministic fallback.
Mandatory freshness/fixture/risk disclosures cannot be omitted by selection. Displayed text
comes from approved bilingual templates, and displayed numbers come from backend evidence.
The legacy free-prose orchestration is preserved for regression comparison, but production
configuration rejects `AI_MODE=legacy`.

SSE stages reflect actual validation, retrieval/computation and optional model selection.
Only after a complete report is validated and saved do `validated_text` chunks stream its
approved answer. A bounded 16-event queue, 110-second request deadline and cancellation
cleanup prevent unbounded buffering. Final output is also available in owned session history.
No raw model tokens, generated chart code, SQL, arbitrary URLs, shell or wallet tools exist.

Provider selection defaults to `deepseek/deepseek-v3.2`, retained provisionally from the earlier
catalog verification. Optional selection output is capped at 160 tokens; the legacy cap is
1,800. All calls use bounded byte input, timeouts and a pre-dispatch PostgreSQL reservation.
Positive provider total-token reports reconcile reservations; missing/interrupted usage stays
charged. Invalid/non-finite/negative provider cost cannot reduce the cost guardrail. The task
ceiling is 100,000 cumulative accounted tokens and the application daily cost guardrail is $2.
Pricing assumptions are configuration controls, not a billing guarantee; revalidate provider
prices before changing models. No paid calls were required for the grounded-v2 update.

`admission.py` serializes AI admission under a PostgreSQL transaction advisory lock, retains
request IDs durably, and grants one expiring global lease. Completion releases only its own
lease token, so an old cancellation cannot release a replacement. Redis remains a rate-limit
availability dependency; its failure blocks new AI work. It is no longer the idempotency
source of truth. `auth.py` scopes history to an account UUID or a hashed local browser cookie.

See `AI_EVALUATION.md` for the 30-case full-report regression methodology. Private paid evaluation reports are excluded. Deterministic grounding does not verify provider truth or establish human usefulness.
