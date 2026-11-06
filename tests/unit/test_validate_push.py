"""Tests for validate_push_messages function (LINE validate API)."""

import json
import os
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from nandemo_oshirase.lambda_function import LineMessage, validate_push_messages


def _ok_response() -> MagicMock:
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = b"{}"
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    return mock_response


class TestValidatePushMessages:
    """Test validating messages with the LINE validate API."""

    def test_validate_push_messages_success(self):
        messages: list[LineMessage] = [{"type": "text", "text": "Hello"}]

        with patch("nandemo_oshirase.lambda_function.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _ok_response()

            result = validate_push_messages(messages, "test_token")

            assert result["statusCode"] == 200
            request = mock_urlopen.call_args[0][0]
            assert request.full_url == "https://api.line.me/v2/bot/message/validate/push"
            assert request.get_method() == "POST"
            assert request.get_header("Authorization") == "Bearer test_token"
            assert request.get_header("Content-type") == "application/json"

    def test_validate_push_messages_body_has_no_recipient(self):
        """validate API のボディは messages だけで、送り先（to）は含めない"""
        messages: list[LineMessage] = [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "World"},
        ]

        with patch("nandemo_oshirase.lambda_function.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _ok_response()

            validate_push_messages(messages, "test_token")

            request = mock_urlopen.call_args[0][0]
            body = json.loads(request.data.decode("utf-8"))
            assert body == {"messages": messages}

    def test_validate_push_messages_uses_stub_base_url_when_set(self):
        messages: list[LineMessage] = [{"type": "text", "text": "Hello"}]

        with (
            patch.dict(os.environ, {"LINE_API_BASE_URL": "http://stub:3000"}),
            patch("nandemo_oshirase.lambda_function.urllib.request.urlopen") as mock_urlopen,
        ):
            mock_urlopen.return_value = _ok_response()

            validate_push_messages(messages, "test_token")

            request = mock_urlopen.call_args[0][0]
            assert request.full_url == "http://stub:3000/v2/bot/message/validate/push"

    def test_validate_push_messages_invalid_token(self):
        messages: list[LineMessage] = [{"type": "text", "text": "Hello"}]

        with patch("nandemo_oshirase.lambda_function.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = HTTPError(
                url="https://api.line.me/v2/bot/message/validate/push",
                code=401,
                msg="Unauthorized",
                hdrs=MagicMock(),
                fp=MagicMock(read=lambda: b'{"message": "Authentication failed"}'),
            )

            result = validate_push_messages(messages, "invalid_token")

            expected = {"statusCode": 401, "body": json.dumps({"error": "Unauthorized"})}
            assert result == expected

    def test_validate_push_messages_connection_error(self):
        messages: list[LineMessage] = [{"type": "text", "text": "Hello"}]

        with patch("nandemo_oshirase.lambda_function.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = URLError("Connection refused")

            result = validate_push_messages(messages, "test_token")

            expected = {"statusCode": 502, "body": json.dumps({"error": "Connection refused"})}
            assert result == expected

    def test_validate_push_messages_does_not_count_notifications(self):
        """validate API は送信ではないので、送信件数のメトリクスを増やさない"""
        messages: list[LineMessage] = [{"type": "text", "text": "Hello"}]

        with (
            patch("nandemo_oshirase.lambda_function.urllib.request.urlopen") as mock_urlopen,
            patch("nandemo_oshirase.lambda_function._notification_counter") as mock_counter,
        ):
            mock_urlopen.return_value = _ok_response()

            validate_push_messages(messages, "test_token")

            mock_counter.add.assert_not_called()
