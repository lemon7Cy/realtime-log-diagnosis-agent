"""可观测性数据源：提供日志搜索、指标查询、部署记录、拓扑和资源使用。

定义 DataSource Protocol 接口，demo 使用内存 Mock 实现。
生产环境可实现 ElasticsearchSource / PrometheusSource / K8sSource。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean
from typing import Any, Iterable, Protocol

try:
    from .models import DeployRecord, LogEvent, MetricPoint
except ImportError:
    from models import DeployRecord, LogEvent, MetricPoint


class DataSource(Protocol):
    """数据源协议。定义所有诊断工具需要的底层查询接口。"""

    def search_logs(self, keyword: str, start: datetime, end: datetime, service: str | None = None) -> list[LogEvent]:
        ...

    def query_metrics(self, metric_name: str, start: datetime, end: datetime) -> dict[str, Any]:
        ...

    def get_deploy_history(self, service: str, count: int = 3) -> list[DeployRecord]:
        ...

    def get_service_topology(self, service: str) -> list[str]:
        ...

    def check_resource_usage(self, host: str) -> dict[str, Any]:
        ...


class ObservabilityStore:
    """内存模拟的可观测性数据源。实现 DataSource 协议。"""

    def __init__(self, logs: Iterable[LogEvent]) -> None:
        self.logs = list(logs)
        self.metrics = self._build_demo_metrics()
        self.deploy_history = self._build_demo_deploy_history()
        self.topology = {
            "order-api": ["mysql-primary", "redis-cache", "payment-api"],
            "payment-api": ["payment-db"],
        }
        self.resource_usage = {
            "app-01": {"cpu": 0.58, "memory": 0.64, "disk": 0.41, "note": "应用主机资源正常"},
            "mysql-primary": {"cpu": 0.72, "memory": 0.83, "disk": 0.55, "note": "数据库主机 CPU/内存未打满，瓶颈更像连接池耗尽"},
        }

    @staticmethod
    def _build_demo_metrics() -> list[MetricPoint]:
        base = datetime.fromisoformat("2026-05-23T10:00:00")
        return [
            MetricPoint(base + timedelta(minutes=0), "mysql_connection_pool_usage", 0.62, {"service": "order-api"}),
            MetricPoint(base + timedelta(minutes=1), "mysql_connection_pool_usage", 0.66, {"service": "order-api"}),
            MetricPoint(base + timedelta(minutes=2), "mysql_connection_pool_usage", 0.88, {"service": "order-api"}),
            MetricPoint(base + timedelta(minutes=3), "mysql_connection_pool_usage", 0.99, {"service": "order-api"}),
            MetricPoint(base + timedelta(minutes=4), "mysql_connection_pool_usage", 1.00, {"service": "order-api"}),
            MetricPoint(base + timedelta(minutes=5), "mysql_connection_pool_usage", 0.97, {"service": "order-api"}),
            MetricPoint(base + timedelta(minutes=3), "http_5xx_rate", 0.43, {"service": "order-api"}),
            MetricPoint(base + timedelta(minutes=4), "http_5xx_rate", 0.71, {"service": "order-api"}),
            MetricPoint(base + timedelta(minutes=4), "mysql_active_connections", 100.0, {"service": "order-api", "max": "100"}),
            MetricPoint(base + timedelta(minutes=4), "app_cpu_usage", 0.58, {"host": "app-01"}),
            MetricPoint(base + timedelta(minutes=4), "app_memory_usage", 0.64, {"host": "app-01"}),
        ]

    @staticmethod
    def _build_demo_deploy_history() -> list[DeployRecord]:
        return [
            DeployRecord(
                timestamp=datetime.fromisoformat("2026-05-23T10:00:05"),
                service="order-api",
                version="v2.3.7",
                operator="ci-bot",
                summary="新增批量订单汇总功能 batch_order_summary",
                risk_note="新路径会批量读取用户订单，若连接未复用可能放大 DB 连接数",
            ),
            DeployRecord(
                timestamp=datetime.fromisoformat("2026-05-22T22:10:00"),
                service="order-api",
                version="v2.3.6",
                operator="ci-bot",
                summary="修复订单列表分页展示",
                risk_note="低风险前端字段调整",
            ),
        ]

    def search_logs(self, keyword: str, start: datetime, end: datetime, service: str | None = None) -> list[LogEvent]:
        keyword_lower = keyword.lower()
        return [
            event
            for event in self.logs
            if start <= event.timestamp <= end
            and (service is None or event.service == service)
            and (keyword_lower in event.message.lower() or keyword_lower in event.raw.lower())
        ]

    def query_metrics(self, metric_name: str, start: datetime, end: datetime) -> dict[str, Any]:
        points = [point for point in self.metrics if point.metric_name == metric_name and start <= point.timestamp <= end]
        if not points:
            return {"metric": metric_name, "points": [], "summary": "没有匹配指标点"}
        values = [point.value for point in points]
        latest = points[-1]
        return {
            "metric": metric_name,
            "count": len(points),
            "min": min(values),
            "max": max(values),
            "avg": mean(values),
            "latest": {"timestamp": latest.timestamp.isoformat(timespec="seconds"), "value": latest.value, "labels": latest.labels},
            "points": [
                {"timestamp": point.timestamp.isoformat(timespec="seconds"), "value": point.value, "labels": point.labels}
                for point in points
            ],
        }

    def get_deploy_history(self, service: str, count: int = 3) -> list[DeployRecord]:
        records = [record for record in self.deploy_history if record.service == service]
        return sorted(records, key=lambda item: item.timestamp, reverse=True)[:count]

    def get_service_topology(self, service: str) -> list[str]:
        return self.topology.get(service, [])

    def check_resource_usage(self, host: str) -> dict[str, Any]:
        return self.resource_usage.get(host, {"note": "没有该主机资源数据"})
