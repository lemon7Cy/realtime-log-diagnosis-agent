"""管道入口：串联日志消费 → 异常检测 → 诊断 Agent → 报告生成。"""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from .agent import ReactDiagnosisAgent
    from .consumer import FileTailConsumer
    from .detector import DetectorPipeline, SlidingWindowAnomalyDetector
    from .llm_agent import LLMReActAgent
    from .models import Anomaly, DiagnosisReport
    from .parser import load_log_events
    from .store import ObservabilityStore
    from .tools import ToolRegistry
except ImportError:
    from agent import ReactDiagnosisAgent
    from consumer import FileTailConsumer
    from detector import DetectorPipeline, SlidingWindowAnomalyDetector
    from llm_agent import LLMReActAgent
    from models import Anomaly, DiagnosisReport
    from parser import load_log_events
    from store import ObservabilityStore
    from tools import ToolRegistry


def default_log_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "sample_app.log"


def create_agent(store: ObservabilityStore) -> ReactDiagnosisAgent | LLMReActAgent:
    """根据是否配置了 API Key 自动选择 LLM Agent 或 Heuristic Agent。"""
    tools = ToolRegistry(store)
    llm_agent = LLMReActAgent(tools=tools)
    if llm_agent.available:
        return llm_agent
    return ReactDiagnosisAgent(tools)


def run_pipeline(log_path: Path) -> tuple[list[Anomaly], list[DiagnosisReport]]:
    all_events = load_log_events(log_path)
    detector = SlidingWindowAnomalyDetector()
    anomalies: list[Anomaly] = []

    for event in FileTailConsumer(log_path).stream():
        anomaly = detector.observe(event)
        if anomaly:
            anomalies.append(anomaly)

    store = ObservabilityStore(all_events)
    agent = create_agent(store)
    reports = [agent.diagnose(anomaly) for anomaly in anomalies]
    return anomalies, reports


def run_pipeline_with_multi_detector(log_path: Path) -> tuple[list[Anomaly], list[DiagnosisReport]]:
    """使用多策略检测管道（包含滑动窗口 + Z-Score + 关键词聚类）。"""
    all_events = load_log_events(log_path)
    pipeline = DetectorPipeline()
    anomalies: list[Anomaly] = []

    for event in FileTailConsumer(log_path).stream():
        anomaly = pipeline.observe(event)
        if anomaly:
            anomalies.append(anomaly)

    store = ObservabilityStore(all_events)
    agent = create_agent(store)
    reports = [agent.diagnose(anomaly) for anomaly in anomalies]
    return anomalies, reports


def main() -> None:
    parser = argparse.ArgumentParser(description="实时日志异常诊断 Agent Demo")
    parser.add_argument("--log-file", type=Path, default=default_log_path(), help="待消费日志文件")
    parser.add_argument("--write-report", type=Path, default=None, help="可选：把第一份诊断报告写入 Markdown 文件")
    parser.add_argument("--multi-detector", action="store_true", help="启用多策略检测管道")
    args = parser.parse_args()

    if args.multi_detector:
        anomalies, reports = run_pipeline_with_multi_detector(args.log_file)
    else:
        anomalies, reports = run_pipeline(args.log_file)

    print("=" * 80)
    print("项目三：实时日志异常诊断 Agent")
    print("=" * 80)
    print(f"日志文件：{args.log_file}")
    print(f"检测到异常：{len(anomalies)} 个")

    for anomaly in anomalies:
        print("\n" + anomaly.to_markdown())

    if reports:
        report = reports[0]
        print("\n" + report.to_markdown())
        if len(reports) > 1:
            print(f"\n另外还生成 {len(reports) - 1} 份诊断报告，可通过 API 或 Python 调用查看。")
        if args.write_report:
            args.write_report.parent.mkdir(parents=True, exist_ok=True)
            args.write_report.write_text(report.to_markdown(), encoding="utf-8")
            print(f"\n报告已写入：{args.write_report}")
    else:
        print("\n没有触发诊断报告。")


if __name__ == "__main__":
    main()
