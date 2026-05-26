"""异常检测器：多策略管道，支持滑动窗口、Z-Score 和关键词聚类。"""

from __future__ import annotations

import uuid
from collections import Counter, deque
from datetime import datetime, timedelta
from statistics import mean, stdev
from typing import Protocol

try:
    from .models import Anomaly, LogEvent
except ImportError:
    from models import Anomaly, LogEvent


class AnomalyDetector(Protocol):
    """异常检测器协议。所有检测策略统一实现此接口。"""

    def observe(self, event: LogEvent) -> Anomaly | None:
        ...


class SlidingWindowAnomalyDetector:
    """规则 + 统计的最小异常检测器。"""

    def __init__(
        self,
        window_seconds: int = 120,
        min_5xx_count: int = 3,
        error_rate_threshold: float = 0.30,
        db_timeout_threshold: int = 2,
        cooldown_seconds: int = 180,
    ) -> None:
        self.window = timedelta(seconds=window_seconds)
        self.cooldown = timedelta(seconds=cooldown_seconds)
        self.min_5xx_count = min_5xx_count
        self.error_rate_threshold = error_rate_threshold
        self.db_timeout_threshold = db_timeout_threshold
        self.events: deque[LogEvent] = deque()
        self._last_emitted_at: dict[tuple[str, str], datetime] = {}

    def observe(self, event: LogEvent) -> Anomaly | None:
        self.events.append(event)
        cutoff = event.timestamp - self.window
        while self.events and self.events[0].timestamp < cutoff:
            self.events.popleft()

        service_events = [item for item in self.events if item.service == event.service]
        if not service_events:
            return None

        error_events = [item for item in service_events if item.status_code and item.status_code >= 500]
        db_timeout_events = [
            item
            for item in service_events
            if "connection timeout" in item.message.lower() or "pool exhausted" in item.message.lower()
        ]
        error_rate = len(error_events) / max(len(service_events), 1)
        start = service_events[0].timestamp
        end = service_events[-1].timestamp

        if len(error_events) >= self.min_5xx_count and error_rate >= self.error_rate_threshold:
            if self._can_emit(event.service, "5xx_spike", end):
                return Anomaly(
                    anomaly_id=f"anom-{uuid.uuid4().hex[:8]}",
                    service=event.service,
                    kind="5xx_spike",
                    severity="High",
                    start=start,
                    end=end,
                    summary=f"{len(error_events)} 个 5xx / {len(service_events)} 条请求，错误率 {error_rate:.0%}",
                    evidence=[item.compact() for item in error_events[-5:]],
                )

        if len(db_timeout_events) >= self.db_timeout_threshold:
            if self._can_emit(event.service, "db_timeout_cluster", end):
                return Anomaly(
                    anomaly_id=f"anom-{uuid.uuid4().hex[:8]}",
                    service=event.service,
                    kind="db_timeout_cluster",
                    severity="High",
                    start=start,
                    end=end,
                    summary=f"检测到 {len(db_timeout_events)} 条数据库连接超时/连接池耗尽日志",
                    evidence=[item.compact() for item in db_timeout_events[-5:]],
                )

        return None

    def _can_emit(self, service: str, kind: str, now: datetime) -> bool:
        """对同一服务/异常类型做冷却，避免连续日志造成告警风暴。"""
        key = (service, kind)
        last = self._last_emitted_at.get(key)
        if last and now - last < self.cooldown:
            return False
        self._last_emitted_at[key] = now
        return True


class ZScoreAnomalyDetector:
    """基于 Z-Score 统计异常检测：检测响应时间/错误率的突变。"""

    def __init__(
        self,
        window_seconds: int = 300,
        z_threshold: float = 2.5,
        min_samples: int = 10,
        cooldown_seconds: int = 180,
    ) -> None:
        self.window = timedelta(seconds=window_seconds)
        self.z_threshold = z_threshold
        self.min_samples = min_samples
        self.cooldown = timedelta(seconds=cooldown_seconds)
        self._latencies: deque[tuple[datetime, str, float]] = deque()
        self._last_emitted_at: dict[tuple[str, str], datetime] = {}

    def observe(self, event: LogEvent) -> Anomaly | None:
        latency_str = event.fields.get("latency_ms") or event.fields.get("duration_ms")
        if not latency_str:
            return None
        try:
            latency = float(latency_str)
        except ValueError:
            return None

        self._latencies.append((event.timestamp, event.service, latency))
        cutoff = event.timestamp - self.window
        while self._latencies and self._latencies[0][0] < cutoff:
            self._latencies.popleft()

        service_latencies = [v for ts, svc, v in self._latencies if svc == event.service]
        if len(service_latencies) < self.min_samples:
            return None

        avg = mean(service_latencies)
        sd = stdev(service_latencies) if len(service_latencies) > 1 else 0.0
        if sd == 0:
            return None

        z = (latency - avg) / sd
        if z >= self.z_threshold:
            key = (event.service, "latency_spike")
            last = self._last_emitted_at.get(key)
            if last and event.timestamp - last < self.cooldown:
                return None
            self._last_emitted_at[key] = event.timestamp
            return Anomaly(
                anomaly_id=f"anom-{uuid.uuid4().hex[:8]}",
                service=event.service,
                kind="latency_spike",
                severity="Medium",
                start=event.timestamp - self.window,
                end=event.timestamp,
                summary=f"响应时间异常突增：{latency:.0f}ms（均值 {avg:.0f}ms，Z-Score {z:.1f}）",
                evidence=[event.compact()],
            )
        return None


class KeywordClusterDetector:
    """关键词聚类检测：短时间内同一错误关键词出现频率突增。"""

    ALERT_KEYWORDS = [
        "oom", "out of memory", "killed", "segfault",
        "deadlock", "lock wait timeout",
        "certificate expired", "ssl handshake",
        "disk full", "no space left",
    ]

    def __init__(
        self,
        window_seconds: int = 60,
        threshold: int = 3,
        cooldown_seconds: int = 300,
    ) -> None:
        self.window = timedelta(seconds=window_seconds)
        self.threshold = threshold
        self.cooldown = timedelta(seconds=cooldown_seconds)
        self._events: deque[tuple[datetime, str, str]] = deque()
        self._last_emitted_at: dict[tuple[str, str], datetime] = {}

    def observe(self, event: LogEvent) -> Anomaly | None:
        msg_lower = event.message.lower() + " " + event.raw.lower()
        matched_keyword: str | None = None
        for kw in self.ALERT_KEYWORDS:
            if kw in msg_lower:
                matched_keyword = kw
                break
        if not matched_keyword:
            return None

        self._events.append((event.timestamp, event.service, matched_keyword))
        cutoff = event.timestamp - self.window
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

        count = sum(1 for ts, svc, kw in self._events if svc == event.service and kw == matched_keyword)
        if count >= self.threshold:
            key = (event.service, f"keyword_{matched_keyword}")
            last = self._last_emitted_at.get(key)
            if last and event.timestamp - last < self.cooldown:
                return None
            self._last_emitted_at[key] = event.timestamp
            return Anomaly(
                anomaly_id=f"anom-{uuid.uuid4().hex[:8]}",
                service=event.service,
                kind=f"keyword_cluster:{matched_keyword}",
                severity="High" if matched_keyword in ("oom", "out of memory", "deadlock") else "Medium",
                start=event.timestamp - self.window,
                end=event.timestamp,
                summary=f"关键词 `{matched_keyword}` 在 {self.window.seconds}s 内出现 {count} 次",
                evidence=[event.compact()],
            )
        return None


class DetectorPipeline:
    """多策略检测管道：按优先级依次运行检测器，第一个触发的即返回。"""

    def __init__(self, detectors: list[AnomalyDetector] | None = None) -> None:
        self.detectors: list[AnomalyDetector] = detectors or [
            SlidingWindowAnomalyDetector(),
            ZScoreAnomalyDetector(),
            KeywordClusterDetector(),
        ]

    def observe(self, event: LogEvent) -> Anomaly | None:
        for detector in self.detectors:
            anomaly = detector.observe(event)
            if anomaly:
                return anomaly
        return None
