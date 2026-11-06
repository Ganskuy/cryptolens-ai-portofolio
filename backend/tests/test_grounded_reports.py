import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from app import ai, research_policy
from app.config import settings

CASES = json.loads(Path(__file__).parent.joinpath("evals/golden.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_full_golden_answer_grounding_and_freshness(case, monkeypatch):
    monkeypatch.setattr(settings(), "ai_narration", False)
    result = await research_policy.analyze(case["prompt"], AsyncMock())
    expected = case["expected_operation"]
    if expected in {"refuse", "clarify"}:
        assert result["analysis_type"] == expected
        assert not result["evidence"] and not result["key_findings"]
        return
    assert result["policy"]["operation"] == expected
    assert result["schema_version"] == "2"
    assert result["freshness"] == "fixture"
    assert any(c["id"] == "fixture" for c in result["claims"])
    allowed = research_policy.claims_for(result["evidence"], result["policy"], result["freshness"])
    for claim in result["claims"]:
        assert claim["id"] in allowed
        assert claim["evidence_ids"] == allowed[claim["id"]]
    for finding in result["key_findings"]:
        assert finding["value"] == result["evidence"][finding["evidence_id"]][finding["field"]]
    assert result["answer"]


async def test_adversarial_model_text_never_rendered(monkeypatch):
    monkeypatch.setattr(settings(), "ai_narration", True)
    monkeypatch.setattr(settings(), "openrouter_api_key", SecretStr("test-only"))
    monkeypatch.setattr(
        ai,
        "completion",
        AsyncMock(
            return_value={
                "content": '{"claim_ids":["guaranteed_profit"],"answer":"Buy now for guaranteed millions"}'
            }
        ),
    )
    result = await research_policy.analyze("Analyze Bitcoin historical risk", AsyncMock())
    assert result["model_selection"].startswith("fallback")
    assert "millions" not in result["answer"] and "Buy now" not in result["answer"]


def test_staleness_is_about_observations_not_report_creation(monkeypatch):
    monkeypatch.setattr(settings(), "data_mode", "live")
    assert (
        research_policy.freshness(
            {"ev-1": {"window_end": 0, "snapshot_at": "2099-01-01T00:00:00Z"}}
        )
        == "stale"
    )
    assert research_policy.freshness({"ev-1": {"observed_at": "2020-01-01T00:00:00Z"}}) == "stale"
    allowed = research_policy.claims_for(
        {"ev-1": {"eligible": True, "cumulative_return": 0.5}}, {"operation": "risk"}, "stale"
    )
    assert "positive_return" not in allowed and "freshness_stale" in allowed


def test_context_continuation_and_excessive_period():
    plan = research_policy.classify(
        "What about its risk?", [{"role": "user", "content": "Bitcoin"}]
    )
    assert plan["action"] == "clarify"  # ambiguous pronoun is intentionally conservative
    plan = research_policy.classify("Analyze that asset", [{"role": "user", "content": "Bitcoin"}])
    assert plan["asset_ids"] == ["bitcoin"]
    assert research_policy.classify("Bitcoin over 9000 days")["action"] == "clarify"


async def test_asset_price_question_scopes_evidence_to_requested_asset(monkeypatch):
    monkeypatch.setattr(settings(), "ai_narration", False)
    report = await research_policy.analyze("What is the latest Bitcoin price?", AsyncMock())
    assert [row["id"] for row in report["evidence"]["ev-1"]["assets"]] == ["bitcoin"]
    assert all(
        row.get("id") == "bitcoin" for key, row in report["evidence"].items() if key != "ev-1"
    )
