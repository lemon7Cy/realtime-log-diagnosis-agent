"""Runbook planner for structured remediation plans."""

from __future__ import annotations

try:
    from .models import Anomaly
except ImportError:
    from models import Anomaly


class RunbookPlanner:
    """Builds deterministic remediation plans from anomaly/root-cause signals."""

    def plan(self, anomaly: Anomaly, root_cause: str = "") -> dict[str, object]:
        text = f"{anomaly.kind} {anomaly.summary} {root_cause}".lower()
        actions: list[str]
        rollback: list[str]
        verify: list[str]

        if any(token in text for token in ["db_timeout", "connection pool", "mysql", "连接池", "database"]):
            actions = [
                f"确认 `{anomaly.service}` 当前 5xx、连接池使用率、连接等待时间是否仍在高位。",
                "临时关闭高风险入口或功能开关（如 batch_order_summary），对热点接口限流/降级。",
                "检查 MySQL active connections、慢查询和应用连接释放路径，必要时在容量允许下短暂提高连接池上限。",
                "通知服务 owner 与 DBA 协同排查连接泄漏、批量查询和索引退化。",
            ]
            rollback = [
                f"若异常发生在最近发布后，回滚 `{anomaly.service}` 到上一稳定版本。",
                "回滚或禁用新增批量查询路径后保留现场指标，用于后续根因复盘。",
            ]
            verify = [
                "5xx rate 回落到 SLO 阈值以内并持续至少 10 分钟。",
                "连接池使用率低于 80%，连接等待/超时日志不再增长。",
                "抽样验证受影响接口返回 2xx 且延迟恢复到基线。",
            ]
        elif "latency" in text or "slow" in text:
            actions = [
                f"定位 `{anomaly.service}` 慢请求 path、host 和下游依赖。",
                "启用限流或缓存降级，保护核心写路径。",
                "检查近期部署、依赖延迟和资源水位。",
            ]
            rollback = ["若延迟与发布强相关，回滚最近版本或关闭对应 feature flag。"]
            verify = ["P95/P99 latency 恢复到基线。", "错误率未因降级继续升高。"]
        else:
            actions = [
                f"聚合 `{anomaly.service}` 同类日志并确认影响面。",
                "查看部署、依赖拓扑和资源指标，缩小根因范围。",
                "根据业务优先级执行限流、降级或扩容。",
            ]
            rollback = ["若与变更窗口吻合，优先回滚最近变更。"]
            verify = ["异常日志停止增长。", "核心 SLI 恢复到目标阈值内。"]

        return {
            "severity": anomaly.severity,
            "actions": actions,
            "rollback": rollback,
            "verify": verify,
            "owner_hint": f"{anomaly.service}-oncall",
        }
