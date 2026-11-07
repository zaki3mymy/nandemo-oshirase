"""Integration tests for POST /notify with dry_run.

Requires the local stack from `podman-compose up -d` to be running:
stub (Mockoon), otel-collector, jaeger, prometheus and lambda.
"""

import json
import secrets
import time
import urllib.error
import urllib.request

LAMBDA_URL = "http://localhost:9000/2015-03-31/functions/function/invocations"
JAEGER_URL = "http://localhost:16686"


def _invoke_notify(body: dict, trace_id: str) -> dict:
    """Invoke the Lambda as POST /notify and return the Lambda's response."""
    traceparent = f"00-{trace_id}-00f067aa0ba902b7-01"
    event = json.dumps(
        {
            "httpMethod": "POST",
            "path": "/notify",
            "headers": {"x-api-key": "test", "traceparent": traceparent},
            "body": json.dumps(body),
            "queryStringParameters": None,
        }
    ).encode()
    req = urllib.request.Request(
        LAMBDA_URL, data=event, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read())


def _span_names(trace_id: str, timeout: int = 15) -> set[str]:
    """Return the span names recorded in Jaeger for the trace."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{JAEGER_URL}/api/traces/{trace_id}", timeout=5) as res:
                data = json.loads(res.read())
            if data["data"]:
                return {span["operationName"] for span in data["data"][0]["spans"]}
        except urllib.error.HTTPError:
            pass  # まだ Jaeger に届いていない
        time.sleep(1)
    return set()


def test_dry_run_validates_without_pushing():
    trace_id = secrets.token_hex(16)

    response = _invoke_notify({"messages": ["dry run 結合テスト"], "dry_run": True}, trace_id)

    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {
        "message": "Dry run: would send 1 message(s) in 1 batch(es)"
    }
    span_names = _span_names(trace_id)
    assert "validate_push_messages" in span_names
    assert "push_messages" not in span_names


def test_dry_run_returns_validation_error():
    trace_id = secrets.token_hex(16)

    # スタブの validate API は、ボディに __error__ が含まれると 400 を返す
    response = _invoke_notify({"messages": ["__error__"], "dry_run": True}, trace_id)

    assert response["statusCode"] == 400
    span_names = _span_names(trace_id)
    assert "validate_push_messages" in span_names
    assert "push_messages" not in span_names
