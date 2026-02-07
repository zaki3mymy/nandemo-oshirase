"""Lambda function for LINE notification service."""

import base64
import json
import urllib.request
import urllib.error
import os
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


def split_into_batches(messages: list[dict[str, str]], batch_size: int = 5) -> list[list[dict[str, str]]]:
    """Split messages into batches."""
    if not messages:
        return []
    return [messages[i:i + batch_size] for i in range(0, len(messages), batch_size)]


def push_messages(messages: list[dict[str, str]], channel_token: str, user_id: str) -> dict[str, Any]:
    """Send messages to LINE Messaging API."""
    pass


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Main Lambda handler."""
    pass
