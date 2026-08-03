from streamlit.testing.v1 import AppTest


def test_fixpilot_page_initial_render():
    app = AppTest.from_file("ui.py")
    app.run(timeout=10)
    assert not app.exception
    assert app.title[0].value == "FixPilot"
    assert app.button[0].label == "开始只读诊断"


def test_repair_page_renders_baseline_and_comparison():
    app = AppTest.from_file("ui.py")
    app.run(timeout=10)
    app.session_state["repair_result"] = {
        "repair_id": "ui-baseline-test",
        "diagnosis_id": "ui-diagnosis",
        "status": "tests_failed",
        "repairable_reason": "测试允许修复",
        "baseline_test_results": [
            {
                "preset": "pytest",
                "status": "failed",
                "duration_seconds": 0.1,
                "failed_tests": ["test_app.py::test_one"],
                "output_excerpt": "1 failed",
            }
        ],
        "attempts": [
            {
                "attempt": 1,
                "status": "tests_failed",
                "test_results": [
                    {
                        "preset": "pytest",
                        "status": "failed",
                        "duration_seconds": 0.1,
                        "failed_tests": ["test_app.py::test_two"],
                        "output_excerpt": "1 failed",
                    }
                ],
                "fixed_tests": ["test_app.py::test_one"],
                "remaining_failed_tests": [],
                "new_failed_tests": ["test_app.py::test_two"],
                "regressed_tests": ["test_app.py::test_two"],
            }
        ],
        "final_plan": None,
        "diff": "",
        "test_results": [],
        "warnings": [],
    }
    app.run(timeout=10)

    assert not app.exception
    markdown_values = [item.value for item in app.markdown]
    assert "#### 修复前基线" in markdown_values
    assert any("第1轮" in value for value in markdown_values)
