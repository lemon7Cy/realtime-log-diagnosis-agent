# 项目三最终总结：实时日志异常诊断 Agent

## 完成状态

项目三已补到“简历项目完整度”的 MVP+：

```text
日志流消费 → 异常检测 → 告警冷却 → ReAct 工具调用 → 根因分析 → API → React 前端面板
```

当前版本支持两种诊断模式：无 API Key 时走启发式 ReAct，保证求职演示稳定可跑；配置 `claude` / `deepseek` / `newapi` 后，下一次诊断自动升级为 LLM tool use ReAct Agent。

## 核心文件

- `D:\Agent_project\project3_log_diagnosis_agent\src\log_diagnosis_agent.py`
  - 日志解析
  - 滑动窗口异常检测
  - 告警冷却
  - 工具注册与调用
  - ReAct 诊断 Agent
  - Markdown 报告生成
- `D:\Agent_project\project3_log_diagnosis_agent\src\api.py`
  - FastAPI 演示接口和 `/llm-config` 模型配置接口
- `D:\Agent_project\project3_log_diagnosis_agent\src\llm_config.py`
  - 运行时模型配置，支持保存 provider / base_url / model / timeout
- `D:\Agent_project\project3_log_diagnosis_agent\src\llm_client.py`
  - 模型列表刷新与连通性测试
- `D:\Agent_project\project3_log_diagnosis_agent\src\llm_agent.py`
  - LLM tool use ReAct Agent，按工具 Observation 决定下一步排查动作
- `D:\Agent_project\project3_log_diagnosis_agent\frontend\src\App.tsx`
  - React 告警与诊断报告面板
- `D:\Agent_project\project3_log_diagnosis_agent\tests\test_log_diagnosis_agent.py`
  - 核心单元测试
- `D:\Agent_project\project3_log_diagnosis_agent\data\sample_app.log`
  - 可复现的样例日志流

## 已覆盖项目计划中的技术点

| 计划技术点 | 当前实现 |
|---|---|
| 流式数据消费与异常检测 | `FileTailConsumer` + `SlidingWindowAnomalyDetector` |
| ReAct 模式 | `ReactDiagnosisAgent` 输出 Thought / Action / Observation |
| Agent 自主工具选择 | Agent 根据异常依次调用日志、指标、部署、拓扑、资源工具 |
| LLM 模型接入 | 支持 Claude / DeepSeek / newapi，前端运行时配置，未配置时 fallback |
| 时序关联分析 | 把 10:00 部署、10:02 慢查询、10:03 连接超时、10:03~10:05 连接池满关联起来 |
| 后端 API | `src/api.py` 提供 FastAPI 接口 |
| 前端面板 | `frontend` 提供 React + Vite 仪表盘 |
| 工程验证 | `tests` + `npm run build` |

## 可演示场景

样例中 `order-api` 在 `2026-05-23 10:00:05` 发布 v2.3.7，新增批量订单汇总功能。几分钟后 `/api/orders/summary` 出现连续 5xx，Agent 通过工具链确认：

1. 关联日志存在大量 `database connection timeout`。
2. MySQL 连接池使用率达到 99%~100%。
3. 异常前刚发布了 `batch_order_summary`。
4. 应用主机 CPU/内存未打满。

最终诊断：新版本批量查询连接未复用，导致数据库连接池耗尽。

## 运行验证

后端核心：

```powershell
cd D:\Agent_project\project3_log_diagnosis_agent
python src\log_diagnosis_agent.py
python -m unittest discover -s tests -v
```

模型配置接口：

```text
GET  /llm-config
POST /llm-config
POST /llm-config/models
POST /llm-config/test
```

前端：

```powershell
cd D:\Agent_project\project3_log_diagnosis_agent\frontend
npm install
npm run build
```

## 已验证结果

- Python 单元测试覆盖日志解析、异常检测、fallback Agent、模型 URL 规则和报告生成。
- 前端生产构建：通过。
- `npm audit --omit=dev`：0 vulnerabilities。
- CLI 能生成 `docs/sample_diagnosis_report.md`。

## 后续增强方向

- 用 Kafka / Filebeat 替换本地文件 tail。
- 接入 Prometheus API 获取真实指标。
- 接入部署平台 API 获取真实发布记录。
- 接入更多真实诊断数据源，如 trace 查询、慢 SQL 平台、发布平台。
- 增加 WebSocket/SSE，把日志流和告警实时推到前端。
