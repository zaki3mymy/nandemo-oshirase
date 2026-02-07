"""Lambda function for LINE notification service."""

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Any


def parse_request(event: dict[str, Any]) -> list[str]:
    """Parse Lambda event and extract messages."""
    body = event.get("body")
    if not body:
        raise ValueError("Invalid JSON: empty body")

    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e

    if "message" in data:
        return [data["message"]]
    elif "messages" in data:
        return data["messages"]
    else:
        raise ValueError("No message or messages key found")


def validate_messages(messages: list[str]) -> list[str]:
    """Validate and filter messages."""
    return [msg for msg in messages if msg.strip()]


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

    request = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(request) as response:
            return {
                "statusCode": response.status,
                "body": response.read().decode("utf-8"),
            }
    except urllib.error.HTTPError as e:
        return {"statusCode": e.code, "error": e.reason}


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Main Lambda handler."""
    channel_token = os.environ.get("LINE_CHANNEL_TOKEN")
    if not channel_token:
        return {
            "statusCode": 500,
            "body": json.dumps(
                {"error": "LINE_CHANNEL_TOKEN environment variable not set"}
            ),
        }

    user_id = os.environ.get("LINE_USER_ID")
    if not user_id:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "LINE_USER_ID environment variable not set"}),
        }

    try:
        raw_messages = parse_request(event)
    except ValueError as e:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": str(e)}),
        }

    messages = validate_messages(raw_messages)
    if not messages:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "No valid messages to send"}),
        }

    formatted = format_line_messages(messages)
    batches = split_into_batches(formatted)

    for batch in batches:
        result = push_messages(batch, channel_token, user_id)
        if result["statusCode"] != 200:
            return result

    return {
        "statusCode": 200,
        "body": json.dumps(
            {"message": f"Successfully sent {len(messages)} message(s)"}
        ),
    }
