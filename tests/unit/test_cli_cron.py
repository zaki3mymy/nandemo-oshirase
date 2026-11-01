"""Tests for oshirase_cli.cron."""

import pytest

from oshirase_cli import cron


class TestParseAt:
    @pytest.mark.parametrize(
        ("at", "expected"), [("21:00", (21, 0)), ("7:05", (7, 5)), (" 00:59 ", (0, 59))]
    )
    def test_valid(self, at, expected):
        assert cron.parse_at(at) == expected

    @pytest.mark.parametrize("at", ["2100", "21:0", "abc", ""])
    def test_invalid_format(self, at):
        with pytest.raises(ValueError, match="HH:MM"):
            cron.parse_at(at)

    @pytest.mark.parametrize("at", ["24:00", "12:60"])
    def test_out_of_range(self, at):
        with pytest.raises(ValueError, match="範囲外"):
            cron.parse_at(at)


class TestParseDays:
    def test_english(self):
        assert cron.parse_days("thu,mon") == [2, 5]

    def test_english_full_name_and_case(self):
        assert cron.parse_days("Monday, SUN") == [1, 2]

    def test_japanese(self):
        assert cron.parse_days("月・木") == [2, 5]

    def test_dedup(self):
        assert cron.parse_days("mon,月") == [2]

    def test_invalid(self):
        with pytest.raises(ValueError, match="曜日が不正"):
            cron.parse_days("mon,xyz")

    def test_empty(self):
        with pytest.raises(ValueError, match="1つ以上"):
            cron.parse_days(" , ")


class TestBuildExpression:
    def test_daily(self):
        assert cron.build_expression("07:30", daily=True) == "cron(30 7 * * ? *)"

    def test_weekly(self):
        assert cron.build_expression("21:00", weekly="mon,thu") == "cron(0 21 ? * MON,THU *)"

    def test_weekly_nth(self):
        assert cron.build_expression("21:00", weekly="水", nth=2) == "cron(0 21 ? * 4#2 *)"

    def test_neither(self):
        with pytest.raises(ValueError, match="どちらか一方"):
            cron.build_expression("21:00")

    def test_both(self):
        with pytest.raises(ValueError, match="どちらか一方"):
            cron.build_expression("21:00", daily=True, weekly="mon")

    def test_daily_with_nth(self):
        with pytest.raises(ValueError, match="--nth"):
            cron.build_expression("21:00", daily=True, nth=1)

    @pytest.mark.parametrize("nth", [0, 6])
    def test_nth_out_of_range(self, nth):
        with pytest.raises(ValueError, match="1〜5"):
            cron.build_expression("21:00", weekly="wed", nth=nth)

    def test_nth_multiple_days(self):
        with pytest.raises(ValueError, match="曜日は1つだけ"):
            cron.build_expression("21:00", weekly="wed,fri", nth=1)


class TestReplaceTime:
    def test_replace(self):
        assert cron.replace_time("cron(0 21 ? * MON *)", "20:30") == "cron(30 20 ? * MON *)"

    @pytest.mark.parametrize("expr", ["cron(0/5 * * * ? *)", "rate(1 hour)"])
    def test_unsupported(self, expr):
        with pytest.raises(ValueError, match="--at だけでは変更できません"):
            cron.replace_time(expr, "20:30")


class TestDescribe:
    @pytest.mark.parametrize(
        ("expr", "expected"),
        [
            ("cron(30 7 * * ? *)", "毎日 07:30"),
            ("cron(0 21 ? * MON *)", "毎週月曜 21:00"),
            ("cron(0 21 ? * MON,THU *)", "毎週月・木曜 21:00"),
            ("cron(0 21 ? * 2,5 *)", "毎週月・木曜 21:00"),
            ("cron(0 21 ? * 4#2 *)", "毎月第2水曜 21:00"),
            ("cron(0 21 ? * WED#3 *)", "毎月第3水曜 21:00"),
        ],
    )
    def test_known(self, expr, expected):
        assert cron.describe(expr) == expected

    @pytest.mark.parametrize(
        "expr",
        [
            "rate(1 hour)",
            "cron(0/5 * * * ? *)",
            "cron(0 8 1 * ? *)",
            "cron(0 8 ? 1 MON *)",
            "cron(0 8 ? * MON-FRI *)",
            "cron(0 8 ? * XYZ#2 *)",
            "cron(0 8 ? * 9 *)",
        ],
    )
    def test_fallback_to_raw(self, expr):
        assert cron.describe(expr) == expr
