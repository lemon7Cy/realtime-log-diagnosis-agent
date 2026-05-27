# 项目三：实时日志异常诊断 Agent

这是一个可观测性诊断 Agent，用来展示“日志流 → 异常检测 → 告警生命周期 → ReAct 工具调用 → 根因诊断报告 → 前端告警面板”的完整闭环。

## 已实现能力

### 后端 / Agent

- 简单 tail 消费：从 `data/sample_app.log` 逐行模拟实时日志流。
- 异常检测：基于滑动窗口统计 5xx 错误率、DB timeout / connection pool exhausted 聚集。
- 告警冷却 + 关联聚合：对同一服务和异常类型做 cooldown，并把相近时间窗口内的同类告警聚合为 incident，降低告警风暴。
- Runbook planner：根据 anomaly kind / root cause 自动生成结构化 remediation plan（severity、actions、rollback、verify）。
- SLO impact：基于日志窗口估算 affected requests、observed error rate 和 error budget burn rate，并写入报告 payload。
- 异步诊断任务：支持 `/diagnosis/jobs` 后台执行 sample 诊断，通过 job id 查询状态和结果。
- ReAct Agent：按 Thought / Action / Observation 方式自主调用诊断工具。
- LLM 模型接入：未配置 API Key 时使用启发式 ReAct，配置模型后自动切换到 LLM tool use 诊断。
- 工具集：
  - `search_logs(keyword, time_range)`
  - `query_metrics(metric_name, time_range)`
  - `get_deploy_history(service, count)`
  - `get_service_topology(service)`
  - `check_resource_usage(host)`
- 输出 Markdown 诊断报告，包含根因、证据、时间线和修复建议。
- FastAPI 后端：提供 `/diagnose/sample`、`/ingest-log`、`/alerts`、`/reports/{id}` 和 `/llm-config`。

### 前端

- React + Vite 实时告警面板。
- 一键运行 sample 诊断。
- 模型配置面板：支持 `claude` / `deepseek` / `newapi`，可刷新模型、测试连接、保存运行时配置。
- 展示异常事件列表、诊断报告、ReAct 轨迹。
- Vite proxy 转发到 FastAPI 后端。

### 测试

- `unittest` 覆盖日志解析、异常检测、告警回放、诊断报告生成。
- 前端生产构建由 CI 执行。

## 运行方式

### 1. 本地命令行 demo

不依赖 API Key：

```powershell
cd D:\Agent_project\project3_log_diagnosis_agent
python src\log_diagnosis_agent.py
```

写出报告文件：

```powershell
python src\log_diagnosis_agent.py --write-report docs\sample_diagnosis_report.md
```

### 2. 启动后端 API

```powershell
cd D:\Agent_project\project3_log_diagnosis_agent
pip install -r requirements.txt
uvicorn src.api:app --reload --port 8003
```

一键诊断 sample：

```powershell
curl -X POST http://127.0.0.1:8003/diagnose/sample -H "Content-Type: application/json" -d "{}"
```

回放 sample 日志流并进入告警生命周期：

```powershell
curl -X POST http://127.0.0.1:8003/ingest/sample -H "Content-Type: application/json" -d "{\"reset_state\":true}"
```

工程化增强接口：

```text
POST /diagnosis/jobs             # 创建后台诊断任务，返回 job_id
GET  /diagnosis/jobs/{job_id}    # 查询任务状态和 result
```

`/diagnose/sample` 与异步 job 的 report payload 会额外包含：

```json
{
  "incidents": [{"incident_id": "inc-...", "alert_count": 2}],
  "reports": [{
    "runbook": {"severity": "High", "actions": [], "rollback": [], "verify": []},
    "slo_impact": {"affected_requests": 8, "error_budget_burn_rate": 100.0}
  }]
}
```

### 2.1 模型配置

不配置 API Key 时，系统仍可用启发式 ReAct Agent 完整演示。配置模型后，下一次诊断会自动使用 LLM ReAct Agent 调用工具链。

支持两种方式：

```powershell
Copy-Item .env.example .env
notepad .env
```

或在前端点击 **模型配置**，运行时保存：

- provider：`claude` / `deepseek` / `newapi`
- base_url：官方 Claude 可留空；DeepSeek 默认 `https://api.deepseek.com`；newapi 填 OpenAI-compatible 中转站地址
- model：模型名，可刷新 `/v1/models`
- api_key：留空则不覆盖已保存 key
- timeout：请求超时秒数

后端接口：

```text
GET  /llm-config
POST /llm-config
POST /llm-config/models
POST /llm-config/test
```

### 3. 启动前端面板

```powershell
cd D:\Agent_project\project3_log_diagnosis_agent\frontend
npm install
npm run dev
```

打开：

```text
http://127.0.0.1:3003
```

Docker Compose：

```powershell
Copy-Item .env.example .env
docker compose up --build
```

默认前端：`http://127.0.0.1:3003`，后端：`http://127.0.0.1:8003`。

### 4. 运行测试

```powershell
cd D:\Agent_project\project3_log_diagnosis_agent
python -m unittest discover -s tests -v
```

前端构建：

```powershell
cd D:\Agent_project\project3_log_diagnosis_agent\frontend
npm run build
```

## 目录结构

```text
project3_log_diagnosis_agent/
├─ data/sample_app.log                    # 模拟应用日志流
├─ docs/project3_final_summary.md         # 最终总结
├─ docs/sample_diagnosis_report.md        # 样例诊断报告
├─ docs/ARCHITECTURE.md                   # 架构设计说明
├─ docs/INTERVIEW_NOTES.md                # 面试讲法
├─ docs/notes/day1_notes.md               # 学习/实现笔记
├─ frontend/                              # React 告警面板
│  ├─ src/App.tsx
│  ├─ src/styles.css
│  └─ package.json
├─ src/log_diagnosis_agent.py             # 兼容入口
├─ src/api.py                             # FastAPI 演示接口
├─ src/llm_config.py                      # 运行时模型配置
├─ src/llm_client.py                      # 模型列表与连通性测试
├─ src/llm_agent.py                       # LLM tool use ReAct Agent
├─ src/correlation.py                      # 告警关联与 incident 聚合
├─ src/runbook.py                          # 结构化修复 runbook 生成
├─ src/slo.py                              # SLO 影响与错误预算燃烧估算
├─ tests/test_log_diagnosis_agent.py      # 单元测试
├─ requirements.txt
└─ .env.example
```

## 面试表达

> 我把项目三设计成一个运维诊断 Agent：日志流进入后先由轻量规则和滑动窗口检测异常，只有触发异常才启动 ReAct Agent。无 API Key 时启发式 Agent 保证 demo 可跑；配置 Claude / DeepSeek / newapi 后，LLM 会通过 tool use 自主选择日志、指标、部署、拓扑和资源工具收集证据，再输出可追溯的根因报告。前端面板用于展示异常事件、模型配置、ReAct 轨迹和修复建议，整体贴近生产中的告警诊断流程。
