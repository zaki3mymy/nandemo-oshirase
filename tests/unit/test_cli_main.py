"""Tests for oshirase_cli.main (AWS calls are stubbed with botocore Stubber)."""

import io
import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber

from oshirase_cli.main import (
    SCHEDULE_ARN_PLACEHOLDER,
    SCHEDULER_EVENT_SOURCE,
    Config,
    ReminderService,
    main,
)

ACCOUNT = "123456789012"
GROUP = "prod-nandemo-oshirase-reminders"
FUNCTION_ARN = f"arn:aws:lambda:ap-northeast-1:{ACCOUNT}:function:prod-nandemo-oshirase-function"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/prod-nandemo-oshirase-scheduler-role"


@dataclass
class Stubs:
    service: ReminderService
    scheduler: Stubber
    lambda_: Stubber
    sts: Stubber

    def expect_account(self) -> None:
        self.sts.add_response(
            "get_caller_identity",
            {"Account": ACCOUNT, "UserId": "u", "Arn": f"arn:aws:iam::{ACCOUNT}:user/u"},
        )


def _client(name: str) -> Any:
    return boto3.client(
        name,
        region_name="ap-northeast-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )


@pytest.fixture
def stubs() -> Iterator[Stubs]:
    scheduler, lambda_client, sts = _client("scheduler"), _client("lambda"), _client("sts")
    config = Config(
        env="prod", project="nandemo-oshirase", region="ap-northeast-1", timezone="Asia/Tokyo"
    )
    service = ReminderService(config, scheduler, lambda_client, sts)
    with Stubber(scheduler) as s1, Stubber(lambda_client) as s2, Stubber(sts) as s3:
        yield Stubs(service, s1, s2, s3)
        s1.assert_no_pending_responses()
        s2.assert_no_pending_responses()
        s3.assert_no_pending_responses()


def input_json(messages: list[str]) -> str:
    return json.dumps(
        {
            "source": SCHEDULER_EVENT_SOURCE,
            "messages": messages,
            "schedule_arn": SCHEDULE_ARN_PLACEHOLDER,
        },
        ensure_ascii=False,
    )


def schedule_params(
    name: str, expr: str, messages: list[str], state: str = "ENABLED"
) -> dict[str, Any]:
    return {
        "Name": name,
        "GroupName": GROUP,
        "ScheduleExpression": expr,
        "ScheduleExpressionTimezone": "Asia/Tokyo",
        "State": state,
        "FlexibleTimeWindow": {"Mode": "OFF"},
        "Target": {
            "Arn": FUNCTION_ARN,
            "RoleArn": ROLE_ARN,
            "Input": input_json(messages),
            "RetryPolicy": {"MaximumRetryAttempts": 3, "MaximumEventAgeInSeconds": 3600},
        },
    }


def get_response(
    name: str, expr: str, messages: list[str], state: str = "ENABLED", **overrides: Any
) -> dict[str, Any]:
    res: dict[str, Any] = {
        "Name": name,
        "GroupName": GROUP,
        "ScheduleExpression": expr,
        "ScheduleExpressionTimezone": "Asia/Tokyo",
        "State": state,
        "FlexibleTimeWindow": {"Mode": "OFF"},
        "Target": {"Arn": FUNCTION_ARN, "RoleArn": ROLE_ARN, "Input": input_json(messages)},
    }
    res.update(overrides)
    return res


def expect_get(stubs: Stubs, name: str, response: dict[str, Any]) -> None:
    stubs.scheduler.add_response("get_schedule", response, {"Name": name, "GroupName": GROUP})


def expect_not_found(stubs: Stubs, method: str, name: str) -> None:
    stubs.scheduler.add_client_error(
        method,
        service_error_code="ResourceNotFoundException",
        expected_params={"Name": name, "GroupName": GROUP},
    )


class TestAdd:
    def test_weekly(self, stubs, capsys):
        stubs.expect_account()
        stubs.scheduler.add_response(
            "create_schedule",
            {"ScheduleArn": "arn"},
            schedule_params("gomi", "cron(0 21 ? * MON *)", ["明日は燃えるゴミです"]),
        )

        code = main(
            ["add", "gomi", "--weekly", "mon", "--at", "21:00", "-m", "明日は燃えるゴミです"],
            stubs.service,
        )

        assert code == 0
        out = capsys.readouterr().out
        assert "追加しました" in out
        assert "gomi  [有効]  毎週月曜 21:00" in out
        assert "明日は燃えるゴミです" in out

    def test_multiple_messages_and_blank_removed(self, stubs):
        stubs.expect_account()
        stubs.scheduler.add_response(
            "create_schedule",
            {"ScheduleArn": "arn"},
            schedule_params("a", "cron(30 7 * * ? *)", ["x", "y"]),
        )

        code = main(
            ["add", "a", "--daily", "--at", "7:30", "-m", "x", "-m", " ", "-m", "y"],
            stubs.service,
        )

        assert code == 0

    @pytest.mark.parametrize("cron_arg", ["0 8 1 * ? *", "cron(0 8 1 * ? *)"])
    def test_cron(self, stubs, cron_arg):
        stubs.expect_account()
        stubs.scheduler.add_response(
            "create_schedule",
            {"ScheduleArn": "arn"},
            schedule_params("c", "cron(0 8 1 * ? *)", ["m"]),
        )

        assert main(["add", "c", "--cron", cron_arg, "-m", "m"], stubs.service) == 0

    def test_conflict(self, stubs, capsys):
        stubs.expect_account()
        stubs.scheduler.add_client_error("create_schedule", service_error_code="ConflictException")

        code = main(["add", "gomi", "--daily", "--at", "21:00", "-m", "x"], stubs.service)

        assert code == 1
        assert "既に存在します" in capsys.readouterr().err

    def test_other_aws_error(self, stubs, capsys):
        stubs.expect_account()
        stubs.scheduler.add_client_error(
            "create_schedule", service_error_code="AccessDeniedException", service_message="nope"
        )

        code = main(["add", "gomi", "--daily", "--at", "21:00", "-m", "x"], stubs.service)

        assert code == 1
        assert "AWSエラー: AccessDeniedException: nope" in capsys.readouterr().err

    @pytest.mark.parametrize(
        ("argv", "message"),
        [
            (["add", "ゴミ", "--daily", "--at", "21:00", "-m", "x"], "名前は英数字"),
            (["add", "a", "--daily", "-m", "x"], "--at で送信時刻"),
            (["add", "a", "--at", "21:00", "-m", "x"], "いずれかを指定"),
            (["add", "a", "--cron", "0 8 1 * ? *", "--at", "21:00", "-m", "x"], "同時に指定"),
            (["add", "a", "--daily", "--at", "21:00", "-m", " "], "メッセージを1つ以上"),
        ],
    )
    def test_user_errors(self, stubs, capsys, argv, message):
        assert main(argv, stubs.service) == 1
        assert message in capsys.readouterr().err

    def test_value_error_exit_code_2(self, stubs, capsys):
        assert main(["add", "a", "--daily", "--at", "25:00", "-m", "x"], stubs.service) == 2
        assert "範囲外" in capsys.readouterr().err


class TestList:
    def test_empty(self, stubs, capsys):
        stubs.scheduler.add_response("list_schedules", {"Schedules": []}, {"GroupName": GROUP})

        assert main(["list"], stubs.service) == 0
        assert "登録されていません" in capsys.readouterr().out

    def test_paginated_and_sorted(self, stubs, capsys):
        stubs.scheduler.add_response(
            "list_schedules",
            {"Schedules": [{"Name": "z"}], "NextToken": "t"},
            {"GroupName": GROUP},
        )
        stubs.scheduler.add_response(
            "list_schedules", {"Schedules": [{"Name": "a"}]}, {"GroupName": GROUP, "NextToken": "t"}
        )
        expect_get(stubs, "a", get_response("a", "cron(30 7 * * ? *)", ["朝"]))
        expect_get(
            stubs,
            "z",
            get_response("z", "cron(0 21 ? * 4#2 *)", ["夜"], state="DISABLED"),
        )

        assert main(["list"], stubs.service) == 0
        out = capsys.readouterr().out
        assert out.index("a  [有効]  毎日 07:30") < out.index("z  [停止中]  毎月第2水曜 21:00")


class TestShow:
    def test_show(self, stubs, capsys):
        expect_get(stubs, "a", get_response("a", "cron(30 7 * * ? *)", ["朝"]))

        assert main(["show", "a"], stubs.service) == 0
        assert "式: cron(30 7 * * ? *)  タイムゾーン: Asia/Tokyo" in capsys.readouterr().out

    def test_missing_input_and_timezone(self, stubs, capsys):
        res = get_response("a", "cron(30 7 * * ? *)", [])
        del res["ScheduleExpressionTimezone"]
        del res["Target"]["Input"]
        expect_get(stubs, "a", res)

        assert main(["show", "a"], stubs.service) == 0
        assert "a  [有効]  毎日 07:30 (UTC)" in capsys.readouterr().out

    def test_not_found(self, stubs, capsys):
        expect_not_found(stubs, "get_schedule", "a")

        assert main(["show", "a"], stubs.service) == 1
        assert "見つかりません" in capsys.readouterr().err

    def test_other_error(self, stubs, capsys):
        stubs.scheduler.add_client_error("get_schedule", service_error_code="ThrottlingException")

        assert main(["show", "a"], stubs.service) == 1
        assert "ThrottlingException" in capsys.readouterr().err


class TestUpdate:
    def _expect_current(self, stubs):
        expect_get(stubs, "gomi", get_response("gomi", "cron(0 21 ? * MON *)", ["燃える"]))

    def test_at_only(self, stubs, capsys):
        self._expect_current(stubs)
        stubs.expect_account()
        stubs.scheduler.add_response(
            "update_schedule",
            {"ScheduleArn": "arn"},
            schedule_params("gomi", "cron(30 20 ? * MON *)", ["燃える"]),
        )

        assert main(["update", "gomi", "--at", "20:30"], stubs.service) == 0
        assert "毎週月曜 20:30" in capsys.readouterr().out

    def test_weekly_and_message(self, stubs):
        self._expect_current(stubs)
        stubs.expect_account()
        stubs.scheduler.add_response(
            "update_schedule",
            {"ScheduleArn": "arn"},
            schedule_params("gomi", "cron(0 20 ? * TUE *)", ["新しい"]),
        )

        argv = ["update", "gomi", "--weekly", "tue", "--at", "20:00", "-m", "新しい"]
        assert main(argv, stubs.service) == 0

    def test_keeps_disabled_state(self, stubs):
        expect_get(
            stubs,
            "gomi",
            get_response("gomi", "cron(0 21 ? * MON *)", ["燃える"], state="DISABLED"),
        )
        stubs.expect_account()
        stubs.scheduler.add_response(
            "update_schedule",
            {"ScheduleArn": "arn"},
            schedule_params("gomi", "cron(0 21 ? * MON *)", ["変更"], state="DISABLED"),
        )

        assert main(["update", "gomi", "-m", "変更"], stubs.service) == 0

    def test_no_change(self, stubs, capsys):
        self._expect_current(stubs)

        assert main(["update", "gomi"], stubs.service) == 1
        assert "変更内容がありません" in capsys.readouterr().err

    def test_nth_without_weekly(self, stubs, capsys):
        self._expect_current(stubs)

        assert main(["update", "gomi", "--nth", "2"], stubs.service) == 1
        assert "--nth は --weekly" in capsys.readouterr().err

    def test_at_on_custom_cron(self, stubs, capsys):
        expect_get(stubs, "x", get_response("x", "cron(0/5 * * * ? *)", ["m"]))

        assert main(["update", "x", "--at", "20:00"], stubs.service) == 1
        assert "--at だけでは変更できません" in capsys.readouterr().err

    def test_not_found(self, stubs):
        expect_not_found(stubs, "get_schedule", "gomi")

        assert main(["update", "gomi", "--at", "20:00"], stubs.service) == 1


class TestEnableDisable:
    @pytest.mark.parametrize(
        ("cmd", "before", "after", "label"),
        [
            ("disable", "ENABLED", "DISABLED", "停止しました"),
            ("enable", "DISABLED", "ENABLED", "有効にしました"),
        ],
    )
    def test_toggle(self, stubs, capsys, cmd, before, after, label):
        expect_get(stubs, "a", get_response("a", "cron(30 7 * * ? *)", ["朝"], state=before))
        stubs.expect_account()
        stubs.scheduler.add_response(
            "update_schedule",
            {"ScheduleArn": "arn"},
            schedule_params("a", "cron(30 7 * * ? *)", ["朝"], state=after),
        )

        assert main([cmd, "a"], stubs.service) == 0
        assert label in capsys.readouterr().out


class TestDelete:
    def test_delete(self, stubs, capsys):
        stubs.scheduler.add_response("delete_schedule", {}, {"Name": "a", "GroupName": GROUP})

        assert main(["delete", "a"], stubs.service) == 0
        assert "削除しました: a" in capsys.readouterr().out

    def test_not_found(self, stubs, capsys):
        expect_not_found(stubs, "delete_schedule", "a")

        assert main(["delete", "a"], stubs.service) == 1
        assert "見つかりません" in capsys.readouterr().err

    def test_other_error(self, stubs, capsys):
        stubs.scheduler.add_client_error("delete_schedule", service_error_code="ConflictException")

        assert main(["delete", "a"], stubs.service) == 1
        assert "AWSエラー: ConflictException" in capsys.readouterr().err


class TestSend:
    def _expect_invoke(self, stubs, body: bytes, function_error: str | None = None):
        response: dict[str, Any] = {
            "StatusCode": 200,
            "Payload": StreamingBody(io.BytesIO(body), len(body)),
        }
        if function_error:
            response["FunctionError"] = function_error
        stubs.lambda_.add_response(
            "invoke",
            response,
            {
                "FunctionName": "prod-nandemo-oshirase-function",
                "InvocationType": "RequestResponse",
                "Payload": ANY,
            },
        )

    def test_send(self, stubs, capsys):
        expect_get(stubs, "a", get_response("a", "cron(30 7 * * ? *)", ["朝"]))
        self._expect_invoke(stubs, b'{"statusCode": 200}')

        assert main(["send", "a"], stubs.service) == 0
        assert "送信しました" in capsys.readouterr().out

    def test_send_failure(self, stubs, capsys):
        expect_get(stubs, "a", get_response("a", "cron(30 7 * * ? *)", ["朝"]))
        self._expect_invoke(stubs, b'{"errorMessage": "boom"}', function_error="Unhandled")

        assert main(["send", "a"], stubs.service) == 1
        assert "送信に失敗しました" in capsys.readouterr().err


class TestAccountIdCached:
    def test_sts_called_once(self, stubs):
        stubs.expect_account()

        assert stubs.service.role_arn == ROLE_ARN
        assert stubs.service.function_arn == FUNCTION_ARN


class TestBotoCoreError:
    def test_no_credentials(self, stubs, capsys, monkeypatch):
        from botocore.exceptions import NoCredentialsError

        def raise_no_credentials():
            raise NoCredentialsError()

        monkeypatch.setattr(stubs.service, "list_all", raise_no_credentials)

        assert main(["list"], stubs.service) == 1
        assert "認証情報" in capsys.readouterr().err
