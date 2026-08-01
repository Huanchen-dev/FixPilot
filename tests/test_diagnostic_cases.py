import json
from pathlib import Path

import pytest

from app.graph import _fallback_draft
from app.traceback_parser import parse_traceback


CASE_PATH = Path(__file__).parent / "fixtures" / "diagnostic_cases.json"
CASES = json.loads(CASE_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_known_root_cause_cases(case):
    info = parse_traceback(case["traceback"])
    draft = _fallback_draft(info)
    assert case["expected_title_keyword"] in draft.root_causes[0].title
    assert draft.root_causes[0].category == case["expected_category"]
    assert draft.root_causes[0].evidence_ids == ["traceback-1"]
