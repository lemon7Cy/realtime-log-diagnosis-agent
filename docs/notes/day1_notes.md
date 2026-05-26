# Day1 学习笔记：实时日志异常诊断 Agent

今天完成项目三 MVP。

## 今日目标

把文档里的项目三核心闭环跑通：

```text
日志流 → 异常检测 → 触发 Agent → 工具调用 → 根因报告
```

## 今日新增文件

| 文件 | 作用 |
|---|---|
| `src/log_diagnosis_agent.py` | 核心 demo：日志解析、滑动窗口检测、ReAct 诊断、报告输出 |
| `src/api.py` | FastAPI 接口层，方便后续接前端 |
| `data/sample_app.log` | 模拟生产日志 |
| `docs/dev/architecture.md` | 架构说明 |
| `README.md` | 运行说明 |

## 关键实现

1. 用 `SlidingWindowAnomalyDetector` 在 120 秒窗口里统计 5xx 和 DB timeout。
2. 一旦触发 `Anomaly`，启动 `ReactDiagnosisAgent`。
3. Agent 依次调用：
   - `search_logs`
   - `query_metrics`
   - `get_deploy_history`
   - `get_service_topology`
   - `check_resource_usage`
4. 最后输出 `DiagnosisReport`。

## 本次样例根因

`order-api` 在 10:00 发布 v2.3.7 后，新功能 `batch_order_summary` 触发批量订单查询。10:03 起连接池使用率升至 99%~100%，日志中出现连续 `database connection timeout` 和 `connection pool exhausted`，最终导致 `/api/orders/summary` 5xx 突增。

## 面试话术

> 我没有让 Agent 从海量日志里盲目总结，而是先用滑动窗口检测异常，再把异常上下文交给 ReAct Agent。Agent 每一步都会调用具体工具验证假设，比如先查关联日志，再查连接池指标，再查部署记录和拓扑。最终报告里的根因不是凭空生成，而是由工具 Observation 串起来的证据链。
