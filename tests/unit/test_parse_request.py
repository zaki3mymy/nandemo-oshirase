"""Tests for parse_request function."""

import base64
import json

import pytest

from nandemo_oshirase.lambda_function import LambdaEvent, NotifyRequest, parse_request


class TestParseRequestSingleMessage:
    """Test parsing single message."""

    def test_parse_request_single_message(self):
        event: LambdaEvent = {"body": json.dumps({"message": "Hello"})}
        result = parse_request(event)
        assert result == NotifyRequest(messages=["Hello"], dry_run=False)

    def test_parse_request_single_message_japanese(self):
        event: LambdaEvent = {"body": json.dumps({"message": "こんにちは"})}
        result = parse_request(event)
        assert result == NotifyRequest(messages=["こんにちは"], dry_run=False)

    def test_parse_request_single_message_dry_run(self):
        event: LambdaEvent = {"body": json.dumps({"message": "Hello", "dry_run": True})}
        result = parse_request(event)
        assert result == NotifyRequest(messages=["Hello"], dry_run=True)

    @pytest.mark.parametrize("value", [False, "true", 1, None, [], {}])
    def test_parse_request_single_message_dry_run_only_true_boolean(self, value):
        """JSON の true（真偽値）のときだけ dry run にする"""
        event: LambdaEvent = {"body": json.dumps({"message": "Hello", "dry_run": value})}
        result = parse_request(event)
        assert result == NotifyRequest(messages=["Hello"], dry_run=False)


class TestParseRequestMultipleMessages:
    """Test parsing multiple messages."""

    def test_parse_request_multiple_messages(self):
        event: LambdaEvent = {"body": json.dumps({"messages": ["Hello", "World"]})}
        result = parse_request(event)
        assert result == NotifyRequest(messages=["Hello", "World"], dry_run=False)

    def test_parse_request_multiple_messages_empty_list(self):
        event: LambdaEvent = {"body": json.dumps({"messages": []})}
        result = parse_request(event)
        assert result == NotifyRequest(messages=[], dry_run=False)

    def test_parse_request_multiple_messages_dry_run(self):
        event: LambdaEvent = {"body": json.dumps({"messages": ["Hello", "World"], "dry_run": True})}
        result = parse_request(event)
        assert result == NotifyRequest(messages=["Hello", "World"], dry_run=True)


class TestParseRequestBase64:
    """Test parsing base64 encoded body."""

    def test_parse_request_base64_encoded(self):
        body = json.dumps({"message": "Hello"})
        encoded_body = base64.b64encode(body.encode()).decode()
        event: LambdaEvent = {"body": encoded_body, "isBase64Encoded": True}
        result = parse_request(event)
        assert result == NotifyRequest(messages=["Hello"], dry_run=False)

    def test_parse_request_base64_encoded_dry_run(self):
        body = json.dumps({"message": "Hello", "dry_run": True})
        encoded_body = base64.b64encode(body.encode()).decode()
        event: LambdaEvent = {"body": encoded_body, "isBase64Encoded": True}
        result = parse_request(event)
        assert result == NotifyRequest(messages=["Hello"], dry_run=True)

    def test_parse_request_base64_encoded_false(self):
        event: LambdaEvent = {"body": json.dumps({"message": "Hello"}), "isBase64Encoded": False}
        result = parse_request(event)
        assert result == NotifyRequest(messages=["Hello"], dry_run=False)


class TestParseRequestInvalidJson:
    """Test parsing invalid JSON."""

    def test_parse_request_invalid_json(self):
        event: LambdaEvent = {"body": "not valid json"}
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_request(event)

    def test_parse_request_empty_body(self):
        event: LambdaEvent = {"body": ""}
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_request(event)

    def test_parse_request_none_body(self):
        event: LambdaEvent = {"body": None}
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_request(event)

    def test_parse_request_no_message_key(self):
        event: LambdaEvent = {"body": json.dumps({"other": "data"})}
        with pytest.raises(ValueError, match="No message"):
            parse_request(event)
