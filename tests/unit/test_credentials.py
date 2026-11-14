"""Tests for load_line_credentials (environment variables and SSM Parameter Store)."""

import os
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError
from botocore.stub import Stubber

from nandemo_oshirase import lambda_function
from nandemo_oshirase.lambda_function import (
    CREDENTIALS_CACHE_TTL_SECONDS,
    LineCredentials,
    MissingCredentialError,
    load_line_credentials,
)

TOKEN_PARAM = "/app/nandemo_oshirase/dev/line_channel_token"
USER_PARAM = "/app/nandemo_oshirase/dev/line_user_id"
PARAM_ENV = {"LINE_CHANNEL_TOKEN_PARAM": TOKEN_PARAM, "LINE_USER_ID_PARAM": USER_PARAM}


def _param(name: str, value: str) -> dict[str, Any]:
    return {"Name": name, "Type": "SecureString", "Value": value, "Version": 1}


@pytest.fixture
def ssm() -> Iterator[Stubber]:
    client = boto3.client(
        "ssm",
        region_name="ap-northeast-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    lambda_function.clear_credentials_cache()
    with patch.object(lambda_function, "_get_ssm_client", return_value=client):
        with Stubber(client) as stubber:
            yield stubber
            stubber.assert_no_pending_responses()
    lambda_function.clear_credentials_cache()


def expect_get_parameters(
    ssm: Stubber,
    names: list[str],
    params: list[dict[str, Any]],
    invalid: list[str] | None = None,
) -> None:
    response: dict[str, Any] = {"Parameters": params}
    if invalid:
        response["InvalidParameters"] = invalid
    ssm.add_response("get_parameters", response, {"Names": names, "WithDecryption": True})


class TestFromEnvironment:
    def test_direct_values(self):
        env = {"LINE_CHANNEL_TOKEN": "token", "LINE_USER_ID": "user"}
        with patch.dict(os.environ, env, clear=True):
            assert load_line_credentials() == LineCredentials("token", "user")

    def test_direct_value_takes_precedence_over_param(self, ssm):
        env = {**PARAM_ENV, "LINE_CHANNEL_TOKEN": "direct-token"}
        expect_get_parameters(ssm, [USER_PARAM], [_param(USER_PARAM, "ssm-user")])

        with patch.dict(os.environ, env, clear=True):
            assert load_line_credentials() == LineCredentials("direct-token", "ssm-user")


class TestFromSsm:
    def test_reads_both_in_one_call(self, ssm):
        expect_get_parameters(
            ssm,
            sorted([TOKEN_PARAM, USER_PARAM]),
            [_param(TOKEN_PARAM, "ssm-token"), _param(USER_PARAM, "ssm-user")],
        )

        with patch.dict(os.environ, PARAM_ENV, clear=True):
            assert load_line_credentials() == LineCredentials("ssm-token", "ssm-user")

    def test_cached_within_ttl(self, ssm):
        expect_get_parameters(
            ssm,
            sorted([TOKEN_PARAM, USER_PARAM]),
            [_param(TOKEN_PARAM, "ssm-token"), _param(USER_PARAM, "ssm-user")],
        )

        with patch.dict(os.environ, PARAM_ENV, clear=True):
            with patch.object(lambda_function.time, "monotonic", return_value=1000.0):
                load_line_credentials()
            with patch.object(
                lambda_function.time,
                "monotonic",
                return_value=1000.0 + CREDENTIALS_CACHE_TTL_SECONDS - 1,
            ):
                # 2回目は SSM を呼ばない（Stubber に応答を1つしか積んでいない）
                assert load_line_credentials() == LineCredentials("ssm-token", "ssm-user")

    def test_reloaded_after_ttl(self, ssm):
        names = sorted([TOKEN_PARAM, USER_PARAM])
        expect_get_parameters(
            ssm, names, [_param(TOKEN_PARAM, "old-token"), _param(USER_PARAM, "user")]
        )
        expect_get_parameters(
            ssm, names, [_param(TOKEN_PARAM, "new-token"), _param(USER_PARAM, "user")]
        )

        with patch.dict(os.environ, PARAM_ENV, clear=True):
            with patch.object(lambda_function.time, "monotonic", return_value=1000.0):
                assert load_line_credentials().channel_token == "old-token"
            with patch.object(
                lambda_function.time,
                "monotonic",
                return_value=1000.0 + CREDENTIALS_CACHE_TTL_SECONDS,
            ):
                assert load_line_credentials().channel_token == "new-token"

    def test_same_parameter_for_both_is_fetched_once(self, ssm):
        env = {"LINE_CHANNEL_TOKEN_PARAM": TOKEN_PARAM, "LINE_USER_ID_PARAM": TOKEN_PARAM}
        expect_get_parameters(ssm, [TOKEN_PARAM], [_param(TOKEN_PARAM, "same")])

        with patch.dict(os.environ, env, clear=True):
            assert load_line_credentials() == LineCredentials("same", "same")


class TestFailures:
    @pytest.mark.parametrize(
        ("env", "message"),
        [
            ({"LINE_USER_ID": "u"}, "LINE_CHANNEL_TOKEN or LINE_CHANNEL_TOKEN_PARAM"),
            ({"LINE_CHANNEL_TOKEN": "t"}, "LINE_USER_ID or LINE_USER_ID_PARAM"),
        ],
    )
    def test_not_configured(self, env, message):
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(MissingCredentialError, match=message):
                load_line_credentials()

    def test_parameter_not_found(self, ssm):
        expect_get_parameters(
            ssm,
            sorted([TOKEN_PARAM, USER_PARAM]),
            [_param(USER_PARAM, "user")],
            invalid=[TOKEN_PARAM],
        )

        with patch.dict(os.environ, PARAM_ENV, clear=True):
            with pytest.raises(MissingCredentialError, match="SSM parameter not found"):
                load_line_credentials()

    def test_parameter_empty(self, ssm):
        expect_get_parameters(
            ssm,
            sorted([TOKEN_PARAM, USER_PARAM]),
            [_param(TOKEN_PARAM, ""), _param(USER_PARAM, "user")],
        )

        with patch.dict(os.environ, PARAM_ENV, clear=True):
            with pytest.raises(MissingCredentialError, match="SSM parameter is empty"):
                load_line_credentials()

    def test_access_denied_does_not_leak_details(self, ssm):
        ssm.add_client_error(
            "get_parameters",
            service_error_code="AccessDeniedException",
            service_message="User: arn:aws:sts::123456789012:assumed-role/x is not authorized",
        )

        with patch.dict(os.environ, PARAM_ENV, clear=True):
            with pytest.raises(MissingCredentialError) as excinfo:
                load_line_credentials()

        assert "AccessDeniedException" in str(excinfo.value)
        assert "123456789012" not in str(excinfo.value)

    def test_connection_error(self, ssm):
        with patch.dict(os.environ, PARAM_ENV, clear=True):
            with patch.object(
                lambda_function._get_ssm_client(),
                "get_parameters",
                side_effect=EndpointConnectionError(endpoint_url="https://ssm"),
            ):
                with pytest.raises(MissingCredentialError, match="EndpointConnectionError"):
                    load_line_credentials()

    def test_failure_is_not_cached(self, ssm):
        names = sorted([TOKEN_PARAM, USER_PARAM])
        ssm.add_client_error("get_parameters", service_error_code="ThrottlingException")
        expect_get_parameters(
            ssm, names, [_param(TOKEN_PARAM, "token"), _param(USER_PARAM, "user")]
        )

        with patch.dict(os.environ, PARAM_ENV, clear=True):
            with pytest.raises(MissingCredentialError):
                load_line_credentials()
            assert load_line_credentials() == LineCredentials("token", "user")


class TestHandlerIntegration:
    def test_notify_returns_500_when_ssm_fails(self, ssm):
        ssm.add_client_error("get_parameters", service_error_code="AccessDeniedException")

        with patch.dict(os.environ, PARAM_ENV, clear=True):
            result = lambda_function.lambda_handler({"body": '{"message": "hi"}'}, None)

        assert result["statusCode"] == 500
        assert "AccessDeniedException" in result["body"]


class TestGetSsmClient:
    def test_client_is_created_once(self):
        lambda_function._ssm_client = None
        try:
            with patch("boto3.client") as client_factory:
                first = lambda_function._get_ssm_client()
                second = lambda_function._get_ssm_client()
            assert first is second
            client_factory.assert_called_once_with("ssm")
        finally:
            lambda_function._ssm_client = None

    def test_client_is_created_in_its_own_span(self):
        # コールドスタートでのクライアントの作成を、SSM の処理と区別できるよう別の span にする
        lambda_function._ssm_client = None
        try:
            with (
                patch("boto3.client"),
                patch.object(lambda_function, "_tracer") as tracer,
            ):
                lambda_function._get_ssm_client()
                lambda_function._get_ssm_client()
            tracer.start_as_current_span.assert_called_once_with("create_ssm_client")
        finally:
            lambda_function._ssm_client = None
