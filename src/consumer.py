"""日志消费器：模拟实时 tail 消费，可替换为 Kafka / Filebeat 等实现。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, Protocol

try:
    from .models import LogEvent
    from .parser import load_log_events
except ImportError:
    from models import LogEvent
    from parser import load_log_events


class LogConsumer(Protocol):
    """日志消费器协议。生产环境可实现 KafkaConsumer / FilebeatConsumer。"""

    def stream(self) -> Iterator[LogEvent]:
        ...


class FileTailConsumer:
    """简单 tail 消费器。Demo 中逐行 yield；生产中可替换为 Kafka / Filebeat。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def stream(self) -> Iterator[LogEvent]:
        for event in load_log_events(self.path):
            yield event
