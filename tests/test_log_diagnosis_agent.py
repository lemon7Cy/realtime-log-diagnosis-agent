import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from log_diagnosis_agent import (  # noqa: E402
    ReactDiagnosisAgent,
    SlidingWindowAnomalyDetector,
    default_log_path,
    load_log_events,
    parse_log_line,
    run_pipeline,
)
from llm_client import openai_base_url, use_openai_compatible  # noqa: E402
from llm_config import LLMConfig  # noqa: E402
from pipeline import create_agent  # noqa: E402
from store import ObservabilityStore  # noqa: E402
from api import ReplaySampleRequest, ingest_sample  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
