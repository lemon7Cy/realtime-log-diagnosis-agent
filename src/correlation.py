"""Alert correlation and incident grouping utilities."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

try:
    from .models import Anomaly
except ImportError:
    from models import Anomaly


SEVERITY_RANK = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}


@dataclass
class Incident:
    """A correlated group of alerts/anomalies for the same blast radius."""

    incident_id: str
    service: str
    kind: str
    severity: str
    start: datetime
    end: datetime
    anomaly_ids: list[str] = field(default_factory=list)
    summaries: list[str] = field(default_factory=list)

    @property
    def alert_count(self) -> int:
        return len(self.anomaly_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "incident_id": self.incident_id,
            "service": self.service,
            "kind": self.kind,
            "severity": self.severity,
            "start": self.start.isoformat(timespec="seconds"),
            "end": self.end.isoformat(timespec="seconds"),
            "alert_count": self.alert_count,
            "anomaly_ids": list(self.anomaly_ids),
            "summaries": list(self.summaries),
        }


class AlertCorrelator:
    """Groups same-service/same-kind anomalies into incidents within a time window."""

    def __init__(self, window_minutes: int = 5) -> None:
        self.window = timedelta(minutes=window_minutes)
        self._incidents: list[Incident] = []

    def correlate(self, anomaly: Anomaly) -> Incident:
        incident = self._find_match(anomaly)
        if incident is None:
            incident = Incident(
                incident_id=f"inc-{uuid.uuid4().hex[:8]}",
                service=anomaly.service,
                kind=anomaly.kind,
                severity=anomaly.severity,
                start=anomaly.start,
                end=anomaly.end,
                anomaly_ids=[anomaly.anomaly_id],
                summaries=[anomaly.summary],
            )
            self._incidents.append(incident)
            return incident

        incident.start = min(incident.start, anomaly.start)
        incident.end = max(incident.end, anomaly.end)
        if anomaly.anomaly_id not in incident.anomaly_ids:
            incident.anomaly_ids.append(anomaly.anomaly_id)
        incident.summaries.append(anomaly.summary)
        if SEVERITY_RANK.get(anomaly.severity, 0) > SEVERITY_RANK.get(incident.severity, 0):
            incident.severity = anomaly.severity
        return incident

    def list_incidents(self) -> list[Incident]:
        return list(self._incidents)

    def _find_match(self, anomaly: Anomaly) -> Incident | None:
        for incident in reversed(self._incidents):
            if incident.service != anomaly.service or incident.kind != anomaly.kind:
                continue
            if anomaly.start <= incident.end + self.window and anomaly.end >= incident.start - self.window:
                return incident
        return None
