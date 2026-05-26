# 实时日志异常诊断报告 `report-5caa93ae`

### High / db_timeout_cluster
- 服务：`order-api`
- 时间窗：`2026-05-23T10:02:10` ~ `2026-05-23T10:03:15`
- 摘要：检测到 2 条数据库连接超时/连接池耗尽日志
- 证据：
  - 2026-05-23T10:03:02 order-api ERROR status=500 host=app-01 path=/api/orders/summary message="database connection timeout while loading batch order summary"
  - 2026-05-23T10:03:15 order-api ERROR status=500 host=app-01 path=/api/orders/summary message="database connection timeout while loading batch order summary"

## 根因结论
- 置信度：High
- 根因：`order-api` 在 2026-05-23T10:00:05 发布 `v2.3.7` 后，新功能“新增批量订单汇总功能 batch_order_summary”触发批量订单查询，数据库连接未充分复用，导致 MySQL 连接池使用率升至 100%，请求在获取连接时超时并放大为 5xx。
- 影响：`/api/orders/summary` 请求出现连续 5xx，订单汇总能力受影响；其他服务暂未显示同类异常。

## ReAct 诊断轨迹
- Thought：检测到 5xx/DB timeout 异常，先查同时间窗内是否有数据库连接相关日志。
  - Action：`search_logs(keyword='connection', time_range='2026-05-23T09:59:10~2026-05-23T10:04:15', service='order-api')`
  - Observation：2026-05-23T10:03:02 order-api ERROR status=500 host=app-01 path=/api/orders/summary message="database connection timeout while loading batch order summary"; 2026-05-23T10:03:15 order-api ERROR status=500 host=app-01 path=/api/orders/summary message="database connection timeout while loading batch order summary"; 2026-05-23T10:03:42 order-api ERROR status=500 host=app-01 path=/api/orders/summary message="database connection timeout while loading batch order summary"; ... 共 4 条
- Thought：连接超时集中出现，需要确认 MySQL 连接池是否达到上限。
  - Action：`query_metrics(metric_name='mysql_connection_pool_usage', time_range='same_window')`
  - Observation：mysql_connection_pool_usage: max=1.00, avg=0.83, latest=1.00
- Thought：指标显示连接池高水位，需要查看异常前是否刚发布过相关版本。
  - Action：`get_deploy_history(service='order-api', count=3)`
  - Observation：2026-05-23T10:00:05 v2.3.7 新增批量订单汇总功能 batch_order_summary; 2026-05-22T22:10:00 v2.3.6 修复订单列表分页展示
- Thought：确认服务依赖，判断超时是否与下游数据库链路一致。
  - Action：`get_service_topology(service='order-api')`
  - Observation：order-api 依赖：mysql-primary, redis-cache, payment-api
- Thought：排除应用主机 CPU/内存打满导致的假象。
  - Action：`check_resource_usage(host='app-01')`
  - Observation：app-01: cpu=58%, memory=64%, disk=41%; 应用主机资源正常

## 关键时间线
- 10:00:05 发布 order-api v2.3.7，包含 batch_order_summary 新路径。
- 10:02:10 开始出现 slow query 日志。
- 10:03:02~10:04:20 `/api/orders/summary` 连续出现 DB connection timeout / pool exhausted。
- 10:03~10:05 MySQL 连接池使用率维持在 97%~100%。

## 关键证据
- 检测到 2 条数据库连接超时/连接池耗尽日志
- 同窗口连接相关日志 4 条。
- mysql_connection_pool_usage max=1.00。
- 服务拓扑显示 `order-api` 依赖 `mysql-primary, redis-cache, payment-api`。
- 主机资源：应用主机资源正常。
- 最近部署：v2.3.7 / 新路径会批量读取用户订单，若连接未复用可能放大 DB 连接数。

## 修复建议
1. 立即止血：回滚 `order-api` 到 v2.3.6，或关闭 `batch_order_summary` 功能开关。
2. 短期缓解：在确认数据库容量允许时临时提高连接池上限，并对 `/api/orders/summary` 做限流/降级。
3. 根修复：批量查询使用单次 `WHERE id IN (...)` 或分页批处理，确保连接通过连接池复用并及时释放。
4. 补充观测：为连接池等待时间、活跃连接数、慢查询、接口维度 5xx 建立告警，并把部署事件写入告警上下文。