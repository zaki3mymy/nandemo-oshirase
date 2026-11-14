"""Tests for the retry key (X-Line-Retry-Key) stored in DynamoDB."""

import json
import os
import uuid
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError
from botocore.stub import Stubber
from moto import mock_aws

from nandemo_oshirase import lambda_function
from nandemo_oshirase.lambda_function import (
    RETRY_KEY_TTL_SECONDS,
    LineMessage,
    RetryKeyError,
    deliver_messages,
    get_retry_key,
    push_messages,
)

TABLE = "test-retry-keys"
OK = {"statusCode": 200, "body": "{}"}
DUPLICATE = {"statusCode": 409, "body": json.dumps({"error": "Conflict"})}
ERROR = {"statusCode": 500, "body": json.dumps({"error": "Internal Server Error"})}


def _client() -> Any:
    return boto3.client(
        "dynamodb",
        region_name="ap-northeast-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )


@pytest.fixture
def clock() -> Iterator[list[float]]:
    """time.time() を進められるようにする。"""
    now = [1_800_000_000.0]
    with patch("nandemo_oshirase.lambda_function.time.time", side_effect=lambda: now[0]):
        yield now


@pytest.fixture
def table() -> Iterator[Any]:
    """moto の DynamoDB にテーブルを作り、Lambda がそれを使うようにする。"""
    with mock_aws():
        client = _client()
        client.create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        with (
            patch.object(lambda_function, "_get_dynamodb_client", return_value=client),
            patch.dict(os.environ, {"RETRY_KEY_TABLE_NAME": TABLE}),
        ):
            yield client


@pytest.fixture
def mock_push() -> Iterator[MagicMock]:
    with patch("nandemo_oshirase.lambda_function.push_messages") as mock:
        mock.return_value = OK
        yield mock


def _retry_keys(mock_push: MagicMock) -> list[str]:
    return [c.kwargs["retry_key"] for c in mock_push.call_args_list]


class TestGetRetryKey:
    def test_creates_uuid_and_stores_it(self, table, clock):
        key = get_retry_key(TABLE, "batch")

        uuid.UUID(key)
        item = table.get_item(TableName=TABLE, Key={"pk": {"S": "batch"}})["Item"]
        assert item["retry_key"]["S"] == key
        assert item["expires_at"]["N"] == str(int(clock[0]) + RETRY_KEY_TTL_SECONDS)

    def test_reuses_key_within_ttl(self, table, clock):
        first = get_retry_key(TABLE, "batch")
        clock[0] += RETRY_KEY_TTL_SECONDS - 1

        assert get_retry_key(TABLE, "batch") == first

    def test_creates_new_key_after_ttl(self, table, clock):
        # TTL による削除は遅れることがあるので、項目が残っていても expires_at で判定する
        first = get_retry_key(TABLE, "batch")
        clock[0] += RETRY_KEY_TTL_SECONDS

        assert get_retry_key(TABLE, "batch") != first

    def test_different_batches_get_different_keys(self, table, clock):
        assert get_retry_key(TABLE, "a") != get_retry_key(TABLE, "b")

    def test_raises_on_client_error(self):
        client = _client()
        with (
            patch.object(lambda_function, "_get_dynamodb_client", return_value=client),
            Stubber(client) as stubber,
        ):
            stubber.add_client_error("put_item", "ResourceNotFoundException")
            with pytest.raises(RetryKeyError, match="ResourceNotFoundException"):
                get_retry_key(TABLE, "batch")

    def test_raises_when_existing_item_has_no_key(self):
        client = _client()
        with (
            patch.object(lambda_function, "_get_dynamodb_client", return_value=client),
            Stubber(client) as stubber,
        ):
            stubber.add_client_error("put_item", "ConditionalCheckFailedException")
            with pytest.raises(RetryKeyError, match="not found"):
                get_retry_key(TABLE, "batch")

    def test_raises_on_connection_error(self):
        client = MagicMock()
        client.put_item.side_effect = EndpointConnectionError(endpoint_url="http://x")
        with patch.object(lambda_function, "_get_dynamodb_client", return_value=client):
            with pytest.raises(RetryKeyError, match="EndpointConnectionError"):
                get_retry_key(TABLE, "batch")

    def test_creates_client_once(self):
        with patch.object(lambda_function, "_dynamodb_client", None), patch("boto3.client") as m:
            assert lambda_function._get_dynamodb_client() is m.return_value
            assert lambda_function._get_dynamodb_client() is m.return_value
        m.assert_called_once_with("dynamodb")


class TestDeliverWithRetryKey:
    def test_resend_within_ttl_uses_same_key(self, table, clock, mock_push):
        first = deliver_messages(["hello"], "token", "user")
        mock_push.return_value = DUPLICATE
        second = deliver_messages(["hello"], "token", "user")

        keys = _retry_keys(mock_push)
        assert keys[0] == keys[1]
        # LINE が 409 を返しても、最初と同じレスポンスを返す
        assert second == first

    def test_resend_after_ttl_uses_new_key(self, table, clock, mock_push):
        deliver_messages(["hello"], "token", "user")
        clock[0] += RETRY_KEY_TTL_SECONDS
        deliver_messages(["hello"], "token", "user")

        keys = _retry_keys(mock_push)
        assert keys[0] != keys[1]

    def test_different_messages_use_different_keys(self, table, clock, mock_push):
        deliver_messages(["hello"], "token", "user")
        deliver_messages(["world"], "token", "user")

        keys = _retry_keys(mock_push)
        assert keys[0] != keys[1]

    def test_different_user_uses_different_key(self, table, clock, mock_push):
        deliver_messages(["hello"], "token", "user-a")
        deliver_messages(["hello"], "token", "user-b")

        keys = _retry_keys(mock_push)
        assert keys[0] != keys[1]

    def test_identical_batches_in_one_request_use_different_keys(self, table, clock, mock_push):
        deliver_messages(["same"] * 10, "token", "user")

        keys = _retry_keys(mock_push)
        assert len(keys) == 2
        assert keys[0] != keys[1]

    def test_resend_after_partial_failure_reuses_keys(self, table, clock, mock_push):
        messages = [f"msg{i}" for i in range(7)]  # 2 バッチ
        mock_push.side_effect = [OK, ERROR]
        assert deliver_messages(messages, "token", "user")["statusCode"] == 500

        # 再送: 1 つ目は LINE が送信済みとして 409、2 つ目は送られる
        mock_push.side_effect = [DUPLICATE, OK]
        assert deliver_messages(messages, "token", "user")["statusCode"] == 200

        keys = _retry_keys(mock_push)
        assert keys[0] == keys[2]
        assert keys[1] == keys[3]

    def test_dynamodb_error_returns_500_without_sending(self, mock_push):
        with (
            patch.dict(os.environ, {"RETRY_KEY_TABLE_NAME": TABLE}),
            patch.object(
                lambda_function, "get_retry_key", side_effect=RetryKeyError("DynamoDB down")
            ),
        ):
            result = deliver_messages(["hello"], "token", "user")

        assert result == {"statusCode": 500, "body": json.dumps({"error": "DynamoDB down"})}
        mock_push.assert_not_called()

    def test_without_table_sends_without_key(self, mock_push):
        with patch.dict(os.environ, {}, clear=True):
            deliver_messages(["hello"], "token", "user")

        assert _retry_keys(mock_push) == [None]

    def test_409_without_retry_key_is_error(self, mock_push):
        mock_push.return_value = DUPLICATE
        with patch.dict(os.environ, {}, clear=True):
            result = deliver_messages(["hello"], "token", "user")

        assert result == DUPLICATE

    def test_dry_run_does_not_store_key(self, table, clock, mock_push):
        with patch.object(lambda_function, "validate_push_messages", return_value=OK):
            deliver_messages(["hello"], "token", "user", dry_run=True)

        assert table.scan(TableName=TABLE)["Count"] == 0


class TestPushWithRetryKey:
    def _urlopen(self, status: int = 200) -> MagicMock:
        response = MagicMock()
        response.status = status
        response.read.return_value = b"{}"
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        return response

    def test_sends_retry_key_header(self):
        messages: list[LineMessage] = [{"type": "text", "text": "Hello"}]
        with patch("nandemo_oshirase.lambda_function.urllib.request.urlopen") as m:
            m.return_value = self._urlopen()
            push_messages(messages, "token", "user", retry_key="key-1")

        assert m.call_args[0][0].get_header("X-line-retry-key") == "key-1"

    def test_no_retry_key_header_by_default(self):
        messages: list[LineMessage] = [{"type": "text", "text": "Hello"}]
        with patch("nandemo_oshirase.lambda_function.urllib.request.urlopen") as m:
            m.return_value = self._urlopen()
            push_messages(messages, "token", "user")

        assert m.call_args[0][0].get_header("X-line-retry-key") is None

    def test_409_with_retry_key_is_counted_as_duplicate(self):
        messages: list[LineMessage] = [{"type": "text", "text": "Hello"}]
        with (
            patch.object(lambda_function, "_post_line_api", return_value=DUPLICATE),
            patch.object(lambda_function, "_notification_counter") as counter,
        ):
            push_messages(messages, "token", "user", retry_key="key-1")

        counter.add.assert_called_once_with(1, {"status": "duplicate"})

    def test_409_without_retry_key_is_counted_as_error(self):
        messages: list[LineMessage] = [{"type": "text", "text": "Hello"}]
        with (
            patch.object(lambda_function, "_post_line_api", return_value=DUPLICATE),
            patch.object(lambda_function, "_notification_counter") as counter,
        ):
            push_messages(messages, "token", "user")

        counter.add.assert_called_once_with(1, {"status": "error"})
