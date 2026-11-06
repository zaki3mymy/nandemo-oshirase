"""Tests for lambda_handler function."""

import json
import os
from pathlib import Path
from unittest.mock import call, patch

from nandemo_oshirase.lambda_function import LambdaEvent, lambda_handler


class TestLambdaHandlerSuccess:
    """Test successful lambda handler execution."""

    def test_lambda_handler_success_single_message(self):
        event: LambdaEvent = {"body": json.dumps({"message": "Hello"})}

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"},
        ):
            with patch("nandemo_oshirase.lambda_function.push_messages") as mock_push:
                mock_push.return_value = {"statusCode": 200, "body": "{}"}

                result = lambda_handler(event, None)

                expected = {
                    "statusCode": 200,
                    "body": json.dumps({"message": "Successfully sent 1 message(s)"}),
                }
                assert result == expected
                mock_push.assert_called_once()
                call_args = mock_push.call_args[0]
                assert call_args[0] == [{"type": "text", "text": "Hello"}]
                assert call_args[1] == "test_token"
                assert call_args[2] == "test_user"

    def test_lambda_handler_success_multiple_messages(self):
        event: LambdaEvent = {"body": json.dumps({"messages": ["Hello", "World"]})}

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"},
        ):
            with patch("nandemo_oshirase.lambda_function.push_messages") as mock_push:
                mock_push.return_value = {"statusCode": 200, "body": "{}"}

                result = lambda_handler(event, None)

                expected = {
                    "statusCode": 200,
                    "body": json.dumps({"message": "Successfully sent 2 message(s)"}),
                }
                assert result == expected

    def test_lambda_handler_success_batch_messages(self):
        event: LambdaEvent = {"body": json.dumps({"messages": [f"msg{i}" for i in range(7)]})}

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"},
        ):
            with patch("nandemo_oshirase.lambda_function.push_messages") as mock_push:
                mock_push.return_value = {"statusCode": 200, "body": "{}"}

                result = lambda_handler(event, None)

                expected = {
                    "statusCode": 200,
                    "body": json.dumps({"message": "Successfully sent 7 message(s)"}),
                }
                assert result == expected
                assert mock_push.call_count == 2


class TestLambdaHandlerNoMessages:
    """Test lambda handler with no valid messages."""

    def test_lambda_handler_no_messages_empty_list(self):
        event: LambdaEvent = {"body": json.dumps({"messages": []})}

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"},
        ):
            result = lambda_handler(event, None)

            expected = {
                "statusCode": 400,
                "body": json.dumps({"error": "No valid messages to send"}),
            }
            assert result == expected

    def test_lambda_handler_no_messages_all_empty_strings(self):
        event: LambdaEvent = {"body": json.dumps({"messages": ["", "  ", "\t"]})}

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"},
        ):
            result = lambda_handler(event, None)

            expected = {
                "statusCode": 400,
                "body": json.dumps({"error": "No valid messages to send"}),
            }
            assert result == expected


class TestLambdaHandlerMissingEnv:
    """Test lambda handler with missing environment variables."""

    def test_lambda_handler_missing_token(self):
        event: LambdaEvent = {"body": json.dumps({"message": "Hello"})}

        with patch.dict(os.environ, {"LINE_USER_ID": "test_user"}, clear=True):
            result = lambda_handler(event, None)

            expected = {
                "statusCode": 500,
                "body": json.dumps(
                    {
                        "error": "LINE_CHANNEL_TOKEN or LINE_CHANNEL_TOKEN_PARAM "
                        "environment variable not set"
                    }
                ),
            }
            assert result == expected

    def test_lambda_handler_missing_user_id(self):
        event: LambdaEvent = {"body": json.dumps({"message": "Hello"})}

        with patch.dict(os.environ, {"LINE_CHANNEL_TOKEN": "test_token"}, clear=True):
            result = lambda_handler(event, None)

            expected = {
                "statusCode": 500,
                "body": json.dumps(
                    {"error": "LINE_USER_ID or LINE_USER_ID_PARAM environment variable not set"}
                ),
            }
            assert result == expected


class TestLambdaHandlerInvalidRequest:
    """Test lambda handler with invalid request."""

    def test_lambda_handler_invalid_json(self):
        event: LambdaEvent = {"body": "not valid json"}

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"},
        ):
            result = lambda_handler(event, None)

            assert result["statusCode"] == 400
            assert json.loads(result["body"]).keys() == {"error"}


class TestLambdaHandlerDocs:
    """Test GET /docs endpoint."""

    docs_html = Path(__file__).parent.parent.parent / "src" / "nandemo_oshirase" / "docs.html"

    def setup_method(self):
        self.docs_html.write_text("<!DOCTYPE html><html><body>openapi</body></html>")

    def teardown_method(self):
        self.docs_html.unlink(missing_ok=True)

    def test_docs_returns_200(self):
        event: LambdaEvent = {"httpMethod": "GET", "path": "/docs"}
        result = lambda_handler(event, None)
        assert result["statusCode"] == 200

    def test_docs_content_type_html(self):
        event: LambdaEvent = {"httpMethod": "GET", "path": "/docs"}
        result = lambda_handler(event, None)
        assert result["headers"]["Content-Type"] == "text/html"

    def test_docs_body_contains_openapi(self):
        event: LambdaEvent = {"httpMethod": "GET", "path": "/docs"}
        result = lambda_handler(event, None)
        body = result["body"].lower()
        assert "swagger" in body or "openapi" in body


class TestLambdaHandlerWebhook:
    """Test routing to webhook handler."""

    def test_routes_post_webhook_to_handle_webhook(self):
        event: LambdaEvent = {
            "httpMethod": "POST",
            "path": "/webhook",
            "body": json.dumps(
                {"events": [{"source": {"type": "group", "groupId": "C123", "userId": "U456"}}]}
            ),
        }
        result = lambda_handler(event, None)
        assert result["statusCode"] == 200


class TestLambdaHandlerPushError:
    """Test lambda handler when push_messages fails."""

    def test_lambda_handler_push_error(self):
        event: LambdaEvent = {"body": json.dumps({"message": "Hello"})}

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"},
        ):
            with patch("nandemo_oshirase.lambda_function.push_messages") as mock_push:
                mock_push.return_value = {
                    "statusCode": 400,
                    "body": json.dumps({"error": "Bad Request"}),
                }

                result = lambda_handler(event, None)

                expected = {
                    "statusCode": 400,
                    "body": json.dumps({"error": "Bad Request"}),
                }
                assert result == expected


class TestLambdaHandlerDryRun:
    """Test POST /notify with dry_run."""

    def test_dry_run_does_not_push(self):
        event: LambdaEvent = {"body": json.dumps({"message": "Hello", "dry_run": True})}

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"},
        ):
            with patch("nandemo_oshirase.lambda_function.push_messages") as mock_push:
                result = lambda_handler(event, None)

                expected = {
                    "statusCode": 200,
                    "body": json.dumps(
                        {"message": "Dry run: would send 1 message(s) in 1 batch(es)"}
                    ),
                }
                assert result == expected
                mock_push.assert_not_called()

    def test_dry_run_reports_batches(self):
        event: LambdaEvent = {
            "body": json.dumps({"messages": [f"msg{i}" for i in range(7)], "dry_run": True})
        }

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"},
        ):
            with patch("nandemo_oshirase.lambda_function.push_messages") as mock_push:
                result = lambda_handler(event, None)

                expected = {
                    "statusCode": 200,
                    "body": json.dumps(
                        {"message": "Dry run: would send 7 message(s) in 2 batch(es)"}
                    ),
                }
                assert result == expected
                mock_push.assert_not_called()

    def test_dry_run_still_validates_messages(self):
        """dry run でも、送信できるメッセージがなければ通常と同じく 400 を返す"""
        event: LambdaEvent = {"body": json.dumps({"messages": ["", " "], "dry_run": True})}

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"},
        ):
            result = lambda_handler(event, None)

            expected = {
                "statusCode": 400,
                "body": json.dumps({"error": "No valid messages to send"}),
            }
            assert result == expected

    def test_dry_run_still_requires_credentials(self):
        """dry run でも LINE の認証情報を読み込み、読めなければ通常と同じく 500 を返す"""
        event: LambdaEvent = {"body": json.dumps({"message": "Hello", "dry_run": True})}

        with patch.dict(os.environ, {"LINE_USER_ID": "test_user"}, clear=True):
            result = lambda_handler(event, None)

            assert result["statusCode"] == 500

    def test_dry_run_false_sends(self):
        event: LambdaEvent = {"body": json.dumps({"message": "Hello", "dry_run": False})}

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"},
        ):
            with patch("nandemo_oshirase.lambda_function.push_messages") as mock_push:
                mock_push.return_value = {"statusCode": 200, "body": "{}"}

                result = lambda_handler(event, None)

                assert result["statusCode"] == 200
                mock_push.assert_called_once()

    def test_dry_run_sets_span_attribute(self):
        event: LambdaEvent = {"body": json.dumps({"message": "Hello", "dry_run": True})}

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"},
        ):
            with patch("nandemo_oshirase.lambda_function.trace.get_current_span") as mock_span:
                lambda_handler(event, None)

                assert (
                    call("notify.dry_run", True) in mock_span.return_value.set_attribute.mock_calls
                )

    def test_normal_send_does_not_set_dry_run_attribute(self):
        """通常の送信では notify.dry_run の属性を付けない"""
        event: LambdaEvent = {"body": json.dumps({"message": "Hello"})}

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"},
        ):
            with (
                patch("nandemo_oshirase.lambda_function.trace.get_current_span") as mock_span,
                patch("nandemo_oshirase.lambda_function.push_messages") as mock_push,
            ):
                mock_push.return_value = {"statusCode": 200, "body": "{}"}

                lambda_handler(event, None)

                keys = [c.args[0] for c in mock_span.return_value.set_attribute.mock_calls]
                assert "notify.dry_run" not in keys

    def test_dry_run_does_not_record_batch_count_metric(self):
        """dry run は送信しないので、送信したバッチ数のメトリクスに含めない"""
        event: LambdaEvent = {"body": json.dumps({"message": "Hello", "dry_run": True})}

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"},
        ):
            with patch("nandemo_oshirase.lambda_function._batch_count_histogram") as mock_hist:
                lambda_handler(event, None)

                mock_hist.record.assert_not_called()

    def test_normal_send_records_batch_count_metric(self):
        event: LambdaEvent = {"body": json.dumps({"messages": [f"msg{i}" for i in range(7)]})}

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"},
        ):
            with (
                patch("nandemo_oshirase.lambda_function._batch_count_histogram") as mock_hist,
                patch("nandemo_oshirase.lambda_function.push_messages") as mock_push,
            ):
                mock_push.return_value = {"statusCode": 200, "body": "{}"}

                lambda_handler(event, None)

                mock_hist.record.assert_called_once_with(2)
