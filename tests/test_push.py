"""Tests for push_messages function."""

import json
from unittest.mock import MagicMock, patch

from nandemo_oshirase.lambda_function import push_messages


class TestPushMessages:
    """Test pushing messages to LINE API."""

    def test_push_messages_success(self):
        messages = [{"type": "text", "text": "Hello"}]

        with patch("nandemo_oshirase.lambda_function.urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.read.return_value = b"{}"
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response

            result = push_messages(messages, "test_token", "test_user_id")

            assert result["statusCode"] == 200
            mock_urlopen.assert_called_once()

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            assert request.full_url == "https://api.line.me/v2/bot/message/push"
            assert request.get_header("Authorization") == "Bearer test_token"
            assert request.get_header("Content-type") == "application/json"

            body = json.loads(request.data.decode("utf-8"))
            assert body["to"] == "test_user_id"
            assert body["messages"] == messages

    def test_push_messages_multiple(self):
        messages = [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "World"},
        ]

        with patch("nandemo_oshirase.lambda_function.urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.read.return_value = b"{}"
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response

            result = push_messages(messages, "test_token", "test_user_id")

            assert result["statusCode"] == 200

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            body = json.loads(request.data.decode("utf-8"))
            assert len(body["messages"]) == 2

    def test_push_messages_api_error(self):
        messages = [{"type": "text", "text": "Hello"}]

        with patch("nandemo_oshirase.lambda_function.urllib.request.urlopen") as mock_urlopen:
            from urllib.error import HTTPError

            mock_urlopen.side_effect = HTTPError(
                url="https://api.line.me/v2/bot/message/push",
                code=400,
                msg="Bad Request",
                hdrs=MagicMock(),
                fp=MagicMock(read=lambda: b'{"message": "Invalid request"}'),
            )

            result = push_messages(messages, "test_token", "test_user_id")

            assert result["statusCode"] == 400
            assert "error" in result
