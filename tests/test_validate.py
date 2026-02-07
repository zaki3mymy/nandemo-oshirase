"""Tests for validate_messages function."""

import pytest

from nandemo_oshirase.lambda_function import validate_messages


class TestValidateMessagesValid:
    """Test valid messages."""

    def test_validate_messages_valid(self):
        messages = ["Hello", "World"]
        result = validate_messages(messages)
        assert result == ["Hello", "World"]

    def test_validate_messages_single(self):
        messages = ["Hello"]
        result = validate_messages(messages)
        assert result == ["Hello"]


class TestValidateMessagesEmptyString:
    """Test empty string handling."""

    def test_validate_messages_empty_string(self):
        messages = ["Hello", "", "World"]
        result = validate_messages(messages)
        assert result == ["Hello", "World"]

    def test_validate_messages_all_empty(self):
        messages = ["", "", ""]
        result = validate_messages(messages)
        assert result == []


class TestValidateMessagesWhitespaceOnly:
    """Test whitespace-only string handling."""

    def test_validate_messages_whitespace_only(self):
        messages = ["Hello", "   ", "World"]
        result = validate_messages(messages)
        assert result == ["Hello", "World"]

    def test_validate_messages_tabs_and_newlines(self):
        messages = ["Hello", "\t\n", "World"]
        result = validate_messages(messages)
        assert result == ["Hello", "World"]

    def test_validate_messages_preserves_content_with_whitespace(self):
        messages = ["  Hello  ", "World"]
        result = validate_messages(messages)
        assert result == ["  Hello  ", "World"]
