"""
项目三：实时日志异常诊断 Agent — 兼容入口。

本文件作为向后兼容 shim，将所有公开符号从模块化包中重新导出。
直接运行 `python src/log_diagnosis_agent.py` 仍然可以正常工作。

模块化源码位于：
  - src/models.py       数据模型
  - src/parser.py       日志解析
  - src/consumer.py     日志消费器
  - src/detector.py     异常检测器（滑动窗口 / Z-Score / 关键词聚类）
  - src/store.py        可观测性数据源
  - src/tools/          诊断工具注册表
  - src/agent.py        启发式 ReAct Agent（无 LLM fallback）
  - src/llm_config.py   运行时模型配置
  - src/llm_client.py   模型列表/连通性适配
  - src/llm_agent.py    LLM 驱动的 ReAct Agent（Claude / OpenAI tool_use）
  - src/pipeline.py     管道入口
"""

from __future__ import annotations

import sys
from pathlib import Path as _Path

# 确保 src 目录在 path 中（支持 `python src/log_diagnosis_agent.py` 直接运行）
_src_dir = str(_Path(__file__).resolve().parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

# 从模块化包中重新导出所有公开符号
from models import (  # noqa: E402
    Anomaly,
    DeployRecord,
    DiagnosisReport,
    LogEvent,
    MetricPoint,
    ReActStep,
)
from parser import parse_log_line, load_log_events  # noqa: E402
from consumer import FileTailConsumer  # noqa: E402
from detector import SlidingWindowAnomalyDetector, DetectorPipeline  # noqa: E402
from store import ObservabilityStore  # noqa: E402
from correlation import AlertCorrelator, Incident  # noqa: E402
from runbook import RunbookPlanner  # noqa: E402
from slo import SLOImpactCalculator  # noqa: E402
from tools import ToolRegistry, TOOL_DEFINITIONS  # noqa: E402
from agent import ReactDiagnosisAgent  # noqa: E402
from llm_agent import LLMReActAgent  # noqa: E402
from llm_config import LLMConfig, get_llm_config, public_config, save_llm_config  # noqa: E402
from pipeline import create_agent, default_log_path, run_pipeline, main  # noqa: E402


if __name__ == "__main__":
    main()
