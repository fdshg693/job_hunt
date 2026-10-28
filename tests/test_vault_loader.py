"""共通ローダー (scripts/vault/loader.py) と検証 CLI (scripts/vault/validate.py) の単体テスト."""

import datetime as dt
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# プロジェクトルート設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.vault.loader import IssueLevel, load_vault
from scripts.vault.schema import (
    ArchiveDoc,
    CompanyDoc,
    CompanyStatus,
    InterviewDoc,
    MaterialDoc,
    RecruiterDoc,
    TechAreaDoc,
    TechProjectDoc,
)

COMPANY = """---
company: "株式会社サンプル"
company_key: "sample"
track: "domestic"
status: "casual_interview"
date: "2026-10-01"
updated_at: "2026-10-01"
fit_score_min: 60
fit_score_max: 80
recruiter: "bizreach_yamada-taro"
---

# 本文
"""

INTERVIEW = """---
company: "株式会社サンプル"
company_key: "sample"
date: "2026-10-05"
stage: "casual"
---
"""

RECRUITER = """---
name: "山田 太郎"
recruiter_key: "bizreach_yamada-taro"
platform: "bizreach"
tracks:
  - "domestic"
introduced_companies:
  - company: "株式会社サンプル"
    company_key: "sample"
date: "2026-10-01"
updated_at: "2026-10-01"
---
"""

SCREENING = """---
date: "2026-10-08"
type: "discarded_batch"
topic: "テスト"
companies:
  - name: "打ち切り株式会社"
    reason: "出社"
---
"""

EMPLOYER = """---
company: "前職株式会社"
company_key: "prev"
status: "employer"
date: "2026-10-01"
updated_at: "2026-10-01"
---
"""

ARCHIVE = """---
type: "closed_archive"
track: "domestic"
updated_at: "2026-10-19"
companies:
  - name: "圧縮済み株式会社"
    company_key: "archived-co"
    aliases:
      - "Archived Inc."
    status: "declined"
    considered_at: "2026-09-01"
    closed_at: "2026-10-01"
    reached: "casual_interview"
    fit_score_min: 40
    fit_score_max: 60
    reason: "週3出社必須"
    reconsider_if: "出社が週1以下になったら"
    recruiter: "bizreach_yamada-taro"
    source: "company_log"
  - name: "畳み込み株式会社"
    status: "discarded"
    considered_at: "2026-10-08"
    closed_at: "2026-10-08"
    reason: "SES"
    source: "screening"
---

見送り台帳。一覧は Web UI で見る。
"""

TECH_PROJECT = """---
project_key: "job-hunt"
title: "就活サポートリポジトリ"
project_type: "personal"
status: "active"
areas:
  - "rag"
updated_at: "2026-10-22"
---
"""

TECH_AREA = """---
area_key: "rag"
title: "RAG"
depth: "practical"
projects:
  - "job-hunt"
updated_at: "2026-10-22"
---
"""

PIPELINE = """---
title: "パイプライン"
track: "domestic"
updated_at: "2026-10-01"
---
"""


class VaultFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.vault = self.root / "vault"
        self.write("tracks/domestic/companies/sample/index.md", COMPANY)
        self.write("tracks/domestic/companies/sample/2026-10-05_casual.md", INTERVIEW)
        self.write("tracks/domestic/companies/sample/memo.md", "メモ（対象外）")
        self.write("tracks/domestic/screening/2026-10-08_test.md", SCREENING)
        self.write("tracks/domestic/pipeline.md", PIPELINE)
        self.write("tracks/domestic/criteria.md", "---\nvisibility: internal\n---\n")
        self.write("recruiters/bizreach_yamada-taro/index.md", RECRUITER)
        self.write("recruiters/bizreach_yamada-taro/2026-10-02_career-consultation.md",
                   '---\ndate: "2026-10-02"\nstage: "career-consultation"\n---\n')
        self.write("profile/employers/prev.md", EMPLOYER)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel: str, text: str) -> Path:
        path = self.vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def messages(self, vault, level=None):
        return [str(i) for i in vault.issues if level is None or i.level == level]


class TestLoadVault(VaultFixture):
    def test_loads_every_kind_and_ignores_other_files(self):
        vault = load_vault(self.root)
        self.assertEqual(self.messages(vault), [])
        self.assertEqual(
            [len(vault.companies), len(vault.interviews), len(vault.recruiters),
             len(vault.screening), len(vault.pipelines), len(vault.employers)],
            [1, 2, 1, 1, 1, 1],
        )
        company = vault.companies[0]
        self.assertIsInstance(company.model, CompanyDoc)
        self.assertEqual(company.model.status, CompanyStatus.CASUAL_INTERVIEW)
        self.assertEqual((company.track, company.folder_key), ("domestic", "sample"))
        self.assertEqual(company.rel, "vault/tracks/domestic/companies/sample/index.md")
        self.assertIn("# 本文", company.body)

    def test_resolves_relations(self):
        vault = load_vault(self.root)
        company = vault.company("sample")
        interviews = vault.interviews_of(company)
        self.assertEqual([i.path.name for i in interviews], ["2026-10-05_casual.md"])
        self.assertIsInstance(interviews[0].model, InterviewDoc)

        recruiter = vault.recruiter_of(company)
        self.assertIsInstance(recruiter.model, RecruiterDoc)
        self.assertEqual(vault.companies_introduced_by(recruiter), [company])
        self.assertEqual(
            [i.path.name for i in vault.recruiter_interviews(recruiter)], ["2026-10-02_career-consultation.md"]
        )
        self.assertEqual(vault.pipeline("domestic").model.track, "domestic")
        self.assertIsNone(vault.company("sample", track="overseas"))

    def test_schema_error_keeps_raw_data(self):
        self.write(
            "tracks/domestic/companies/broken/index.md",
            '---\ncompany: "壊れた株式会社"\ncompany_key: "broken"\nstatus: "interested"\n---\n本文\n',
        )
        vault = load_vault(self.root)
        broken = vault.company("broken")
        self.assertIsNone(broken.model)
        self.assertEqual(broken.data["company"], "壊れた株式会社")
        errors = self.messages(vault, IssueLevel.ERROR)
        self.assertTrue(any("broken/index.md: status" in e for e in errors))
        self.assertTrue(any("broken/index.md: track" in e for e in errors))

    def test_missing_frontmatter_and_bad_yaml_are_errors(self):
        self.write("tracks/domestic/companies/nofm/index.md", "# 本文だけ\n")
        self.write("tracks/domestic/companies/badyaml/index.md", "---\ncompany: [\n---\n")
        errors = self.messages(load_vault(self.root), IssueLevel.ERROR)
        self.assertTrue(any("nofm/index.md: フロントマターが無い" in e for e in errors))
        self.assertTrue(any("badyaml/index.md: フロントマターを読み込めない" in e for e in errors))

    def test_location_mismatches_are_errors(self):
        self.write("tracks/domestic/companies/other/index.md", COMPANY)  # company_key=sample のまま
        self.write("tracks/domestic/companies/sample/2026-10-06_1st-interview.md", INTERVIEW)  # date / stage 不一致
        self.write("recruiters/bizreach_someone/index.md", RECRUITER)
        errors = self.messages(load_vault(self.root), IssueLevel.ERROR)
        self.assertTrue(any("other/index.md: company_key=sample がフォルダ名 other" in e for e in errors))
        self.assertTrue(any("2026-10-06_1st-interview.md: date=2026-10-05" in e for e in errors))
        self.assertTrue(any("2026-10-06_1st-interview.md: stage=casual" in e for e in errors))
        self.assertTrue(any("bizreach_someone/index.md: recruiter_key" in e for e in errors))

    def test_warnings_for_links_lint_and_overdue(self):
        self.write(
            "tracks/domestic/companies/sample/index.md",
            COMPANY.replace("bizreach_yamada-taro", "bizreach_nobody").replace(
                "fit_score_max: 80", 'fit_score_max: 60\naction_type: "action_required"\nnext_action: "返信"\nnext_due: "2026-10-10"'
            ),
        )
        vault = load_vault(self.root, today=dt.date(2026, 10, 19))
        warnings = self.messages(vault, IssueLevel.WARNING)
        self.assertEqual(self.messages(vault, IssueLevel.ERROR), [])
        self.assertTrue(any("recruiter=bizreach_nobody" in w for w in warnings))
        self.assertTrue(any("fit_score に幅が無い" in w for w in warnings))
        self.assertTrue(any("next_due=2026-10-10 を過ぎている" in w for w in warnings))

        # today を渡さなければ期限切れは検査しない
        no_due = self.messages(load_vault(self.root), IssueLevel.WARNING)
        self.assertFalse(any("を過ぎている" in w for w in no_due))

    def test_dangling_introduced_company_is_warning(self):
        self.write("recruiters/bizreach_yamada-taro/index.md", RECRUITER.replace('company_key: "sample"', 'company_key: "ghost"'))
        warnings = self.messages(load_vault(self.root), IssueLevel.WARNING)
        self.assertTrue(any("company_key=ghost の企業ログ・台帳エントリが無い" in w for w in warnings))


class TestMaterials(VaultFixture):
    LINKS = """recruiter: "bizreach_yamada-taro"
links:
  - category: "deck"
    title: "会社説明資料"
    url: "https://speakerdeck.com/example/deck"
    material: "materials/deck.md"{extra}"""

    MATERIAL = """---
title: "会社説明資料"
source_url: "{url}"
fetched_at: "2026-10-20"
raw_data:
  - "data/speakerdeck/example/deck/"
raw_fetched_at: "2026-10-20"
---

# 会社説明資料 要約
"""

    def write_company_links(self, extra: str = "") -> None:
        block = self.LINKS.format(extra=extra)
        self.write("tracks/domestic/companies/sample/index.md", COMPANY.replace('recruiter: "bizreach_yamada-taro"', block))

    def write_material(self, rel: str = "tracks/domestic/companies/sample/materials/deck.md",
                       url: str = "https://speakerdeck.com/example/deck") -> None:
        self.write(rel, self.MATERIAL.format(url=url))

    def test_loads_materials_of_company_and_recruiter(self):
        self.write_company_links()
        self.write_material()
        self.write_material("recruiters/bizreach_yamada-taro/materials/agency.md")
        vault = load_vault(self.root)
        self.assertEqual(self.messages(vault), [])
        self.assertEqual(len(vault.materials), 2)
        company_mats = vault.materials_of(vault.company("sample"))
        self.assertEqual([(m.track, m.folder_key) for m in company_mats], [("domestic", "sample")])
        self.assertIsInstance(company_mats[0].model, MaterialDoc)
        self.assertEqual(company_mats[0].model.raw_data, ["data/speakerdeck/example/deck/"])
        recruiter_mats = vault.materials_of(vault.recruiter("bizreach_yamada-taro"))
        self.assertEqual([(m.track, m.folder_key) for m in recruiter_mats], [(None, "bizreach_yamada-taro")])

    def test_missing_material_file_is_warning(self):
        self.write_company_links()
        warnings = self.messages(load_vault(self.root), IssueLevel.WARNING)
        self.assertTrue(any("links の material=materials/deck.md の資料ファイルが無い" in w for w in warnings))

    def test_material_without_frontmatter_is_error(self):
        self.write_company_links()
        self.write("tracks/domestic/companies/sample/materials/deck.md", "# 会社説明資料要約\n")
        errors = self.messages(load_vault(self.root), IssueLevel.ERROR)
        self.assertTrue(any("materials/deck.md: フロントマターが無い" in e for e in errors))

    def test_link_fetched_at_and_url_mismatch_are_warnings(self):
        self.write_company_links(extra='\n    fetched_at: "2026-10-20"')
        self.write_material(url="https://speakerdeck.com/example/other")
        vault = load_vault(self.root)
        self.assertEqual(self.messages(vault, IssueLevel.ERROR), [])
        warnings = self.messages(vault, IssueLevel.WARNING)
        self.assertTrue(any("material=materials/deck.md に fetched_at がある" in w for w in warnings))
        self.assertTrue(any("source_url（https://speakerdeck.com/example/other）と一致しない" in w for w in warnings))

    def test_missing_raw_data_is_not_warned(self):
        # 生データは保持期間で消えるのが正常なので、存在しなくても警告しない
        self.write_company_links()
        self.write_material()
        self.assertEqual(self.messages(load_vault(self.root)), [])


class TestArchive(VaultFixture):
    def setUp(self):
        super().setUp()
        self.write("tracks/domestic/archive.md", ARCHIVE)

    def test_loads_archive_and_resolves_keys(self):
        vault = load_vault(self.root)
        self.assertEqual(self.messages(vault), [])
        self.assertEqual(len(vault.archives), 1)
        self.assertIsInstance(vault.archive("domestic").model, ArchiveDoc)
        self.assertIsNone(vault.archive("overseas"))
        self.assertEqual([e.name for _, e in vault.archived_entries("domestic")], ["圧縮済み株式会社", "畳み込み株式会社"])
        self.assertEqual(vault.archived_entries("overseas"), [])
        doc, entry = vault.archived("archived-co")
        self.assertEqual((doc.track, entry.reached), ("domestic", CompanyStatus.CASUAL_INTERVIEW))

    def test_recruiter_key_resolves_to_archive(self):
        self.write(
            "recruiters/bizreach_yamada-taro/index.md",
            RECRUITER.replace('company_key: "sample"', 'company_key: "archived-co"'),
        )
        self.assertEqual(self.messages(load_vault(self.root)), [])

    def test_key_in_both_archive_and_folder_is_error(self):
        self.write("tracks/domestic/archive.md", ARCHIVE.replace('"archived-co"', '"sample"'))
        errors = self.messages(load_vault(self.root), IssueLevel.ERROR)
        self.assertTrue(any("archive.md: company_key=sample が台帳と企業フォルダ" in e for e in errors))

    def test_entry_errors(self):
        cases = {
            "重複": (ARCHIVE.replace('reason: "SES"', 'reason: "SES"\n    company_key: "archived-co"'),
                     "company_key が重複している: archived-co"),
            "キー無し": (ARCHIVE.replace('    company_key: "archived-co"\n', ""), "company_key が必要"),
            "日付逆転": (ARCHIVE.replace('closed_at: "2026-10-01"', 'closed_at: "2026-08-01"'),
                       "considered_at が closed_at より後"),
            "track不一致": (ARCHIVE.replace('track: "domestic"', 'track: "overseas"'),
                          "track=overseas が配置先 track domestic と一致しない"),
        }
        for name, (text, expected) in cases.items():
            with self.subTest(name):
                self.write("tracks/domestic/archive.md", text)
                errors = self.messages(load_vault(self.root), IssueLevel.ERROR)
                self.assertTrue(any(expected in e for e in errors), errors)

    def test_long_reason_is_warning(self):
        self.write("tracks/domestic/archive.md", ARCHIVE.replace('reason: "SES"', f'reason: "{"長" * 121}"'))
        vault = load_vault(self.root)
        self.assertEqual(self.messages(vault, IssueLevel.ERROR), [])
        self.assertTrue(any("reason が 121 字" in w for w in self.messages(vault, IssueLevel.WARNING)))

    def test_empty_archive_is_valid(self):
        self.write(
            "tracks/overseas/archive.md",
            '---\ntype: "closed_archive"\ntrack: "overseas"\nupdated_at: "2026-10-19"\n---\n',
        )
        self.assertEqual(self.messages(load_vault(self.root)), [])


class TestTechNotes(VaultFixture):
    def setUp(self):
        super().setUp()
        self.write("profile/tech/README.md", "---\ntitle: 技術ノート\n---\n")  # 説明文書は対象外
        self.write("profile/tech/projects/job-hunt.md", TECH_PROJECT)
        self.write("profile/tech/areas/rag.md", TECH_AREA)

    def test_loads_projects_and_areas(self):
        vault = load_vault(self.root)
        self.assertEqual(self.messages(vault), [])
        self.assertEqual([d.folder_key for d in vault.tech_projects], ["job-hunt"])
        self.assertEqual([d.folder_key for d in vault.tech_areas], ["rag"])
        self.assertIsInstance(vault.tech_projects[0].model, TechProjectDoc)
        self.assertIsInstance(vault.tech_areas[0].model, TechAreaDoc)
        self.assertIsNone(vault.tech_areas[0].track)

    def test_key_must_match_file_name(self):
        self.write("profile/tech/projects/other.md", TECH_PROJECT)
        self.write("profile/tech/areas/llm.md", TECH_AREA)
        errors = self.messages(load_vault(self.root), IssueLevel.ERROR)
        self.assertTrue(any("projects/other.md: project_key=job-hunt がファイル名 other" in e for e in errors))
        self.assertTrue(any("areas/llm.md: area_key=rag がファイル名 llm" in e for e in errors))

    def test_dangling_links_are_warnings(self):
        self.write("profile/tech/projects/job-hunt.md", TECH_PROJECT.replace('- "rag"', '- "ghost-area"'))
        self.write("profile/tech/areas/rag.md", TECH_AREA.replace('- "job-hunt"', '- "ghost-project"'))
        vault = load_vault(self.root)
        self.assertEqual(self.messages(vault, IssueLevel.ERROR), [])
        warnings = self.messages(vault, IssueLevel.WARNING)
        self.assertTrue(any("areas の ghost-area の領域ノート" in w for w in warnings))
        self.assertTrue(any("projects の ghost-project のプロジェクトノート" in w for w in warnings))

    def test_one_sided_link_is_fine(self):
        self.write("profile/tech/areas/rag.md", TECH_AREA.replace('projects:\n  - "job-hunt"\n', ""))
        self.assertEqual(self.messages(load_vault(self.root)), [])


class TestValidateCli(VaultFixture):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "vault" / "validate.py"), "--root", str(self.root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=PROJECT_ROOT,
        )

    def test_clean_vault_exits_zero(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_errors_fail_and_print_paths(self):
        self.write("tracks/domestic/companies/sample/index.md", COMPANY.replace("casual_interview", "interested"))
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertIn("vault/tracks/domestic/companies/sample/index.md", result.stdout)
        self.assertIn("status", result.stderr)

    def test_warnings_fail_only_with_strict(self):
        self.write("tracks/domestic/companies/sample/index.md", COMPANY.replace("fit_score_max: 80", "fit_score_max: 60"))
        self.assertEqual(self.run_cli().returncode, 0)
        self.assertEqual(self.run_cli("--strict").returncode, 1)


@unittest.skipUnless((PROJECT_ROOT / "vault").exists(), "実 vault が存在しない環境ではスキップ")
class TestRealVault(unittest.TestCase):
    def test_repository_vault_and_templates_have_no_errors(self):
        for root in (PROJECT_ROOT, PROJECT_ROOT / "templates"):
            if root == PROJECT_ROOT and not (PROJECT_ROOT / "vault").exists():
                continue
            vault = load_vault(root)
            self.assertEqual([str(e) for e in vault.errors], [], f"{root} にスキーマエラーがある")


if __name__ == "__main__":
    unittest.main()
