"""Integration tests for the LINE message quota Lambda (nandemo-oshirase-quota).

Requires the local stack from `podman-compose up -d` to be running:
stub (Mockoon), otel-collector, jaeger, prometheus and lambda-quota.
The stub returns {"type": "limited", "value": 200} and {"totalUsage": 42}.
"""

import json
import time
import urllib.parse
import urllib.request

QUOTA_LAMBDA_URL = "http://localhost:9001/2015-03-31/functions/function/invocations"
JAEGER_URL = "http://localhost:16686"
PROMETHEUS_URL = "http://localhost:9090"


def _invoke_quota_lambda() -> dict:
    # EventBridge Scheduler からの呼び出しと同じく、イベントの中身は使わない
    req = urllib.request.Request(
        QUOTA_LAMBDA_URL, data=b"{}", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as res:
        return json.loads(res.read())


def _prometheus_value(query: str, timeout: int = 30) -> float | None:
    url = f"{PROMETHEUS_URL}/api/v1/query?query={urllib.parse.quote(query)}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        with urllib.request.urlopen(url, timeout=3) as res:
            result = json.loads(res.read())["data"]["result"]
        if result:
            return float(result[0]["value"][1])
        time.sleep(2)
    return None


def test_returns_usage_and_limit():
    assert _invoke_quota_lambda() == {"totalUsage": 42, "limit": 200}


def test_usage_and_limit_recorded_in_prometheus():
    _invoke_quota_lambda()
    # unit が {message} なので、Prometheus の名前に単位の接尾辞（_ratio など）は付かない
    assert _prometheus_value("line_quota_consumption") == 42
    assert _prometheus_value("line_quota_limit") == 200


def test_line_api_calls_recorded_in_jaeger():
    _invoke_quota_lambda()
    url = f"{JAEGER_URL}/api/traces?service=nandemo-oshirase-quota&limit=1"
    span_names: set[str] = set()
    deadline = time.time() + 15
    while time.time() < deadline:
        with urllib.request.urlopen(url, timeout=5) as res:
            traces = json.loads(res.read())["data"]
        span_names = {span["operationName"] for t in traces for span in t["spans"]}
        if {"get_message_quota", "get_message_consumption"} <= span_names:
            break
        time.sleep(2)
    assert {"get_message_quota", "get_message_consumption"} <= span_names, span_names
