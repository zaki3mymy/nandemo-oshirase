"""Integration tests for the retry key (X-Line-Retry-Key) stored in DynamoDB Local.

Requires the local stack from `podman-compose up -d` to be running:
stub (Mockoon), dynamodb, dynamodb-init, otel-collector, jaeger, prometheus and lambda.
"""

import json
import secrets
import time
import urllib.error
import urllib.request
import uuid

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


def _span_tags(trace_id: str, name: str, timeout: int = 15) -> list[dict]:
    """Return the tags of each span named ``name`` in the trace recorded in Jaeger."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{JAEGER_URL}/api/traces/{trace_id}", timeout=5) as res:
                data = json.loads(res.read())
            if data["data"]:
                return [
                    {tag["key"]: tag["value"] for tag in span["tags"]}
                    for span in data["data"][0]["spans"]
                    if span["operationName"] == name
                ]
        except urllib.error.HTTPError:
            pass  # まだ Jaeger に届いていない
        time.sleep(1)
    return []


def test_resend_reuses_retry_key():
    body = {"messages": [f"再送キー結合テスト {uuid.uuid4()}"]}

    first_trace, second_trace = secrets.token_hex(16), secrets.token_hex(16)
    first = _invoke_notify(body, first_trace)
    second = _invoke_notify(body, second_trace)

    assert first["statusCode"] == 200
    assert second == first
    assert [t["line.retry_key_reused"] for t in _span_tags(first_trace, "get_retry_key")] == [False]
    assert [t["line.retry_key_reused"] for t in _span_tags(second_trace, "get_retry_key")] == [True]


def test_already_accepted_by_line_is_success():
    # スタブの push API は、ボディに __already_sent__ が含まれると 409 を返す
    response = _invoke_notify(
        {"messages": [f"__already_sent__ {uuid.uuid4()}"]}, secrets.token_hex(16)
    )

    assert response == {
        "statusCode": 200,
        "body": json.dumps({"message": "Successfully sent 1 message(s)"}),
    }
