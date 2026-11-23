import json
import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from opentelemetry._logs._internal import ProxyLoggerProvider
from opentelemetry.sdk._logs import LoggerProvider

from nandemo_oshirase.lambda_function import (
    LOG_FLUSH_TIMEOUT_MILLIS,
    LambdaEvent,
    deliver_messages,
    lambda_handler,
)


class TestLambdaHandlerSuccess:
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


class TestRouteMethodAndPath:
    """/docs と /webhook は、HTTP メソッドとパスの両方が一致するときだけ振り分ける"""

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("POST", "/docs"),
            ("GET", "/webhook"),
            ("GET", "/notify"),
            ("POST", "/notify"),
        ],
    )
    def test_other_requests_go_to_notify(self, method, path):
        event: LambdaEvent = {"httpMethod": method, "path": path, "body": "{}"}

        with (
            patch("nandemo_oshirase.lambda_function.serve_docs") as mock_docs,
            patch("nandemo_oshirase.lambda_function.handle_webhook") as mock_webhook,
            patch("nandemo_oshirase.lambda_function.handle_notify") as mock_notify,
        ):
            lambda_handler(event, None)

        mock_docs.assert_not_called()
        mock_webhook.assert_not_called()
        mock_notify.assert_called_once_with(event)


class TestDeliverMessagesBatches:
    """失敗したバッチの番号（1 始まり）をログに出し、バッチ数を span の属性に記録する"""

    @staticmethod
    def _error_batch_numbers(caplog: pytest.LogCaptureFixture) -> list[object]:
        return [
            r.args[0]
            for r in caplog.records
            if r.levelno == logging.ERROR and isinstance(r.args, tuple)
        ]

    def test_failed_batch_number_is_logged(self, caplog, monkeypatch):
        monkeypatch.delenv("RETRY_KEY_TABLE_NAME", raising=False)
        ok = {"statusCode": 200, "body": "{}"}
        ng = {"statusCode": 500, "body": "{}"}

        with patch("nandemo_oshirase.lambda_function.push_messages", side_effect=[ok, ng]):
            result = deliver_messages([f"msg{i}" for i in range(7)], "token", "user")

        assert result == ng
        assert self._error_batch_numbers(caplog) == [2]

    def test_failed_batch_number_is_logged_in_dry_run(self, caplog):
        ok = {"statusCode": 200, "body": "{}"}
        ng = {"statusCode": 400, "body": "{}"}

        with patch("nandemo_oshirase.lambda_function.validate_push_messages", side_effect=[ok, ng]):
            result = deliver_messages([f"msg{i}" for i in range(7)], "token", "user", dry_run=True)

        assert result == ng
        assert self._error_batch_numbers(caplog) == [2]

    @pytest.mark.parametrize("dry_run", [False, True])
    def test_batch_count_is_set_on_span(self, monkeypatch, dry_run):
        monkeypatch.delenv("RETRY_KEY_TABLE_NAME", raising=False)
        ok = {"statusCode": 200, "body": "{}"}

        with (
            patch("nandemo_oshirase.lambda_function.trace") as mock_trace,
            patch("nandemo_oshirase.lambda_function.push_messages", return_value=ok),
            patch("nandemo_oshirase.lambda_function.validate_push_messages", return_value=ok),
        ):
            deliver_messages([f"msg{i}" for i in range(7)], "token", "user", dry_run=dry_run)

        set_attribute = mock_trace.get_current_span.return_value.set_attribute
        assert call("line.batch_count", 2) in set_attribute.mock_calls


class TestLambdaHandlerPushError:
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
    def test_dry_run_does_not_push(self):
        event: LambdaEvent = {"body": json.dumps({"message": "Hello", "dry_run": True})}

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"},
        ):
            with (
                patch("nandemo_oshirase.lambda_function.push_messages") as mock_push,
                patch("nandemo_oshirase.lambda_function.validate_push_messages") as mock_validate,
            ):
                mock_validate.return_value = {"statusCode": 200, "body": "{}"}

                result = lambda_handler(event, None)

                expected = {
                    "statusCode": 200,
                    "body": json.dumps(
                        {"message": "Dry run: would send 1 message(s) in 1 batch(es)"}
                    ),
                }
                assert result == expected
                mock_push.assert_not_called()
                mock_validate.assert_called_once_with(
                    [{"type": "text", "text": "Hello"}], "test_token"
                )

    def test_dry_run_reports_batches(self):
        event: LambdaEvent = {
            "body": json.dumps({"messages": [f"msg{i}" for i in range(7)], "dry_run": True})
        }

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"},
        ):
            with (
                patch("nandemo_oshirase.lambda_function.push_messages") as mock_push,
                patch("nandemo_oshirase.lambda_function.validate_push_messages") as mock_validate,
            ):
                mock_validate.return_value = {"statusCode": 200, "body": "{}"}

                result = lambda_handler(event, None)

                expected = {
                    "statusCode": 200,
                    "body": json.dumps(
                        {"message": "Dry run: would send 7 message(s) in 2 batch(es)"}
                    ),
                }
                assert result == expected
                mock_push.assert_not_called()
                # LINE の validate API も push API と同じく 1回5件までなので、バッチごとに呼ぶ
                assert mock_validate.call_count == 2

    def test_dry_run_returns_line_validation_error(self):
        """LINE の validate API でエラーになったら、そのエラーを返して残りのバッチは確認しない"""
        event: LambdaEvent = {
            "body": json.dumps({"messages": [f"msg{i}" for i in range(7)], "dry_run": True})
        }

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_TOKEN": "invalid_token", "LINE_USER_ID": "test_user"},
        ):
            with (
                patch("nandemo_oshirase.lambda_function.push_messages") as mock_push,
                patch("nandemo_oshirase.lambda_function.validate_push_messages") as mock_validate,
            ):
                mock_validate.return_value = {
                    "statusCode": 401,
                    "body": json.dumps({"error": "Unauthorized"}),
                }

                result = lambda_handler(event, None)

                expected = {"statusCode": 401, "body": json.dumps({"error": "Unauthorized"})}
                assert result == expected
                mock_validate.assert_called_once()
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
            with (
                patch("nandemo_oshirase.lambda_function.trace") as mock_trace,
                patch("nandemo_oshirase.lambda_function.validate_push_messages") as mock_validate,
            ):
                mock_validate.return_value = {"statusCode": 200, "body": "{}"}

                lambda_handler(event, None)

                assert (
                    call("notify.dry_run", True)
                    in mock_trace.get_current_span.return_value.set_attribute.mock_calls
                )

    def test_normal_send_does_not_set_dry_run_attribute(self):
        """通常の送信では notify.dry_run の属性を付けない"""
        event: LambdaEvent = {"body": json.dumps({"message": "Hello"})}

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"},
        ):
            with (
                patch("nandemo_oshirase.lambda_function.trace") as mock_trace,
                patch("nandemo_oshirase.lambda_function.push_messages") as mock_push,
            ):
                mock_push.return_value = {"statusCode": 200, "body": "{}"}

                lambda_handler(event, None)

                keys = [
                    c.args[0]
                    for c in mock_trace.get_current_span.return_value.set_attribute.mock_calls
                ]
                assert "notify.dry_run" not in keys

    def test_dry_run_does_not_record_batch_count_metric(self):
        """dry run は送信しないので、送信したバッチ数のメトリクスに含めない"""
        event: LambdaEvent = {"body": json.dumps({"message": "Hello", "dry_run": True})}

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"},
        ):
            with (
                patch("nandemo_oshirase.lambda_function._batch_count_histogram") as mock_hist,
                patch("nandemo_oshirase.lambda_function.validate_push_messages") as mock_validate,
            ):
                mock_validate.return_value = {"statusCode": 200, "body": "{}"}

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


class TestLambdaHandlerFlushLogs:
    def test_flushes_logs_after_handling(self):
        event: LambdaEvent = {"httpMethod": "POST", "path": "/webhook", "body": '{"events": []}'}

        provider = MagicMock(spec=LoggerProvider)
        with patch("nandemo_oshirase.lambda_function.get_logger_provider", return_value=provider):
            lambda_handler(event, None)

        provider.force_flush.assert_called_once_with(timeout_millis=LOG_FLUSH_TIMEOUT_MILLIS)

    def test_flushes_logs_even_when_handling_raises(self):
        event: LambdaEvent = {"httpMethod": "POST", "path": "/webhook", "body": '{"events": []}'}

        provider = MagicMock(spec=LoggerProvider)
        with (
            patch("nandemo_oshirase.lambda_function.get_logger_provider", return_value=provider),
            patch(
                "nandemo_oshirase.lambda_function.handle_webhook", side_effect=RuntimeError("boom")
            ),
            pytest.raises(RuntimeError),
        ):
            lambda_handler(event, None)

        provider.force_flush.assert_called_once()

    def test_skips_flush_without_sdk(self):
        # SDK が設定されていないときは、API の ProxyLoggerProvider が返る
        event: LambdaEvent = {"httpMethod": "POST", "path": "/webhook", "body": '{"events": []}'}

        with patch(
            "nandemo_oshirase.lambda_function.get_logger_provider",
            return_value=ProxyLoggerProvider(),
        ):
            result = lambda_handler(event, None)

        assert result["statusCode"] == 200
