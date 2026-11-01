"""Tests for oshirase_cli.cron."""

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from oshirase_cli import cron

# (英語3文字, 英語フルネーム, 日本語, EventBridgeの曜日番号, EventBridgeの曜日名)
WEEKDAYS = [
    ("sun", "Sunday", "日", 1, "SUN"),
    ("mon", "Monday", "月", 2, "MON"),
    ("tue", "Tuesday", "火", 3, "TUE"),
    ("wed", "Wednesday", "水", 4, "WED"),
    ("thu", "Thursday", "木", 5, "THU"),
    ("fri", "Friday", "金", 6, "FRI"),
    ("sat", "Saturday", "土", 7, "SAT"),
]
WEEKDAY_IDS = [w[0] for w in WEEKDAYS]

hours = st.integers(min_value=0, max_value=23)
minutes = st.integers(min_value=0, max_value=59)
weekdays = st.sampled_from(WEEKDAYS)
weekday_sets = st.lists(weekdays, min_size=1, max_size=7, unique_by=lambda w: w[3])
nths = st.integers(min_value=1, max_value=5)


def fmt_at(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


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
    @pytest.mark.parametrize(("short", "full", "ja", "num", "name"), WEEKDAYS, ids=WEEKDAY_IDS)
    def test_every_weekday(self, short, full, ja, num, name):
        assert cron.parse_days(short) == [num]
        assert cron.parse_days(short.upper()) == [num]
        assert cron.parse_days(full) == [num]
        assert cron.parse_days(ja) == [num]

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
    @pytest.mark.parametrize(("short", "full", "ja", "num", "name"), WEEKDAYS, ids=WEEKDAY_IDS)
    def test_weekly_every_weekday(self, short, full, ja, num, name):
        expr = cron.build_expression("21:00", weekly=short)
        assert expr == f"cron(0 21 ? * {name} *)"
        assert cron.describe(expr) == f"毎週{ja}曜 21:00"

    @pytest.mark.parametrize(("short", "full", "ja", "num", "name"), WEEKDAYS, ids=WEEKDAY_IDS)
    def test_nth_every_weekday(self, short, full, ja, num, name):
        expr = cron.build_expression("21:00", weekly=ja, nth=3)
        assert expr == f"cron(0 21 ? * {num}#3 *)"
        assert cron.describe(expr) == f"毎月第3{ja}曜 21:00"

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


class TestProperties:
    """Property-based tests (Hypothesis)."""

    @given(hours, minutes)
    def test_parse_at_roundtrip(self, hour, minute):
        assert cron.parse_at(fmt_at(hour, minute)) == (hour, minute)
        assert cron.parse_at(f"{hour}:{minute:02d}") == (hour, minute)

    @given(st.integers(min_value=24, max_value=99), minutes)
    def test_parse_at_rejects_hour_out_of_range(self, hour, minute):
        with pytest.raises(ValueError):
            cron.parse_at(fmt_at(hour, minute))

    @given(hours, st.integers(min_value=60, max_value=99))
    def test_parse_at_rejects_minute_out_of_range(self, hour, minute):
        with pytest.raises(ValueError):
            cron.parse_at(fmt_at(hour, minute))

    @given(st.text())
    def test_parse_at_only_raises_value_error(self, text):
        try:
            hour, minute = cron.parse_at(text)
        except ValueError:
            return
        assert 0 <= hour <= 23 and 0 <= minute <= 59

    @given(weekday_sets, st.data())
    def test_parse_days_any_subset_any_notation(self, days, data):
        tokens = [data.draw(st.sampled_from(d[:3])) for d in days]
        sep = data.draw(st.sampled_from([",", "、", "・", " ", ", "]))
        assert cron.parse_days(sep.join(tokens)) == sorted(d[3] for d in days)

    @given(hours, minutes)
    def test_daily_expression_roundtrip(self, hour, minute):
        expr = cron.build_expression(fmt_at(hour, minute), daily=True)
        assert expr == f"cron({minute} {hour} * * ? *)"
        assert cron.describe(expr) == f"毎日 {fmt_at(hour, minute)}"

    @given(hours, minutes, weekday_sets)
    def test_weekly_expression_roundtrip(self, hour, minute, days):
        expr = cron.build_expression(fmt_at(hour, minute), weekly=",".join(d[0] for d in days))
        ordered = sorted(days, key=lambda d: d[3])
        assert expr == f"cron({minute} {hour} ? * {','.join(d[4] for d in ordered)} *)"
        labels = "・".join(d[2] for d in ordered)
        assert cron.describe(expr) == f"毎週{labels}曜 {fmt_at(hour, minute)}"

    @given(hours, minutes, weekdays, nths)
    def test_nth_expression_roundtrip(self, hour, minute, day, nth):
        expr = cron.build_expression(fmt_at(hour, minute), weekly=day[0], nth=nth)
        assert expr == f"cron({minute} {hour} ? * {day[3]}#{nth} *)"
        assert cron.describe(expr) == f"毎月第{nth}{day[2]}曜 {fmt_at(hour, minute)}"

    @given(hours, minutes, hours, minutes, weekday_sets)
    def test_replace_time_only_changes_time(self, h1, m1, h2, m2, days):
        original = cron.build_expression(fmt_at(h1, m1), weekly=",".join(d[0] for d in days))
        replaced = cron.replace_time(original, fmt_at(h2, m2))
        assert replaced == cron.build_expression(
            fmt_at(h2, m2), weekly=",".join(d[0] for d in days)
        )
        # 時刻以外のフィールドは変わらない
        assert original.split(" ")[2:] == replaced.split(" ")[2:]

    @given(st.text())
    def test_describe_never_raises(self, text):
        result = cron.describe(text)
        assert isinstance(result, str)
        if not re.match(r"^cron\(", text):
            assert result == text
