"""重複チェックおよび企業一覧取得モジュール (scripts/common/check_company.py) の単体テスト."""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

# プロジェクトルート設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.check_company import (
    CompanyEntry,
    CompanyRegistry,
    canonical_key,
    check_company,
    main,
)


class TestCanonicalKey(unittest.TestCase):
    def test_canonical_key_variations(self):
        # 法人格（前株・後株・括弧）
        self.assertEqual(canonical_key("株式会社ラクス"), "ラクス")
        self.assertEqual(canonical_key("ラクス株式会社"), "ラクス")
        self.assertEqual(canonical_key("（株）ラクス"), "ラクス")
        self.assertEqual(canonical_key("(株)ラクス"), "ラクス")

        # 英語・記号・大文字小文字
        self.assertEqual(canonical_key("BALUS Co., Ltd."), "balus")
        self.assertEqual(canonical_key("Balus Inc."), "balus")
        self.assertEqual(canonical_key("SecureNavi 株式会社"), "securenavi")
        self.assertEqual(canonical_key("株式会社on call"), "oncall")

        # 全角英数・記号
        self.assertEqual(
            canonical_key("ＫＤＤＩアジャイル開発センター株式会社"),
            "kddiアジャイル開発センター",
        )
        self.assertEqual(
            canonical_key("KDDIアジャイル開発センター株式会社"),
            "kddiアジャイル開発センター",
        )

        # 空白・空文字
        self.assertEqual(canonical_key(""), "")
        self.assertEqual(canonical_key("   "), "")


class TestCompanyRegistry(unittest.TestCase):
    def test_add_or_update_and_merge(self):
        registry = CompanyRegistry()

        # 1. active として初期登録
        entry1 = registry.add_or_update_entry(
            name="株式会社サンプル",
            status="considering",
            aliases=["サンプル", "Sample Corp"],
            reason="",
            source_file="vault/tracks/domestic/companies/sample/index.md",
        )
        self.assertEqual(entry1.name, "株式会社サンプル")
        self.assertEqual(entry1.category, "active")
        self.assertFalse(entry1.is_exclusion)
        self.assertIn("vault/tracks/domestic/companies/sample/index.md", entry1.source_files)

        # 2. その後 declined として更新（別名 "SAMPLE" 追加、理由追加）
        entry2 = registry.add_or_update_entry(
            name="サンプル",
            status="declined",
            aliases=["SAMPLE", "Sample Ltd."],
            reason="出社週3日必須のため見送り",
            source_file="vault/tracks/domestic/companies/sample-old/index.md",
        )
        # 同じ canonical_key なので同一エントリが更新される
        self.assertEqual(entry2.status, "declined")
        self.assertEqual(entry2.category, "exclusion")
        self.assertTrue(entry2.is_exclusion)
        self.assertIn("Sample Corp", entry2.aliases)
        self.assertIn("vault/tracks/domestic/companies/sample/index.md", entry2.source_files)
        self.assertIn("vault/tracks/domestic/companies/sample-old/index.md", entry2.source_files)
        self.assertIn("出社週3日必須のため見送り", entry2.reason)

    def test_find_matches(self):
        registry = CompanyRegistry()
        registry.add_or_update_entry(
            name="株式会社ラクス",
            status="declined",
            aliases=["ラクス", "RAKUS"],
            reason="週4日出社必須",
        )
        registry.add_or_update_entry(
            name="バルス株式会社",
            status="declined",
            aliases=["Balus", "SPWN"],
            reason="残業37h・突発対応",
        )
        registry.add_or_update_entry(
            name="KDDIアジャイル開発センター株式会社",
            status="discarded",
            aliases=["KAG"],
            reason="出社前提",
        )

        # 1. 完全一致
        matches_exact = registry.find_matches("株式会社ラクス")
        self.assertTrue(len(matches_exact) > 0)
        self.assertEqual(matches_exact[0].match_type, "exact")
        self.assertEqual(matches_exact[0].score, 1.0)
        self.assertTrue(matches_exact[0].is_exclusion)

        # 2. 別名完全一致
        matches_alias = registry.find_matches("RAKUS")
        self.assertTrue(len(matches_alias) > 0)
        self.assertEqual(matches_alias[0].match_type, "alias_exact")
        self.assertEqual(matches_alias[0].entry.name, "株式会社ラクス")

        # 3. 法人格なし入力
        matches_bare = registry.find_matches("バルス")
        self.assertTrue(len(matches_bare) > 0)
        self.assertEqual(matches_bare[0].score, 1.0)

        # 4. 部分一致 (KDDI -> KDDIアジャイル開発センター)
        matches_sub = registry.find_matches("KDDI")
        self.assertTrue(len(matches_sub) > 0)
        self.assertIn(matches_sub[0].match_type, ("substring", "alias_substring"))
        self.assertEqual(matches_sub[0].entry.name, "KDDIアジャイル開発センター株式会社")

        # 5. 未登録企業
        matches_none = registry.find_matches("まったく存在しない未知の会社XYZ")
        self.assertEqual(len(matches_none), 0)

    def test_is_excluded(self):
        registry = CompanyRegistry()
        registry.add_or_update_entry(
            name="株式会社プラスアルファ・コンサルティング",
            status="blacklisted",
            reason="1社目出禁",
        )
        registry.add_or_update_entry(
            name="株式会社グラファー",
            status="considering",
            notes="選考検討中",
        )

        # 除外企業
        is_exc, match_exc = registry.is_excluded("プラスアルファ・コンサルティング")
        self.assertTrue(is_exc)
        self.assertIsNotNone(match_exc)
        self.assertEqual(match_exc.entry.status, "blacklisted")

        # 検討中企業 (除外ではない)
        is_active, match_active = registry.is_excluded("グラファー")
        self.assertFalse(is_active)

    def test_discarded_file_parsing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            chat_discarded = tmp_path / "vault" / "tracks" / "domestic" / "screening"
            chat_discarded.mkdir(parents=True, exist_ok=True)

            sample_md = chat_discarded / "2026-10-08_batch.md"
            sample_content = """---
date: "2026-10-08"
type: discarded_batch
topic: "テストバッチ"
companies:
  - name: "テストA株式会社"
    reason: "週5日出社必須"
  - name: "テストB株式会社"
    aliases: ["TestB"]
    reason: "年収レンジ乖離"
---

# バッチ打ち切りログ
"""
            sample_md.write_text(sample_content, encoding="utf-8")

            registry = CompanyRegistry(root_dir=tmp_path)
            registry.load_all()

            # テストA
            matches_a = registry.find_matches("テストA")
            self.assertTrue(len(matches_a) > 0)
            self.assertEqual(matches_a[0].entry.status, "discarded")
            self.assertIn("週5日出社必須", matches_a[0].entry.reason)

            # テストB (aliases)
            matches_b = registry.find_matches("TestB")
            self.assertTrue(len(matches_b) > 0)
            self.assertEqual(matches_b[0].entry.name, "テストB株式会社")
            self.assertIn("年収レンジ乖離", matches_b[0].entry.reason)


    def test_vault_layout_loading(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            companies = tmp_path / "vault" / "tracks" / "domestic" / "companies"
            (companies / "sample").mkdir(parents=True)
            (companies / "sample" / "index.md").write_text(
                '---\ncompany: "株式会社サンプル"\ncompany_key: "sample"\ntrack: "domestic"\nstatus: "declined"\n'
                'decline_reason: "週3出社"\ndate: "2026-10-01"\nupdated_at: "2026-10-01"\n---\n',
                encoding="utf-8",
            )
            # 同居する面談ログは企業エントリとして読まない
            (companies / "sample" / "2026-10-01_casual.md").write_text(
                '---\ncompany: "株式会社面談ログ"\n---\n',
                encoding="utf-8",
            )
            # status 欠落（スキーマ違反）も読めた範囲で登録し、researching 扱い
            (companies / "nostatus").mkdir()
            (companies / "nostatus" / "index.md").write_text(
                '---\ncompany: "ステータス無し株式会社"\n---\n',
                encoding="utf-8",
            )
            employers = tmp_path / "vault" / "profile" / "employers"
            employers.mkdir(parents=True)
            (employers / "prev.md").write_text(
                '---\ncompany: "前職株式会社"\ncompany_key: "prev"\nstatus: "employer"\n'
                'date: "2026-10-01"\nupdated_at: "2026-10-01"\n---\n',
                encoding="utf-8",
            )

            registry = CompanyRegistry(root_dir=tmp_path)
            registry.load_all()

            sample = registry.find_matches("サンプル")[0]
            self.assertEqual(sample.entry.status, "declined")
            self.assertTrue(sample.is_exclusion)
            self.assertEqual(registry.find_matches("ステータス無し")[0].entry.status, "researching")
            employer = registry.find_matches("前職")[0]
            self.assertEqual(employer.entry.category, "employer")
            # 前職・現職は全 track で除外
            self.assertTrue(employer.is_exclusion)
            self.assertTrue(registry.is_excluded("前職", track="overseas")[0])
            self.assertEqual(registry.find_matches("面談ログ"), [])
            self.assertEqual(sample.entry.track, "domestic")
            self.assertTrue(sample.entry.log_path.endswith("vault/tracks/domestic/companies/sample/index.md"))

    def test_cross_track_matching(self):
        registry = CompanyRegistry()
        registry.add_or_update_entry(name="株式会社サンプル", status="declined", reason="週3出社", track="domestic")
        registry.add_or_update_entry(name="サンプル", status="considering", track="overseas")
        registry.add_or_update_entry(name="出禁株式会社", status="blacklisted", track="domestic")
        registry.add_or_update_entry(name="前職株式会社", status="employer")

        # track が異なれば別エントリとして保持する
        self.assertEqual(len(registry.find_matches("サンプル")), 2)

        # 既定（all）: 全 track を同一扱いで除外判定
        self.assertTrue(registry.is_excluded("サンプル")[0])

        # overseas 照会: 国内の辞退は除外せず他 track 履歴として提示し、同一 track のヒットを優先
        matches = registry.find_matches("サンプル", track="overseas")
        self.assertEqual(matches[0].entry.track, "overseas")
        other = matches[1]
        self.assertTrue(other.is_other_track)
        self.assertFalse(other.is_exclusion)
        self.assertFalse(registry.is_excluded("サンプル", track="overseas")[0])

        # blacklisted は全 track で除外、track 非依存エントリは他 track 扱いしない
        self.assertTrue(registry.is_excluded("出禁", track="overseas")[0])
        employer = registry.find_matches("前職", track="overseas")[0]
        self.assertFalse(employer.is_other_track)

        # 一覧の track 絞り込み（track 非依存エントリは含む）
        names = {e.name for e in registry.list_entries(track="overseas")}
        self.assertEqual(names, {"サンプル", "前職株式会社"})


    def test_archive_entries(self):
        from tests.test_vault_loader import ARCHIVE

        blacklisted = (
            '  - name: "出禁株式会社"\n    status: "blacklisted"\n    considered_at: "2026-10-01"\n'
            '    closed_at: "2026-10-02"\n    reason: "虚偽の求人"\n    source: "screening"\n'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            domestic = root / "vault" / "tracks" / "domestic"
            domestic.mkdir(parents=True)
            (domestic / "archive.md").write_text(
                ARCHIVE.replace('    source: "screening"\n', '    source: "screening"\n' + blacklisted),
                encoding="utf-8",
            )
            registry = CompanyRegistry(root_dir=root)
            registry.load_all()

            # 社名・別名・元の company_key のどれでも照合でき、同一 track では除外
            for query in ("圧縮済み", "Archived Inc.", "archived-co"):
                excluded, match = registry.is_excluded(query, track="domestic")
                self.assertTrue(excluded, query)
                self.assertEqual(match.entry.name, "圧縮済み株式会社")
            entry = match.entry
            self.assertEqual(entry.status, "declined")
            self.assertEqual(entry.reason, "週3出社必須")
            self.assertEqual(entry.closed_at, "2026-10-01")
            self.assertEqual(entry.reconsider_if, "出社が週1以下になったら")
            self.assertIn("2026-09-01〜2026-10-01", entry.notes)
            self.assertIn("カジュアル面談", entry.notes)
            self.assertTrue(entry.log_path.endswith("vault/tracks/domestic/archive.md"))

            # 別 track では参考提示のみ。blacklisted とスクリーニング由来（discarded）の扱いはスキーマどおり
            self.assertFalse(registry.is_excluded("圧縮済み", track="overseas")[0])
            self.assertTrue(registry.is_excluded("出禁", track="overseas")[0])
            self.assertTrue(registry.is_excluded("畳み込み", track="domestic")[0])
            self.assertFalse(registry.is_excluded("畳み込み", track="overseas")[0])
            self.assertEqual(registry.find_matches("畳み込み")[0].entry.status, "discarded")


@unittest.skipUnless((PROJECT_ROOT / "vault").exists(), "実 vault が存在しない環境ではスキップ")
class TestCliExecution(unittest.TestCase):
    def test_cli_query_summary(self):
        # 既存実データに対して CLI を実行
        captured = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = captured
            code = main(["ラクス", "--summary"])
        finally:
            sys.stdout = old_stdout

        self.assertEqual(code, 0)
        output = captured.getvalue()
        self.assertIn("株式会社ラクス", output)
        self.assertIn("除外・見送り企業に該当します", output)

    def test_cli_query_json(self):
        captured = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = captured
            code = main(["株式会社ラクス", "--json"])
        finally:
            sys.stdout = old_stdout

        self.assertEqual(code, 0)
        data = json.loads(captured.getvalue())
        self.assertTrue(data["matched"])
        self.assertTrue(data["has_exclusion"])
        self.assertEqual(data["matches"][0]["entry"]["name"], "株式会社ラクス")

    def test_cli_strict_exit(self):
        # 除外企業の場合 exit code 2
        code = main(["株式会社ラクス", "--strict-exit"])
        self.assertEqual(code, 2)

        # 新規企業の場合 exit code 0
        code_new = main(["存在しない企業XYZ12345", "--strict-exit"])
        self.assertEqual(code_new, 0)

    def test_cli_list_summary(self):
        captured = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = captured
            code = main(["--list", "--category", "exclusion", "--summary"])
        finally:
            sys.stdout = old_stdout

        self.assertEqual(code, 0)
        output = captured.getvalue()
        self.assertIn("登録企業一覧", output)
        self.assertIn("株式会社ラクス", output)
        self.assertIn("バルス株式会社", output)

    def test_cli_check_file(self):
        # 既存求人ファイル data/bizreach/jobs/7755397.md (サンダーソフトジャパン)
        job_file = PROJECT_ROOT / "data" / "bizreach" / "jobs" / "7755397.md"
        if not job_file.exists():
            self.skipTest("求人ファイル 7755397.md が存在しないためスキップ")
        captured = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = captured
            code = main(["--check-file", str(job_file), "--summary"])
        finally:
            sys.stdout = old_stdout

        self.assertEqual(code, 0)
        self.assertIn("サンダーソフトジャパン", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
