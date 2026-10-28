"""予定の作成・更新・削除（scripts/gcal/manage_events.py）の単体テスト.

service をフェイクにして、安全ガード（ツール作成でない予定・招待予定・ゲスト付き予定の拒否、重複作成の拒否）、
sendUpdates=none の固定、etag（If-Match）、変更前バックアップ、dry-run で書き換えないことを確かめる。
"""

import argparse
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from scripts.common.cli import EntrypointContext
from scripts.gcal import manage_events as me
from scripts.gcal.client import COMPANY_PROPERTY_KEY, MANAGED_PROPERTY_KEY

TOKYO = ZoneInfo("Asia/Tokyo")


class _Request:
    def __init__(self, fn):
        self._fn = fn
        self.headers = {}

    def execute(self):
        return self._fn(self.headers)


class FakeEvents:
    """events() の get / list / insert / patch / delete だけを持つフェイク."""

    def __init__(self, events=None):
        self.store = {e["id"]: e for e in (events or [])}
        self.calls = []

    def events(self):
        return self

    def _record(self, name, kw, fn):
        req = _Request(lambda headers: (self.calls.append((name, kw, dict(headers))), fn())[1])
        return req

    def get(self, calendarId, eventId):
        return self._record("get", {"eventId": eventId}, lambda: self.store[eventId])

    def list(self, **kw):
        return self._record("list", kw, lambda: {"items": self._match(kw.get("privateExtendedProperty"))})

    def _match(self, prop):
        key, value = prop.split("=", 1)
        return [e for e in self.store.values() if e.get("extendedProperties", {}).get("private", {}).get(key) == value]

    def insert(self, calendarId, body, sendUpdates):
        def run():
            event = {**body, "id": "new1", "etag": '"1"', "organizer": {"self": True}, "status": "confirmed"}
            self.store["new1"] = event
            return event

        return self._record("insert", {"body": body, "sendUpdates": sendUpdates}, run)

    def patch(self, calendarId, eventId, body, sendUpdates):
        def run():
            self.store[eventId] = {**self.store[eventId], **body}
            return self.store[eventId]

        return self._record("patch", {"eventId": eventId, "body": body, "sendUpdates": sendUpdates}, run)

    def delete(self, calendarId, eventId, sendUpdates):
        return self._record("delete", {"eventId": eventId, "sendUpdates": sendUpdates}, lambda: self.store.pop(eventId) and "")


def managed_event(event_id="ev1", company_key="acme", **kw):
    private = {MANAGED_PROPERTY_KEY: "1"}
    if company_key:
        private[COMPANY_PROPERTY_KEY] = company_key
    base = {
        "id": event_id,
        "etag": '"7"',
        "summary": "【面談】Acme カジュアル面談",
        "start": {"dateTime": "2026-10-28T15:00:00+09:00"},
        "end": {"dateTime": "2026-10-28T16:00:00+09:00"},
        "organizer": {"email": "me@example.com", "self": True},
        "status": "confirmed",
        "extendedProperties": {"private": private},
    }
    base.update(kw)
    return base


def args(**kw):
    base = dict(
        calendar="primary", dry_run=False, force=False, title=None, start=None, end=None, duration=None,
        location=None, description=None, company_key=None, id=None,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def names(fake):
    return [c[0] for c in fake.calls]


class ManageTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name)
        patcher = mock.patch.object(me, "DATA_DIR", self.data_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        # save_result は client 側の DATA_DIR を見るので合わせて差し替える
        patcher = mock.patch("scripts.gcal.client.DATA_DIR", self.data_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ctx = EntrypointContext()


class ParseTest(unittest.TestCase):
    def test_local_datetime(self):
        self.assertEqual(me.parse_local_datetime("2026-10-28 15:00", TOKYO), datetime(2026, 10, 28, 15, tzinfo=TOKYO))
        for bad in ("2026/10/28 15:00", "2026-10-28T15:00+09:00"):
            with self.assertRaises(ValueError):
                me.parse_local_datetime(bad, TOKYO)

    def test_resolve_end(self):
        start = datetime(2026, 10, 28, 15, tzinfo=TOKYO)
        self.assertEqual(me.resolve_end(start, None, None, TOKYO), datetime(2026, 10, 28, 16, tzinfo=TOKYO))
        self.assertEqual(me.resolve_end(start, None, 45, TOKYO), datetime(2026, 10, 28, 15, 45, tzinfo=TOKYO))
        with self.assertRaises(ValueError):
            me.resolve_end(start, "2026-10-28 14:00", None, TOKYO)
        with self.assertRaises(ValueError):
            me.resolve_end(start, "2026-10-28 16:00", 30, TOKYO)


class CreateTest(ManageTestCase):
    def test_create_sets_marker_and_no_notifications(self):
        fake = FakeEvents()
        res = me.cmd_create(args(title="【面談】Acme", start="2026-10-28 15:00", company_key="acme"), fake, self.ctx, TOKYO)
        name, kw, _ = fake.calls[-1]
        self.assertEqual(name, "insert")
        self.assertEqual(kw["sendUpdates"], "none")
        self.assertNotIn("attendees", kw["body"])
        self.assertEqual(kw["body"]["extendedProperties"]["private"], {MANAGED_PROPERTY_KEY: "1", COMPANY_PROPERTY_KEY: "acme"})
        self.assertEqual(kw["body"]["end"], {"dateTime": "2026-10-28T16:00:00+09:00", "timeZone": "Asia/Tokyo"})
        self.assertEqual(res["event"]["id"], "new1")
        self.assertEqual(len(self.ctx.result_paths), 2)  # changes/ の .md と .json
        self.assertEqual(len(list((self.data_dir / "changes").glob("*.json"))), 1)

    def test_duplicate_same_company_rejected_unless_force(self):
        fake = FakeEvents([managed_event()])
        a = args(title="別タイトル", start="2026-10-28 18:00", company_key="acme")
        with self.assertRaises(me.GuardError):
            me.cmd_create(a, fake, self.ctx, TOKYO)
        self.assertNotIn("insert", names(fake))
        self.assertEqual(fake.calls[0][1]["privateExtendedProperty"], f"{COMPANY_PROPERTY_KEY}=acme")
        a.force = True
        me.cmd_create(a, fake, self.ctx, TOKYO)
        self.assertIn("insert", names(fake))

    def test_duplicate_without_company_matches_title(self):
        fake = FakeEvents([managed_event(company_key=None)])
        me.cmd_create(args(title="別の予定", start="2026-10-28 18:00"), fake, self.ctx, TOKYO)
        self.assertIn("insert", names(fake))
        with self.assertRaises(me.GuardError):
            me.cmd_create(args(title="【面談】Acme カジュアル面談", start="2026-10-28 18:00"), fake, self.ctx, TOKYO)

    def test_dry_run_does_not_insert(self):
        fake = FakeEvents()
        res = me.cmd_create(args(title="x", start="2026-10-28 15:00", dry_run=True), fake, self.ctx, TOKYO)
        self.assertTrue(res["dry_run"])
        self.assertEqual(names(fake), ["list"])
        self.assertEqual(self.ctx.result_paths, [])


class GuardTest(unittest.TestCase):
    def test_unmanaged_needs_force(self):
        event = managed_event(extendedProperties={})
        with self.assertRaises(me.GuardError):
            me.check_writable(event, force=False)
        me.check_writable(event, force=True)

    def test_invited_event_rejected_even_with_force(self):
        event = managed_event(organizer={"email": "hr@corp.example", "self": False})
        with self.assertRaises(me.GuardError) as cm:
            me.check_writable(event, force=True)
        self.assertIn("主催者", str(cm.exception))

    def test_cancelled_rejected(self):
        with self.assertRaises(me.GuardError):
            me.check_writable(managed_event(status="cancelled"), force=True)

    def test_empty_id(self):
        with self.assertRaises(ValueError):
            me.get_event(FakeEvents(), "primary", " ")

    def test_guests_rejected_even_with_force(self):
        event = managed_event(attendees=[{"email": "me@example.com", "self": True}, {"email": "x@corp.example"}])
        with self.assertRaises(me.GuardError):
            me.check_writable(event, force=True)
        me.check_writable(managed_event(attendees=[{"email": "me@example.com", "self": True}]), force=False)


class UpdateTest(ManageTestCase):
    def test_reschedule_keeps_duration_and_uses_etag(self):
        fake = FakeEvents([managed_event()])
        res = me.cmd_update(args(id="ev1", start="2026-10-30 11:00"), fake, self.ctx, TOKYO)
        name, kw, headers = fake.calls[-1]
        self.assertEqual(name, "patch")
        self.assertEqual(kw["sendUpdates"], "none")
        self.assertEqual(headers["If-Match"], '"7"')
        self.assertEqual(kw["body"]["start"]["dateTime"], "2026-10-30T11:00:00+09:00")
        self.assertEqual(kw["body"]["end"]["dateTime"], "2026-10-30T12:00:00+09:00")
        self.assertEqual(set(kw["body"]), {"start", "end"})
        self.assertIn("start", res["diff"])
        backups = list((self.data_dir / "backups").glob("*_update_ev1.json"))
        self.assertEqual(len(backups), 1)
        self.assertIn('"2026-10-28T15:00:00+09:00"', backups[0].read_text(encoding="utf-8"))

    def test_company_key_keeps_marker(self):
        patch = me.build_patch(managed_event(company_key=None), TOKYO, company_key="acme")
        self.assertEqual(patch["extendedProperties"]["private"], {MANAGED_PROPERTY_KEY: "1", COMPANY_PROPERTY_KEY: "acme"})

    def test_all_day_time_change_rejected(self):
        event = managed_event(start={"date": "2026-10-28"}, end={"date": "2026-10-29"})
        with self.assertRaises(me.GuardError):
            me.build_patch(event, TOKYO, start="2026-10-28 10:00")
        self.assertEqual(me.build_patch(event, TOKYO, title="t"), {"summary": "t"})

    def test_unmanaged_rejected_before_patch(self):
        fake = FakeEvents([managed_event(extendedProperties={})])
        with self.assertRaises(me.GuardError):
            me.cmd_update(args(id="ev1", title="x"), fake, self.ctx, TOKYO)
        self.assertEqual(names(fake), ["get"])
        self.assertFalse((self.data_dir / "backups").exists())

    def test_nothing_to_change(self):
        fake = FakeEvents([managed_event()])
        with self.assertRaises(ValueError):
            me.cmd_update(args(id="ev1"), fake, self.ctx, TOKYO)

    def test_dry_run_does_not_patch(self):
        fake = FakeEvents([managed_event()])
        res = me.cmd_update(args(id="ev1", title="新", dry_run=True), fake, self.ctx, TOKYO)
        self.assertEqual(res["diff"]["summary"], {"before": "【面談】Acme カジュアル面談", "after": "新"})
        self.assertEqual(names(fake), ["get"])
        self.assertFalse((self.data_dir / "backups").exists())


class DeleteTest(ManageTestCase):
    def test_delete_backs_up_and_uses_etag(self):
        fake = FakeEvents([managed_event()])
        me.cmd_delete(args(id="ev1"), fake, self.ctx, TOKYO)
        name, kw, headers = fake.calls[-1]
        self.assertEqual((name, kw["sendUpdates"], headers["If-Match"]), ("delete", "none", '"7"'))
        self.assertNotIn("ev1", fake.store)
        self.assertEqual(len(list((self.data_dir / "backups").glob("*_delete_ev1.json"))), 1)

    def test_invited_event_not_deleted(self):
        fake = FakeEvents([managed_event(organizer={"email": "hr@corp.example"})])
        with self.assertRaises(me.GuardError):
            me.cmd_delete(args(id="ev1", force=True), fake, self.ctx, TOKYO)
        self.assertIn("ev1", fake.store)

    def test_dry_run_does_not_delete(self):
        fake = FakeEvents([managed_event()])
        me.cmd_delete(args(id="ev1", dry_run=True), fake, self.ctx, TOKYO)
        self.assertIn("ev1", fake.store)
        self.assertEqual(names(fake), ["get"])


if __name__ == "__main__":
    unittest.main()
