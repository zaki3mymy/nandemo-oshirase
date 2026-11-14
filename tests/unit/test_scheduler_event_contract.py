"""Contract tests between the oshirase CLI and the Lambda for scheduled events.

The CLI builds the event that EventBridge Scheduler passes to the Lambda
(Target.Input). If the two sides disagree on its shape, scheduled notifications
silently fall through to the /notify handler and fail, so check that the event the
CLI builds is handled by the Lambda as a scheduled notification.
"""

import json
import os
from typing import Any
from unittest.mock import patch

from nandemo_oshirase import lambda_function
from oshirase_cli import main as cli

ENV = {"LINE_CHANNEL_TOKEN": "test_token", "LINE_USER_ID": "test_user"}
SCHEDULE_ARN = "arn:aws:scheduler:ap-northeast-1:123456789012:schedule/g/gomi"


def scheduler_event(messages: list[str]) -> Any:
    """Return the event the Lambda receives for a schedule created by the CLI.

    EventBridge Scheduler replaces the context attribute placeholder in the input
    with the actual schedule ARN before invoking the target.
    """
    raw = cli.build_input(messages).replace(cli.SCHEDULE_ARN_PLACEHOLDER, SCHEDULE_ARN)
    return json.loads(raw)


def test_event_source_constants_match():
    assert cli.SCHEDULER_EVENT_SOURCE == lambda_function.SCHEDULER_EVENT_SOURCE


def test_cli_input_is_recognized_as_scheduled_event():
    assert lambda_function.is_scheduled_event(scheduler_event(["明日は燃えるゴミです"]))


def test_cli_input_is_delivered_by_scheduled_handler():
    event = scheduler_event(["明日は燃えるゴミです", "資源ごみも"])

    with patch.dict(os.environ, ENV, clear=True):
        with (
            patch.object(lambda_function, "push_messages") as mock_push,
            patch.object(
                lambda_function, "handle_notify", side_effect=AssertionError("not scheduled")
            ),
        ):
            mock_push.return_value = {"statusCode": 200, "body": "{}"}
            result = lambda_function.lambda_handler(event, None)

    assert result["statusCode"] == 200
    mock_push.assert_called_once_with(
        [
            {"type": "text", "text": "明日は燃えるゴミです"},
            {"type": "text", "text": "資源ごみも"},
        ],
        "test_token",
        "test_user",
        retry_key=None,
    )


def test_cli_input_passes_schedule_arn_to_lambda():
    event = scheduler_event(["hello"])

    assert event["schedule_arn"] == SCHEDULE_ARN
