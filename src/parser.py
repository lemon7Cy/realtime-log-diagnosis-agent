"""日志解析器：将原始日志行解析为结构化 LogEvent。"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

try:
    from .models import LogEvent
except ImportError:
    from models import LogEvent

LOG_PATTERN = re.compile(
    r"^(?P<ts>\S+)\s+(?P<service>\S+)\s+(?P<level>\S+)\s+(?P<kv>.*?)(?:\s+message=\"(?P<message>.*)\")?$"
)
KV_PATTERN = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>\S+)")


def parse_log_line(line: str) -> LogEvent:
    line = line.strip()
    match = LOG_PATTERN.match(line)
    if not match:
        raise ValueError(f"无法解析日志行: {line}")

    kv_text = match.group("kv") or ""
    fields = {m.group("key"): m.group("value") for m in KV_PATTERN.finditer(kv_text)}
    message = match.group("message") or fields.pop("message", "")
    return LogEvent(
        timestamp=datetime.fromisoformat(match.group("ts")),
        service=match.group("service"),
        level=match.group("level"),
        message=message,
        fields=fields,
        raw=line,
    )


def load_log_events(path: Path) -> list[LogEvent]:
    return [parse_log_line(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
