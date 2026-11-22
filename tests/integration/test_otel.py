"""Integration tests verifying OTel telemetry reaches Jaeger, Prometheus and Loki.

Requires the local stack from `podman-compose up -d` to be running:
stub (Mockoon), otel-collector, jaeger, prometheus, loki and lambda.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import pytest

LAMBDA_URL = "http://localhost:9000/2015-03-31/functions/function/invocations"
JAEGER_URL = "http://localhost:16686"
PROMETHEUS_URL = "http://localhost:9090"
LOKI_URL = "http://localhost:3100"
OTEL_COLLECTOR_URL = "http://localhost:13133"


def _get(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=3) as res:
            return res.status
    except urllib.error.URLError:
        return 0


@pytest.fixture(autouse=True)
def require_services():
    services = {
        "otel-collector": _get(f"{OTEL_COLLECTOR_URL}/"),
        "prometheus": _get(f"{PROMETHEUS_URL}/-/healthy"),
        "jaeger": _get(f"{JAEGER_URL}/api/services"),
        "loki": _get(f"{LOKI_URL}/ready"),
    }
    not_ready = [name for name, status in services.items() if status != 200]
    if not_ready:
        pytest.fail(f"services not ready: {', '.join(not_ready)}")


def _invoke_lambda(messages: list[str]) -> int:
    # 15 分以内に同じメッセージを送ると、送信済みとしてスキップされるため、一意にする
    messages = [f"{m} {uuid.uuid4()}" for m in messages]
    body = json.dumps(
        {
            "httpMethod": "POST",
            "path": "/notify",
            "headers": {"x-api-key": "test"},
            "body": json.dumps({"messages": messages}),
            "queryStringParameters": None,
        }
    ).encode()
    req = urllib.request.Request(
        LAMBDA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return res.status


def _wait_for_prometheus(query: str, timeout: int = 30) -> bool:
    url = f"{PROMETHEUS_URL}/api/v1/query?query={urllib.parse.quote(query)}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        with urllib.request.urlopen(url, timeout=3) as res:
            data = json.loads(res.read())
        if data["data"]["result"]:
            return True
        time.sleep(2)
    return False


def test_trace_recorded_in_jaeger():
    _invoke_lambda(["結合テスト用メッセージ"])
    time.sleep(3)
    with urllib.request.urlopen(
        f"{JAEGER_URL}/api/traces?service=nandemo-oshirase&limit=1", timeout=5
    ) as res:
        data = json.loads(res.read())
    assert len(data["data"]) > 0


def test_metrics_recorded_in_prometheus():
    _invoke_lambda(["結合テスト用メッセージ"])
    assert _wait_for_prometheus('line_notifications_sent_total{status="success"}')


def test_error_metrics_recorded_in_prometheus():
    _invoke_lambda(["__error__"])
    assert _wait_for_prometheus('line_notifications_sent_total{status="error"}')


def test_trace_linked_from_external_caller():
    # 外部アプリからの呼び出しをシミュレート: traceparent をイベントの headers に注入する
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    traceparent = f"00-{trace_id}-00f067aa0ba902b7-01"

    body = json.dumps(
        {
            "httpMethod": "POST",
            "path": "/notify",
            "headers": {"traceparent": traceparent},
            "body": json.dumps({"messages": [f"分散トレーシング結合テスト {uuid.uuid4()}"]}),
            "queryStringParameters": None,
        }
    ).encode()
    req = urllib.request.Request(
        LAMBDA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        assert res.status == 200

    time.sleep(3)

    with urllib.request.urlopen(f"{JAEGER_URL}/api/traces/{trace_id}", timeout=5) as res:
        data = json.loads(res.read())

    assert len(data["data"]) > 0, "trace_id が Jaeger に記録されていない"
    processes = data["data"][0]["processes"]
    service_names = [p["serviceName"] for p in processes.values()]
    assert "nandemo-oshirase" in service_names


def test_logs_recorded_in_loki_with_trace_id():
    # 呼び出し元の trace_id を渡し、その実行のログに同じ trace_id が付いて Loki に届くことを確かめる
    trace_id = uuid.uuid4().hex
    body = json.dumps(
        {
            "httpMethod": "POST",
            "path": "/notify",
            "headers": {"traceparent": f"00-{trace_id}-00f067aa0ba902b7-01"},
            "body": json.dumps({"messages": [f"ログの結合テスト {uuid.uuid4()}"]}),
            "queryStringParameters": None,
        }
    ).encode()
    req = urllib.request.Request(
        LAMBDA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        assert res.status == 200

    # Loki は OTLP の service.name を service_name ラベルに、trace_id を structured metadata にする
    query = f'{{service_name="nandemo-oshirase"}} | trace_id="{trace_id}"'
    url = f"{LOKI_URL}/loki/api/v1/query_range?query={urllib.parse.quote(query)}&since=5m"
    lines: list[str] = []
    deadline = time.time() + 30
    while time.time() < deadline:
        with urllib.request.urlopen(url, timeout=3) as res:
            data = json.loads(res.read())
        lines = [line for stream in data["data"]["result"] for _, line in stream["values"]]
        if lines:
            break
        time.sleep(2)

    assert "Lambda invoked" in lines, f"trace_id={trace_id} のログが Loki に無い: {lines}"
