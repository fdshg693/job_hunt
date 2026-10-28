"""面談候補日の算出（純粋関数。API を呼ばない）.

freeBusy の busy 区間から、稼働時間帯・曜日・祝日・前後バッファ・最短長の条件で空き枠を出し、
返信に貼れる表記（例: `10/28(火) 13:00〜15:00`）に整形する。

- 時刻はすべてタイムゾーン付き datetime で扱う。稼働時間帯・曜日・祝日はカレンダー側のタイムゾーン（既定 Asia/Tokyo）で判定し、
  表示だけ別のタイムゾーンに変えられる（overseas track 向け）。
- 空き枠は「連続した空き」をそのまま返す。どの枠を相手に出すかは AI が状況を見て間引く（機械的に選ばない）。
仕様は docs/gcal/README.md を参照。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAY_JA = "月火水木金土日"
WEEKDAY_EN = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTH_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_HOURS_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?-(\d{1,2})(?::(\d{2}))?$")
_BUSY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{1,2}:\d{2})-(\d{1,2}:\d{2})$")

Interval = tuple[datetime, datetime]


@dataclass(frozen=True)
class SlotRules:
    """空き枠の条件."""

    tz: ZoneInfo  # 稼働時間帯・曜日・祝日を判定するタイムゾーン
    day_start: time = time(10, 0)
    day_end: time = time(19, 0)
    weekdays: frozenset[int] = frozenset(range(5))  # 0=月 … 6=日
    holidays: frozenset[date] = frozenset()
    buffer: timedelta = timedelta(minutes=15)  # busy の前後に空ける時間
    min_duration: timedelta = timedelta(minutes=60)
    align: timedelta = timedelta(minutes=30)  # 枠の開始・終了をこの刻みに揃える


def parse_hours(value: str) -> tuple[time, time]:
    """`10-19` / `9:30-18:00` を (開始, 終了) にする（日跨ぎ・24:00 は不可）."""
    m = _HOURS_RE.match(value.strip())
    if not m:
        raise ValueError(f"時間帯は 10-19 や 9:30-18:00 の形式で指定してください: {value}")
    try:
        start, end = time(int(m[1]), int(m[2] or 0)), time(int(m[3]), int(m[4] or 0))
    except ValueError:
        raise ValueError(f"時間帯の時刻が不正です（0:00〜23:59）: {value}") from None
    if end <= start:
        raise ValueError(f"時間帯の終了は開始より後にしてください（日跨ぎは不可）: {value}")
    return start, end


def parse_weekdays(value: str) -> frozenset[int]:
    """`mon-fri` / `mon,wed,fri` / `sat-sun` を曜日番号（0=月）の集合にする."""
    days: set[int] = set()
    for part in value.lower().replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            ia, ib = _weekday_index(a), _weekday_index(b)
            i = ia
            while True:
                days.add(i)
                if i == ib:
                    break
                i = (i + 1) % 7
        else:
            days.add(_weekday_index(part))
    if not days:
        raise ValueError(f"曜日を 1 つ以上指定してください: {value}")
    return frozenset(days)


def _weekday_index(key: str) -> int:
    try:
        return WEEKDAY_KEYS.index(key[:3])
    except ValueError:
        raise ValueError(f"曜日は {'/'.join(WEEKDAY_KEYS)} で指定してください: {key}") from None


def parse_busy_arg(value: str, tz: ZoneInfo) -> Interval:
    """`2026-10-23 18:30-19:30`（tz の現地時刻）を busy 区間にする。カレンダー未登録の予定を足す用."""
    m = _BUSY_RE.match(value.strip())
    if not m:
        raise ValueError(f"--busy は 'YYYY-MM-DD HH:MM-HH:MM' の形式で指定してください: {value}")
    day = date.fromisoformat(m[1])
    start = datetime.combine(day, time.fromisoformat(m[2].zfill(5)), tz)
    end = datetime.combine(day, time.fromisoformat(m[3].zfill(5)), tz)
    if end <= start:
        raise ValueError(f"--busy の終了は開始より後にしてください: {value}")
    return start, end


def parse_freebusy(calendars: dict[str, dict]) -> list[Interval]:
    """freebusy.query 応答の calendars から busy 区間を集める（エラーのあるカレンダーは呼び出し側で扱う）."""
    busy: list[Interval] = []
    for cal in calendars.values():
        for b in cal.get("busy", []):
            busy.append((datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"])))
    return busy


def merge_intervals(intervals: Iterable[Interval]) -> list[Interval]:
    """重なる・接する区間を合成し、開始順に並べる."""
    merged: list[Interval] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _ceil(dt: datetime, step: timedelta) -> datetime:
    """dt を現地時刻の 0 時起点で step 刻みに切り上げる."""
    if step <= timedelta(0):
        return dt
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    n = -(-(dt - midnight) // step)
    return midnight + n * step


def _floor(dt: datetime, step: timedelta) -> datetime:
    if step <= timedelta(0):
        return dt
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight + ((dt - midnight) // step) * step


def day_windows(start: datetime, end: datetime, rules: SlotRules) -> list[Interval]:
    """[start, end) の中の稼働時間帯（曜日・祝日を除く）を日ごとに返す."""
    windows: list[Interval] = []
    day = start.astimezone(rules.tz).date()
    last = end.astimezone(rules.tz).date()
    while day <= last:
        if day.weekday() in rules.weekdays and day not in rules.holidays:
            w_start = datetime.combine(day, rules.day_start, rules.tz)
            w_end = datetime.combine(day, rules.day_end, rules.tz)
            s, e = max(w_start, start), min(w_end, end)
            if s < e:
                windows.append((s, e))
        day += timedelta(days=1)
    return windows


def free_slots(busy: Iterable[Interval], start: datetime, end: datetime, rules: SlotRules) -> list[Interval]:
    """busy 区間を除いた空き枠（稼働時間帯内・最短長以上・刻みに揃えたもの）を開始順に返す."""
    blocked = merge_intervals((s - rules.buffer, e + rules.buffer) for s, e in busy)
    slots: list[Interval] = []
    for w_start, w_end in day_windows(start, end, rules):
        cursor = w_start
        for b_start, b_end in blocked:
            if b_end <= cursor or b_start >= w_end:
                continue
            _append(slots, cursor, min(b_start, w_end), rules)
            cursor = max(cursor, b_end)
            if cursor >= w_end:
                break
        _append(slots, cursor, w_end, rules)
    return slots


def _append(slots: list[Interval], start: datetime, end: datetime, rules: SlotRules) -> None:
    s = _ceil(start.astimezone(rules.tz), rules.align)
    e = _floor(end.astimezone(rules.tz), rules.align)
    if e - s >= rules.min_duration:
        slots.append((s, e))


def format_slot(start: datetime, end: datetime, tz: ZoneInfo, lang: str = "ja", show_tz: bool = False) -> str:
    """空き枠を返信用の 1 行にする（ja: `10/28(火) 13:00〜15:00`、en: `Tue, Oct 28 13:00-15:00`）."""
    s, e = start.astimezone(tz), end.astimezone(tz)
    # 表示タイムゾーンでは日付を跨ぐことがある（例: 東京の 10:00〜19:00 を米西海岸で見る）
    date_fn = _date_en if lang == "en" else _date_ja
    if s.date() == e.date():
        sep, end_label = ("-" if lang == "en" else "〜"), f"{e:%H:%M}"
    else:
        sep, end_label = (" - " if lang == "en" else "〜"), f"{date_fn(e)} {e:%H:%M}"
    text = f"{date_fn(s)} {s:%H:%M}{sep}{end_label}"
    if show_tz:
        text += f" ({s.tzname()})" if s.tzname() == e.tzname() else f" ({s.tzname()}/{e.tzname()})"
    return text


def _date_ja(dt: datetime) -> str:
    return f"{dt.month}/{dt.day}({WEEKDAY_JA[dt.weekday()]})"


def _date_en(dt: datetime) -> str:
    return f"{WEEKDAY_EN[dt.weekday()]}, {MONTH_EN[dt.month - 1]} {dt.day}"


def country_holidays(country: str | None, first: date, last: date) -> frozenset[date]:
    """first〜last の祝日（holidays パッケージ。country は ISO 3166-1 alpha-2、None なら祝日なし）."""
    if not country:
        return frozenset()
    import holidays

    days = holidays.country_holidays(country.upper(), years=range(first.year, last.year + 1))
    return frozenset(d for d in days if first <= d <= last)
