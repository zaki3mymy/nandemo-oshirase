"""Tests for invocations from EventBridge Scheduler."""

import json
import os
from typing import Any
from unittest.mock import patch

import pytest

from nandemo_oshirase.lambda_function import (
    SCHEDULER_EVENT_SOURCE,
    ScheduledEvent,
    ScheduledNotificationError,
    lambda_handler,
)

ENV = {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"}


def make_event(messages: list[str], schedule_arn: str | None = None) -> ScheduledEvent:
    event: ScheduledEvent = {"source": SCHEDULER_EVENT_SOURCE, "messages": messages}
    if schedule_arn is not None:
        event["schedule_arn"] = schedule_arn
    return event


class TestScheduledSuccess:
    def test_sends_messages(self):
        event = make_event(["明日は燃えるゴミです"])

        with patch.dict(os.environ, ENV):
            with patch("nandemo_oshirase.lambda_function.push_messages") as mock_push:
                mock_push.return_value = {"statusCode": 200, "body": "{}"}

                result = lambda_handler(event, None)

        assert result == {
            "statusCode": 200,
            "body": json.dumps({"message": "Successfully sent 1 message(s)"}),
        }
        mock_push.assert_called_once_with(
            [{"type": "text", "text": "明日は燃えるゴミです"}], "test_token", "test_user"
        )

    def test_accepts_schedule_arn(self):
        event = make_event(
            ["hello"], schedule_arn="arn:aws:scheduler:ap-northeast-1:123:schedule/g/n"
        )

        with patch.dict(os.environ, ENV):
            with patch("nandemo_oshirase.lambda_function.push_messages") as mock_push:
                mock_push.return_value = {"statusCode": 200, "body": "{}"}

                result = lambda_handler(event, None)

        assert result["statusCode"] == 200

    def test_does_not_route_to_notify_or_webhook(self):
        event = make_event(["hello"])

        with patch.dict(os.environ, ENV):
            with (
                patch("nandemo_oshirase.lambda_function.push_messages") as mock_push,
                patch("nandemo_oshirase.lambda_function.handle_notify") as mock_notify,
                patch("nandemo_oshirase.lambda_function.handle_webhook") as mock_webhook,
            ):
                mock_push.return_value = {"statusCode": 200, "body": "{}"}

                lambda_handler(event, None)

        mock_notify.assert_not_called()
        mock_webhook.assert_not_called()


class TestScheduledFailure:
    def test_raises_when_push_fails(self):
        event = make_event(["hello"])

        with patch.dict(os.environ, ENV):
            with patch("nandemo_oshirase.lambda_function.push_messages") as mock_push:
                mock_push.return_value = {
                    "statusCode": 429,
                    "body": json.dumps({"error": "Too Many Requests"}),
                }

                with pytest.raises(ScheduledNotificationError, match="Too Many Requests"):
                    lambda_handler(event, None)

    def test_raises_when_no_valid_messages(self):
        event = make_event(["", "  "])

        with patch.dict(os.environ, ENV):
            with pytest.raises(ScheduledNotificationError, match="No valid messages"):
                lambda_handler(event, None)

    def test_raises_when_messages_missing(self):
        event: Any = {"source": SCHEDULER_EVENT_SOURCE}

        with patch.dict(os.environ, ENV):
            with pytest.raises(ScheduledNotificationError, match="list of str"):
                lambda_handler(event, None)

    def test_raises_when_messages_not_str(self):
        event: Any = {"source": SCHEDULER_EVENT_SOURCE, "messages": ["ok", 1]}

        with patch.dict(os.environ, ENV):
            with pytest.raises(ScheduledNotificationError, match="list of str"):
                lambda_handler(event, None)

    def test_raises_when_token_missing(self):
        event = make_event(["hello"])

        with patch.dict(os.environ, {"LINE_USER_ID": "test_user"}, clear=True):
            with pytest.raises(ScheduledNotificationError, match="LINE_CHANNEL_TOKEN"):
                lambda_handler(event, None)

    def test_raises_when_user_id_missing(self):
        event = make_event(["hello"])

        with patch.dict(os.environ, {"LINE_CHANNEL_TOKEN": "test_token"}, clear=True):
            with pytest.raises(ScheduledNotificationError, match="LINE_USER_ID"):
                lambda_handler(event, None)


class TestNonSchedulerSource:
    def test_other_source_falls_through_to_notify(self):
        event: Any = {"source": "something-else", "body": json.dumps({"message": "hi"})}

        with patch.dict(os.environ, ENV):
            with patch("nandemo_oshirase.lambda_function.push_messages") as mock_push:
                mock_push.return_value = {"statusCode": 200, "body": "{}"}

                result = lambda_handler(event, None)

        assert result["statusCode"] == 200
