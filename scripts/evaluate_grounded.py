"""Full deterministic report regression on temporary fixture DB; never paid inference."""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="cryptolens-eval-") as temp:
        os.environ.update(
            DATABASE_URL="sqlite:///" + temp + "/eval.db",
            DATA_MODE="fixture",
            AI_NARRATION="false",
            OPENROUTER_API_KEY="",
        )
        sys.path.insert(0, str(ROOT / "backend"))
        from app import research_policy
        from app.db import Base, engine
        from app.worker import fixtures

        Base.metadata.create_all(engine)
        fixtures()
        cases = json.loads((ROOT / "backend/tests/evals/golden.json").read_text())
        results = []

        async def progress(_):
            pass

        async def evaluate():
            for case in cases:
                report = await research_policy.analyze(case["prompt"], progress)
                operation = report["policy"].get("operation", report["analysis_type"])
                numeric = all(
                    f["value"] == report["evidence"][f["evidence_id"]][f["field"]]
                    for f in report["key_findings"]
                )
                eligible = (
                    research_policy.claims_for(
                        report["evidence"], report["policy"], report["freshness"]
                    )
                    if report["claims"]
                    else {}
                )
                claims = all(
                    c["id"] in eligible and c["evidence_ids"] == eligible[c["id"]]
                    for c in report["claims"]
                )
                freshness = report["freshness"] == (
                    "not_applicable"
                    if operation in {"clarify", "refuse"}
                    else "fixture"
                )
                results.append(
                    {
                        "id": case["id"],
                        "expected": case["expected_operation"],
                        "actual": operation,
                        "operation_pass": operation == case["expected_operation"],
                        "numerical_grounding_pass": numeric,
                        "claim_grounding_pass": claims,
                        "freshness_pass": freshness,
                        "findings": len(report["key_findings"]),
                        "claim_ids": [c["id"] for c in report["claims"]],
                    }
                )

        try:
            asyncio.run(evaluate())
            passed = sum(
                all(
                    r[k]
                    for k in [
                        "operation_pass",
                        "numerical_grounding_pass",
                        "claim_grounding_pass",
                        "freshness_pass",
                    ]
                )
                for r in results
            )
            result = {
                "policy": research_policy.VERSION,
                "mode": "deterministic synthetic fixture; no external model",
                "passed": passed,
                "total": len(results),
                "external_tokens": 0,
                "limitation": "Regression on known golden prompts; not human-reviewed answer usefulness or out-of-distribution model accuracy",
                "cases": results,
            }
            (ROOT / "docs/grounded-answer-evaluation.json").write_text(
                json.dumps(result, indent=2) + "\n"
            )
            print(
                f"Grounded answer regression: {passed}/{len(results)}; external tokens 0"
            )
            assert passed == len(results)
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
