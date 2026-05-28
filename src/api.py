"""FastAPI 接口层：把项目三核心能力暴露成可演示后端。

支持：
- REST API（日志写入、诊断、告警管理）
- WebSocket（实时推送告警和诊断轨迹）
- 告警生命周期管理（acknowledge / resolve / silence / escalate）
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from .llm_client import list_models, test_model
    from .llm_config import LLMConfig, LLMConfigUpdate, LLMModelsRequest, get_llm_config, public_config, save_llm_config
    from .models import Anomaly, DiagnosisReport
    from .parser import parse_log_line, load_log_events
    from .detector import SlidingWindowAnomalyDetector, DetectorPipeline
    from .store import ObservabilityStore
    from .tools import ToolRegistry
    from .agent import ReactDiagnosisAgent
    from .llm_agent import LLMReActAgent
    from .pipeline import create_agent, default_log_path, run_pipeline
    from .correlation import AlertCorrelator
    from .runbook import RunbookPlanner
    from .slo import SLOImpactCalculator
except ImportError:
    from llm_client import list_models, test_model
    from llm_config import LLMConfig, LLMConfigUpdate, LLMModelsRequest, get_llm_config, public_config, save_llm_config
    from models import Anomaly, DiagnosisReport
    from parser import parse_log_line, load_log_events
    from detector import SlidingWindowAnomalyDetector, DetectorPipeline
    from store import ObservabilityStore
    from tools import ToolRegistry
    from agent import ReactDiagnosisAgent
    from llm_agent import LLMReActAgent
    from pipeline import create_agent, default_log_path, run_pipeline
    from correlation import AlertCorrelator
    from runbook import RunbookPlanner
    from slo import SLOImpactCalculator


class IngestLogRequest(BaseModel):
    line: str = Field(..., examples=["2026-05-23T10:04:20 order-api ERROR status=500 host=app-01 path=/api/orders/summary dependency=mysql message=\"database connection timeout\""])


class DiagnoseSampleRequest(BaseModel):
    log_file: str | None = None


class CreateDiagnosisJobRequest(BaseModel):
    log_file: str | None = None


class DiagnosisJobRecord(BaseModel):
    job_id: str
    status: str
    created_at: str
    updated_at: str
    result: dict[str, Any] | None = None
    error: str | None = None


class ReplaySampleRequest(BaseModel):
    log_file: str | None = None
    reset_state: bool = True


# ─── 告警生命周期状态机 ──────────────────────────────────────────────────

class AlertStatus(str, Enum):
    FIRING = "firing"
    ACKNOWLEDGED = "acknowledged"
    INVESTIGATING = "investigating"
    SILENCED = "silenced"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


VALID_TRANSITIONS: dict[AlertStatus, set[AlertStatus]] = {
    AlertStatus.FIRING: {AlertStatus.ACKNOWLEDGED, AlertStatus.SILENCED, AlertStatus.RESOLVED},
    AlertStatus.ACKNOWLEDGED: {AlertStatus.INVESTIGATING, AlertStatus.SILENCED, AlertStatus.RESOLVED, AlertStatus.ESCALATED},
    AlertStatus.INVESTIGATING: {AlertStatus.RESOLVED, AlertStatus.ESCALATED},
    AlertStatus.SILENCED: {AlertStatus.FIRING, AlertStatus.RESOLVED},
    AlertStatus.RESOLVED: {AlertStatus.FIRING},
    AlertStatus.ESCALATED: {AlertStatus.RESOLVED, AlertStatus.INVESTIGATING},
}


class AlertRecord(BaseModel):
    alert_id: str
    anomaly_id: str
    service: str
    kind: str
    severity: str
    summary: str
    status: AlertStatus = AlertStatus.FIRING
    created_at: str
    updated_at: str
    report_id: str | None = None
    silenced_until: str | None = None
    acknowledged_by: str | None = None


class AlertActionRequest(BaseModel):
    operator: str = "anonymous"
    comment: str = ""
    duration_minutes: int | None = None


# ─── WebSocket 连接管理器 ────────────────────────────────────────────────

class ConnectionManager:
    """管理 WebSocket 连接，支持广播推送。"""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.active_connections.remove(conn)


# ─── App 初始化 ──────────────────────────────────────────────────────────

try:
    from .config import get_settings
    from .log import setup_logging, get_logger
except ImportError:
    from config import get_settings
    from log import setup_logging, get_logger

_app_settings = get_settings()
setup_logging(_app_settings.log_level, _app_settings.log_format)
_logger = get_logger(__name__)

app = FastAPI(title="Realtime Log Diagnosis Agent", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_app_settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

_initial_events = load_log_events(default_log_path())
_store = ObservabilityStore(_initial_events)
_detector = DetectorPipeline()
_alerts: dict[str, AlertRecord] = {}
_reports: dict[str, str] = {}
_jobs: dict[str, DiagnosisJobRecord] = {}
_ws_manager = ConnectionManager()
_alert_counter = 0
_job_counter = 0
_correlator = AlertCorrelator()
_runbook_planner = RunbookPlanner()
_slo_calculator = SLOImpactCalculator()


def _next_alert_id() -> str:
    global _alert_counter
    _alert_counter += 1
    return f"alert-{_alert_counter:04d}"


def _next_job_id() -> str:
    global _job_counter
    _job_counter += 1
    return f"job-{_job_counter:04d}"


def _reset_runtime_state() -> None:
    global _detector, _alert_counter, _correlator
    _store.logs = list(_initial_events)
    _detector = DetectorPipeline()
    _alerts.clear()
    _reports.clear()
    _alert_counter = 0
    _correlator = AlertCorrelator()


def _diagnose_with_current_agent(anomaly: Anomaly) -> DiagnosisReport:
    return create_agent(_store).diagnose(anomaly)


def _report_payload(report: DiagnosisReport) -> dict[str, Any]:
    return {
        "report_id": report.report_id,
        "markdown": report.to_markdown(),
        "root_cause": report.root_cause,
        "confidence": report.confidence,
        "impact": report.impact,
        "slo_impact": _slo_calculator.calculate(_store, report.anomaly),
        "runbook": _runbook_planner.plan(report.anomaly, report.root_cause),
        "timeline": report.timeline,
        "evidence": report.evidence,
        "recommendations": report.recommendations,
        "react_trace": [
            {"thought": step.thought, "action": step.action, "observation": step.observation}
            for step in report.react_trace
        ],
    }


# ─── Health ──────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "realtime-log-diagnosis-agent",
        "version": "2.0.0",
        "alerts_count": len(_alerts),
        "events_loaded": len(_initial_events),
    }


@app.get("/llm-config")
async def get_runtime_llm_config():
    return public_config()


@app.post("/llm-config")
async def update_runtime_llm_config(req: LLMConfigUpdate):
    if not req.model.strip():
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    config = save_llm_config(req)
    return public_config(config)


@app.post("/llm-config/models")
async def list_runtime_llm_models(req: LLMModelsRequest):
    current = get_llm_config()
    api_key = req.api_key.strip() if req.api_key else current.api_key
    base_url = req.base_url.strip()
    if req.provider == "deepseek" and not base_url:
        base_url = "https://api.deepseek.com"
    config = LLMConfig(
        provider=req.provider,
        api_key=api_key,
        base_url=base_url,
        model=req.model or current.model,
        timeout=req.timeout,
    )
    try:
        return {"models": await list_models(config)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"刷新模型列表失败: {e}")


@app.post("/llm-config/test")
async def test_runtime_llm_config(req: LLMModelsRequest):
    current = get_llm_config()
    api_key = req.api_key.strip() if req.api_key else current.api_key
    base_url = req.base_url.strip()
    if req.provider == "deepseek" and not base_url:
        base_url = "https://api.deepseek.com"
    config = LLMConfig(
        provider=req.provider,
        api_key=api_key,
        base_url=base_url,
        model=req.model or current.model,
        timeout=req.timeout,
    )
    try:
        message = await test_model(config)
        return {"ok": True, "message": message or "OK"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"模型连通性测试失败: {e}")


# ─── WebSocket 实时推送 ──────────────────────────────────────────────────

@app.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket) -> None:
    """WebSocket 端点：实时推送告警和诊断轨迹。"""
    await _ws_manager.connect(websocket)
    try:
        while True:
            # 保持连接活跃，接收客户端心跳
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        _ws_manager.disconnect(websocket)


# ─── 日志写入 + 异常检测 ─────────────────────────────────────────────────

@app.post("/ingest-log")
async def ingest_log(payload: IngestLogRequest) -> dict[str, Any]:
    """模拟实时日志写入：每写一行就过多策略检测管道。"""
    event = parse_log_line(payload.line)
    _store.logs.append(event)
    anomaly = _detector.observe(event)
    if not anomaly:
        return {"triggered": False, "message": "no anomaly"}

    report = _diagnose_with_current_agent(anomaly)
    now = datetime.now().isoformat(timespec="seconds")
    alert_id = _next_alert_id()
    alert = AlertRecord(
        alert_id=alert_id,
        anomaly_id=anomaly.anomaly_id,
        service=anomaly.service,
        kind=anomaly.kind,
        severity=anomaly.severity,
        summary=anomaly.summary,
        created_at=now,
        updated_at=now,
        report_id=report.report_id,
    )
    incident = _correlator.correlate(anomaly)
    _alerts[alert_id] = alert
    _reports[report.report_id] = report.to_markdown()

    # 通过 WebSocket 广播新告警和诊断轨迹
    await _ws_manager.broadcast({
        "type": "new_alert",
        "alert": alert.model_dump(),
        "incident": incident.to_dict(),
        "react_trace": [
            {"thought": step.thought, "action": step.action, "observation": step.observation}
            for step in report.react_trace
        ],
    })

    return {"triggered": True, "alert_id": alert_id, "incident": incident.to_dict(), "anomaly": anomaly.__dict__, "report_id": report.report_id}


# ─── 一键演示 ────────────────────────────────────────────────────────────

@app.post("/diagnose/sample")
def diagnose_sample(payload: DiagnoseSampleRequest | None = None) -> dict[str, Any]:
    """对 sample_app.log 跑完整检测 + ReAct 诊断，适合前端一键演示。"""
    path = Path(payload.log_file) if payload and payload.log_file else default_log_path()
    anomalies, reports = run_pipeline(path)
    sample_store = ObservabilityStore(load_log_events(path))
    original_logs = _store.logs
    _store.logs = sample_store.logs
    try:
        report_payloads = [_report_payload(report) for report in reports]
    finally:
        _store.logs = original_logs
    for report in reports:
        _reports[report.report_id] = report.to_markdown()
    incidents = [_correlator.correlate(anomaly).to_dict() for anomaly in anomalies]
    return {
        "log_file": str(path),
        "anomaly_count": len(anomalies),
        "report_count": len(reports),
        "anomalies": [anomaly.__dict__ for anomaly in anomalies],
        "incidents": incidents,
        "reports": report_payloads,
    }


@app.post("/ingest/sample")
async def ingest_sample(payload: ReplaySampleRequest | None = None) -> dict[str, Any]:
    """Replay sample logs through the live ingest path so alerts enter the lifecycle store."""
    if payload is None:
        payload = ReplaySampleRequest()
    if payload.reset_state:
        _reset_runtime_state()

    path = Path(payload.log_file) if payload.log_file else default_log_path()
    triggered: list[dict[str, Any]] = []
    for event in load_log_events(path):
        result = await ingest_log(IngestLogRequest(line=event.raw or event.compact()))
        if result.get("triggered"):
            triggered.append(result)

    return {
        "log_file": str(path),
        "ingested": len(load_log_events(path)),
        "triggered_count": len(triggered),
        "alerts": [alert.model_dump() for alert in _alerts.values()],
        "incidents": [incident.to_dict() for incident in _correlator.list_incidents()],
        "reports": [{"report_id": report_id, "markdown": markdown} for report_id, markdown in _reports.items()],
    }


# ─── 异步诊断任务 ─────────────────────────────────────────────────────────

@app.post("/diagnosis/jobs")
async def create_diagnosis_job(payload: CreateDiagnosisJobRequest | None = None) -> dict[str, Any]:
    job_id = _next_job_id()
    now = datetime.now().isoformat(timespec="seconds")
    job = DiagnosisJobRecord(job_id=job_id, status="running", created_at=now, updated_at=now)
    _jobs[job_id] = job

    async def _run() -> None:
        try:
            result = diagnose_sample(DiagnoseSampleRequest(log_file=payload.log_file if payload else None))
            job.status = "succeeded"
            job.result = result
        except Exception as exc:  # pragma: no cover - defensive job boundary
            job.status = "failed"
            job.error = str(exc)
        finally:
            job.updated_at = datetime.now().isoformat(timespec="seconds")

    asyncio.create_task(_run())
    return {"job_id": job_id, "status": job.status}


@app.get("/diagnosis/jobs/{job_id}")
def get_diagnosis_job(job_id: str) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job.model_dump()


# ─── 告警管理 ────────────────────────────────────────────────────────────

@app.get("/alerts")
def list_alerts(status: AlertStatus | None = None) -> list[dict[str, Any]]:
    """列出所有告警，可按状态过滤。"""
    alerts = list(_alerts.values())
    if status:
        alerts = [a for a in alerts if a.status == status]
    return [a.model_dump() for a in alerts]


@app.get("/alerts/{alert_id}")
def get_alert(alert_id: str) -> dict[str, Any]:
    alert = _alerts.get(alert_id)
    if not alert:
        return {"found": False, "message": "alert not found"}
    return {"found": True, "alert": alert.model_dump()}


@app.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, body: AlertActionRequest | None = None) -> dict[str, Any]:
    """确认告警。"""
    return await _transition_alert(alert_id, AlertStatus.ACKNOWLEDGED, body)


@app.post("/alerts/{alert_id}/investigate")
async def investigate_alert(alert_id: str, body: AlertActionRequest | None = None) -> dict[str, Any]:
    """标记为调查中。"""
    return await _transition_alert(alert_id, AlertStatus.INVESTIGATING, body)


@app.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str, body: AlertActionRequest | None = None) -> dict[str, Any]:
    """解决告警。"""
    return await _transition_alert(alert_id, AlertStatus.RESOLVED, body)


@app.post("/alerts/{alert_id}/silence")
async def silence_alert(alert_id: str, body: AlertActionRequest | None = None) -> dict[str, Any]:
    """静默告警（默认 30 分钟）。"""
    return await _transition_alert(alert_id, AlertStatus.SILENCED, body)


@app.post("/alerts/{alert_id}/escalate")
async def escalate_alert(alert_id: str, body: AlertActionRequest | None = None) -> dict[str, Any]:
    """升级告警。"""
    return await _transition_alert(alert_id, AlertStatus.ESCALATED, body)


async def _transition_alert(alert_id: str, target: AlertStatus, body: AlertActionRequest | None) -> dict[str, Any]:
    alert = _alerts.get(alert_id)
    if not alert:
        return {"success": False, "message": "alert not found"}

    valid = VALID_TRANSITIONS.get(alert.status, set())
    if target not in valid:
        return {"success": False, "message": f"无法从 {alert.status.value} 转换到 {target.value}"}

    now = datetime.now().isoformat(timespec="seconds")
    alert.status = target
    alert.updated_at = now
    if body:
        alert.acknowledged_by = body.operator
        if target == AlertStatus.SILENCED:
            duration = body.duration_minutes or 30
            silenced_until = datetime.now() + timedelta(minutes=duration)
            alert.silenced_until = silenced_until.isoformat(timespec="seconds")

    # 广播状态变更
    await _ws_manager.broadcast({
        "type": "alert_status_change",
        "alert_id": alert_id,
        "new_status": target.value,
        "operator": body.operator if body else "system",
        "timestamp": now,
    })

    return {"success": True, "alert": alert.model_dump()}


# ─── 报告 ────────────────────────────────────────────────────────────────

@app.get("/reports/{report_id}")
def get_report(report_id: str) -> dict[str, Any]:
    markdown = _reports.get(report_id)
    if markdown is None:
        return {"found": False, "message": "report not found"}
    return {"found": True, "report_id": report_id, "markdown": markdown}
