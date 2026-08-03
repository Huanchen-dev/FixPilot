import pytest

from app.repair_agent import materialize_repair_plan
from app.schemas import RepairProposal, TextReplacement


def proposal(old_text: str = "return left - right") -> RepairProposal:
    return RepairProposal(
        summary="把减法修正为加法",
        replacements=[
            TextReplacement(
                relative_path="calculator.py",
                base_sha256="a" * 64,
                old_text=old_text,
                new_text="return left + right",
                reason="函数应执行加法",
            )
        ],
    )


def test_text_replacement_materializes_complete_file():
    plan = materialize_repair_plan(
        proposal(),
        [
            {
                "relative_path": "calculator.py",
                "base_sha256": "a" * 64,
                "content": "def add(left, right):\n    return left - right\n",
            }
        ],
    )
    assert plan.changes[0].updated_content == (
        "def add(left, right):\n    return left + right\n"
    )


def test_text_replacement_rejects_ambiguous_old_text():
    with pytest.raises(ValueError, match="exactly once"):
        materialize_repair_plan(
            proposal(old_text="return"),
            [
                {
                    "relative_path": "calculator.py",
                    "base_sha256": "a" * 64,
                    "content": "def one():\n    return 1\ndef two():\n    return 2\n",
                }
            ],
        )


def test_text_replacement_accepts_one_ast_equivalent_fragment():
    semantic_proposal = RepairProposal(
        summary="修正响应字段",
        replacements=[
            TextReplacement(
                relative_path="profile_service.py",
                base_sha256="b" * 64,
                old_text="return payload[“profile”][“display_name”].strip()",
                new_text="return payload[“user_profile”][“display_name”].strip()",
                reason="实现应使用响应契约中的user_profile字段。",
            )
        ],
    )

    plan = materialize_repair_plan(
        semantic_proposal,
        [
            {
                "relative_path": "profile_service.py",
                "base_sha256": "b" * 64,
                "content": (
                    "def get_display_name(payload):\n"
                    '    return payload["profile"]["display_name"].strip()\n'
                ),
            }
        ],
    )

    assert 'payload["user_profile"]' in plan.changes[0].updated_content


def test_text_replacement_rejects_ambiguous_ast_equivalent_fragments():
    with pytest.raises(ValueError, match="AST-equivalent"):
        materialize_repair_plan(
            proposal(old_text="return 'same'"),
            [
                {
                    "relative_path": "calculator.py",
                    "base_sha256": "a" * 64,
                    "content": (
                        'def one():\n    return "same"\n'
                        'def two():\n    return "same"\n'
                    ),
                }
            ],
        )
