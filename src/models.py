"""数据模型定义：日志事件、指标点、部署记录、异常、ReAct 步骤、诊断报告。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class LogEvent:
    timestamp: datetime
    service: str
    level: str
    message: str
    fields: dict[str, str] = field(default_factory=dict)
    raw: str = ""

    @property
    def status_code(self) -> int | None:
        status = self.fields.get("status")
        if status and status.isdigit():
            return int(status)
        return None

    @property
    def host(self) -> str | None:
        return self.fields.get("host")

    def compact(self) -> str:
        status = self.fields.get("status", "-")
        host = self.fields.get("host", "-")
        path = self.fields.get("path", "-")
        return f"{self.timestamp.isoformat(timespec='seconds')} {self.service} {self.level} status={status} host={host} path={path} message=\"{self.message}\""


@dataclass(frozen=True)
class MetricPoint:
    timestamp: datetime
    metric_name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DeployRecord:
    timestamp: datetime
    service: str
    version: str
    operator: str
    summary: str
    risk_note: str


@dataclass(frozen=True)
class Anomaly:
    anomaly_id: str
    service: str
    kind: str
    severity: str
    start: datetime
    end: datetime
    summary: str
    evidence: list[str]

    def to_markdown(self) -> str:
        lines = [
            f"### {self.severity} / {self.kind}",
            f"- 服务：`{self.service}`",
            f"- 时间窗：`{self.start.isoformat(timespec='seconds')}` ~ `{self.end.isoformat(timespec='seconds')}`",
            f"- 摘要：{self.summary}",
            "- 证据：",
        ]
        lines.extend(f"  - {item}" for item in self.evidence)
        return "\n".join(lines)


@dataclass(frozen=True)
class ReActStep:
    thought: str
    action: str
    observation: str

    def to_markdown(self) -> str:
        return f"- Thought：{self.thought}\n  - Action：`{self.action}`\n  - Observation：{self.observation}"


@dataclass(frozen=True)
class DiagnosisReport:
    report_id: str
    anomaly: Anomaly
    root_cause: str
    confidence: str
    impact: str
    timeline: list[str]
    evidence: list[str]
    recommendations: list[str]
    react_trace: list[ReActStep]
    created_at: datetime = field(default_factory=datetime.now)

    def to_markdown(self) -> str:
        lines = [
            f"# 实时日志异常诊断报告 `{self.report_id}`",
            "",
            self.anomaly.to_markdown(),
            "",
            "## 根因结论",
            f"- 置信度：{self.confidence}",
            f"- 根因：{self.root_cause}",
            f"- 影响：{self.impact}",
            "",
            "## ReAct 诊断轨迹",
        ]
        lines.extend(step.to_markdown() for step in self.react_trace)
        lines.extend(["", "## 关键时间线"])
        lines.extend(f"- {item}" for item in self.timeline)
        lines.extend(["", "## 关键证据"])
        lines.extend(f"- {item}" for item in self.evidence)
        lines.extend(["", "## 修复建议"])
        lines.extend(f"{idx}. {item}" for idx, item in enumerate(self.recommendations, start=1))
        return "\n".join(lines)
