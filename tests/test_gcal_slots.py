"""面談候補日の算出（scripts/gcal/slots.py）の単体テスト.

busy の合成、稼働時間帯・曜日・祝日・バッファ・刻みでの空き枠算出と、返信用の表記（日跨ぎ・DST のある TZ）を確かめる。
"""

import unittest
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from scripts.gcal import slots

TOKYO = ZoneInfo("Asia/Tokyo")
LA = ZoneInfo("America/Los_Angeles")


def jst(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=TOKYO)


def rules(**kw):
    base = dict(tz=TOKYO, buffer=timedelta(0), min_duration=timedelta(minutes=60))
    base.update(kw)
    return slots.SlotRules(**base)


class ParseTest(unittest.TestCase):
    def test_hours(self):
        self.assertEqual(slots.parse_hours("10-19"), (time(10), time(19)))
        self.assertEqual(slots.parse_hours("9:30-18:00"), (time(9, 30), time(18)))
        for bad in ("19-10", "10", "10-24", "25-26"):
            with self.assertRaises(ValueError):
                slots.parse_hours(bad)

    def test_weekdays(self):
        self.assertEqual(slots.parse_weekdays("mon-fri"), frozenset(range(5)))
        self.assertEqual(slots.parse_weekdays("mon,wed,fri"), frozenset({0, 2, 4}))
        self.assertEqual(slots.parse_weekdays("fri-mon"), frozenset({4, 5, 6, 0}))
        with self.assertRaises(ValueError):
            slots.parse_weekdays("xyz")

    def test_busy_arg(self):
        self.assertEqual(
            slots.parse_busy_arg("2026-10-23 18:30-19:30", TOKYO), (jst(2026, 10, 23, 18, 30), jst(2026, 10, 23, 19, 30))
        )
        with self.assertRaises(ValueError):
            slots.parse_busy_arg("2026-10-23 19:30-18:30", TOKYO)

    def test_freebusy_utc(self):
        cals = {"primary": {"busy": [{"start": "2026-10-28T04:00:00Z", "end": "2026-10-28T05:00:00Z"}]}}
        self.assertEqual(slots.parse_freebusy(cals), [(jst(2026, 10, 28, 13), jst(2026, 10, 28, 14))])


class MergeTest(unittest.TestCase):
    def test_overlapping_and_touching(self):
        merged = slots.merge_intervals(
            [
                (jst(2026, 10, 28, 13), jst(2026, 10, 28, 14)),
                (jst(2026, 10, 28, 10), jst(2026, 10, 28, 11)),
                (jst(2026, 10, 28, 13, 30), jst(2026, 10, 28, 15)),
                (jst(2026, 10, 28, 15), jst(2026, 10, 28, 16)),
            ]
        )
        self.assertEqual(
            merged,
            [(jst(2026, 10, 28, 10), jst(2026, 10, 28, 11)), (jst(2026, 10, 28, 13), jst(2026, 10, 28, 16))],
        )


class FreeSlotsTest(unittest.TestCase):
    # 2026-10-28 は水曜
    def test_busy_splits_day(self):
        busy = [(jst(2026, 10, 28, 12), jst(2026, 10, 28, 13)), (jst(2026, 10, 28, 12, 30), jst(2026, 10, 28, 14))]
        got = slots.free_slots(busy, jst(2026, 10, 28), jst(2026, 10, 29), rules())
        self.assertEqual(got, [(jst(2026, 10, 28, 10), jst(2026, 10, 28, 12)), (jst(2026, 10, 28, 14), jst(2026, 10, 28, 19))])

    def test_buffer_and_alignment(self):
        busy = [(jst(2026, 10, 28, 12), jst(2026, 10, 28, 13, 10))]
        got = slots.free_slots(busy, jst(2026, 10, 28), jst(2026, 10, 29), rules(buffer=timedelta(minutes=15)))
        # 前: 11:45 まで → 11:30 に切り下げ。後: 13:25 から → 13:30 に切り上げ
        self.assertEqual(
            got, [(jst(2026, 10, 28, 10), jst(2026, 10, 28, 11, 30)), (jst(2026, 10, 28, 13, 30), jst(2026, 10, 28, 19))]
        )

    def test_min_duration_drops_short_gap(self):
        busy = [(jst(2026, 10, 28, 10), jst(2026, 10, 28, 13)), (jst(2026, 10, 28, 13, 30), jst(2026, 10, 28, 19))]
        self.assertEqual(slots.free_slots(busy, jst(2026, 10, 28), jst(2026, 10, 29), rules()), [])

    def test_weekend_and_holiday_excluded(self):
        # 10/30(金)〜11/4(水)。11/3(火) は文化の日
        hol = slots.country_holidays("JP", date(2026, 10, 30), date(2026, 11, 4))
        self.assertIn(date(2026, 11, 3), hol)
        got = slots.free_slots([], jst(2026, 10, 30), jst(2026, 11, 5), rules(holidays=hol))
        self.assertEqual([s.date() for s, _ in got], [date(2026, 10, 30), date(2026, 11, 2), date(2026, 11, 4)])

    def test_range_clips_window(self):
        # 開始が 15:10（現在時刻相当）なら 15:30 から
        got = slots.free_slots([], jst(2026, 10, 28, 15, 10), jst(2026, 10, 29), rules())
        self.assertEqual(got, [(jst(2026, 10, 28, 15, 30), jst(2026, 10, 28, 19))])

    def test_all_day_busy_across_days(self):
        # 終日予定（UTC 区切りで日を跨ぐ busy）も稼働時間帯ごとに効く
        busy = [(datetime.fromisoformat("2026-10-27T15:00:00Z"), datetime.fromisoformat("2026-10-28T15:00:00Z"))]
        got = slots.free_slots(busy, jst(2026, 10, 28), jst(2026, 10, 30), rules())
        self.assertEqual(got, [(jst(2026, 10, 29, 10), jst(2026, 10, 29, 19))])

    def test_no_holidays_when_country_none(self):
        self.assertEqual(slots.country_holidays(None, date(2026, 1, 1), date(2026, 12, 31)), frozenset())


class FormatTest(unittest.TestCase):
    def test_en_crosses_date(self):
        self.assertEqual(
            slots.format_slot(jst(2026, 10, 28, 10), jst(2026, 10, 28, 19), LA, lang="en", show_tz=True),
            "Tue, Oct 27 18:00 - Wed, Oct 28 03:00 (PDT)",
        )

    def test_ja(self):
        self.assertEqual(slots.format_slot(jst(2026, 10, 28, 13), jst(2026, 10, 28, 15), TOKYO), "10/28(水) 13:00〜15:00")

    def test_en_with_tz(self):
        self.assertEqual(
            slots.format_slot(jst(2026, 10, 28, 13), jst(2026, 10, 28, 15), TOKYO, lang="en", show_tz=True),
            "Wed, Oct 28 13:00-15:00 (JST)",
        )

    def test_display_tz_crosses_date(self):
        # 東京 10:00〜19:00 は LA（夏時間 PDT, UTC-7）で前日 18:00〜03:00
        self.assertEqual(
            slots.format_slot(jst(2026, 10, 28, 10), jst(2026, 10, 28, 19), LA, show_tz=True),
            "10/27(火) 18:00〜10/28(水) 03:00 (PDT)",
        )

    def test_dst_switch(self):
        # LA は 2026-11-01 09:00 UTC に PDT→PST。東京 11/1 17:00〜19:00（UTC 08:00〜10:00）は切替を跨ぐ
        s, e = jst(2026, 11, 1, 17), jst(2026, 11, 1, 19)
        self.assertEqual(slots.format_slot(s, e, LA, show_tz=True), "11/1(日) 01:00〜02:00 (PDT/PST)")


class _Request:
    def __init__(self, fn, kwargs):
        self._fn, self._kwargs = fn, kwargs

    def execute(self):
        return self._fn(**self._kwargs)


class FakeCalendar:
    """freebusy().query と events().list だけを持つフェイク."""

    def __init__(self, freebusy=None, events=None, page_size=2):
        self.freebusy_resp = freebusy or {}
        self.events_data = events or []
        self.page_size = page_size
        self.calls = []

    def freebusy(self):
        return self

    def events(self):
        return self

    def query(self, body):
        self.calls.append(("freebusy", body))
        return _Request(lambda: self.freebusy_resp, {})

    def list(self, **kw):
        self.calls.append(("events", kw))
        return _Request(self._list, kw)

    def _list(self, pageToken=None, **kw):
        i = int(pageToken or 0)
        resp = {"items": self.events_data[i : i + self.page_size]}
        if i + self.page_size < len(self.events_data):
            resp["nextPageToken"] = str(i + self.page_size)
        return resp


class CliTest(unittest.TestCase):
    def test_resolve_range_defaults(self):
        from scripts.gcal.client import resolve_range

        self.assertEqual(resolve_range(None, None, TOKYO, now=jst(2026, 10, 22, 15)), (jst(2026, 10, 22), jst(2026, 11, 5)))
        self.assertEqual(resolve_range("2026-10-26", "2026-10-30", TOKYO), (jst(2026, 10, 26), jst(2026, 10, 31)))
        with self.assertRaises(ValueError):
            resolve_range("2026-10-30", "2026-10-26", TOKYO)

    def test_query_busy_calendar_error(self):
        from scripts.gcal import find_slots

        fake = FakeCalendar(freebusy={"calendars": {"primary": {"busy": []}, "x@example.com": {"errors": [{"reason": "notFound"}]}}})
        with self.assertRaises(find_slots.FreeBusyError) as cm:
            find_slots.query_busy(fake, ["primary", "x@example.com"], jst(2026, 10, 26), jst(2026, 10, 27))
        self.assertIn("notFound", str(cm.exception))

    def test_query_busy_and_find(self):
        from scripts.gcal import find_slots

        fake = FakeCalendar(
            freebusy={"calendars": {"primary": {"busy": [{"start": "2026-10-28T01:00:00Z", "end": "2026-10-28T09:00:00Z"}]}}}
        )
        busy = find_slots.query_busy(fake, ["primary"], jst(2026, 10, 28), jst(2026, 10, 29))
        got = find_slots.find(busy, jst(2026, 10, 28), jst(2026, 10, 29), rules(), limit=5, now=jst(2026, 10, 22))
        # 10:00〜18:00 JST が埋まっている → 18:00〜19:00 だけ
        self.assertEqual(got, [(jst(2026, 10, 28, 18), jst(2026, 10, 28, 19))])
        self.assertEqual(fake.calls[0][1]["items"], [{"id": "primary"}])

    def test_list_events_paging_and_job_only(self):
        from scripts.gcal import list_events
        from scripts.gcal.client import MANAGED_PROPERTY_KEY

        items = [
            {"id": f"e{i}", "summary": f"予定{i}", "start": {"dateTime": f"2026-10-2{i}T10:00:00+09:00"}, "end": {"dateTime": f"2026-10-2{i}T11:00:00+09:00"}}
            for i in range(5)
        ]
        items[1]["extendedProperties"] = {"private": {MANAGED_PROPERTY_KEY: "1"}}
        items[2] = {"id": "allday", "start": {"date": "2026-10-22"}, "end": {"date": "2026-10-23"}, "transparency": "transparent"}
        fake = FakeCalendar(events=items)
        rows = list_events.list_events(fake, "primary", jst(2026, 10, 20), jst(2026, 10, 30), limit=4, tz=TOKYO, job_only=True)
        self.assertEqual([r["id"] for r in rows], ["e0", "e1", "allday", "e3"])
        self.assertTrue(rows[1]["managed"])
        self.assertTrue(rows[2]["all_day"])
        self.assertEqual(rows[2]["summary"], "（タイトルなし）")
        self.assertEqual(fake.calls[0][1]["privateExtendedProperty"], f"{MANAGED_PROPERTY_KEY}=1")
        self.assertTrue(fake.calls[0][1]["singleEvents"])


if __name__ == "__main__":
    unittest.main()
