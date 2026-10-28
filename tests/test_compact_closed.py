"""見送り企業の圧縮 CLI (scripts/vault/compact_closed.py) の単体テスト."""

import datetime as dt
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# プロジェクトルート設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.vault.compact_closed import (
    REASON_PLACEHOLDER,
    CompactionError,
    apply_company,
    apply_screening,
    archive_path,
    draft_entry,
    find_company,
    list_candidates,
)
from scripts.vault.loader import load_vault
from scripts.vault.schema import ArchivedStatus, ArchiveDoc, ArchiveSource, CompanyStatus

TODAY = dt.date(2026, 10, 30)

SCREENING = """---
date: "2026-10-01"
type: "discarded_batch"
topic: "テストスクリーニング"
companies:
  - name: "株式会社スクリーン"
    aliases:
      - "スクリーン"
    reason: "出社前提"
  - name: "株式会社ネクスト"
    reason: "年収上限低め"
---

# 本文
"""

ARCHIVE = """---
type: "closed_archive"
track: "domestic"
updated_at: "2026-10-20"
companies:
  - name: "株式会社サマリ済"
    company_key: "summarized"
    status: "declined"
    considered_at: "2026-10-01"
    closed_at: "2026-10-05"
    reason: "出社週3"
    source: "company_log"
---

# 見送り台帳

手書きの説明は残す。
"""


def _write_company(root: Path, key: str, status: str, updated_at: str, extra: str = "") -> Path:
    folder = root / "vault" / "tracks" / "domestic" / "companies" / key
    folder.mkdir(parents=True)
    (folder / "index.md").write_text(
        f'---\ncompany: "株式会社{key}"\ncompany_key: "{key}"\naliases:\n  - "{key}"\ntrack: "domestic"\n'
        f'status: "{status}"\ndate: "2026-10-01"\nupdated_at: "{updated_at}"\n'
        f'fit_score_min: 40\nfit_score_max: 60\ndecline_reason: "理由"\n{extra}---\n\n# 本文\n',
        encoding="utf-8",
    )
    return folder


def _write_interview(folder: Path, date: str, stage: str) -> None:
    (folder / f"{date}_{stage}.md").write_text(
        f'---\ndate: "{date}"\nstage: "{stage}"\nresult: "not_applicable"\n---\n\n# 面談\n', encoding="utf-8"
    )


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


@unittest.skipIf(shutil.which("git") is None, "git が必要")
class TestCompactClosed(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.track_dir = self.root / "vault" / "tracks" / "domestic"
        self.track_dir.mkdir(parents=True)

        old = _write_company(self.root, "old-declined", "declined", "2026-10-10")
        _write_interview(old, "2026-10-03", "casual")
        _write_interview(old, "2026-10-08", "1st-interview")
        _write_company(self.root, "recent-declined", "declined", "2026-10-25")
        _write_company(self.root, "old-active", "considering", "2026-10-01")
        _write_company(self.root, "black", "blacklisted", "2026-10-02")
        (self.track_dir / "screening").mkdir()
        (self.track_dir / "screening" / "2026-10-01_test.md").write_text(SCREENING, encoding="utf-8")

        _git(self.root, "init", "-q")
        _git(self.root, "config", "user.email", "test@example.com")
        _git(self.root, "config", "user.name", "test")
        self._commit()

    def tearDown(self):
        self._tmp.cleanup()

    def _commit(self):
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "fixture")

    def _vault(self):
        return load_vault(self.root)

    # --- list / draft ---------------------------------------------------------

    def test_list_candidates_by_days(self):
        candidates = list_candidates(self._vault(), "domestic", TODAY, 14)
        keys = [c.doc.folder_key or c.doc.path.name for c in candidates]
        # 終了して 14 日以上（10/16 以前）のものだけ。active は日付に関係なく出ない
        self.assertEqual(keys, ["2026-10-01_test.md", "black", "old-declined"])
        self.assertEqual(
            [c.kind for c in list_candidates(self._vault(), "domestic", TODAY, 0)].count("company"), 3
        )

    def test_draft_entry_from_company_log(self):
        vault = self._vault()
        entry = draft_entry(vault, find_company(vault, "old-declined", None))
        self.assertEqual(entry.name, "株式会社old-declined")
        self.assertEqual(entry.company_key, "old-declined")
        self.assertEqual(entry.aliases, ["old-declined"])
        self.assertEqual(entry.status, ArchivedStatus.DECLINED)
        self.assertEqual(entry.considered_at, dt.date(2026, 10, 1))
        self.assertEqual(entry.closed_at, dt.date(2026, 10, 10))
        self.assertEqual(entry.reached, CompanyStatus.FIRST_INTERVIEW)  # 面談ログの最も進んだ段階
        self.assertEqual((entry.fit_score_min, entry.fit_score_max), (40, 60))
        self.assertEqual(entry.reason, REASON_PLACEHOLDER)
        self.assertEqual(entry.source, ArchiveSource.COMPANY_LOG)

    def test_active_company_is_refused_even_with_key(self):
        with self.assertRaises(CompactionError):
            find_company(self._vault(), "old-active", None)
        with self.assertRaises(CompactionError):
            apply_company(self._vault(), self.root, "old-active", overrides={"reason": "x"}, today=TODAY)

    # --- apply（企業フォルダ） --------------------------------------------------

    def test_apply_refuses_without_entry_or_reason(self):
        with self.assertRaises(CompactionError):
            apply_company(self._vault(), self.root, "old-declined", today=TODAY)
        self.assertTrue((self.track_dir / "companies" / "old-declined").exists())
        self.assertFalse(archive_path(self.root, "domestic").exists())

    def test_apply_with_reason_creates_archive_and_removes_folder(self):
        result = apply_company(
            self._vault(), self.root, "old-declined",
            overrides={"reason": "出社週3が必須", "reconsider_if": "週1以下になったら"}, today=TODAY,
        )
        self.assertEqual(result.archive, archive_path(self.root, "domestic"))
        self.assertFalse((self.track_dir / "companies" / "old-declined").exists())
        self.assertIn("D  vault/tracks/domestic/companies/old-declined/index.md", _git(self.root, "status", "--porcelain"))

        vault = self._vault()
        self.assertEqual(vault.errors, [])
        doc = vault.archive("domestic")
        self.assertIsInstance(doc.model, ArchiveDoc)
        self.assertEqual(doc.model.updated_at, TODAY)
        [entry] = doc.model.companies
        self.assertEqual((entry.company_key, entry.reason, entry.reconsider_if), ("old-declined", "出社週3が必須", "週1以下になったら"))
        self.assertEqual(entry.reached, CompanyStatus.FIRST_INTERVIEW)

    def test_apply_uses_existing_entry_and_keeps_body(self):
        archive = archive_path(self.root, "domestic")
        archive.write_text(ARCHIVE.replace("summarized", "old-declined"), encoding="utf-8")
        self._commit()
        before = archive.read_text(encoding="utf-8")

        result = apply_company(self._vault(), self.root, "old-declined", today=TODAY)
        self.assertEqual(result.added, [])
        self.assertEqual(archive.read_text(encoding="utf-8"), before)  # 台帳は変えずフォルダだけ消す
        self.assertFalse((self.track_dir / "companies" / "old-declined").exists())

    def test_apply_refuses_reason_when_entry_exists(self):
        archive_path(self.root, "domestic").write_text(ARCHIVE.replace("summarized", "old-declined"), encoding="utf-8")
        self._commit()
        with self.assertRaises(CompactionError):
            apply_company(self._vault(), self.root, "old-declined", overrides={"reason": "x"}, today=TODAY)
        self.assertTrue((self.track_dir / "companies" / "old-declined").exists())

    def test_apply_appends_to_existing_archive(self):
        archive = archive_path(self.root, "domestic")
        archive.write_text(ARCHIVE, encoding="utf-8")
        self._commit()

        apply_company(self._vault(), self.root, "black", overrides={"reason": "強引な勧誘"}, today=TODAY)
        text = archive.read_text(encoding="utf-8")
        self.assertIn("手書きの説明は残す。", text)
        model = self._vault().archive("domestic").model
        self.assertEqual([e.company_key for e in model.companies], ["summarized", "black"])
        self.assertEqual(model.companies[1].status, ArchivedStatus.BLACKLISTED)

    def test_apply_refuses_uncommitted_changes(self):
        index = self.track_dir / "companies" / "old-declined" / "index.md"
        index.write_text(index.read_text(encoding="utf-8") + "\n追記\n", encoding="utf-8")
        with self.assertRaises(CompactionError):
            apply_company(self._vault(), self.root, "old-declined", overrides={"reason": "x"}, today=TODAY)
        self.assertTrue(index.exists())
        self.assertFalse(archive_path(self.root, "domestic").exists())  # 拒否時は台帳にも書かない

    def test_apply_dry_run_changes_nothing(self):
        result = apply_company(
            self._vault(), self.root, "old-declined", overrides={"reason": "x"}, today=TODAY, dry_run=True
        )
        self.assertEqual(len(result.added), 1)
        self.assertTrue((self.track_dir / "companies" / "old-declined").exists())
        self.assertFalse(archive_path(self.root, "domestic").exists())

    # --- apply（スクリーニング） -------------------------------------------------

    def test_apply_screening_converts_entries(self):
        batch = self.track_dir / "screening" / "2026-10-01_test.md"
        result = apply_screening(self._vault(), self.root, batch, today=TODAY)
        self.assertEqual([e.name for e in result.added], ["株式会社スクリーン", "株式会社ネクスト"])
        self.assertFalse(batch.exists())

        vault = self._vault()
        self.assertEqual(vault.errors, [])
        first = vault.archive("domestic").model.companies[0]
        self.assertEqual(first.status, ArchivedStatus.DISCARDED)
        self.assertEqual(first.source, ArchiveSource.SCREENING)
        self.assertEqual((first.considered_at, first.closed_at), (dt.date(2026, 10, 1), dt.date(2026, 10, 1)))
        self.assertEqual(first.aliases, ["スクリーン"])
        self.assertIsNone(first.company_key)

    def test_apply_screening_skips_entries_already_in_archive(self):
        batch = self.track_dir / "screening" / "2026-10-01_test.md"
        archive = archive_path(self.root, "domestic")
        archive.write_text(
            ARCHIVE.replace(
                "---\n\n# 見送り台帳",
                '  - name: "株式会社スクリーン"\n    status: "discarded"\n    considered_at: "2026-10-01"\n'
                '    closed_at: "2026-10-01"\n    reason: "出社前提"\n    source: "screening"\n---\n\n# 見送り台帳',
            ),
            encoding="utf-8",
        )
        self._commit()
        result = apply_screening(self._vault(), self.root, batch, today=TODAY)
        self.assertEqual(result.skipped, ["株式会社スクリーン"])
        self.assertEqual([e.name for e in result.added], ["株式会社ネクスト"])
        self.assertEqual(len(self._vault().archive("domestic").model.companies), 3)


if __name__ == "__main__":
    unittest.main()
