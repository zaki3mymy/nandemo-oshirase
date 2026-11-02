"""Tests for handle_webhook function."""

import base64
import json
import logging

import pytest

from nandemo_oshirase.lambda_function import LambdaEvent, handle_webhook


def _event(body: dict) -> LambdaEvent:
    return {"body": json.dumps(body)}


def _event_b64(body: dict) -> LambdaEvent:
    encoded = base64.b64encode(json.dumps(body).encode()).decode()
    return {"body": encoded, "isBase64Encoded": True}


class TestHandleWebhookLogsSourceIds:
    """Verify that source IDs are logged for each source type."""

    def test_logs_user_event(self, caplog: pytest.LogCaptureFixture):
        event = _event({"events": [{"source": {"type": "user", "userId": "U123"}}]})
        with caplog.at_level(logging.INFO, logger="nandemo_oshirase.lambda_function"):
            handle_webhook(event)
        assert caplog.messages == ["Webhook source: type=user userId=U123"]

    def test_logs_group_event(self, caplog: pytest.LogCaptureFixture):
        event = _event(
            {"events": [{"source": {"type": "group", "groupId": "C456", "userId": "U789"}}]}
        )
        with caplog.at_level(logging.INFO, logger="nandemo_oshirase.lambda_function"):
            handle_webhook(event)
        assert caplog.messages == ["Webhook source: type=group groupId=C456 userId=U789"]

    def test_logs_room_event(self, caplog: pytest.LogCaptureFixture):
        event = _event(
            {"events": [{"source": {"type": "room", "roomId": "R111", "userId": "U222"}}]}
        )
        with caplog.at_level(logging.INFO, logger="nandemo_oshirase.lambda_function"):
            handle_webhook(event)
        assert caplog.messages == ["Webhook source: type=room roomId=R111 userId=U222"]

    def test_logs_unknown_source_type(self, caplog: pytest.LogCaptureFixture):
        event = _event({"events": [{"source": {"type": "future_type"}}]})
        with caplog.at_level(logging.INFO, logger="nandemo_oshirase.lambda_function"):
            handle_webhook(event)
        assert caplog.messages == [
            "Webhook source: type=future_type source={'type': 'future_type'}"
        ]

    def test_logs_multiple_events(self, caplog: pytest.LogCaptureFixture):
        event = _event(
            {
                "events": [
                    {"source": {"type": "user", "userId": "U001"}},
                    {"source": {"type": "group", "groupId": "C002", "userId": "U003"}},
                    {"source": {"type": "room", "roomId": "R004", "userId": "U005"}},
                ]
            }
        )
        with caplog.at_level(logging.INFO, logger="nandemo_oshirase.lambda_function"):
            handle_webhook(event)
        assert caplog.messages == [
            "Webhook source: type=user userId=U001",
            "Webhook source: type=group groupId=C002 userId=U003",
            "Webhook source: type=room roomId=R004 userId=U005",
        ]

    def test_logs_warning_on_empty_body(self, caplog: pytest.LogCaptureFixture):
        with caplog.at_level(logging.WARNING, logger="nandemo_oshirase.lambda_function"):
            handle_webhook({})
        assert caplog.messages == ["Webhook received empty body"]

    def test_logs_warning_on_invalid_json(self, caplog: pytest.LogCaptureFixture):
        with caplog.at_level(logging.WARNING, logger="nandemo_oshirase.lambda_function"):
            handle_webhook({"body": "not-json"})
        assert caplog.messages == [
            "Webhook received invalid JSON: Expecting value: line 1 column 1 (char 0)"
        ]


class TestHandleWebhookAlwaysReturns200:
    """Webhook endpoint must always return 200 to satisfy LINE platform."""

    def test_returns_200_with_group_event(self):
        event = _event(
            {"events": [{"source": {"type": "group", "groupId": "C456", "userId": "U789"}}]}
        )
        assert handle_webhook(event)["statusCode"] == 200

    def test_returns_200_with_empty_body(self):
        assert handle_webhook({})["statusCode"] == 200

    def test_returns_200_with_invalid_json(self):
        assert handle_webhook({"body": "not-json"})["statusCode"] == 200

    def test_returns_200_with_empty_events(self):
        assert handle_webhook(_event({"events": []}))["statusCode"] == 200

    def test_returns_200_with_base64_encoded_body(self):
        event = _event_b64(
            {"events": [{"source": {"type": "group", "groupId": "C999", "userId": "U000"}}]}
        )
        assert handle_webhook(event)["statusCode"] == 200

    def test_returns_200_with_event_missing_source(self):
        assert handle_webhook(_event({"events": [{}]}))["statusCode"] == 200
