"""Tests for format_line_messages function."""

import pytest

from nandemo_oshirase.lambda_function import format_line_messages


class TestFormatLineMessages:
    """Test formatting messages for LINE API."""

    def test_format_line_messages_single(self):
        messages = ["Hello"]
        result = format_line_messages(messages)
        assert result == [{"type": "text", "text": "Hello"}]

    def test_format_line_messages_multiple(self):
        messages = ["Hello", "World"]
        result = format_line_messages(messages)
        assert result == [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "World"},
        ]

    def test_format_line_messages_empty(self):
        messages = []
        result = format_line_messages(messages)
        assert result == []

    def test_format_line_messages_japanese(self):
        messages = ["こんにちは", "世界"]
        result = format_line_messages(messages)
        assert result == [
            {"type": "text", "text": "こんにちは"},
            {"type": "text", "text": "世界"},
        ]
