"""诊断工具注册表：Agent 可调用的工具集。

每个工具返回 (结构化数据, 适合进入 Observation 的短文本)。
工具定义同时提供 JSON Schema，供 LLM tool_use 使用。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

try:
    from ..models import DeployRecord, LogEvent
    from ..store import DataSource, ObservabilityStore
except ImportError:
    from models import DeployRecord, LogEvent
    from store import DataSource, ObservabilityStore


# LLM tool_use 的 JSON Schema 定义
TOOL_DEFINITIONS = [
    {
        "name": "search_logs",
        "description": "在日志中搜索关键词，返回匹配的日志条目。用于查找特定错误、超时、异常等信息。",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词，如 'timeout', 'connection', 'error'"},
                "start": {"type": "string", "description": "开始时间 ISO 格式，如 '2026-05-23T10:00:00'"},
                "end": {"type": "string", "description": "结束时间 ISO 格式"},
                "service": {"type": "string", "description": "可选，限定服务名"},
            },
            "required": ["keyword", "start", "end"],
        },
    },
    {
        "name": "query_metrics",
        "description": "查询监控指标时间序列（如连接池使用率、CPU、内存、5xx 比率等）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_name": {"type": "string", "description": "指标名，如 'mysql_connection_pool_usage', 'http_5xx_rate', 'app_cpu_usage'"},
                "start": {"type": "string", "description": "开始时间 ISO 格式"},
                "end": {"type": "string", "description": "结束时间 ISO 格式"},
            },
            "required": ["metric_name", "start", "end"],
        },
    },
    {
        "name": "get_deploy_history",
        "description": "获取指定服务的最近部署记录，用于判断异常是否与最近发布有关。",
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "服务名"},
                "count": {"type": "integer", "description": "返回最近 N 条记录，默认 3", "default": 3},
            },
            "required": ["service"],
        },
    },
    {
        "name": "get_service_topology",
        "description": "查看服务的依赖拓扑，了解上下游关系。",
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "服务名"},
            },
            "required": ["service"],
        },
    },
    {
        "name": "check_resource_usage",
        "description": "查看主机资源使用情况（CPU、内存、磁盘），排除资源瓶颈。",
        "input_schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "主机名，如 'app-01', 'mysql-primary'"},
            },
            "required": ["host"],
        },
    },
]


class ToolRegistry:
    """Agent 可调用工具集；方法返回适合进入 Observation 的短文本。"""

    def __init__(self, store: DataSource) -> None:
        self.store = store

    def execute(self, tool_name: str, args: dict[str, Any]) -> tuple[Any, str]:
        """统一工具调用入口，供 LLM Agent 使用。返回 (结构化结果, 文本摘要)。"""
        dispatch = {
            "search_logs": self._exec_search_logs,
            "query_metrics": self._exec_query_metrics,
            "get_deploy_history": self._exec_get_deploy_history,
            "get_service_topology": self._exec_get_service_topology,
            "check_resource_usage": self._exec_check_resource_usage,
        }
        handler = dispatch.get(tool_name)
        if not handler:
            return None, f"未知工具: {tool_name}"
        return handler(args)

    def _exec_search_logs(self, args: dict[str, Any]) -> tuple[list[LogEvent], str]:
        start = datetime.fromisoformat(args["start"])
        end = datetime.fromisoformat(args["end"])
        service = args.get("service")
        return self.search_logs(args["keyword"], start, end, service)

    def _exec_query_metrics(self, args: dict[str, Any]) -> tuple[dict[str, Any], str]:
        start = datetime.fromisoformat(args["start"])
        end = datetime.fromisoformat(args["end"])
        return self.query_metrics(args["metric_name"], start, end)

    def _exec_get_deploy_history(self, args: dict[str, Any]) -> tuple[list[DeployRecord], str]:
        return self.get_deploy_history(args["service"], args.get("count", 3))

    def _exec_get_service_topology(self, args: dict[str, Any]) -> tuple[list[str], str]:
        return self.get_service_topology(args["service"])

    def _exec_check_resource_usage(self, args: dict[str, Any]) -> tuple[dict[str, Any], str]:
        return self.check_resource_usage(args["host"])

    # --- 直接调用方法（供 heuristic agent 使用）---

    def search_logs(self, keyword: str, start: datetime, end: datetime, service: str | None = None) -> tuple[list[LogEvent], str]:
        logs = self.store.search_logs(keyword, start, end, service)
        preview = "; ".join(event.compact() for event in logs[:3])
        if len(logs) > 3:
            preview += f"; ... 共 {len(logs)} 条"
        return logs, preview or "没有匹配日志"

    def query_metrics(self, metric_name: str, start: datetime, end: datetime) -> tuple[dict[str, Any], str]:
        result = self.store.query_metrics(metric_name, start, end)
        if not result.get("points"):
            return result, result["summary"]
        return result, f"{metric_name}: max={result['max']:.2f}, avg={result['avg']:.2f}, latest={result['latest']['value']:.2f}"

    def get_deploy_history(self, service: str, count: int = 3) -> tuple[list[DeployRecord], str]:
        records = self.store.get_deploy_history(service, count)
        if not records:
            return records, "没有部署记录"
        return records, "; ".join(
            f"{record.timestamp.isoformat(timespec='seconds')} {record.version} {record.summary}" for record in records
        )

    def get_service_topology(self, service: str) -> tuple[list[str], str]:
        deps = self.store.get_service_topology(service)
        return deps, f"{service} 依赖：{', '.join(deps) if deps else '无记录'}"

    def check_resource_usage(self, host: str) -> tuple[dict[str, Any], str]:
        usage = self.store.check_resource_usage(host)
        if "cpu" not in usage:
            return usage, usage.get("note", "无资源数据")
        return usage, (
            f"{host}: cpu={usage['cpu']:.0%}, memory={usage['memory']:.0%}, "
            f"disk={usage['disk']:.0%}; {usage['note']}"
        )
