"""Tests for lambda_handler function."""

import json
import os
from unittest.mock import patch, MagicMock
import pytest

from nandemo_oshirase.lambda_function import lambda_handler


class TestLambdaHandlerSuccess:
    """Test successful lambda handler execution."""

    def test_lambda_handler_success_single_message(self):
        event = {"body": json.dumps({"message": "Hello"})}

        with patch.dict(os.environ, {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"}):
            with patch("nandemo_oshirase.lambda_function.push_messages") as mock_push:
                mock_push.return_value = {"statusCode": 200, "body": "{}"}

                result = lambda_handler(event, None)

                assert result["statusCode"] == 200
                mock_push.assert_called_once()
                call_args = mock_push.call_args[0]
                assert call_args[0] == [{"type": "text", "text": "Hello"}]
                assert call_args[1] == "test_token"
                assert call_args[2] == "test_user"

    def test_lambda_handler_success_multiple_messages(self):
        event = {"body": json.dumps({"messages": ["Hello", "World"]})}

        with patch.dict(os.environ, {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"}):
            with patch("nandemo_oshirase.lambda_function.push_messages") as mock_push:
                mock_push.return_value = {"statusCode": 200, "body": "{}"}

                result = lambda_handler(event, None)

                assert result["statusCode"] == 200

    def test_lambda_handler_success_batch_messages(self):
        event = {"body": json.dumps({"messages": [f"msg{i}" for i in range(7)]})}

        with patch.dict(os.environ, {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"}):
            with patch("nandemo_oshirase.lambda_function.push_messages") as mock_push:
                mock_push.return_value = {"statusCode": 200, "body": "{}"}

                result = lambda_handler(event, None)

                assert result["statusCode"] == 200
                assert mock_push.call_count == 2


class TestLambdaHandlerNoMessages:
    """Test lambda handler with no valid messages."""

    def test_lambda_handler_no_messages_empty_list(self):
        event = {"body": json.dumps({"messages": []})}

        with patch.dict(os.environ, {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"}):
            result = lambda_handler(event, None)

            assert result["statusCode"] == 400
            body = json.loads(result["body"])
            assert "error" in body

    def test_lambda_handler_no_messages_all_empty_strings(self):
        event = {"body": json.dumps({"messages": ["", "  ", "\t"]})}

        with patch.dict(os.environ, {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"}):
            result = lambda_handler(event, None)

            assert result["statusCode"] == 400


class TestLambdaHandlerMissingEnv:
    """Test lambda handler with missing environment variables."""

    def test_lambda_handler_missing_token(self):
        event = {"body": json.dumps({"message": "Hello"})}

        with patch.dict(os.environ, {"LINE_USER_ID": "test_user"}, clear=True):
            result = lambda_handler(event, None)

            assert result["statusCode"] == 500
            body = json.loads(result["body"])
            assert "LINE_CHANNEL_TOKEN" in body["error"]

    def test_lambda_handler_missing_user_id(self):
        event = {"body": json.dumps({"message": "Hello"})}

        with patch.dict(os.environ, {"LINE_CHANNEL_TOKEN": "test_token"}, clear=True):
            result = lambda_handler(event, None)

            assert result["statusCode"] == 500
            body = json.loads(result["body"])
            assert "LINE_USER_ID" in body["error"]


class TestLambdaHandlerInvalidRequest:
    """Test lambda handler with invalid request."""

    def test_lambda_handler_invalid_json(self):
        event = {"body": "not valid json"}

        with patch.dict(os.environ, {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"}):
            result = lambda_handler(event, None)

            assert result["statusCode"] == 400
            body = json.loads(result["body"])
            assert "error" in body
