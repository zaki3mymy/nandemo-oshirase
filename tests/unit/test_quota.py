"""Tests for the LINE message quota Lambda (nandemo_oshirase_quota)."""

import io
import json
import os
import urllib.error
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError
from botocore.stub import Stubber
from opentelemetry._logs._internal import ProxyLoggerProvider
from opentelemetry.sdk._logs import LoggerProvider

from nandemo_oshirase_quota import lambda_function
from nandemo_oshirase_quota.lambda_function import (
    Quota,
    QuotaError,
    get_message_consumption,
    get_message_quota,
    lambda_handler,
    load_channel_token,
    record_quota,
)

MODULE = "nandemo_oshirase_quota.lambda_function"
TOKEN_PARAM = "/app/nandemo_oshirase/prod/line_channel_token"


def _response(body: Any) -> MagicMock:
    response = MagicMock()
    response.read.return_value = (body if isinstance(body, str) else json.dumps(body)).encode()
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return response


def _http_error(code: int, reason: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="http://stub", code=code, msg=reason, hdrs=MagicMock(), fp=io.BytesIO(b"{}")
    )


@pytest.fixture
def urlopen() -> Iterator[MagicMock]:
    with patch(f"{MODULE}.urllib.request.urlopen") as mock_urlopen:
        yield mock_urlopen


@pytest.fixture
def ssm() -> Iterator[Stubber]:
    client = boto3.client(
        "ssm",
        region_name="ap-northeast-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    with patch.object(lambda_function, "_create_ssm_client", return_value=client):
        with Stubber(client) as stubber:
            yield stubber
            stubber.assert_no_pending_responses()


class TestLoadChannelToken:
    def test_uses_environment_variable_first(self):
        with patch.dict(
            os.environ, {"LINE_CHANNEL_TOKEN": "direct", "LINE_CHANNEL_TOKEN_PARAM": TOKEN_PARAM}
        ):
            assert load_channel_token() == "direct"

    def test_reads_ssm_parameter(self, ssm: Stubber):
        ssm.add_response(
            "get_parameter",
            {"Parameter": {"Name": TOKEN_PARAM, "Type": "SecureString", "Value": "from-ssm"}},
            {"Name": TOKEN_PARAM, "WithDecryption": True},
        )
        with patch.dict(os.environ, {"LINE_CHANNEL_TOKEN_PARAM": TOKEN_PARAM}, clear=True):
            assert load_channel_token() == "from-ssm"

    def test_raises_when_ssm_parameter_is_empty(self, ssm: Stubber):
        ssm.add_response(
            "get_parameter",
            {"Parameter": {"Name": TOKEN_PARAM, "Type": "SecureString", "Value": ""}},
            {"Name": TOKEN_PARAM, "WithDecryption": True},
        )
        with patch.dict(os.environ, {"LINE_CHANNEL_TOKEN_PARAM": TOKEN_PARAM}, clear=True):
            with pytest.raises(QuotaError, match="SSM parameter is empty"):
                load_channel_token()

    def test_raises_on_ssm_client_error(self, ssm: Stubber):
        ssm.add_client_error("get_parameter", service_error_code="ParameterNotFound")
        with patch.dict(os.environ, {"LINE_CHANNEL_TOKEN_PARAM": TOKEN_PARAM}, clear=True):
            with pytest.raises(QuotaError, match=r"\(ParameterNotFound\)"):
                load_channel_token()

    def test_raises_on_botocore_error(self):
        client = MagicMock()
        client.get_parameter.side_effect = EndpointConnectionError(endpoint_url="http://ssm")
        with (
            patch.object(lambda_function, "_create_ssm_client", return_value=client),
            patch.dict(os.environ, {"LINE_CHANNEL_TOKEN_PARAM": TOKEN_PARAM}, clear=True),
        ):
            with pytest.raises(QuotaError, match=r"\(EndpointConnectionError\)"):
                load_channel_token()

    def test_raises_when_neither_variable_is_set(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(QuotaError, match="environment variable not set"):
                load_channel_token()


def test_create_ssm_client_returns_boto3_client():
    env = {
        "AWS_DEFAULT_REGION": "ap-northeast-1",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
    }
    with patch.dict(os.environ, env):
        client = lambda_function._create_ssm_client()
    assert client.meta.service_model.service_name == "ssm"


class TestGetMessageQuota:
    def test_returns_value_when_limited(self, urlopen: MagicMock):
        urlopen.return_value = _response({"type": "limited", "value": 200})
        with patch.dict(os.environ, {"LINE_API_BASE_URL": "http://stub:3000"}):
            assert get_message_quota("token") == 200

        request = urlopen.call_args[0][0]
        assert request.full_url == "http://stub:3000/v2/bot/message/quota"
        assert request.get_method() == "GET"
        assert request.get_header("Authorization") == "Bearer token"

    def test_uses_line_api_by_default(self, urlopen: MagicMock):
        urlopen.return_value = _response({"type": "limited", "value": 200})
        with patch.dict(os.environ, {}, clear=True):
            get_message_quota("token")
        assert urlopen.call_args[0][0].full_url == "https://api.line.me/v2/bot/message/quota"

    def test_returns_none_when_no_limit_is_set(self, urlopen: MagicMock):
        urlopen.return_value = _response({"type": "none"})
        assert get_message_quota("token") is None

    def test_raises_on_unexpected_type(self, urlopen: MagicMock):
        urlopen.return_value = _response({"type": "unknown"})
        with pytest.raises(QuotaError, match="unexpected type"):
            get_message_quota("token")

    @pytest.mark.parametrize("value", [None, "200", True])
    def test_raises_on_unexpected_value(self, urlopen: MagicMock, value: Any):
        urlopen.return_value = _response({"type": "limited", "value": value})
        with pytest.raises(QuotaError, match="unexpected value"):
            get_message_quota("token")


class TestGetMessageConsumption:
    def test_returns_total_usage(self, urlopen: MagicMock):
        urlopen.return_value = _response({"totalUsage": 42})
        assert get_message_consumption("token") == 42
        assert urlopen.call_args[0][0].full_url.endswith("/v2/bot/message/quota/consumption")

    def test_raises_on_http_error(self, urlopen: MagicMock):
        urlopen.side_effect = _http_error(401, "Unauthorized")
        with pytest.raises(QuotaError, match="status=401"):
            get_message_consumption("token")

    def test_raises_on_connection_error(self, urlopen: MagicMock):
        urlopen.side_effect = urllib.error.URLError("refused")
        with pytest.raises(QuotaError, match="connection error: refused"):
            get_message_consumption("token")

    def test_raises_on_invalid_json(self, urlopen: MagicMock):
        urlopen.return_value = _response("not json")
        with pytest.raises(QuotaError, match="invalid JSON"):
            get_message_consumption("token")

    def test_raises_on_non_object_body(self, urlopen: MagicMock):
        urlopen.return_value = _response([1, 2])
        with pytest.raises(QuotaError, match="unexpected body"):
            get_message_consumption("token")

    def test_raises_when_total_usage_is_missing(self, urlopen: MagicMock):
        urlopen.return_value = _response({})
        with pytest.raises(QuotaError, match="unexpected totalUsage"):
            get_message_consumption("token")


class TestRecordQuota:
    def test_records_usage_and_limit(self):
        with (
            patch(f"{MODULE}._consumption_gauge") as consumption,
            patch(f"{MODULE}._limit_gauge") as limit,
        ):
            record_quota(Quota(total_usage=42, limit=200))
        consumption.set.assert_called_once_with(42)
        limit.set.assert_called_once_with(200)

    def test_does_not_record_limit_when_no_limit_is_set(self):
        with (
            patch(f"{MODULE}._consumption_gauge") as consumption,
            patch(f"{MODULE}._limit_gauge") as limit,
        ):
            record_quota(Quota(total_usage=42, limit=None))
        consumption.set.assert_called_once_with(42)
        limit.set.assert_not_called()


class TestLambdaHandler:
    def test_fetches_and_records_quota(self, urlopen: MagicMock):
        def respond(request: Any, timeout: float) -> MagicMock:
            if request.full_url.endswith("/consumption"):
                return _response({"totalUsage": 42})
            return _response({"type": "limited", "value": 200})

        urlopen.side_effect = respond
        with (
            patch.dict(os.environ, {"LINE_CHANNEL_TOKEN": "token"}),
            patch(f"{MODULE}._consumption_gauge") as consumption,
            patch(f"{MODULE}._limit_gauge") as limit,
        ):
            result = lambda_handler({}, None)

        assert result == {"totalUsage": 42, "limit": 200}
        consumption.set.assert_called_once_with(42)
        limit.set.assert_called_once_with(200)

    def test_raises_and_flushes_logs_on_error(self, urlopen: MagicMock):
        urlopen.side_effect = _http_error(500, "Internal Server Error")
        with (
            patch.dict(os.environ, {"LINE_CHANNEL_TOKEN": "token"}),
            patch(f"{MODULE}.flush_logs") as flush,
        ):
            with pytest.raises(QuotaError):
                lambda_handler({}, None)
        flush.assert_called_once()


class TestFlushLogs:
    def test_flushes_sdk_logger_provider(self):
        provider = MagicMock(spec=LoggerProvider)
        with patch(f"{MODULE}.get_logger_provider", return_value=provider):
            lambda_function.flush_logs()
        provider.force_flush.assert_called_once_with(
            timeout_millis=lambda_function.LOG_FLUSH_TIMEOUT_MILLIS
        )

    def test_skips_when_sdk_is_not_configured(self):
        # SDK が設定されていないときは、API の ProxyLoggerProvider が返る
        with patch(f"{MODULE}.get_logger_provider", return_value=ProxyLoggerProvider()):
            lambda_function.flush_logs()
