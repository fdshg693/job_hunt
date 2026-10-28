"""Google 共通認証層（scripts/google/client.py）の単体テスト.

スコープの完全一致判定（不足・過剰・Gmail の変更系スコープ混入の拒否）と、認証情報ディレクトリの解決を確かめる。
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from scripts.google import auth, client


class TestCheckScopes(unittest.TestCase):
    def test_accepts_exact_union(self):
        client.check_scopes(client.GMAIL_SCOPES + client.CALENDAR_SCOPES)

    def test_accepts_space_separated_string(self):
        client.check_scopes(" ".join(reversed(client.SCOPES)))

    def test_rejects_gmail_only_token(self):
        # 統合前の token.json（gmail.readonly だけ）は不足として拒否する
        with self.assertRaises(client.GoogleAuthError) as cm:
            client.check_scopes(client.GMAIL_SCOPES)
        self.assertIn("不足", cm.exception.reason)
        self.assertIn("calendar.events.owned", cm.exception.reason)

    def test_rejects_calendar_only_token(self):
        # 分割同意で Gmail だけ外された場合
        with self.assertRaises(client.GoogleAuthError) as cm:
            client.check_scopes(client.CALENDAR_SCOPES)
        self.assertIn("gmail.readonly", cm.exception.reason)

    def test_rejects_gmail_modify(self):
        # 読み取り専用の担保: 和集合を満たしていても Gmail の変更系スコープが混ざれば拒否
        with self.assertRaises(client.GoogleAuthError) as cm:
            client.check_scopes(client.SCOPES + ["https://www.googleapis.com/auth/gmail.modify"])
        self.assertIn("想定外", cm.exception.reason)
        self.assertIn("gmail.modify", cm.exception.reason)

    def test_rejects_full_calendar_scope(self):
        with self.assertRaises(client.GoogleAuthError):
            client.check_scopes(client.SCOPES + ["https://www.googleapis.com/auth/calendar"])

    def test_rejects_empty(self):
        with self.assertRaises(client.GoogleAuthError):
            client.check_scopes(None)

    def test_scopes_is_union_without_duplicates(self):
        self.assertEqual(len(client.SCOPES), len(set(client.SCOPES)))
        self.assertEqual(set(client.SCOPES), set(client.GMAIL_SCOPES) | set(client.CALENDAR_SCOPES))
        # Gmail は readonly だけ
        self.assertEqual([s for s in client.SCOPES if "/auth/gmail" in s], ["https://www.googleapis.com/auth/gmail.readonly"])


class TestCredentialsDir(unittest.TestCase):
    def test_env_override(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {client.GOOGLE_DIR_ENV: tmp}):
            self.assertEqual(client.credentials_dir(), Path(tmp).resolve())
            self.assertEqual(client.token_path().name, "token.json")
            self.assertEqual(client.client_secret_path().name, "client_secret.json")

    def test_default_under_localappdata(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"LOCALAPPDATA": tmp}
            with mock.patch.dict("os.environ", env):
                import os

                os.environ.pop(client.GOOGLE_DIR_ENV, None)
                self.assertEqual(client.credentials_dir(), (Path(tmp) / "job-hunt" / "google").resolve())

    def test_old_gmail_env_is_ignored(self):
        # 旧 JOB_HUNT_GMAIL_DIR へのフォールバックは作らない
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as old:
            with mock.patch.dict("os.environ", {"LOCALAPPDATA": tmp, "JOB_HUNT_GMAIL_DIR": old}):
                import os

                os.environ.pop(client.GOOGLE_DIR_ENV, None)
                self.assertNotEqual(client.credentials_dir(), Path(old).resolve())


class TestLoadCredentials(unittest.TestCase):
    def test_missing_token_raises(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {client.GOOGLE_DIR_ENV: tmp}):
            with self.assertRaises(client.GoogleAuthError) as cm:
                client.load_credentials()
            self.assertIn("未認可", cm.exception.reason)

    def test_old_gmail_only_token_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {client.GOOGLE_DIR_ENV: tmp}):
            Path(tmp, "token.json").write_text(
                json.dumps({"token": "x", "refresh_token": "y", "client_id": "c", "client_secret": "s", "scopes": client.GMAIL_SCOPES}),
                encoding="utf-8",
            )
            with self.assertRaises(client.GoogleAuthError) as cm:
                client.load_credentials()
            self.assertIn("スコープ", cm.exception.reason)

    def test_check_cli_exits_2_with_handoff(self):
        out, err = io.StringIO(), io.StringIO()
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict("os.environ", {client.GOOGLE_DIR_ENV: tmp}),
            mock.patch("sys.argv", ["auth.py", "--check"]),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = auth.main()
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("scripts/google/auth.py", err.getvalue())


if __name__ == "__main__":
    unittest.main()
