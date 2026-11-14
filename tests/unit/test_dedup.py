"""Tests for skipping batches that were already sent (idempotent delivery)."""

import json
from unittest.mock import patch

import pytest

from nandemo_oshirase import lambda_function
from nandemo_oshirase.lambda_function import DEDUP_TTL_SECONDS, deliver_messages

OK = {"statusCode": 200, "body": "{}"}
ERROR = {"statusCode": 500, "body": json.dumps({"error": "Internal Server Error"})}


@pytest.fixture
def mock_push():
    with patch("nandemo_oshirase.lambda_function.push_messages") as mock:
        mock.return_value = OK
        yield mock


@pytest.fixture
def clock():
    """time.monotonic() を進められるようにする。"""
    now = [1000.0]
    with patch("nandemo_oshirase.lambda_function.time.monotonic", side_effect=lambda: now[0]):
        yield now


class TestDedup:
    def test_resend_within_ttl_is_skipped(self, mock_push, clock):
        first = deliver_messages(["hello"], "token", "user")
        clock[0] += DEDUP_TTL_SECONDS - 1
        second = deliver_messages(["hello"], "token", "user")

        assert mock_push.call_count == 1
        # 再送でも最初と同じレスポンスを返す
        assert second == first

    def test_resend_after_ttl_is_sent_again(self, mock_push, clock):
        deliver_messages(["hello"], "token", "user")
        clock[0] += DEDUP_TTL_SECONDS
        deliver_messages(["hello"], "token", "user")

        assert mock_push.call_count == 2

    def test_different_messages_are_sent(self, mock_push, clock):
        deliver_messages(["hello"], "token", "user")
        deliver_messages(["world"], "token", "user")

        assert mock_push.call_count == 2

    def test_different_user_is_sent(self, mock_push, clock):
        deliver_messages(["hello"], "token", "user-a")
        deliver_messages(["hello"], "token", "user-b")

        assert mock_push.call_count == 2

    def test_failed_batch_is_not_recorded(self, mock_push, clock):
        mock_push.return_value = ERROR
        assert deliver_messages(["hello"], "token", "user")["statusCode"] == 500

        mock_push.return_value = OK
        assert deliver_messages(["hello"], "token", "user")["statusCode"] == 200
        assert mock_push.call_count == 2

    def test_resend_after_partial_failure_resumes_from_failed_batch(self, mock_push, clock):
        messages = [f"msg{i}" for i in range(7)]  # 2 バッチ
        mock_push.side_effect = [OK, ERROR]
        assert deliver_messages(messages, "token", "user")["statusCode"] == 500

        mock_push.side_effect = None
        mock_push.return_value = OK
        mock_push.reset_mock()
        result = deliver_messages(messages, "token", "user")

        assert result["statusCode"] == 200
        mock_push.assert_called_once()
        assert [m["text"] for m in mock_push.call_args[0][0]] == ["msg5", "msg6"]

    def test_identical_batches_in_one_request_are_both_sent(self, mock_push, clock):
        messages = ["same"] * 10  # 同じ内容のバッチが 2 つ

        deliver_messages(messages, "token", "user")

        assert mock_push.call_count == 2

    def test_dry_run_does_not_record(self, mock_push, clock):
        with patch("nandemo_oshirase.lambda_function.validate_push_messages", return_value=OK):
            deliver_messages(["hello"], "token", "user", dry_run=True)
        deliver_messages(["hello"], "token", "user")

        mock_push.assert_called_once()

    def test_expired_keys_are_pruned(self, mock_push, clock):
        deliver_messages(["old"], "token", "user")
        clock[0] += DEDUP_TTL_SECONDS
        deliver_messages(["new"], "token", "user")

        assert len(lambda_function._sent_batches) == 1
