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

    def test_logs_user_id_for_user_event(self, caplog: pytest.LogCaptureFixture):
        event = _event({"events": [{"source": {"type": "user", "userId": "U123"}}]})
        with caplog.at_level(logging.INFO, logger="nandemo_oshirase.lambda_function"):
            handle_webhook(event)
        assert "U123" in caplog.text

    def test_logs_group_id_for_group_event(self, caplog: pytest.LogCaptureFixture):
        event = _event(
            {"events": [{"source": {"type": "group", "groupId": "C456", "userId": "U789"}}]}
        )
        with caplog.at_level(logging.INFO, logger="nandemo_oshirase.lambda_function"):
            handle_webhook(event)
        assert "C456" in caplog.text

    def test_logs_user_id_for_group_event(self, caplog: pytest.LogCaptureFixture):
        event = _event(
            {"events": [{"source": {"type": "group", "groupId": "C456", "userId": "U789"}}]}
        )
        with caplog.at_level(logging.INFO, logger="nandemo_oshirase.lambda_function"):
            handle_webhook(event)
        assert "U789" in caplog.text

    def test_logs_room_id_for_room_event(self, caplog: pytest.LogCaptureFixture):
        event = _event(
            {"events": [{"source": {"type": "room", "roomId": "R111", "userId": "U222"}}]}
        )
        with caplog.at_level(logging.INFO, logger="nandemo_oshirase.lambda_function"):
            handle_webhook(event)
        assert "R111" in caplog.text

    def test_logs_unknown_source_type(self, caplog: pytest.LogCaptureFixture):
        event = _event({"events": [{"source": {"type": "future_type"}}]})
        with caplog.at_level(logging.INFO, logger="nandemo_oshirase.lambda_function"):
            handle_webhook(event)
        assert "future_type" in caplog.text

    def test_logs_ids_for_multiple_events(self, caplog: pytest.LogCaptureFixture):
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
        assert "U001" in caplog.text
        assert "C002" in caplog.text
        assert "R004" in caplog.text

    def test_logs_warning_on_empty_body(self, caplog: pytest.LogCaptureFixture):
        with caplog.at_level(logging.WARNING, logger="nandemo_oshirase.lambda_function"):
            handle_webhook({})
        assert caplog.records
        assert caplog.records[0].levelno == logging.WARNING

    def test_logs_warning_on_invalid_json(self, caplog: pytest.LogCaptureFixture):
        with caplog.at_level(logging.WARNING, logger="nandemo_oshirase.lambda_function"):
            handle_webhook({"body": "not-json"})
        assert caplog.records
        assert caplog.records[0].levelno == logging.WARNING


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
