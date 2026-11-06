"""Dataset integrity, not an assertion of live model quality."""

import json
from pathlib import Path


def test_golden_has_required_coverage():
    cases = json.loads(Path(__file__).with_name("golden.json").read_text())
    assert len(cases) >= 30
    assert len({c["id"] for c in cases}) == len(cases)
    assert {"en", "id"} == {c["language"] for c in cases}
    assert {
        "overview",
        "fundamentals",
        "risk",
        "rankings",
        "compare",
        "identify",
        "defi",
        "refuse",
        "clarify",
    } <= {c["expected_operation"] for c in cases}
