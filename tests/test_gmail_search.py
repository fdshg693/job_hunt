"""Gmail 検索・スレッド取得（scripts/gmail/search_messages.py, fetch_thread.py）の単体テスト.

Gmail API の service をフェイクに差し替え、ページネーション・保存済みスキップ・JOB ラベルの範囲・stdout の形式を確かめる。
"""

import base64
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from email.mime.text import MIMEText
from pathlib import Path
from unittest import mock

from scripts.gmail import client, fetch_thread, labels, search_messages
from scripts.google import client as google_client


def _raw(subject: str, body: str, sender: str) -> str:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = "me@example.com"
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii").rstrip("=")


class _Request:
    def __init__(self, fn, kwargs):
        self._fn = fn
        self._kwargs = kwargs

    def execute(self):
        return self._fn(**self._kwargs)


# Gmail 側のラベル（ユーザーラベルの ID は Label_*）
LABELS = [
    {"id": "INBOX", "name": "INBOX"},
    {"id": "Label_1", "name": "JOB"},
    {"id": "Label_2", "name": "JOB/RECRUITER"},
    {"id": "Label_3", "name": "JOB/SCHEDULE"},
    {"id": "Label_9", "name": "PRIVATE"},
]


class FakeGmail:
    """users().messages()/threads()/labels() の list/get だけを持つフェイク."""

    def __init__(self, threads: dict[str, list[dict]], page_size: int = 2, labels: list[dict] | None = None):
        # threads: {thread_id: [{id, internalDate, subject, from, body, labelIds}]}（古い順）
        self.data = threads
        self.page_size = page_size
        self.labels_data = LABELS if labels is None else labels
        self.calls: list[tuple[str, dict]] = []

    # --- チェーン ---
    def users(self):
        return self

    def messages(self):
        self._target = "messages"
        return self

    def threads(self):
        self._target = "threads"
        return self

    def labels(self):
        self._target = "labels"
        return self

    def list(self, **kwargs):
        fn = self._labels_list if self._target == "labels" else self._messages_list
        return _Request(fn, kwargs)

    def get(self, **kwargs):
        fn = self._messages_get if self._target == "messages" else self._threads_get
        return _Request(fn, kwargs)

    # --- 実装 ---
    def _all_messages_newest_first(self):
        msgs = [(tid, m) for tid, ms in self.data.items() for m in ms]
        return sorted(msgs, key=lambda x: int(x[1]["internalDate"]), reverse=True)

    def _find(self, message_id):
        for tid, m in self._all_messages_newest_first():
            if m["id"] == message_id:
                return tid, m
        raise KeyError(message_id)

    def _labels_list(self, userId):
        self.calls.append(("labels.list", {}))
        return {"labels": self.labels_data}

    def _messages_list(self, userId, q, maxResults, pageToken=None):
        self.calls.append(("messages.list", {"q": q, "pageToken": pageToken}))
        allm = self._all_messages_newest_first()
        start = int(pageToken or 0)
        page = allm[start : start + self.page_size]
        resp = {
            "messages": [{"id": m["id"], "threadId": tid} for tid, m in page],
            "resultSizeEstimate": len(allm),
        }
        if start + self.page_size < len(allm):
            resp["nextPageToken"] = str(start + self.page_size)
        return resp

    def _messages_get(self, userId, id, format, metadataHeaders=None):
        self.calls.append(("messages.get", {"id": id, "format": format}))
        tid, m = self._find(id)
        if format == "raw":
            return {"id": id, "threadId": tid, "raw": _raw(m["subject"], m["body"], m["from"])}
        headers = [{"name": "Subject", "value": m["subject"]}, {"name": "From", "value": m["from"]}]
        return {
            "id": id,
            "threadId": tid,
            "internalDate": m["internalDate"],
            "snippet": m["body"][:20],
            "labelIds": m["labelIds"],
            "payload": {"headers": headers},
        }

    def _threads_get(self, userId, id, format, metadataHeaders=None):
        self.calls.append(("threads.get", {"id": id, "format": format}))
        return {
            "id": id,
            "messages": [
                {"id": m["id"], "threadId": id, "internalDate": m["internalDate"], "labelIds": m["labelIds"]}
                for m in self.data[id]
            ],
        }

    def count(self, name, **match):
        return sum(1 for n, kw in self.calls if n == name and all(kw.get(k) == v for k, v in match.items()))


BASE_TS = 1_792_000_000_000  # 2026-10 頃（エポックミリ秒）


def _msg(mid, ts, subject="件名", sender="Recruiter <r@example.com>", body="本文", label_ids=("INBOX", "Label_1")):
    return {
        "id": mid,
        "internalDate": str(BASE_TS + ts),
        "subject": subject,
        "from": sender,
        "body": body,
        "labelIds": list(label_ids),
    }


def _sample_threads():
    return {
        "t1": [_msg("m1", 1_000), _msg("m4", 4_000, subject="Re: 件名", body="返信です")],
        "t2": [_msg("m2", 2_000, subject="スカウト")],
        "t3": [_msg("m3", 3_000, subject="面談日程")],
    }


class TestBuildQuery(unittest.TestCase):
    def test_combines_query_and_since(self):
        self.assertEqual(search_messages.build_query("from:a.com", "7d"), "from:a.com newer_than:7d")
        self.assertEqual(search_messages.build_query(None, "2m"), "newer_than:2m")
        self.assertEqual(search_messages.build_query(None, None), "")

    def test_rejects_bad_since(self):
        with self.assertRaises(ValueError):
            search_messages.build_query("x", "7 days")

    def test_scoped_query_wraps_user_query(self):
        self.assertEqual(search_messages.scoped_query("label:job", "a OR b"), "label:job (a OR b)")
        self.assertEqual(search_messages.scoped_query("label:job", ""), "label:job")


class TestLabels(unittest.TestCase):
    names = {label["id"]: label["name"] for label in LABELS}

    def test_scope_includes_sublabels(self):
        self.assertEqual(
            labels.scope_query(self.names), "{label:job label:job-recruiter label:job-schedule}"
        )
        self.assertEqual(labels.scope_query(self.names, "recruiter"), "label:job-recruiter")

    def test_scope_requires_label(self):
        with self.assertRaises(labels.LabelSetupError):
            labels.scope_query({"INBOX": "INBOX"})
        with self.assertRaises(labels.LabelSetupError):
            labels.scope_query({"Label_1": "JOB"}, "schedule")

    def test_job_label_matching(self):
        self.assertTrue(labels.is_job_label("JOB"))
        self.assertTrue(labels.is_job_label("job/recruiter"))
        self.assertFalse(labels.is_job_label("JOBS"))
        self.assertFalse(labels.has_job_label(["INBOX", "Label_9"], self.names))
        self.assertEqual(labels.label_names_of(["Label_2", "INBOX"], self.names), ["INBOX", "JOB/RECRUITER"])


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_pagination_groups_by_thread(self):
        fake = FakeGmail(_sample_threads(), page_size=2)
        hits, estimate = search_messages.list_thread_hits(fake, "q", limit=10)
        self.assertEqual([h["thread_id"] for h in hits], ["t1", "t3", "t2"])  # 最新ヒット順
        self.assertEqual(hits[0]["message_id"], "m4")
        self.assertEqual(hits[0]["hit_count"], 2)
        self.assertEqual(estimate, 4)
        self.assertEqual(fake.count("messages.list"), 2)

    def test_limit_stops_paging(self):
        fake = FakeGmail(_sample_threads(), page_size=2)
        hits, _ = search_messages.list_thread_hits(fake, "q", limit=2)
        self.assertEqual([h["thread_id"] for h in hits], ["t1", "t3"])
        self.assertEqual(fake.count("messages.list"), 1)

    def test_run_search_saves_list_without_bodies(self):
        fake = FakeGmail(_sample_threads())
        rows, paths = search_messages.run_search(fake, "from:example.com", 10, data_dir=self.data_dir)
        self.assertEqual(len(rows), 3)
        self.assertEqual([p.suffix for p in paths], [".md", ".json"])
        self.assertEqual(fake.count("messages.get", format="raw"), 0)
        payload = json.loads(paths[1].read_text(encoding="utf-8"))
        self.assertEqual(payload["query"], "from:example.com")
        self.assertEqual(payload["label"], "all")
        self.assertEqual(
            payload["gmail_query"], "{label:job label:job-recruiter label:job-schedule} (from:example.com)"
        )
        self.assertEqual(payload["threads"][0]["subject"], "Re: 件名")
        self.assertEqual(payload["threads"][0]["labels"], ["INBOX", "JOB"])
        self.assertIn("Re: 件名", paths[0].read_text(encoding="utf-8"))
        # 検索は必ず JOB ラベル配下に限る
        queries = [kw["q"] for name, kw in fake.calls if name == "messages.list"]
        self.assertTrue(queries)
        self.assertTrue(all(q.startswith("{label:job") for q in queries))

    def test_category_label_narrows_query(self):
        fake = FakeGmail(_sample_threads())
        search_messages.run_search(fake, "", 10, label="schedule", data_dir=self.data_dir)
        self.assertEqual(fake.count("messages.list", q="label:job-schedule", pageToken=None), 1)

    def test_missing_job_label_is_setup_error(self):
        fake = FakeGmail(_sample_threads(), labels=[{"id": "INBOX", "name": "INBOX"}])
        with self.assertRaises(labels.LabelSetupError):
            search_messages.run_search(fake, "q", 10, data_dir=self.data_dir)
        self.assertEqual(fake.count("messages.list"), 0)

    def test_thread_without_job_label_is_not_fetched(self):
        threads = {"t9": [_msg("m9", 9_000, label_ids=("INBOX", "Label_9"))]}
        fake = FakeGmail(threads)
        with self.assertRaises(fetch_thread.OutOfScopeError):
            fetch_thread.fetch_and_save_thread(fake, "t9", data_dir=self.data_dir)
        self.assertEqual(fake.count("messages.get", format="raw"), 0)
        self.assertFalse((self.data_dir / "threads" / "t9.md").exists())

    def test_download_saves_threads_and_skips_unchanged(self):
        fake = FakeGmail(_sample_threads())
        _, paths = search_messages.run_search(fake, "q", 10, download=True, data_dir=self.data_dir)
        thread_files = [p for p in paths if p.parent.name == "threads"]
        self.assertEqual(sorted(p.stem for p in thread_files), ["t1", "t2", "t3"])
        self.assertEqual(fake.count("messages.get", format="raw"), 4)
        t1 = (self.data_dir / "threads" / "t1.md").read_text(encoding="utf-8")
        self.assertIn("message_count: 2", t1)
        self.assertIn("- JOB", t1)
        self.assertIn("返信です", t1)

        # 2 回目: メッセージ数が変わらないので本文は取り直さない
        fake2 = FakeGmail(_sample_threads())
        search_messages.run_search(fake2, "q", 10, download=True, data_dir=self.data_dir)
        self.assertEqual(fake2.count("messages.get", format="raw"), 0)

        # 返信が増えたスレッドだけ取り直す
        threads = _sample_threads()
        threads["t2"].append(_msg("m5", 5_000, subject="Re: スカウト", body="追加の返信"))
        fake3 = FakeGmail(threads)
        search_messages.run_search(fake3, "q", 10, download=True, data_dir=self.data_dir)
        self.assertEqual(fake3.count("messages.get", format="raw"), 2)
        self.assertIn("追加の返信", (self.data_dir / "threads" / "t2.md").read_text(encoding="utf-8"))

        # --force は増えていなくても取り直す
        fake4 = FakeGmail(threads)
        fetch_thread.fetch_and_save_thread(fake4, "t3", force=True, data_dir=self.data_dir)
        self.assertEqual(fake4.count("messages.get", format="raw"), 1)


class TestStdout(unittest.TestCase):
    def test_stdout_is_paths_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            fake = FakeGmail(_sample_threads())
            out, err = io.StringIO(), io.StringIO()
            with (
                mock.patch.object(search_messages, "build_service", return_value=fake),
                mock.patch.object(search_messages, "DATA_DIR", data_dir),
                mock.patch.object(fetch_thread, "DATA_DIR", data_dir),
                mock.patch("sys.argv", ["search_messages.py", "-q", "from:example.com", "--download"]),
                redirect_stdout(out),
                redirect_stderr(err),
            ):
                code = search_messages.main()

            self.assertEqual(code, 0)
            lines = out.getvalue().splitlines()
            self.assertEqual(len(lines), 5)  # 一覧 .md / .json ＋ スレッド 3 件
            for line in lines:
                self.assertTrue(line.endswith((".md", ".json")), line)
                self.assertNotIn("件名", line)

    def test_auth_error_exits_2(self):
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(fetch_thread, "build_service", side_effect=client.GoogleAuthError("トークン失効")),
            mock.patch("sys.argv", ["fetch_thread.py", "--thread-id", "t1"]),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = fetch_thread.main()
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("scripts/google/auth.py", err.getvalue())


class TestRetry(unittest.TestCase):
    def _http_error(self, status, reason=None):
        from googleapiclient.errors import HttpError

        resp = mock.Mock(status=status, reason="")
        content = json.dumps({"error": {"errors": [{"reason": reason}] if reason else []}}).encode()
        return HttpError(resp, content)

    def test_retries_rate_limit_then_succeeds(self):
        request = mock.Mock()
        request.execute.side_effect = [
            self._http_error(429),
            self._http_error(403, "userRateLimitExceeded"),
            {"ok": True},
        ]
        with mock.patch.object(google_client, "_sleep") as sleep, redirect_stderr(io.StringIO()):
            self.assertEqual(client.execute(request), {"ok": True})
        self.assertEqual(sleep.call_count, 2)

    def test_does_not_retry_permission_error(self):
        request = mock.Mock()
        request.execute.side_effect = [self._http_error(403, "insufficientPermissions")]
        from googleapiclient.errors import HttpError

        with mock.patch.object(google_client, "_sleep") as sleep, self.assertRaises(HttpError):
            client.execute(request)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
