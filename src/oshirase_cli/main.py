"""``oshirase`` command: manage scheduled LINE notifications on EventBridge Scheduler.

Schedules (time and message) live only in AWS, never in this repository.
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from oshirase_cli import cron

# Lambda側（nandemo_oshirase.lambda_function.SCHEDULER_EVENT_SOURCE）と一致させること
SCHEDULER_EVENT_SOURCE = "nandemo-oshirase.scheduler"
# EventBridge Scheduler がinvoke時にスケジュールARNへ置き換えるプレースホルダ
SCHEDULE_ARN_PLACEHOLDER = "<aws.scheduler.schedule-arn>"

_NAME_PATTERN = re.compile(r"^[0-9a-zA-Z_.-]{1,64}$")


class CliError(Exception):
    """User-facing error."""


@dataclass(frozen=True)
class Config:
    env: str
    project: str
    region: str
    timezone: str

    @property
    def prefix(self) -> str:
        return f"{self.env}-{self.project}"

    @property
    def group_name(self) -> str:
        return f"{self.prefix}-reminders"

    @property
    def function_name(self) -> str:
        return f"{self.prefix}-function"

    @property
    def role_name(self) -> str:
        return f"{self.prefix}-scheduler-role"


@dataclass(frozen=True)
class Reminder:
    name: str
    expression: str
    timezone: str
    enabled: bool
    messages: list[str]

    @property
    def description(self) -> str:
        return cron.describe(self.expression)


def validate_name(name: str) -> str:
    if not _NAME_PATTERN.match(name):
        raise CliError(f"名前は英数字と - _ . のみ、64文字以内で指定してください: {name!r}")
    return name


def validate_messages(messages: list[str]) -> list[str]:
    cleaned = [m for m in messages if m.strip()]
    if not cleaned:
        raise CliError("メッセージを1つ以上指定してください（-m）")
    return cleaned


def build_input(messages: list[str]) -> str:
    return json.dumps(
        {
            "source": SCHEDULER_EVENT_SOURCE,
            "messages": messages,
            "schedule_arn": SCHEDULE_ARN_PLACEHOLDER,
        },
        ensure_ascii=False,
    )


class ReminderService:
    """Thin wrapper around EventBridge Scheduler / Lambda for one environment."""

    def __init__(self, config: Config, scheduler: Any, lambda_client: Any, sts: Any) -> None:
        self.config = config
        self.scheduler = scheduler
        self.lambda_client = lambda_client
        self.sts = sts
        self._account_id: str | None = None

    @property
    def account_id(self) -> str:
        if self._account_id is None:
            self._account_id = self.sts.get_caller_identity()["Account"]
        return self._account_id

    @property
    def function_arn(self) -> str:
        return (
            f"arn:aws:lambda:{self.config.region}:{self.account_id}"
            f":function:{self.config.function_name}"
        )

    @property
    def role_arn(self) -> str:
        return f"arn:aws:iam::{self.account_id}:role/{self.config.role_name}"

    def _params(
        self, name: str, expression: str, timezone: str, enabled: bool, messages: list[str]
    ) -> dict[str, Any]:
        return {
            "Name": name,
            "GroupName": self.config.group_name,
            "ScheduleExpression": expression,
            "ScheduleExpressionTimezone": timezone,
            "State": "ENABLED" if enabled else "DISABLED",
            "FlexibleTimeWindow": {"Mode": "OFF"},
            "Target": {
                "Arn": self.function_arn,
                "RoleArn": self.role_arn,
                "Input": build_input(messages),
                # Schedulerのリトライは「invoke自体の失敗」が対象。Lambdaは非同期invokeなので
                # 二重送信にはならない。送信失敗時のリトライはLambda側の設定で制御する。
                "RetryPolicy": {"MaximumRetryAttempts": 3, "MaximumEventAgeInSeconds": 3600},
            },
        }

    def _not_found(self, name: str) -> CliError:
        return CliError(f"お知らせ {name!r} が見つかりません（環境: {self.config.env}）")

    def get(self, name: str) -> Reminder:
        try:
            res = self.scheduler.get_schedule(Name=name, GroupName=self.config.group_name)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                raise self._not_found(name) from e
            raise
        payload = json.loads(res["Target"].get("Input") or "{}")
        return Reminder(
            name=res["Name"],
            expression=res["ScheduleExpression"],
            timezone=res.get("ScheduleExpressionTimezone", "UTC"),
            enabled=res.get("State") == "ENABLED",
            messages=list(payload.get("messages", [])),
        )

    def list_all(self) -> list[Reminder]:
        names: list[str] = []
        paginator = self.scheduler.get_paginator("list_schedules")
        for page in paginator.paginate(GroupName=self.config.group_name):
            names.extend(s["Name"] for s in page["Schedules"])
        return [self.get(n) for n in sorted(names)]

    def add(self, name: str, expression: str, messages: list[str]) -> Reminder:
        reminder = Reminder(name, expression, self.config.timezone, True, messages)
        try:
            self.scheduler.create_schedule(
                **self._params(name, expression, self.config.timezone, True, messages)
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConflictException":
                raise CliError(
                    f"お知らせ {name!r} は既に存在します。変更する場合は update を使ってください"
                ) from e
            raise
        return reminder

    def save(self, reminder: Reminder) -> Reminder:
        self.scheduler.update_schedule(
            **self._params(
                reminder.name,
                reminder.expression,
                reminder.timezone,
                reminder.enabled,
                reminder.messages,
            )
        )
        return reminder

    def delete(self, name: str) -> None:
        try:
            self.scheduler.delete_schedule(Name=name, GroupName=self.config.group_name)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                raise self._not_found(name) from e
            raise

    def send_now(self, name: str) -> str:
        reminder = self.get(name)
        payload = {
            "source": SCHEDULER_EVENT_SOURCE,
            "messages": reminder.messages,
            "schedule_arn": f"manual:{name}",
        }
        res = self.lambda_client.invoke(
            FunctionName=self.config.function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )
        body = res["Payload"].read().decode("utf-8")
        if res.get("FunctionError"):
            raise CliError(f"送信に失敗しました: {body}")
        return body


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


def _add_schedule_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("いつ送るか")
    freq = group.add_mutually_exclusive_group()
    freq.add_argument("--daily", action="store_true", help="毎日")
    freq.add_argument("--weekly", metavar="DAYS", help="毎週の曜日（例: mon,thu / 月,木）")
    freq.add_argument(
        "--cron",
        metavar="EXPR",
        help='EventBridgeのcron式をそのまま指定（例: "0 8 1 * ? *"）',
    )
    group.add_argument("--nth", type=int, metavar="N", help="--weekly と併用: 第N週（1〜5）")
    group.add_argument("--at", metavar="HH:MM", help="送信時刻（例: 21:00）")


def _expression_from_args(args: argparse.Namespace) -> str:
    if args.cron:
        if args.at or args.nth is not None:
            raise CliError("--cron と --at / --nth は同時に指定できません")
        expr = args.cron.strip()
        return expr if expr.startswith("cron(") else f"cron({expr})"
    if not args.at:
        raise CliError("--at で送信時刻を指定してください")
    if not args.daily and args.weekly is None:
        raise CliError("--daily / --weekly / --cron のいずれかを指定してください")
    return cron.build_expression(args.at, daily=args.daily, weekly=args.weekly, nth=args.nth)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oshirase",
        description="定時お知らせ（EventBridge Scheduler）を管理する",
    )
    parser.add_argument(
        "--env",
        choices=["prod", "dev"],
        default=os.environ.get("OSHIRASE_ENV", "prod"),
        help="対象環境（既定: prod、環境変数 OSHIRASE_ENV でも指定可）",
    )
    parser.add_argument("--profile", help="AWSプロファイル名")
    parser.add_argument("--region", default="ap-northeast-1", help="AWSリージョン")
    parser.add_argument("--project", default="nandemo-oshirase", help=argparse.SUPPRESS)
    parser.add_argument("--timezone", default="Asia/Tokyo", help="タイムゾーン（既定: Asia/Tokyo）")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p = sub.add_parser("add", help="お知らせを追加する")
    p.add_argument("name", help="名前（英数字と - _ .）")
    _add_schedule_options(p)
    p.add_argument(
        "-m", "--message", action="append", required=True, help="メッセージ（複数指定可）"
    )

    p = sub.add_parser("update", help="お知らせを変更する（指定した項目のみ）")
    p.add_argument("name")
    _add_schedule_options(p)
    p.add_argument("-m", "--message", action="append", help="メッセージ（指定すると全置換）")

    sub.add_parser("list", help="お知らせの一覧を表示する")

    for cmd, help_ in [
        ("show", "お知らせの詳細を表示する"),
        ("enable", "お知らせを有効にする"),
        ("disable", "お知らせを一時停止する"),
        ("delete", "お知らせを削除する"),
        ("send", "お知らせを今すぐ送る（動作確認用）"),
    ]:
        p = sub.add_parser(cmd, help=help_)
        p.add_argument("name")

    return parser


def format_reminder(r: Reminder) -> str:
    state = "有効" if r.enabled else "停止中"
    tz = "" if r.timezone == "Asia/Tokyo" else f" ({r.timezone})"
    lines = [f"{r.name}  [{state}]  {r.description}{tz}"]
    lines.extend(f"    {m}" for m in r.messages)
    return "\n".join(lines)


def run(args: argparse.Namespace, service: ReminderService) -> str:
    """Execute a parsed command and return text to print."""
    cmd = args.command

    if cmd == "list":
        reminders = service.list_all()
        if not reminders:
            return f"お知らせは登録されていません（環境: {service.config.env}）"
        return "\n".join(format_reminder(r) for r in reminders)

    name = validate_name(args.name)

    if cmd == "add":
        expression = _expression_from_args(args)
        reminder = service.add(name, expression, validate_messages(args.message))
        return "追加しました:\n" + format_reminder(reminder)

    if cmd == "update":
        current = service.get(name)
        if args.daily or args.weekly is not None or args.cron:
            expression = _expression_from_args(args)
        elif args.nth is not None:
            raise CliError("--nth は --weekly と一緒に指定してください")
        elif args.at:
            try:
                expression = cron.replace_time(current.expression, args.at)
            except ValueError as e:
                raise CliError(str(e)) from e
        else:
            expression = current.expression
        messages = validate_messages(args.message) if args.message else current.messages
        if expression == current.expression and messages == current.messages:
            raise CliError("変更内容がありません（--at / --weekly / -m などを指定してください）")
        reminder = service.save(
            Reminder(name, expression, current.timezone, current.enabled, messages)
        )
        return "変更しました:\n" + format_reminder(reminder)

    if cmd == "show":
        r = service.get(name)
        return f"{format_reminder(r)}\n  式: {r.expression}  タイムゾーン: {r.timezone}"

    if cmd in ("enable", "disable"):
        current = service.get(name)
        enabled = cmd == "enable"
        reminder = service.save(
            Reminder(name, current.expression, current.timezone, enabled, current.messages)
        )
        return ("有効にしました:\n" if enabled else "停止しました:\n") + format_reminder(reminder)

    if cmd == "delete":
        service.delete(name)
        return f"削除しました: {name}"

    # cmd == "send"
    result = service.send_now(name)
    return f"送信しました: {result}"


def create_service(args: argparse.Namespace) -> ReminderService:  # pragma: no cover
    import boto3

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    config = Config(env=args.env, project=args.project, region=args.region, timezone=args.timezone)
    return ReminderService(
        config,
        scheduler=session.client("scheduler"),
        lambda_client=session.client("lambda"),
        sts=session.client("sts"),
    )


def main(argv: list[str] | None = None, service: ReminderService | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        svc = service or create_service(args)
        print(run(args, svc))
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    except CliError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except ClientError as e:
        err = e.response["Error"]
        print(f"AWSエラー: {err.get('Code')}: {err.get('Message')}", file=sys.stderr)
        return 1
    except BotoCoreError as e:
        print(f"AWSエラー: {e}（認証情報や --profile を確認してください）", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
