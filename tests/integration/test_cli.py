"""Integration tests running the ``oshirase`` CLI as a subprocess against a moto server.

compose のスタックは不要。`send`（Lambda invoke）は moto では Docker が必要なため対象外。
IAM の信頼ポリシーや PassRole は moto が再現しないため、ここでは検証しない。
"""

import json
import os
import subprocess
import uuid

import boto3
import pytest
from moto.server import ThreadedMotoServer

REGION = "ap-northeast-1"
GROUP_NAME = "dev-nandemo-oshirase-reminders"
ROLE_NAME = "dev-nandemo-oshirase-scheduler-role"


@pytest.fixture(scope="module")
def moto_endpoint():
    server = ThreadedMotoServer(port=0)
    server.start()
    host, port = server.get_host_and_port()
    yield f"http://{host}:{port}"
    server.stop()


@pytest.fixture(scope="module")
def aws_env(moto_endpoint):
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env.update(
        AWS_ENDPOINT_URL=moto_endpoint,
        AWS_ACCESS_KEY_ID="testing",
        AWS_SECRET_ACCESS_KEY="testing",
        AWS_DEFAULT_REGION=REGION,
    )
    return env


@pytest.fixture(scope="module")
def scheduler(moto_endpoint):
    kwargs = dict(
        endpoint_url=moto_endpoint,
        region_name=REGION,
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    boto3.client("iam", **kwargs).create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "scheduler.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ],
            }
        ),
    )
    client = boto3.client("scheduler", **kwargs)
    client.create_schedule_group(Name=GROUP_NAME)
    return client


@pytest.fixture
def oshirase(scheduler, aws_env):
    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["uv", "run", "oshirase", "--env", "dev", *args],
            env=aws_env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    return run


@pytest.fixture
def name():
    # モジュール内でmotoの状態を共有するため、テストごとに一意な名前を使う
    return f"t-{uuid.uuid4().hex[:8]}"


def _get(scheduler, name: str) -> dict:
    return scheduler.get_schedule(Name=name, GroupName=GROUP_NAME)


def _messages(schedule: dict) -> list[str]:
    return json.loads(schedule["Target"]["Input"])["messages"]


def test_add_weekly_then_show_and_list(oshirase, scheduler, name):
    res = oshirase("add", name, "--weekly", "mon,thu", "--at", "21:00", "-m", "薬を飲む")
    assert res.returncode == 0, res.stderr
    assert "追加しました" in res.stdout

    schedule = _get(scheduler, name)
    assert schedule["ScheduleExpression"] == "cron(0 21 ? * MON,THU *)"
    assert schedule["ScheduleExpressionTimezone"] == "Asia/Tokyo"
    assert schedule["State"] == "ENABLED"
    assert _messages(schedule) == ["薬を飲む"]

    show = oshirase("show", name)
    assert show.returncode == 0, show.stderr
    assert name in show.stdout
    assert "薬を飲む" in show.stdout
    assert "cron(0 21 ? * MON,THU *)" in show.stdout

    listed = oshirase("list")
    assert listed.returncode == 0, listed.stderr
    assert name in listed.stdout


def test_add_daily(oshirase, scheduler, name):
    res = oshirase("add", name, "--daily", "--at", "07:30", "-m", "朝")
    assert res.returncode == 0, res.stderr
    assert _get(scheduler, name)["ScheduleExpression"] == "cron(30 7 * * ? *)"


def test_add_nth_weekly(oshirase, scheduler, name):
    res = oshirase("add", name, "--weekly", "sat", "--nth", "2", "--at", "09:00", "-m", "ゴミ")
    assert res.returncode == 0, res.stderr
    assert _get(scheduler, name)["ScheduleExpression"] == "cron(0 9 ? * 7#2 *)"


def test_add_cron(oshirase, scheduler, name):
    res = oshirase("add", name, "--cron", "0 8 1 * ? *", "-m", "月初", "-m", "家賃")
    assert res.returncode == 0, res.stderr
    schedule = _get(scheduler, name)
    assert schedule["ScheduleExpression"] == "cron(0 8 1 * ? *)"
    assert _messages(schedule) == ["月初", "家賃"]


def test_update_at_changes_only_time(oshirase, scheduler, name):
    oshirase("add", name, "--weekly", "mon", "--at", "21:00", "-m", "元")

    res = oshirase("update", name, "--at", "22:15")

    assert res.returncode == 0, res.stderr
    schedule = _get(scheduler, name)
    assert schedule["ScheduleExpression"] == "cron(15 22 ? * MON *)"
    assert _messages(schedule) == ["元"]
    assert schedule["State"] == "ENABLED"


def test_update_message_changes_only_message(oshirase, scheduler, name):
    oshirase("add", name, "--daily", "--at", "08:00", "-m", "元")

    res = oshirase("update", name, "-m", "新")

    assert res.returncode == 0, res.stderr
    schedule = _get(scheduler, name)
    assert schedule["ScheduleExpression"] == "cron(0 8 * * ? *)"
    assert _messages(schedule) == ["新"]


def test_update_weekly_keeps_message(oshirase, scheduler, name):
    oshirase("add", name, "--daily", "--at", "08:00", "-m", "元")

    res = oshirase("update", name, "--weekly", "fri", "--at", "08:00")

    assert res.returncode == 0, res.stderr
    schedule = _get(scheduler, name)
    assert schedule["ScheduleExpression"] == "cron(0 8 ? * FRI *)"
    assert _messages(schedule) == ["元"]


def test_disable_then_enable(oshirase, scheduler, name):
    oshirase("add", name, "--daily", "--at", "08:00", "-m", "x")

    assert oshirase("disable", name).returncode == 0
    assert _get(scheduler, name)["State"] == "DISABLED"
    assert "停止中" in oshirase("show", name).stdout

    assert oshirase("enable", name).returncode == 0
    assert _get(scheduler, name)["State"] == "ENABLED"


def test_delete_removes_from_list(oshirase, name):
    oshirase("add", name, "--daily", "--at", "08:00", "-m", "x")

    res = oshirase("delete", name)

    assert res.returncode == 0, res.stderr
    assert name not in oshirase("list").stdout


@pytest.mark.parametrize("command", ["show", "enable", "disable", "delete"])
def test_unknown_name_fails(oshirase, command):
    res = oshirase(command, "does-not-exist")

    assert res.returncode == 1
    assert "見つかりません" in res.stderr


def test_add_duplicate_fails(oshirase, name):
    assert oshirase("add", name, "--daily", "--at", "08:00", "-m", "x").returncode == 0

    res = oshirase("add", name, "--daily", "--at", "09:00", "-m", "y")

    assert res.returncode == 1
    assert "既に存在します" in res.stderr


def test_invalid_time_fails(oshirase, scheduler, name):
    res = oshirase("add", name, "--daily", "--at", "25:00", "-m", "x")

    assert res.returncode == 2
    assert "時刻が範囲外です" in res.stderr
    assert name not in {
        s["Name"] for s in scheduler.list_schedules(GroupName=GROUP_NAME)["Schedules"]
    }
