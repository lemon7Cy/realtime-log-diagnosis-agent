# 项目三架构设计：实时日志异常诊断 Agent

## 1. 核心链路

```text
日志流/File tail
  → SlidingWindowAnomalyDetector
  → Anomaly + cooldown
  → ReactDiagnosisAgent
  → ToolRegistry
  → ObservabilityStore(logs/metrics/deploy/topology/resource)
  → DiagnosisReport
  → FastAPI
  → React Dashboard
```

## 2. 为什么异常检测和 Agent 分层

项目三没有让 LLM 直接读取所有日志，而是先用确定性的检测器做第一层过滤：

- 降低 token 成本；
- 减少误触发；
- 让告警触发条件可解释；
- Agent 只处理“值得诊断”的事件；
- 通过 cooldown 避免同一异常刷屏。

## 3. ReAct 工具调用链

本 demo 的诊断轨迹：

```text
Thought: 5xx 突增，需要查询关联日志
Action: search_logs("connection")
Observation: DB connection timeout 集中出现

Thought: 连接超时可能是连接池耗尽
Action: query_metrics("mysql_connection_pool_usage")
Observation: 使用率 99%~100%

Thought: 需要查看异常前是否有部署变更
Action: get_deploy_history("order-api")
Observation: 10:00 发布 v2.3.7，新增 batch_order_summary

Thought: 确认依赖和主机资源
Action: get_service_topology + check_resource_usage
Observation: order-api 依赖 mysql-primary，应用主机资源正常
```

## 4. 后端接口

| 接口 | 作用 |
|---|---|
| `GET /health` | 健康检查 |
| `POST /diagnose/sample` | 对样例日志跑完整检测与诊断 |
| `POST /ingest-log` | 模拟实时写入单行日志并触发检测 |
| `GET /alerts` | 查看当前告警列表 |
| `GET /reports/{report_id}` | 获取诊断报告 Markdown |

## 5. 前端面板

`frontend` 使用 React + Vite：

- 点击按钮调用 `/diagnose/sample`；
- 左侧展示异常事件；
- 右侧展示 Markdown 报告；
- 页面突出 ReAct、工具链、时序关联等面试亮点。

## 6. 可扩展点

| 当前实现 | 生产替换 |
|---|---|
| `FileTailConsumer` | Kafka / Filebeat / Loki stream |
| 本地 `ObservabilityStore.metrics` | Prometheus API |
| 本地部署记录 | GitHub Actions / ArgoCD / Jenkins API |
| 启发式 ReAct | Claude/OpenAI tool use |
| HTTP 查询 | WebSocket/SSE 实时推送 |
| Markdown 报告 | 告警平台 + 工单系统 |

## 7. 项目亮点

- 不是离线日志总结，而是流式异常触发。
- 不是单轮问答，而是 ReAct 工具调用闭环。
- 报告有可追溯证据链：日志、指标、部署、拓扑、资源。
- 工具层和 Agent 决策层解耦，方便后续接 LLM。
- 有前端面板、API、测试和构建验证，适合作为简历项目展示。
