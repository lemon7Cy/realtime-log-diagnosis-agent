"""生成 sample_app.log 测试数据。"""
from pathlib import Path

LINES = [
    '2026-05-23T09:58:00 order-api INFO status=200 host=app-01 path=/api/orders message="order list ok"',
    '2026-05-23T09:59:00 order-api INFO status=200 host=app-01 path=/api/orders message="order list ok"',
    '2026-05-23T10:00:00 order-api INFO status=200 host=app-01 path=/api/orders message="order list ok"',
    '2026-05-23T10:00:30 order-api INFO status=200 host=app-01 path=/api/orders/summary message="summary ok"',
    '2026-05-23T10:01:00 order-api INFO status=200 host=app-01 path=/api/orders/summary message="summary ok"',
    '2026-05-23T10:02:10 order-api WARN status=200 host=app-01 path=/api/orders/summary latency_ms=1200 message="slow query detected"',
    '2026-05-23T10:02:30 order-api WARN status=200 host=app-01 path=/api/orders/summary latency_ms=2100 message="slow query detected"',
    '2026-05-23T10:03:02 order-api ERROR status=500 host=app-01 path=/api/orders/summary dependency=mysql message="database connection timeout"',
    '2026-05-23T10:03:10 order-api ERROR status=500 host=app-01 path=/api/orders/summary dependency=mysql message="database connection timeout"',
    '2026-05-23T10:03:20 order-api ERROR status=500 host=app-01 path=/api/orders/summary dependency=mysql message="connection pool exhausted"',
    '2026-05-23T10:03:30 order-api ERROR status=500 host=app-01 path=/api/orders/summary dependency=mysql message="database connection timeout"',
    '2026-05-23T10:03:45 order-api ERROR status=500 host=app-01 path=/api/orders/summary dependency=mysql message="database connection timeout"',
    '2026-05-23T10:04:00 order-api ERROR status=500 host=app-01 path=/api/orders/summary dependency=mysql message="connection pool exhausted"',
    '2026-05-23T10:04:10 order-api ERROR status=500 host=app-01 path=/api/orders/summary dependency=mysql message="database connection timeout"',
    '2026-05-23T10:04:20 order-api ERROR status=500 host=app-01 path=/api/orders/summary dependency=mysql message="database connection timeout"',
    '2026-05-23T10:05:00 order-api INFO status=200 host=app-01 path=/api/orders message="order list ok"',
    '2026-05-23T10:05:30 order-api INFO status=200 host=app-02 path=/api/orders message="order list ok"',
    '2026-05-23T10:06:00 payment-api INFO status=200 host=app-03 path=/api/payments message="payment processed"',
]

if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "data" / "sample_app.log"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    print(f"Wrote {len(LINES)} lines to {out}")
