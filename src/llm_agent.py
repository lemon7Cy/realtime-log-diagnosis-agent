"""LLM 驱动的 ReAct 诊断 Agent。

通过 Claude / OpenAI tool_use 实现真正的多轮推理循环：
模型根据每次工具返回的 Observation 动态决定下一步调用哪个工具，
直到收集到足够证据才输出根因诊断结论。

当未配置 API Key 时自动降级到 heuristic agent（见 agent.py）。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

try:
    from .llm_client import openai_base_url, use_openai_compatible
    from .llm_config import get_llm_config
    from .models import Anomaly, DiagnosisReport, ReActStep
    from .tools import TOOL_DEFINITIONS, ToolRegistry
except ImportError:
    from llm_client import openai_base_url, use_openai_compatible
    from llm_config import get_llm_config
    from models import Anomaly, DiagnosisReport, ReActStep
    from tools import TOOL_DEFINITIONS, ToolRegistry

MAX_REACT_STEPS = 8

DIAGNOSIS_SYSTEM_PROMPT = """\
你是一个专业的运维诊断 Agent。当收到异常告警信息后，你需要通过调用可用工具逐步排查根因。

## 工作方式
1. 分析异常信息，思考可能的原因
2. 选择合适的工具获取更多证据
3. 根据观察结果决定下一步动作
4. 重复以上步骤直到有足够信息得出结论

## 输出要求
当你认为已经收集到足够信息时，请直接输出最终诊断结论，格式如下：

```json
{
  "root_cause": "根因描述",
  "confidence": "High/Medium/Low",
  "impact": "影响范围",
  "timeline": ["时间线事件1", "时间线事件2"],
  "evidence": ["关键证据1", "关键证据2"],
  "recommendations": ["修复建议1", "修复建议2"]
}
```

## 原则
- 不要猜测，要用工具验证
- 优先排查最可能的原因
- 关注时间相关性：异常发生前是否有部署、配置变更
- 排除资源层面（CPU/内存/磁盘）的干扰因素
- 如果证据不足请明确说明置信度为 Low
"""


@dataclass
class LLMReActAgent:
    """LLM 驱动的 ReAct 诊断 Agent。支持 Claude Anthropic API 和 OpenAI-compatible API。"""

    tools: ToolRegistry
    provider: str = "claude"
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    timeout: int = 60

    def __post_init__(self) -> None:
        self.refresh_config()

    def refresh_config(self) -> None:
        config = get_llm_config()
        self.provider = config.provider
        self.api_key = config.api_key
        self.model = config.model
        self.base_url = config.base_url
        self.timeout = int(config.timeout)

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.api_key != "your_api_key_here")

    def diagnose(self, anomaly: Anomaly) -> DiagnosisReport:
        """执行多轮 ReAct 诊断循环。"""
        self.refresh_config()
        trace: list[ReActStep] = []
        user_prompt = self._build_initial_prompt(anomaly)

        config = get_llm_config()
        if use_openai_compatible(config):
            return self._diagnose_openai(anomaly, user_prompt, trace)
        return self._diagnose_claude(anomaly, user_prompt, trace)

    # ─── Claude Anthropic API ────────────────────────────────────────────

    def _diagnose_claude(self, anomaly: Anomaly, user_prompt: str, trace: list[ReActStep]) -> DiagnosisReport:
        import httpx

        messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]
        base_url = self.base_url.rstrip("/") if self.base_url else "https://api.anthropic.com"

        for step in range(MAX_REACT_STEPS):
            response = httpx.post(
                f"{base_url}/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": 4096,
                    "system": DIAGNOSIS_SYSTEM_PROMPT,
                    "messages": messages,
                    "tools": TOOL_DEFINITIONS,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()

            stop_reason = result.get("stop_reason", "")
            content_blocks = result.get("content", [])

            # 提取文本思考内容
            thinking_text = ""
            for block in content_blocks:
                if block.get("type") == "text":
                    thinking_text += block.get("text", "")

            # 如果模型停止且没有工具调用，解析最终结论
            if stop_reason == "end_turn":
                return self._parse_final_response(anomaly, thinking_text, trace)

            # 处理工具调用
            tool_results: list[dict[str, Any]] = []
            for block in content_blocks:
                if block.get("type") == "tool_use":
                    tool_name = block["name"]
                    tool_input = block["input"]
                    tool_id = block["id"]

                    _, observation = self.tools.execute(tool_name, tool_input)
                    trace.append(ReActStep(
                        thought=thinking_text.strip() or f"(Step {step + 1})",
                        action=f"{tool_name}({json.dumps(tool_input, ensure_ascii=False)})",
                        observation=observation,
                    ))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": observation,
                    })
                    thinking_text = ""  # Reset for next tool call in same response

            messages.append({"role": "assistant", "content": content_blocks})
            messages.append({"role": "user", "content": tool_results})

        return self._timeout_report(anomaly, trace)

    # ─── OpenAI-compatible API ───────────────────────────────────────────

    def _diagnose_openai(self, anomaly: Anomaly, user_prompt: str, trace: list[ReActStep]) -> DiagnosisReport:
        import httpx

        config = get_llm_config()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": DIAGNOSIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        openai_tools = self._convert_tools_to_openai_format()
        base_url = openai_base_url(config)

        for step in range(MAX_REACT_STEPS):
            response = httpx.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "tools": openai_tools,
                    "max_tokens": 4096,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()
            choice = result["choices"][0]
            message = choice["message"]
            finish_reason = choice.get("finish_reason", "")

            if finish_reason == "stop" or not message.get("tool_calls"):
                return self._parse_final_response(anomaly, message.get("content", ""), trace)

            messages.append(message)
            for tool_call in message["tool_calls"]:
                fn = tool_call["function"]
                tool_name = fn["name"]
                tool_input = json.loads(fn["arguments"])
                thinking = message.get("content", "") or f"(Step {step + 1})"

                _, observation = self.tools.execute(tool_name, tool_input)
                trace.append(ReActStep(
                    thought=thinking.strip(),
                    action=f"{tool_name}({json.dumps(tool_input, ensure_ascii=False)})",
                    observation=observation,
                ))
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": observation,
                })

        return self._timeout_report(anomaly, trace)

    # ─── Helpers ─────────────────────────────────────────────────────────

    def _build_initial_prompt(self, anomaly: Anomaly) -> str:
        return (
            f"检测到以下异常，请通过调用工具进行根因诊断：\n\n"
            f"{anomaly.to_markdown()}\n\n"
            f"请开始诊断。注意时间窗口约为 {anomaly.start.isoformat(timespec='seconds')} ~ {anomaly.end.isoformat(timespec='seconds')}，"
            f"建议适当扩大搜索范围（前后各 3~5 分钟）。"
        )

    def _parse_final_response(self, anomaly: Anomaly, text: str, trace: list[ReActStep]) -> DiagnosisReport:
        """尝试从 LLM 最终输出中解析 JSON 诊断报告。"""
        # 尝试从 text 中提取 JSON
        json_data = self._extract_json(text)
        if json_data:
            return DiagnosisReport(
                report_id=f"report-{uuid.uuid4().hex[:8]}",
                anomaly=anomaly,
                root_cause=json_data.get("root_cause", text[:500]),
                confidence=json_data.get("confidence", "Medium"),
                impact=json_data.get("impact", "需要进一步确认影响范围"),
                timeline=json_data.get("timeline", []),
                evidence=json_data.get("evidence", []),
                recommendations=json_data.get("recommendations", []),
                react_trace=trace,
            )
        # JSON 解析失败时，把整段文本作为 root_cause
        return DiagnosisReport(
            report_id=f"report-{uuid.uuid4().hex[:8]}",
            anomaly=anomaly,
            root_cause=text[:1000] if text else "LLM 未能输出结构化诊断结论",
            confidence="Low",
            impact="需要人工复核",
            timeline=[],
            evidence=[],
            recommendations=["建议人工排查或重新触发诊断"],
            react_trace=trace,
        )

    def _timeout_report(self, anomaly: Anomaly, trace: list[ReActStep]) -> DiagnosisReport:
        """达到最大步数仍未输出结论时的兜底报告。"""
        return DiagnosisReport(
            report_id=f"report-{uuid.uuid4().hex[:8]}",
            anomaly=anomaly,
            root_cause=f"在 {MAX_REACT_STEPS} 步内未能完成诊断，建议人工介入。最后观察：{trace[-1].observation if trace else '无'}",
            confidence="Low",
            impact="需要人工复核",
            timeline=[],
            evidence=[step.observation for step in trace],
            recommendations=["增大诊断步数上限或人工排查"],
            react_trace=trace,
        )

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        """从 LLM 输出中提取 JSON（支持 markdown code block 包裹）。"""
        import re
        # 尝试匹配 ```json ... ``` 块
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        candidate = match.group(1) if match else text
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            pass
        # 尝试直接找 { ... } 最外层
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            try:
                data = json.loads(text[brace_start:brace_end + 1])
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, ValueError):
                pass
        return None

    @staticmethod
    def _convert_tools_to_openai_format() -> list[dict[str, Any]]:
        """把 Claude tool 定义转为 OpenAI function calling 格式。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                },
            }
            for tool in TOOL_DEFINITIONS
        ]
