"""不依赖大模型的Python Traceback结构化解析。"""

import re
from pathlib import Path

from app.schemas import TracebackFrame, TracebackInfo


FRAME_PATTERN = re.compile(
    r'^\s*File "(?P<file>.+)", line (?P<line>\d+), in (?P<function>.+)\s*$'
)
EXCEPTION_PATTERN = re.compile(
    r"^(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Interrupt))"
    r"(?::\s*(?P<message>.*))?$"
)


def _exception_line(lines: list[str]) -> tuple[str, str]:
    for line in reversed(lines):
        candidate = line.strip()
        match = EXCEPTION_PATTERN.match(candidate)
        if match:
            return match.group("type"), (match.group("message") or "").strip()
    last = next((line.strip() for line in reversed(lines) if line.strip()), "")
    if ":" in last:
        name, message = last.split(":", 1)
        return name.strip() or "UnknownError", message.strip()
    return "UnknownError", last or "未提供明确异常信息"


def parse_traceback(raw_traceback: str) -> TracebackInfo:
    """提取异常类型、消息、调用帧以及后续代码搜索关键词。"""

    lines = raw_traceback.strip().splitlines()
    frames: list[TracebackFrame] = []
    for index, line in enumerate(lines):
        match = FRAME_PATTERN.match(line)
        if not match:
            continue
        code = None
        if index + 1 < len(lines):
            next_line = lines[index + 1].strip()
            if next_line and not FRAME_PATTERN.match(lines[index + 1]):
                code = next_line
        frames.append(
            TracebackFrame(
                file=match.group("file"),
                line=int(match.group("line")),
                function=match.group("function").strip(),
                code=code,
            )
        )

    exception_type, message = _exception_line(lines)
    terms: list[str] = [exception_type]
    for frame in reversed(frames[-5:]):
        terms.extend([Path(frame.file).name, frame.function])
    message_words = re.findall(r"[A-Za-z_][\w.-]{2,}", message)
    terms.extend(message_words[:5])

    unique_terms: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = term.strip()
        if not normalized or normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        unique_terms.append(normalized)

    return TracebackInfo(
        exception_type=exception_type,
        message=message,
        frames=frames,
        search_terms=unique_terms[:12],
    )
