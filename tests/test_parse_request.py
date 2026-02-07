"""Tests for parse_request function."""

import base64
import json

import pytest

from nandemo_oshirase.lambda_function import parse_request


class TestParseRequestSingleMessage:
    """Test parsing single message."""

    def test_parse_request_single_message(self):
        event = {"body": json.dumps({"message": "Hello"})}
        result = parse_request(event)
        assert result == ["Hello"]

    def test_parse_request_single_message_japanese(self):
        event = {"body": json.dumps({"message": "こんにちは"})}
        result = parse_request(event)
        assert result == ["こんにちは"]


class TestParseRequestMultipleMessages:
    """Test parsing multiple messages."""

    def test_parse_request_multiple_messages(self):
        event = {"body": json.dumps({"messages": ["Hello", "World"]})}
        result = parse_request(event)
        assert result == ["Hello", "World"]

    def test_parse_request_multiple_messages_empty_list(self):
        event = {"body": json.dumps({"messages": []})}
        result = parse_request(event)
        assert result == []


class TestParseRequestBase64:
    """Test parsing base64 encoded body."""

    def test_parse_request_base64_encoded(self):
        body = json.dumps({"message": "Hello"})
        encoded_body = base64.b64encode(body.encode()).decode()
        event = {"body": encoded_body, "isBase64Encoded": True}
        result = parse_request(event)
        assert result == ["Hello"]

    def test_parse_request_base64_encoded_false(self):
        event = {"body": json.dumps({"message": "Hello"}), "isBase64Encoded": False}
        result = parse_request(event)
        assert result == ["Hello"]


class TestParseRequestInvalidJson:
    """Test parsing invalid JSON."""

    def test_parse_request_invalid_json(self):
        event = {"body": "not valid json"}
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_request(event)

    def test_parse_request_empty_body(self):
        event = {"body": ""}
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_request(event)

    def test_parse_request_none_body(self):
        event = {"body": None}
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_request(event)

    def test_parse_request_no_message_key(self):
        event = {"body": json.dumps({"other": "data"})}
        with pytest.raises(ValueError, match="No message"):
            parse_request(event)
