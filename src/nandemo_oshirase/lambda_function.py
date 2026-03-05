"""Lambda function for LINE notification service."""

import base64
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)
_log_level = logging.getLevelName(os.environ.get("LOG_LEVEL", "INFO").upper())
logger.setLevel(_log_level if isinstance(_log_level, int) else logging.INFO)


def parse_request(event: dict[str, Any]) -> list[str]:
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


def format_line_messages(messages: list[str]) -> list[dict[str, str]]:
    """Format messages for LINE Messaging API."""
    return [{"type": "text", "text": msg} for msg in messages]


def split_into_batches(
    messages: list[dict[str, str]], batch_size: int = 5
) -> list[list[dict[str, str]]]:
    """Split messages into batches."""
    if not messages:
        return []
    return [messages[i : i + batch_size] for i in range(0, len(messages), batch_size)]


def push_messages(
    messages: list[dict[str, str]], channel_token: str, user_id: str
) -> dict[str, Any]:
    """Send messages to LINE Messaging API."""
    url = "https://api.line.me/v2/bot/message/push"
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
            return {"statusCode": status, "body": response_body}
    except urllib.error.HTTPError as e:
        logger.error("LINE API error: status=%d reason=%s", e.code, e.reason)
        return {"statusCode": e.code, "body": json.dumps({"error": e.reason})}


def serve_docs() -> dict[str, Any]:
    """Return Swagger UI HTML for GET /docs."""
    html_path = os.path.join(os.path.dirname(__file__), "docs.html")
    with open(html_path) as f:
        html = f.read()
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/html"},
        "body": html,
    }


def handle_notify(event: dict[str, Any]) -> dict[str, Any]:
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


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Route requests to the appropriate handler."""
    logger.info("Lambda invoked")

    if event.get("httpMethod") == "GET" and event.get("path") == "/docs":
        return serve_docs()

    return handle_notify(event)
