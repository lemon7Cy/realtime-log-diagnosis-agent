"""SLO impact estimation from in-memory observability data."""

from __future__ import annotations

try:
    from .models import Anomaly
    from .store import ObservabilityStore
except ImportError:
    from models import Anomaly
    from store import ObservabilityStore


class SLOImpactCalculator:
    """Estimate affected requests and error-budget burn for an anomaly window."""

    def __init__(self, target_success_rate: float = 0.99) -> None:
        if not 0 < target_success_rate < 1:
            raise ValueError("target_success_rate must be between 0 and 1")
        self.target_success_rate = target_success_rate

    def calculate(self, store: ObservabilityStore, anomaly: Anomaly) -> dict[str, object]:
        window_logs = [
            event for event in store.logs
            if event.service == anomaly.service and anomaly.start <= event.timestamp <= anomaly.end
        ]
        total_requests = len([event for event in window_logs if event.status_code is not None]) or len(window_logs)
        failed_requests = len([event for event in window_logs if event.status_code is not None and event.status_code >= 500])
        affected_requests = failed_requests or self._estimate_from_evidence(anomaly)
        observed_error_rate = affected_requests / max(total_requests, 1)
        allowed_error_rate = 1 - self.target_success_rate
        burn_rate = observed_error_rate / allowed_error_rate if allowed_error_rate > 0 else 0.0

        return {
            "service": anomaly.service,
            "window_start": anomaly.start.isoformat(timespec="seconds"),
            "window_end": anomaly.end.isoformat(timespec="seconds"),
            "slo_target": self.target_success_rate,
            "total_requests": total_requests,
            "affected_requests": affected_requests,
            "observed_error_rate": round(observed_error_rate, 4),
            "error_budget_burn_rate": round(burn_rate, 2),
            "summary": (
                f"{anomaly.service} 在异常窗口内约 {affected_requests}/{max(total_requests, 1)} 个请求失败，"
                f"错误预算燃烧约 {burn_rate:.1f}x。"
            ),
        }

    @staticmethod
    def _estimate_from_evidence(anomaly: Anomaly) -> int:
        return max(len(anomaly.evidence), 1)
