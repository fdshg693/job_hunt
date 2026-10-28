"""雑務検出 CLI (scripts/vault/find_chores.py) の単体テスト."""

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

# プロジェクトルート設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.vault.find_chores import Handling, Priority, Thresholds, find_chores, is_memo_unfilled

TODAY = dt.date(2026, 10, 30)

TEMPLATE_MEMO = """# 面談

## 3. 面談メモ・質疑応答（一次情報）

### 企業・ポジション説明の要点
- 事業の現状と直近の注力分野:
- 評価制度・キャリアパス:

### こちらからの質問と回答
- **Q1. リモートワークの運用実態と出社頻度はどの程度ですか？**
  - **A**:

---

## 4. 所感・カルチャーマッチ・感想（主観メモ）
- 良い印象
"""

PREFILLED_MEMO = """## 4. 面談メモ・質疑応答（一次情報）

※ 面談実施後に記録

- **面談日時**: 2026-10-26（月） 10:00〜10:30
- **面談相手**: 田中氏（役職: ）
- **メモ内容**:
  -

---

## 5. 所感
"""

FILLED_MEMO = """## 4. 面談メモ・質疑応答（一次情報）

- **面談日時**: 2026-10-21（水）12:30〜13:30
- **出社**: 週1出社推奨。
"""


class _VaultBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root

    def company(self, key: str, *, status: str = "considering", updated_at: str = "2026-10-29",
                extra: str = "", body: str = "# 本文\n", track: str = "domestic") -> Path:
        folder = self.root / "vault" / "tracks" / track / "companies" / key
        folder.mkdir(parents=True, exist_ok=True)
        decline = 'decline_reason: "理由"\n' if status in ("declined", "rejected", "blacklisted") else ""
        (folder / "index.md").write_text(
            f'---\ncompany: "株式会社{key}"\ncompany_key: "{key}"\ntrack: "{track}"\nstatus: "{status}"\n'
            f'date: "2026-10-01"\nupdated_at: "{updated_at}"\nfit_score_min: 40\nfit_score_max: 60\n'
            f"{decline}{extra}---\n\n{body}",
            encoding="utf-8",
        )
        return folder

    def interview(self, folder: Path, date: str, stage: str = "casual", result: str = "not_applicable",
                  body: str = "# 面談\n") -> Path:
        path = folder / f"{date}_{stage}.md"
        path.write_text(f'---\ndate: "{date}"\nstage: "{stage}"\nresult: "{result}"\n---\n\n{body}', encoding="utf-8")
        return path

    def pipeline(self, *, updated_at: str, next_due: str | None = None, track: str = "domestic") -> None:
        folder = self.root / "vault" / "tracks" / track
        folder.mkdir(parents=True, exist_ok=True)
        due = f'next_due: "{next_due}"\n' if next_due else ""
        (folder / "pipeline.md").write_text(
            f'---\ntitle: "p"\ntrack: "{track}"\nupdated_at: "{updated_at}"\n{due}---\n\n# p\n', encoding="utf-8"
        )

    def recruiter(self, key: str, *, status: str = "active", updated_at: str) -> None:
        folder = self.root / "vault" / "recruiters" / key
        folder.mkdir(parents=True)
        (folder / "index.md").write_text(
            f'---\nname: "担当"\nrecruiter_key: "{key}"\nplatform: "linkedin"\nstatus: "{status}"\n'
            f'tracks:\n  - "domestic"\ndate: "2026-09-01"\nupdated_at: "{updated_at}"\n---\n\n# r\n',
            encoding="utf-8",
        )

    def profile(self, name: str, updated_at: str, *, en_source: str | None) -> None:
        profile = self.root / "vault" / "profile"
        (profile / "en").mkdir(parents=True, exist_ok=True)
        (profile / name).write_text(f'---\nupdated_at: "{updated_at}"\n---\n\n# p\n', encoding="utf-8")
        if en_source:
            (profile / "en" / name).write_text(
                f'---\nsource_updated_at: "{en_source}"\nsynced_at: "{en_source}"\n---\n\n# en\n', encoding="utf-8"
            )


    def material(self, folder: Path, slug: str, *, fetched_at: str, raw_data: list[str] | None = None) -> Path:
        (folder / "materials").mkdir(exist_ok=True)
        raw = "".join(f'  - "{r}"\n' for r in raw_data or [])
        raw_block = f'raw_data:\n{raw}raw_fetched_at: "{fetched_at}"\n' if raw else ""
        path = folder / "materials" / f"{slug}.md"
        path.write_text(f'---\ntitle: "資料"\nfetched_at: "{fetched_at}"\n{raw_block}---\n\n# 資料\n', encoding="utf-8")
        return path

    def recruiter_folder(self, key: str) -> Path:
        return self.root / "vault" / "recruiters" / key


class TestFindChores(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.v = _VaultBuilder(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def _chores(self, **kwargs):
        return find_chores(self.root, TODAY, **kwargs)

    def _ids(self, **kwargs):
        return [c.id for c in self._chores(**kwargs)]

    # --- 期限切れ・予定日過ぎ ------------------------------------------------------

    def test_overdue_action_boundary(self):
        self.v.company("past", extra='action_type: "action_required"\nnext_action: "返信"\nnext_due: "2026-10-29"\n')
        self.v.company("today", extra='action_type: "action_required"\nnext_action: "返信"\nnext_due: "2026-10-30"\n')
        ids = self._ids()
        self.assertIn("overdue-action:past", ids)
        self.assertNotIn("overdue-action:today", ids)  # 期限当日はまだ切れていない

    def test_past_scheduled_is_not_duplicated_as_overdue_or_warning(self):
        self.v.company("met", extra='action_type: "scheduled"\nnext_action: "面談"\nnext_due: "2026-10-28 10:00"\n')
        chores = self._chores()
        self.assertEqual([c.id for c in chores], ["past-scheduled:met"])
        self.assertEqual(chores[0].handling, Handling.ASK)
        self.assertEqual(chores[0].priority, Priority.DEADLINE)

    def test_closed_company_is_not_overdue(self):
        self.v.company("gone", status="declined",
                       extra='action_type: "action_required"\nnext_action: "返信"\nnext_due: "2026-10-01"\n')
        ids = self._ids(thresholds=Thresholds(compact_days=999))
        self.assertNotIn("overdue-action:gone", ids)
        # 終了しているのに action_type が残っている警告は、AI が直してよい雑務になる
        warning = next(c for c in self._chores(thresholds=Thresholds(compact_days=999)) if c.detector == "validate-warning")
        self.assertEqual(warning.handling, Handling.AUTO)

    # --- 連絡待ち・検討中の放置 ------------------------------------------------------

    def test_waiting_stale_threshold(self):
        self.v.company("w7", updated_at="2026-10-23", extra='action_type: "waiting"\nnext_action: "結果待ち"\n')
        self.v.company("w6", updated_at="2026-10-24", extra='action_type: "waiting"\nnext_action: "結果待ち"\n')
        ids = self._ids()
        self.assertIn("waiting-stale:w7", ids)  # ちょうど 7 日で出る
        self.assertNotIn("waiting-stale:w6", ids)

    def test_idle_company_threshold_and_status(self):
        self.v.company("idle", updated_at="2026-10-16")
        self.v.company("fresh", updated_at="2026-10-17")
        self.v.company("closed", status="rejected", updated_at="2026-10-01")
        ids = self._ids(thresholds=Thresholds(compact_days=999))
        self.assertIn("idle-company:idle", ids)
        self.assertNotIn("idle-company:fresh", ids)
        self.assertNotIn("idle-company:closed", ids)

    # --- 面談ログ -------------------------------------------------------------------

    def test_interview_result_pending_only_after_date(self):
        folder = self.v.company("c", body="[面談](2026-10-29_casual.md) [予定](2026-10-30_1st-interview.md)\n")
        self.v.interview(folder, "2026-10-29", result="pending")
        self.v.interview(folder, "2026-10-30", "1st-interview", result="pending")
        ids = self._ids()
        self.assertIn("interview-result:c/2026-10-29_casual", ids)
        self.assertNotIn("interview-result:c/2026-10-30_1st-interview", ids)

    def test_interview_memo_unfilled(self):
        folder = self.v.company("c", body="2026-10-28_casual.md 2026-10-29_casual.md\n")
        self.v.interview(folder, "2026-10-28", body=FILLED_MEMO)
        self.v.interview(folder, "2026-10-29", body=PREFILLED_MEMO)
        ids = self._ids()
        self.assertIn("interview-memo:c/2026-10-29_casual", ids)
        self.assertNotIn("interview-memo:c/2026-10-28_casual", ids)

    def test_interview_unlinked(self):
        folder = self.v.company("c", body="[カジュアル面談](2026-10-20_casual.md)\n")
        self.v.interview(folder, "2026-10-20")
        self.v.interview(folder, "2026-10-25", "1st-interview")
        chores = [c for c in self._chores() if c.detector == "interview-unlinked"]
        self.assertEqual([c.id for c in chores], ["interview-unlinked:c/2026-10-25_1st-interview"])
        self.assertEqual(chores[0].path, "vault/tracks/domestic/companies/c/index.md")
        self.assertEqual(chores[0].handling, Handling.AUTO)

    def test_memo_unfilled_judgement(self):
        self.assertTrue(is_memo_unfilled(TEMPLATE_MEMO))
        self.assertTrue(is_memo_unfilled(PREFILLED_MEMO))
        self.assertTrue(is_memo_unfilled("## 4. 面談メモ・質疑応答\n\n（面談後に記入）\n\n---\n"))
        self.assertFalse(is_memo_unfilled(FILLED_MEMO))
        self.assertFalse(is_memo_unfilled("# 面談\n\nメモ節の無い形式\n"))  # 節が無ければ判定しない

    # --- pipeline -------------------------------------------------------------------

    def test_pipeline_stale_by_next_due_and_company_update(self):
        self.v.company("c", updated_at="2026-10-29")
        self.v.pipeline(updated_at="2026-10-29", next_due="2026-11-05")
        self.assertNotIn("pipeline-stale:domestic", self._ids())
        self.v.pipeline(updated_at="2026-10-28", next_due="2026-11-05")
        self.assertIn("pipeline-stale:domestic", self._ids())
        self.v.pipeline(updated_at="2026-10-29", next_due="2026-10-29")
        self.assertIn("pipeline-stale:domestic", self._ids())

    def test_pipeline_without_companies_checks_only_next_due(self):
        self.v.pipeline(updated_at="2026-01-01", next_due="2026-12-31", track="overseas")
        self.assertNotIn("pipeline-stale:overseas", self._ids())

    # --- リクルーター・圧縮・英語版 ------------------------------------------------------

    def test_recruiter_stale(self):
        self.v.recruiter("linkedin_old", updated_at="2026-09-30")
        self.v.recruiter("linkedin_new", updated_at="2026-10-01")
        self.v.recruiter("linkedin_done", status="declined", updated_at="2026-01-01")
        ids = self._ids()
        self.assertIn("recruiter-stale:linkedin_old", ids)
        self.assertNotIn("recruiter-stale:linkedin_new", ids)
        self.assertNotIn("recruiter-stale:linkedin_done", ids)

    def test_compact_candidates(self):
        self.v.company("old", status="declined", updated_at="2026-10-16")
        self.v.company("recent", status="declined", updated_at="2026-10-17")
        ids = self._ids()
        self.assertIn("compact:old", ids)
        self.assertNotIn("compact:recent", ids)

    def test_english_sync(self):
        self.v.profile("resume.md", "2026-10-20", en_source="2026-10-20")
        self.v.profile("preferences.md", "2026-10-22", en_source="2026-10-19")
        self.v.profile("skills.md", "2026-10-20", en_source=None)
        ids = self._ids()
        self.assertIn("en-sync:preferences.md", ids)
        self.assertIn("en-sync:skills.md", ids)
        self.assertNotIn("en-sync:resume.md", ids)

    def test_no_english_dir_means_no_english_chores(self):
        self.v.company("c")
        self.assertFalse([i for i in self._ids() if i.startswith("en-sync:")])

    # --- 外部資料の鮮度・data/ の直接参照 ------------------------------------------------

    def test_material_stale_only_for_live_owners(self):
        live = self.v.company("live")
        self.v.material(live, "old", fetched_at="2026-08-31")  # 60 日前
        self.v.material(live, "fresh", fetched_at="2026-09-01")
        closed = self.v.company("closed", status="declined")
        self.v.material(closed, "old", fetched_at="2026-01-01")
        self.v.recruiter("li_rec", updated_at="2026-10-29")
        self.v.material(self.v.recruiter_folder("li_rec"), "deck", fetched_at="2026-08-15")
        ids = [i for i in self._ids() if i.startswith("material")]
        self.assertEqual(sorted(ids), ["material-stale:li_rec/deck", "material-stale:live/old"])
        self.assertEqual(
            [i for i in self._ids(thresholds=Thresholds(material_days=90)) if i.startswith("material")],
            [],
        )

    def test_material_raw_missing_replaces_stale_and_needs_stale(self):
        folder = self.v.company("c")
        (self.root / "data" / "speakerdeck" / "c" / "kept").mkdir(parents=True)
        self.v.material(folder, "gone", fetched_at="2026-08-01", raw_data=["data/speakerdeck/c/gone/"])
        self.v.material(folder, "kept", fetched_at="2026-08-01", raw_data=["data/speakerdeck/c/kept/"])
        self.v.material(folder, "recent", fetched_at="2026-10-20", raw_data=["data/speakerdeck/c/recent/"])
        ids = [i for i in self._ids() if i.startswith("material")]
        self.assertEqual(sorted(ids), ["material-raw-missing:c/gone", "material-stale:c/kept"])

    def test_data_ref_only_for_prunable_paths(self):
        self.v.company("ref", body="口コミ: data/openwork/reviews/a0C1.md\n")
        self.v.company("export", body="提出物: data/exports/2026-10-23_career.pdf と data/findy/\n")
        mat = self.v.company("mat")
        self.v.material(mat, "deck", fetched_at="2026-10-20", raw_data=["data/speakerdeck/mat/deck/"])
        chores = [c for c in self._chores() if c.detector == "data-ref"]
        self.assertEqual([c.id for c in chores], ["data-ref:vault/tracks/domestic/companies/ref/index.md"])
        self.assertEqual(chores[0].handling, Handling.CONFIRM)
        self.assertEqual(chores[0].track, "domestic")
        self.assertFalse([i for i in self._ids(track="overseas") if i.startswith("data-ref:")])

    # --- 並び順・track ----------------------------------------------------------------

    def test_order_by_priority_then_date(self):
        self.v.company("idle", updated_at="2026-09-01")
        self.v.company("late", extra='action_type: "action_required"\nnext_action: "返信"\nnext_due: "2026-10-29"\n')
        self.v.company("later", extra='action_type: "action_required"\nnext_action: "返信"\nnext_due: "2026-10-20"\n')
        self.assertEqual(self._ids(), ["overdue-action:later", "overdue-action:late", "idle-company:idle"])

    def test_track_filter_and_multi_track_ids(self):
        self.v.company("dup", updated_at="2026-09-01")
        self.v.company("dup", updated_at="2026-09-01", track="overseas")
        self.assertEqual(sorted(self._ids()), ["idle-company:dup@domestic", "idle-company:dup@overseas"])
        self.assertEqual(self._ids(track="overseas"), ["idle-company:dup@overseas"])


if __name__ == "__main__":
    unittest.main()
