import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from log_diagnosis_agent import (  # noqa: E402
    Anomaly,
    ReactDiagnosisAgent,
    SlidingWindowAnomalyDetector,
    default_log_path,
    load_log_events,
    parse_log_line,
    run_pipeline,
)
from correlation import AlertCorrelator  # noqa: E402
from runbook import RunbookPlanner  # noqa: E402
from slo import SLOImpactCalculator  # noqa: E402
from llm_client import openai_base_url, use_openai_compatible  # noqa: E402
from llm_config import LLMConfig  # noqa: E402
from pipeline import create_agent  # noqa: E402
from store import ObservabilityStore  # noqa: E402
from api import ReplaySampleRequest, app, ingest_sample  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class LogDiagnosisAgentTests(unittest.TestCase):
    def test_parse_log_line_extracts_core_fields(self):
        line = '2026-05-23T10:03:02 order-api ERROR status=500 host=app-01 path=/api/orders dependency=mysql message="database connection timeout"'
        event = parse_log_line(line)
        self.assertEqual(event.service, "order-api")
        self.assertEqual(event.level, "ERROR")
        self.assertEqual(event.status_code, 500)
        self.assertEqual(event.host, "app-01")
        self.assertIn("connection timeout", event.message)

    def test_detector_triggers_anomaly_on_sample_logs(self):
        detector = SlidingWindowAnomalyDetector()
        anomalies = []
        for event in load_log_events(default_log_path()):
            anomaly = detector.observe(event)
            if anomaly:
                anomalies.append(anomaly)
        kinds = {item.kind for item in anomalies}
        self.assertIn("db_timeout_cluster", kinds)
        self.assertIn("5xx_spike", kinds)

    def test_pipeline_generates_root_cause_report(self):
        anomalies, reports = run_pipeline(default_log_path())
        self.assertGreaterEqual(len(anomalies), 1)
        self.assertGreaterEqual(len(reports), 1)
        markdown = reports[0].to_markdown()
        self.assertIn("ReAct 诊断轨迹", markdown)
        self.assertIn("连接池", markdown)
        self.assertIn("修复建议", markdown)

    def test_openai_base_url_adds_v1_for_compatible_providers(self):
        cfg = LLMConfig(provider="deepseek", api_key="x", base_url="https://api.deepseek.com", model="m")
        self.assertEqual(openai_base_url(cfg), "https://api.deepseek.com/v1")
        self.assertTrue(use_openai_compatible(cfg))

    def test_create_agent_falls_back_without_api_key(self):
        store = ObservabilityStore(load_log_events(default_log_path()))
        agent = create_agent(store)
        self.assertIsInstance(agent, ReactDiagnosisAgent)

    def test_ingest_sample_populates_alert_lifecycle(self):
        import asyncio

        result = asyncio.run(ingest_sample(ReplaySampleRequest(reset_state=True)))
        self.assertGreaterEqual(result["triggered_count"], 1)
        self.assertGreaterEqual(len(result["alerts"]), 1)
        self.assertEqual(result["alerts"][0]["status"], "firing")

    def test_alert_correlator_groups_same_service_kind_within_window(self):
        base = datetime.fromisoformat("2026-05-23T10:03:00")
        first = Anomaly("a1", "order-api", "5xx_spike", "High", base, base + timedelta(seconds=20), "first", ["e1"])
        second = Anomaly("a2", "order-api", "5xx_spike", "Medium", base + timedelta(minutes=2), base + timedelta(minutes=2, seconds=10), "second", ["e2"])
        other = Anomaly("a3", "payment-api", "5xx_spike", "High", base, base, "third", ["e3"])

        correlator = AlertCorrelator(window_minutes=5)
        incident1 = correlator.correlate(first)
        incident2 = correlator.correlate(second)
        incident3 = correlator.correlate(other)

        self.assertEqual(incident1.incident_id, incident2.incident_id)
        self.assertEqual(incident2.alert_count, 2)
        self.assertEqual(incident2.severity, "High")
        self.assertNotEqual(incident1.incident_id, incident3.incident_id)

    def test_runbook_planner_outputs_structured_remediation_plan(self):
        anomaly = Anomaly(
            "a1", "order-api", "db_timeout_cluster", "High",
            datetime.fromisoformat("2026-05-23T10:03:00"), datetime.fromisoformat("2026-05-23T10:05:00"),
            "db timeout", [],
        )
        plan = RunbookPlanner().plan(anomaly, "MySQL connection pool exhausted after deploy")

        self.assertEqual(plan["severity"], "High")
        self.assertGreaterEqual(len(plan["actions"]), 3)
        self.assertTrue(any("回滚" in item or "rollback" in item.lower() for item in plan["rollback"]))
        self.assertTrue(any("5xx" in item or "连接池" in item for item in plan["verify"]))

    def test_slo_impact_calculator_estimates_error_budget_and_affected_requests(self):
        store = ObservabilityStore(load_log_events(default_log_path()))
        anomaly = Anomaly(
            "a1", "order-api", "5xx_spike", "High",
            datetime.fromisoformat("2026-05-23T10:03:00"), datetime.fromisoformat("2026-05-23T10:05:00"),
            "5xx spike", [],
        )
        impact = SLOImpactCalculator(target_success_rate=0.99).calculate(store, anomaly)

        self.assertEqual(impact["service"], "order-api")
        self.assertGreaterEqual(impact["affected_requests"], 1)
        self.assertGreater(impact["error_budget_burn_rate"], 1.0)
        self.assertIn("summary", impact)

    def test_diagnose_sample_report_payload_includes_runbook_and_slo_impact(self):
        client = TestClient(app)
        response = client.post("/diagnose/sample", json={})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(payload["report_count"], 1)
        report = payload["reports"][0]
        self.assertIn("runbook", report)
        self.assertIn("slo_impact", report)
        self.assertIn("actions", report["runbook"])
        self.assertIn("error_budget_burn_rate", report["slo_impact"])

    def test_async_diagnosis_jobs_api_returns_status_and_result(self):
        client = TestClient(app)
        create_response = client.post("/diagnosis/jobs", json={})
        self.assertEqual(create_response.status_code, 200)
        job_id = create_response.json()["job_id"]

        final_payload = None
        for _ in range(20):
            status_response = client.get(f"/diagnosis/jobs/{job_id}")
            self.assertEqual(status_response.status_code, 200)
            final_payload = status_response.json()
            if final_payload["status"] == "succeeded":
                break
        self.assertIsNotNone(final_payload)
        self.assertEqual(final_payload["status"], "succeeded")
        self.assertGreaterEqual(final_payload["result"]["report_count"], 1)


if __name__ == "__main__":
    unittest.main()
