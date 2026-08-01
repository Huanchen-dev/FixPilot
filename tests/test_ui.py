from streamlit.testing.v1 import AppTest


def test_fixpilot_page_initial_render():
    app = AppTest.from_file("ui.py")
    app.run(timeout=10)
    assert not app.exception
    assert app.title[0].value == "FixPilot"
    assert app.button[0].label == "开始只读诊断"
