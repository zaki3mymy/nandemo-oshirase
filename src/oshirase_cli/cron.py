"""Build and describe EventBridge Scheduler cron expressions.

EventBridge cron format: ``cron(minutes hours day-of-month month day-of-week year)``
Day-of-week is 1-7 (SUN-SAT). Either day-of-month or day-of-week must be ``?``.
"""

import re

# 曜日の入力（英語3文字・日本語1文字）→ EventBridgeの曜日番号（SUN=1 ... SAT=7）
_DAY_ALIASES: dict[str, int] = {
    "sun": 1,
    "mon": 2,
    "tue": 3,
    "wed": 4,
    "thu": 5,
    "fri": 6,
    "sat": 7,
    "日": 1,
    "月": 2,
    "火": 3,
    "水": 4,
    "木": 5,
    "金": 6,
    "土": 7,
}
_DAY_NAMES = ["", "SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
_DAY_NAMES_JA = ["", "日", "月", "火", "水", "木", "金", "土"]

_AT_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})$")
_CRON_PATTERN = re.compile(r"^cron\((\S+) (\S+) (\S+) (\S+) (\S+) (\S+)\)$")


def parse_at(at: str) -> tuple[int, int]:
    """Parse ``HH:MM`` into (hour, minute)."""
    m = _AT_PATTERN.match(at.strip())
    if not m:
        raise ValueError(f"時刻は HH:MM 形式で指定してください: {at!r}")
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"時刻が範囲外です: {at!r}")
    return hour, minute


def parse_days(days: str) -> list[int]:
    """Parse ``mon,thu`` / ``月,木`` into sorted unique day numbers (SUN=1)."""
    result: set[int] = set()
    for raw in re.split(r"[,、・\s]+", days.strip()):
        if not raw:
            continue
        key = raw.lower()[:3] if raw.isascii() else raw
        if key not in _DAY_ALIASES:
            raise ValueError(f"曜日が不正です: {raw!r}（mon,tue,... または 月,火,... で指定）")
        result.add(_DAY_ALIASES[key])
    if not result:
        raise ValueError("曜日を1つ以上指定してください")
    return sorted(result)


def build_expression(
    at: str,
    *,
    daily: bool = False,
    weekly: str | None = None,
    nth: int | None = None,
) -> str:
    """Build a cron expression from friendly options."""
    hour, minute = parse_at(at)
    if daily == (weekly is not None):
        raise ValueError("--daily と --weekly のどちらか一方を指定してください")

    if daily:
        if nth is not None:
            raise ValueError("--nth は --weekly と一緒に指定してください")
        return f"cron({minute} {hour} * * ? *)"

    assert weekly is not None
    days = parse_days(weekly)
    if nth is None:
        dow = ",".join(_DAY_NAMES[d] for d in days)
        return f"cron({minute} {hour} ? * {dow} *)"

    if not 1 <= nth <= 5:
        raise ValueError("--nth は 1〜5 で指定してください")
    if len(days) != 1:
        raise ValueError(
            "--nth を使う場合、曜日は1つだけ指定してください"
            "（第1・第3水曜などは2件に分けて登録してください）"
        )
    return f"cron({minute} {hour} ? * {days[0]}#{nth} *)"


def replace_time(expression: str, at: str) -> str:
    """Replace the time-of-day of an existing cron expression."""
    hour, minute = parse_at(at)
    m = _CRON_PATTERN.match(expression)
    if not m or not (m.group(1).isdigit() and m.group(2).isdigit()):
        raise ValueError(
            f"このスケジュール（{expression}）は --at だけでは変更できません。"
            "--daily / --weekly / --cron で指定し直してください"
        )
    rest = " ".join(m.group(i) for i in range(3, 7))
    return f"cron({minute} {hour} {rest})"


def _day_label(token: str) -> str | None:
    """Convert a single day-of-week token (``MON`` or ``2``) into a Japanese label."""
    if token.isdigit() and 1 <= int(token) <= 7:
        return _DAY_NAMES_JA[int(token)]
    if token.upper() in _DAY_NAMES[1:]:
        return _DAY_NAMES_JA[_DAY_NAMES.index(token.upper())]
    return None


def describe(expression: str) -> str:
    """Return a human-readable Japanese description, falling back to the raw expression."""
    m = _CRON_PATTERN.match(expression)
    if not m:
        return expression
    minute, hour, dom, month, dow, year = m.groups()
    if not (minute.isdigit() and hour.isdigit()) or month != "*" or year != "*":
        return expression
    time = f"{int(hour):02d}:{int(minute):02d}"

    if dom == "*" and dow == "?":
        return f"毎日 {time}"

    if dom == "?":
        if "#" in dow:
            day, _, nth = dow.partition("#")
            label = _day_label(day)
            if label and nth.isdigit():
                return f"毎月第{nth}{label}曜 {time}"
            return expression
        labels = [_day_label(d) for d in dow.split(",")]
        if all(labels):
            return f"毎週{'・'.join(label for label in labels if label)}曜 {time}"

    return expression
