import logging

from nandemo_oshirase.lambda_function import validate_messages


class TestValidateMessagesWarning:
    """空のメッセージを除いたときだけ、除いた件数を警告に出す"""

    def test_warns_skipped_count(self, caplog):
        validate_messages(["Hello", "", " ", "World"])

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert [r.args for r in warnings] == [(2,)]

    def test_no_warning_without_empty_messages(self, caplog):
        validate_messages(["Hello", "World"])

        assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


class TestValidateMessagesValid:
    def test_validate_messages_valid(self):
        messages = ["Hello", "World"]
        result = validate_messages(messages)
        assert result == ["Hello", "World"]

    def test_validate_messages_single(self):
        messages = ["Hello"]
        result = validate_messages(messages)
        assert result == ["Hello"]


class TestValidateMessagesEmptyString:
    def test_validate_messages_empty_string(self):
        messages = ["Hello", "", "World"]
        result = validate_messages(messages)
        assert result == ["Hello", "World"]

    def test_validate_messages_all_empty(self):
        messages = ["", "", ""]
        result = validate_messages(messages)
        assert result == []


class TestValidateMessagesWhitespaceOnly:
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
