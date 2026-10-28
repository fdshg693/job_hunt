"""pipeline 一覧自動生成 (scripts/vault/build_pipeline.py) の単体テスト."""

import sys
import tempfile
import unittest
from pathlib import Path

# プロジェクトルート設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.vault.build_pipeline import (
    BEGIN_MARKER,
    END_MARKER,
    build_pipeline,
    format_remote,
    format_salary,
    load_companies,
    render_block,
    replace_block,
)
from scripts.vault.schema import CompanyDoc

PIPELINE_TEMPLATE = f"""---
title: "パイプライン"
track: "domestic"
updated_at: "2026-10-01"
---

# パイプライン

## 次回アクション

- [ ] 手書きメモ

## 選考企業一覧

{BEGIN_MARKER}
古い一覧
{END_MARKER}

## 手書きセクション

残すべき内容
"""


def _write_company(companies_dir: Path, key: str, company: str, status: str, extra: str = "") -> None:
    (companies_dir / key).mkdir(parents=True)
    frontmatter = (
        f'company: "{company}"\ncompany_key: "{key}"\ntrack: "domestic"\nstatus: "{status}"\n'
        f'date: "2026-10-01"\n{extra}'
    )
    if "updated_at:" not in extra:
        frontmatter += 'updated_at: "2026-10-01"\n'
    (companies_dir / key / "index.md").write_text(f"---\n{frontmatter}---\n\n# 本文\n", encoding="utf-8")


def _doc(**overrides) -> CompanyDoc:
    data = {
        "company": "株式会社サンプル",
        "company_key": "sample",
        "track": "domestic",
        "status": "considering",
        "date": "2026-10-01",
        "updated_at": "2026-10-01",
    }
    return CompanyDoc.model_validate({**data, **overrides})


class TestBuildPipeline(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.track_dir = self.root / "vault" / "tracks" / "domestic"
        self.companies_dir = self.track_dir / "companies"
        _write_company(
            self.companies_dir,
            "alpha",
            "アルファ株式会社",
            "considering",
            "fit_score_min: 60\nfit_score_max: 80\ninterest: 3\nsalary_min: 600\nsalary_max: 900\n",
        )
        _write_company(
            self.companies_dir,
            "beta",
            "ベータ株式会社",
            "casual_interview",
            'status_note: "面談|日程調整中"\nupdated_at: "2026-10-02"\nremote_type: "hybrid"\noffice_days_per_week: 2\n',
        )
        _write_company(self.companies_dir, "gamma", "ガンマ株式会社", "declined", 'decline_reason: "出社"\n')
        # 同居する面談ログは対象外
        (self.companies_dir / "beta" / "2026-10-05_casual.md").write_text(
            '---\ncompany: "面談ログ"\ndate: "2026-10-05"\nstage: "casual"\n---\n', encoding="utf-8"
        )
        (self.track_dir / "pipeline.md").write_text(PIPELINE_TEMPLATE, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_load_companies_skips_invalid_with_warning(self):
        # status 欠落はスキーマ違反なので一覧に載せず警告
        (self.companies_dir / "delta").mkdir()
        (self.companies_dir / "delta" / "index.md").write_text('---\ncompany: "デルタ株式会社"\n---\n', encoding="utf-8")
        companies, warnings = load_companies(self.root, "domestic")
        self.assertEqual({c.key for c in companies}, {"alpha", "beta", "gamma"})
        self.assertEqual(len(warnings), 1)
        self.assertIn("delta", warnings[0])

    def test_load_companies_filters_track(self):
        self.assertEqual(load_companies(self.root, "overseas"), ([], []))

    def test_render_block_lists_only_active_in_stage_order(self):
        companies, _ = load_companies(self.root, "domestic")
        block = render_block(companies)

        self.assertTrue(block.startswith(BEGIN_MARKER))
        self.assertTrue(block.endswith(END_MARKER))
        # 進行中アクション見出しと全体一覧見出しが含まれる
        self.assertIn("### 🔴 要対応（自分ボール）", block)
        self.assertIn("### 📅 確定済予定", block)
        self.assertIn("### ⏳ 結果・連絡待ち（相手ボール）", block)
        self.assertIn("### 📋 選考・検討中企業一覧", block)
        # 進んでいる選考（カジュアル面談）が検討中より上。ラベルはスキーマ由来
        self.assertLess(block.index("ベータ株式会社"), block.index("アルファ株式会社"))
        self.assertIn("| カジュアル面談 |", block)
        # 辞退は一覧に載せず件数のみ
        self.assertNotIn("ガンマ株式会社", block)
        self.assertIn("見送り・辞退: 1社", block)
        # 構造化フィールドの表記
        self.assertIn("| 600〜900万円 |", block)
        self.assertIn("| ハイブリッド（週2出社） |", block)
        self.assertIn("| 60〜80 |", block)
        self.assertIn("| ★★★ |", block)
        # セル内のパイプはエスケープ
        self.assertIn("面談\\|日程調整中", block)
        self.assertIn("(companies/beta/index.md)", block)

    def test_render_block_with_action_tracking(self):
        _write_company(
            self.companies_dir,
            "act1",
            "要対応社A",
            "casual_interview",
            'action_type: "action_required"\nnext_action: "面談日程返信"\nnext_due: "2026-10-25"\n',
        )
        _write_company(
            self.companies_dir,
            "act2",
            "要対応社B（直近）",
            "first_interview",
            'action_type: "action_required"\nnext_action: "課題提出"\nnext_due: "2026-10-20"\n',
        )
        _write_company(
            self.companies_dir,
            "sch1",
            "面談予定社",
            "casual_interview",
            'action_type: "scheduled"\nnext_action: "カジュアル面談"\nnext_due: "2026-10-22 19:00"\n',
        )
        _write_company(
            self.companies_dir,
            "wait1",
            "結果待ち社A",
            "first_interview",
            'action_type: "waiting"\nnext_action: "1次面接結果待ち"\nupdated_at: "2026-10-18"\n',
        )
        _write_company(
            self.companies_dir,
            "wait2",
            "結果待ち社B（最新）",
            "second_interview",
            'action_type: "waiting"\nnext_action: "2次面接日程調整待ち"\nupdated_at: "2026-10-19"\n',
        )
        # 辞退企業に action_type が残っていても除外
        _write_company(
            self.companies_dir,
            "declined-act",
            "辞退企業",
            "declined",
            'decline_reason: "x"\naction_type: "action_required"\nnext_action: "返信不要"\n',
        )

        companies, _ = load_companies(self.root, "domestic")
        block = render_block(companies)

        # 🔴 要対応: next_due 昇順（2026-10-20 が 2026-10-25 より前）
        self.assertLess(block.index("要対応社B（直近）"), block.index("要対応社A"))

        # 📅 確定済予定（日時は元の書式で表示）
        self.assertIn("面談予定社", block)
        self.assertIn("2026-10-22 19:00", block)

        # ⏳ 結果待ち: updated_at 降順（2026-10-19 が 2026-10-18 より前）
        self.assertLess(block.index("結果待ち社B（最新）"), block.index("結果待ち社A"))

        # 辞退企業はアクションテーブルにも全体一覧にも表示されない
        self.assertNotIn("辞退企業", block)

    def test_build_pipeline_preserves_handwritten_sections(self):
        path, _, _, changed = build_pipeline("domestic", root=self.root)
        self.assertTrue(changed)
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("古い一覧", text)
        self.assertIn("- [ ] 手書きメモ", text)
        self.assertIn("残すべき内容", text)
        self.assertIn("アルファ株式会社", text)

        # 2回目は変更なし（冪等）
        _, _, _, changed_again = build_pipeline("domestic", root=self.root)
        self.assertFalse(changed_again)

    def test_archived_count_is_shown_separately(self):
        from tests.test_vault_loader import ARCHIVE

        companies, _ = load_companies(self.root, "domestic")
        self.assertNotIn("見送り台帳", render_block(companies))
        self.assertIn("見送り・辞退: 1社（ほかに見送り台帳: 2社）", render_block(companies, archived=2))

        (self.track_dir / "archive.md").write_text(ARCHIVE, encoding="utf-8")
        path, _, _, _ = build_pipeline("domestic", root=self.root)
        self.assertIn("（ほかに見送り台帳: 2社）", path.read_text(encoding="utf-8"))

    def test_build_pipeline_keeps_crlf(self):
        pipeline_md = self.track_dir / "pipeline.md"
        pipeline_md.write_bytes(PIPELINE_TEMPLATE.replace("\n", "\r\n").encode("utf-8"))
        build_pipeline("domestic", root=self.root)
        raw = pipeline_md.read_bytes().decode("utf-8")
        self.assertNotIn("\n", raw.replace("\r\n", ""))

    def test_replace_block_requires_markers(self):
        with self.assertRaises(ValueError):
            replace_block("マーカーなし", "block")


class TestCellFormat(unittest.TestCase):
    def test_format_salary(self):
        self.assertEqual(format_salary(_doc()), "")
        self.assertEqual(format_salary(_doc(salary_min=600, salary_max=900)), "600〜900万円")
        self.assertEqual(format_salary(_doc(salary_min=500)), "500万円〜")
        self.assertEqual(format_salary(_doc(salary_max=900)), "〜900万円")
        self.assertEqual(format_salary(_doc(salary_min=700, salary_max=700)), "700万円")

    def test_format_remote(self):
        self.assertEqual(format_remote(_doc()), "")
        self.assertEqual(format_remote(_doc(remote_type="full_remote")), "フルリモート")
        self.assertEqual(format_remote(_doc(remote_type="hybrid", office_days_per_week=2)), "ハイブリッド（週2出社）")
        self.assertEqual(format_remote(_doc(remote_type="mostly_remote", office_days_per_week=0.5)), "リモート中心（月2出社）")


if __name__ == "__main__":
    unittest.main()
