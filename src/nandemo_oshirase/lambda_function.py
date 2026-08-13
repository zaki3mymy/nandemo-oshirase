"""Lambda function for LINE notification service."""

import base64
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, NotRequired, TypedDict

from opentelemetry import metrics, trace

logger = logging.getLogger(__name__)
_log_level = logging.getLevelName(os.environ.get("LOG_LEVEL", "INFO").upper())
logger.setLevel(_log_level if isinstance(_log_level, int) else logging.INFO)

_tracer = trace.get_tracer("nandemo_oshirase")
_meter = metrics.get_meter("nandemo_oshirase")

_notification_counter = _meter.create_counter(
    "line.notifications.sent",
    unit="1",
    description="Number of LINE notifications sent",
)
_batch_count_histogram = _meter.create_histogram(
    "line.messages.batch_count",
    unit="1",
    description="Number of batches per request",
)


class LambdaEvent(TypedDict):
    body: NotRequired[str | None]
    isBase64Encoded: NotRequired[bool]
    httpMethod: NotRequired[str]
    path: NotRequired[str]


class LambdaResponse(TypedDict):
    statusCode: int
    body: str
    headers: NotRequired[dict[str, str]]


class LineMessage(TypedDict):
    type: str
    text: str


class WebhookSource(TypedDict):
    type: str
    userId: NotRequired[str]
    groupId: NotRequired[str]
    roomId: NotRequired[str]


class WebhookEvent(TypedDict):
    source: NotRequired[WebhookSource]


class WebhookBody(TypedDict):
    events: NotRequired[list[WebhookEvent]]


def parse_request(event: LambdaEvent) -> list[str]:
    """Parse Lambda event and extract messages."""
    body = event.get("body")
    if not body:
        raise ValueError("Invalid JSON: empty body")

    if event.get("isBase64Encoded"):
        logger.debug("Decoding Base64-encoded body")
        body = base64.b64decode(body).decode("utf-8")

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e

    if "message" in data:
        logger.info("Parsed single message from request")
        return [data["message"]]
    elif "messages" in data:
        logger.info("Parsed %d message(s) from request", len(data["messages"]))
        return data["messages"]
    else:
        raise ValueError("No message or messages key found")


def validate_messages(messages: list[str]) -> list[str]:
    """Validate and filter messages."""
    validated = [msg for msg in messages if msg.strip()]
    skipped = len(messages) - len(validated)
    if skipped:
        logger.warning("Skipped %d empty message(s)", skipped)
    return validated


def format_line_messages(messages: list[str]) -> list[LineMessage]:
    """Format messages for LINE Messaging API."""
    return [{"type": "text", "text": msg} for msg in messages]


def split_into_batches(messages: list[LineMessage], batch_size: int = 5) -> list[list[LineMessage]]:
    """Split messages into batches."""
    if not messages:
        return []
    return [messages[i : i + batch_size] for i in range(0, len(messages), batch_size)]


@_tracer.start_as_current_span("push_messages")
def push_messages(messages: list[LineMessage], channel_token: str, user_id: str) -> LambdaResponse:
    """Send messages to LINE Messaging API."""
    # このバッチ（最大 batch_size 件）に含まれるメッセージ数。リクエスト全体の総数ではない。
    trace.get_current_span().set_attribute("line.batch_message_count", len(messages))

    base_url = os.environ.get("LINE_API_BASE_URL", "https://api.line.me")
    url = f"{base_url}/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {channel_token}",
    }
    body = json.dumps({"to": user_id, "messages": messages}).encode("utf-8")

    logger.info("Sending %d message(s) to LINE API (user_id=%s)", len(messages), user_id)
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(request) as response:
            status = response.status
            response_body = response.read().decode("utf-8")
            logger.info("LINE API responded with status %d", status)
            _notification_counter.add(len(messages), {"status": "success"})
            return {"statusCode": status, "body": response_body}
    except urllib.error.HTTPError as e:
        logger.error("LINE API error: status=%d reason=%s", e.code, e.reason)
        _notification_counter.add(len(messages), {"status": "error"})
        return {"statusCode": e.code, "body": json.dumps({"error": e.reason})}
    except urllib.error.URLError as e:
        logger.error("LINE API connection error: %s", e.reason)
        _notification_counter.add(len(messages), {"status": "error"})
        return {"statusCode": 502, "body": json.dumps({"error": str(e.reason)})}


@_tracer.start_as_current_span("handle_webhook")
def handle_webhook(event: LambdaEvent) -> LambdaResponse:
    """Handle POST /webhook: log source IDs from LINE webhook events."""
    body = event.get("body")
    if not body:
        logger.warning("Webhook received empty body")
        return {"statusCode": 200, "body": json.dumps({"message": "ok"})}

    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")

    try:
        data: WebhookBody = json.loads(body)
    except json.JSONDecodeError as e:
        logger.warning("Webhook received invalid JSON: %s", e)
        return {"statusCode": 200, "body": json.dumps({"message": "ok"})}

    for webhook_event in data.get("events", []):
        source: WebhookSource = webhook_event.get("source", {"type": "unknown"})
        source_type = source.get("type")
        if source_type == "user":
            logger.info("Webhook source: type=user userId=%s", source.get("userId"))
        elif source_type == "group":
            logger.info(
                "Webhook source: type=group groupId=%s userId=%s",
                source.get("groupId"),
                source.get("userId"),
            )
        elif source_type == "room":
            logger.info(
                "Webhook source: type=room roomId=%s userId=%s",
                source.get("roomId"),
                source.get("userId"),
            )
        else:
            logger.info("Webhook source: type=%s source=%s", source_type, source)

    return {"statusCode": 200, "body": json.dumps({"message": "ok"})}


@_tracer.start_as_current_span("serve_docs")
def serve_docs() -> LambdaResponse:
    """Return Swagger UI HTML for GET /docs."""
    html_path = os.path.join(os.path.dirname(__file__), "docs.html")
    with _tracer.start_as_current_span("open_file"):
        with open(html_path) as f:
            html = f.read()
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/html"},
        "body": html,
    }


@_tracer.start_as_current_span("handle_notify")
def handle_notify(event: LambdaEvent) -> LambdaResponse:
    """Handle POST /notify: send messages via LINE."""
    channel_token = os.environ.get("LINE_CHANNEL_TOKEN")
    if not channel_token:
        logger.error("LINE_CHANNEL_TOKEN is not set")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "LINE_CHANNEL_TOKEN environment variable not set"}),
        }

    user_id = os.environ.get("LINE_USER_ID")
    if not user_id:
        logger.error("LINE_USER_ID is not set")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "LINE_USER_ID environment variable not set"}),
        }

    try:
        raw_messages = parse_request(event)
    except ValueError as e:
        logger.warning("Failed to parse request: %s", e)
        return {
            "statusCode": 400,
            "body": json.dumps({"error": str(e)}),
        }

    messages = validate_messages(raw_messages)
    if not messages:
        logger.warning("No valid messages after validation")
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "No valid messages to send"}),
        }

    formatted = format_line_messages(messages)
    batches = split_into_batches(formatted)
    trace.get_current_span().set_attribute("line.batch_count", len(batches))
    _batch_count_histogram.record(len(batches))
    logger.info("Sending %d message(s) in %d batch(es)", len(messages), len(batches))

    for i, batch in enumerate(batches, start=1):
        logger.debug("Sending batch %d/%d", i, len(batches))
        result = push_messages(batch, channel_token, user_id)
        if result["statusCode"] != 200:
            logger.error("Batch %d failed: %s", i, result)
            return result

    logger.info("All messages sent successfully")
    return {
        "statusCode": 200,
        "body": json.dumps({"message": f"Successfully sent {len(messages)} message(s)"}),
    }


def lambda_handler(event: LambdaEvent, context: Any) -> LambdaResponse:
    """Route requests to the appropriate handler."""
    logger.info("Lambda invoked")

    if event.get("httpMethod") == "GET" and event.get("path") == "/docs":
        return serve_docs()

    if event.get("httpMethod") == "POST" and event.get("path") == "/webhook":
        return handle_webhook(event)

    return handle_notify(event)
