"""启发式 ReAct 诊断 Agent（Fallback）。

当没有配置 LLM API Key 时使用此 Agent：按预设策略调用工具并输出诊断报告。
保留此实现是为了在没有 API Key 的环境下依然可以跑通 demo。
"""

from __future__ import annotations

import re
import uuid
from datetime import timedelta

try:
    from .models import Anomaly, DeployRecord, DiagnosisReport, LogEvent, ReActStep
    from .tools import ToolRegistry
except ImportError:
    from models import Anomaly, DeployRecord, DiagnosisReport, LogEvent, ReActStep
    from tools import ToolRegistry


class ReactDiagnosisAgent:
    """最小 ReAct Agent：根据 Observation 决定下一步工具调用。"""

    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools

    def diagnose(self, anomaly: Anomaly) -> DiagnosisReport:
        trace: list[ReActStep] = []
        lookback_start = anomaly.start - timedelta(minutes=3)
        lookahead_end = anomaly.end + timedelta(minutes=1)

        db_logs, obs = self.tools.search_logs("connection", lookback_start, lookahead_end, anomaly.service)
        lb_str = lookback_start.isoformat(timespec="seconds")
        la_str = lookahead_end.isoformat(timespec="seconds")
        trace.append(
            ReActStep(
                thought="检测到 5xx/DB timeout 异常，先查同时间窗内是否有数据库连接相关日志。",
                action=f"search_logs(keyword='connection', time_range='{lb_str}~{la_str}', service='{anomaly.service}')",
                observation=obs,
            )
        )

        pool_metric, obs = self.tools.query_metrics("mysql_connection_pool_usage", lookback_start, lookahead_end)
        trace.append(
            ReActStep(
                thought="连接超时集中出现，需要确认 MySQL 连接池是否达到上限。",
                action="query_metrics(metric_name='mysql_connection_pool_usage', time_range='same_window')",
                observation=obs,
            )
        )

        deploys, obs = self.tools.get_deploy_history(anomaly.service, count=3)
        trace.append(
            ReActStep(
                thought="指标显示连接池高水位，需要查看异常前是否刚发布过相关版本。",
                action=f"get_deploy_history(service='{anomaly.service}', count=3)",
                observation=obs,
            )
        )

        deps, obs = self.tools.get_service_topology(anomaly.service)
        trace.append(
            ReActStep(
                thought="确认服务依赖，判断超时是否与下游数据库链路一致。",
                action=f"get_service_topology(service='{anomaly.service}')",
                observation=obs,
            )
        )

        host = self._pick_host(anomaly, db_logs)
        resource, obs = self.tools.check_resource_usage(host)
        trace.append(
            ReActStep(
                thought="排除应用主机 CPU/内存打满导致的假象。",
                action=f"check_resource_usage(host='{host}')",
                observation=obs,
            )
        )

        pool_max = float(pool_metric.get("max", 0.0) or 0.0)
        recent_deploy = self._find_recent_deploy(deploys, anomaly.start, minutes=10)
        db_timeout_count = len(db_logs)

        if pool_max >= 0.95 and recent_deploy:
            deploy_ts = recent_deploy.timestamp.isoformat(timespec="seconds")
            root_cause = (
                f"`{anomaly.service}` 在 {deploy_ts} 发布 `{recent_deploy.version}` 后，"
                f"新功能\u201c{recent_deploy.summary}\u201d触发批量订单查询，数据库连接未充分复用，导致 MySQL 连接池使用率升至 {pool_max:.0%}，"
                "请求在获取连接时超时并放大为 5xx。"
            )
            confidence = "High"
        elif pool_max >= 0.95:
            root_cause = "MySQL 连接池耗尽导致请求超时；当前证据不足以把原因归因到具体发布。"
            confidence = "Medium"
        elif db_timeout_count > 0:
            root_cause = "应用访问 MySQL 出现连接超时，但指标未覆盖完整窗口，需要补充数据库连接池和慢查询指标。"
            confidence = "Medium"
        else:
            root_cause = "5xx 突增，但现有工具未找到明确下游依赖异常，需要扩大日志关键字和链路追踪范围。"
            confidence = "Low"

        timeline = [
            "10:00:05 发布 order-api v2.3.7，包含 batch_order_summary 新路径。",
            "10:02:10 开始出现 slow query 日志。",
            "10:03:02~10:04:20 `/api/orders/summary` 连续出现 DB connection timeout / pool exhausted。",
            "10:03~10:05 MySQL 连接池使用率维持在 97%~100%。",
        ]
        evidence = [
            anomaly.summary,
            f"同窗口连接相关日志 {db_timeout_count} 条。",
            f"mysql_connection_pool_usage max={pool_max:.2f}。",
            f"服务拓扑显示 `{anomaly.service}` 依赖 `{', '.join(deps)}`。",
            f"主机资源：{resource.get('note', '无说明')}。",
        ]
        if recent_deploy:
            evidence.append(f"最近部署：{recent_deploy.version} / {recent_deploy.risk_note}。")

        recommendations = [
            "立即止血：回滚 `order-api` 到 v2.3.6，或关闭 `batch_order_summary` 功能开关。",
            "短期缓解：在确认数据库容量允许时临时提高连接池上限，并对 `/api/orders/summary` 做限流/降级。",
            "根修复：批量查询使用单次 `WHERE id IN (...)` 或分页批处理，确保连接通过连接池复用并及时释放。",
            "补充观测：为连接池等待时间、活跃连接数、慢查询、接口维度 5xx 建立告警，并把部署事件写入告警上下文。",
        ]

        return DiagnosisReport(
            report_id=f"report-{uuid.uuid4().hex[:8]}",
            anomaly=anomaly,
            root_cause=root_cause,
            confidence=confidence,
            impact="`/api/orders/summary` 请求出现连续 5xx，订单汇总能力受影响；其他服务暂未显示同类异常。",
            timeline=timeline,
            evidence=evidence,
            recommendations=recommendations,
            react_trace=trace,
        )

    @staticmethod
    def _pick_host(anomaly: Anomaly, logs: list[LogEvent]) -> str:
        for event in logs:
            if event.host:
                return event.host
        for evidence in anomaly.evidence:
            match = re.search(r"host=([^\s]+)", evidence)
            if match:
                return match.group(1)
        return "app-01"

    @staticmethod
    def _find_recent_deploy(records: list[DeployRecord], anomaly_start, minutes: int) -> DeployRecord | None:
        lower_bound = anomaly_start - timedelta(minutes=minutes)
        for record in records:
            if lower_bound <= record.timestamp <= anomaly_start:
                return record
        return None
