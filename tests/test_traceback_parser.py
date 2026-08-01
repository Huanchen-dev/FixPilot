from app.traceback_parser import parse_traceback


def test_parse_python_traceback():
    info = parse_traceback(
        'Traceback (most recent call last):\n'
        '  File "D:\\demo\\service.py", line 18, in start\n'
        "    import missing_package\n"
        "ModuleNotFoundError: No module named 'missing_package'"
    )
    assert info.exception_type == "ModuleNotFoundError"
    assert info.message == "No module named 'missing_package'"
    assert info.frames[0].file.endswith("service.py")
    assert info.frames[0].line == 18
    assert "missing_package" in info.search_terms


def test_parse_single_error_line():
    info = parse_traceback("PermissionError: [Errno 13] Permission denied")
    assert info.exception_type == "PermissionError"
    assert info.frames == []
