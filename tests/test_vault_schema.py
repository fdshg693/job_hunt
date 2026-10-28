"""vault フロントマタースキーマ (scripts/vault/schema/) と文書生成 (scripts/vault/gen_schema_doc.py) の単体テスト."""

import datetime as dt
import sys
import unittest
from pathlib import Path

import yaml
from pydantic import ValidationError

# プロジェクトルート設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.vault.gen_schema_doc import SCHEMA_DOC_PATH, render_doc
from scripts.vault.schema import (
    COMPANY_STATUS_META,
    ENUM_LABELS,
    KIND_GLOBS,
    MODEL_BY_KIND,
    ActionType,
    CompanyDoc,
    CompanyStatus,
    EmployerDoc,
    InterviewDoc,
    InterviewResult,
    InterviewStage,
    LinkCategory,
    MatchingAccuracy,
    MaterialDoc,
    Platform,
    Rating,
    RecruiterDoc,
    RecruiterStatus,
    ReferenceLink,
    ScreeningBatchDoc,
    StatusCategory,
    TechAreaDoc,
    TechDepth,
    TechProjectDoc,
    is_excluded,
    label_of,
    sorted_by_status,
    statuses_in,
)


def company(**overrides):
    data = {
        "company": "株式会社サンプル",
        "company_key": "sample",
        "track": "domestic",
        "status": "considering",
        "date": "2026-10-19",
        "updated_at": "2026-10-19",
        "fit_score_min": 50,
        "fit_score_max": 80,
    }
    data.update(overrides)
    return data


class TestEnums(unittest.TestCase):
    def test_every_enum_member_has_label(self):
        for enum_cls, labels in ENUM_LABELS.items():
            for member in enum_cls:
                self.assertIn(member, labels, f"{enum_cls.__name__}.{member.name} にラベルが無い")

    def test_every_company_status_has_meta_with_unique_order(self):
        self.assertEqual(set(COMPANY_STATUS_META), set(CompanyStatus))
        orders = [m.order for m in COMPANY_STATUS_META.values()]
        self.assertEqual(len(orders), len(set(orders)))

    def test_status_categories(self):
        self.assertIn(CompanyStatus.OFFER, statuses_in(StatusCategory.ACTIVE))
        self.assertEqual(
            statuses_in(StatusCategory.CLOSED),
            {CompanyStatus.ACCEPTED, CompanyStatus.DECLINED, CompanyStatus.REJECTED},
        )
        self.assertEqual(statuses_in(StatusCategory.EXCLUDED), {CompanyStatus.BLACKLISTED})

    def test_exclusion_scope(self):
        self.assertTrue(is_excluded("declined", same_track=True))
        self.assertFalse(is_excluded("declined", same_track=False))
        self.assertTrue(is_excluded("blacklisted", same_track=False))
        self.assertFalse(is_excluded("considering", same_track=True))
        self.assertFalse(is_excluded("accepted", same_track=True))

    def test_sorted_by_status_puts_advanced_first(self):
        result = sorted_by_status([CompanyStatus.CONSIDERING, CompanyStatus.OFFER, CompanyStatus.APPLIED])
        self.assertEqual(result, [CompanyStatus.OFFER, CompanyStatus.APPLIED, CompanyStatus.CONSIDERING])

    def test_label_of(self):
        self.assertEqual(label_of(CompanyStatus.CASUAL_INTERVIEW), "カジュアル面談")
        self.assertEqual(label_of(InterviewStage.FIRST_INTERVIEW), "1次面接")

    def test_removed_statuses_are_rejected(self):
        for old in ("interested", "active", "unverified", "passed", "discarded", "employer"):
            with self.assertRaises(ValidationError, msg=old):
                CompanyDoc(**company(status=old))


class TestCompanyDoc(unittest.TestCase):
    def test_minimal_valid(self):
        doc = CompanyDoc(**company())
        self.assertEqual(doc.status, CompanyStatus.CONSIDERING)
        self.assertEqual(doc.action_type, ActionType.NONE)
        self.assertEqual(doc.date, dt.date(2026, 10, 19))
        self.assertEqual(doc.lint(), [])

    def test_unknown_key_is_error(self):
        with self.assertRaises(ValidationError):
            CompanyDoc(**company(salary_range="800万円〜"))

    def test_blank_string_is_none(self):
        doc = CompanyDoc(**company(recruiter="", status_note="  "))
        self.assertIsNone(doc.recruiter)
        self.assertIsNone(doc.status_note)

    def test_required_blank_is_error(self):
        with self.assertRaises(ValidationError):
            CompanyDoc(**company(company=""))

    def test_company_key_must_be_kebab_case(self):
        for bad in ("Sample", "sample_co", "sample--co", "-sample"):
            with self.assertRaises(ValidationError, msg=bad):
                CompanyDoc(**company(company_key=bad))

    def test_yaml_unquoted_date_is_accepted(self):
        fm = yaml.safe_load("date: 2026-10-19\nupdated_at: '2026-10-19'")
        doc = CompanyDoc(**company(**fm))
        self.assertEqual(doc.date, doc.updated_at)

    def test_fit_score_must_be_pair_and_ordered(self):
        with self.assertRaises(ValidationError):
            CompanyDoc(**company(fit_score_max=None))
        with self.assertRaises(ValidationError):
            CompanyDoc(**company(fit_score_min=90, fit_score_max=80))
        with self.assertRaises(ValidationError):
            CompanyDoc(**company(fit_score_max=101))

    def test_fit_score_without_width_warns_only_when_active(self):
        active = CompanyDoc(**company(fit_score_min=70, fit_score_max=70))
        self.assertTrue(any("幅が無い" in w for w in active.lint()))
        closed = CompanyDoc(**company(status="declined", decline_reason="出社週3", fit_score_min=0, fit_score_max=0))
        self.assertEqual(closed.lint(), [])

    def test_closed_without_reason_warns(self):
        doc = CompanyDoc(**company(status="rejected"))
        self.assertTrue(any("decline_reason" in w for w in doc.lint()))

    def test_salary_range(self):
        with self.assertRaises(ValidationError):
            CompanyDoc(**company(salary_min=900, salary_max=800))
        doc = CompanyDoc(**company(salary_min=8000000))
        self.assertTrue(any("円単位" in w for w in doc.lint()))

    def test_interest_bounds(self):
        self.assertEqual(CompanyDoc(**company(interest=5)).interest, 5)
        for bad in (0, 6):
            with self.assertRaises(ValidationError):
                CompanyDoc(**company(interest=bad))

    def test_next_due_accepts_date_and_datetime(self):
        cases = {
            "2026-10-20": "2026-10-20",
            "2026-10-20 10:30": "2026-10-20 10:30",
            dt.date(2026, 10, 20): "2026-10-20",
            dt.datetime(2026, 10, 20, 9, 0): "2026-10-20 09:00",
        }
        for raw, expected in cases.items():
            doc = CompanyDoc(**company(action_type="scheduled", next_action="面談", next_due=raw))
            self.assertEqual(doc.model_dump(mode="json")["next_due"], expected, raw)

    def test_dump_excludes_unset_defaults(self):
        dumped = CompanyDoc(**company()).model_dump(mode="json", exclude_defaults=True)
        self.assertNotIn("next_due", dumped)
        self.assertNotIn("action_type", dumped)
        self.assertEqual(dumped["status"], "considering")

    def test_action_lints(self):
        doc = CompanyDoc(**company(action_type="scheduled"))
        warnings = doc.lint()
        self.assertTrue(any("next_action" in w for w in warnings))
        self.assertTrue(any("next_due" in w for w in warnings))
        stale = CompanyDoc(**company(status="declined", decline_reason="x", action_type="waiting", next_action="x"))
        self.assertTrue(any("終了しているのに" in w for w in stale.lint()))

    def test_links_defaults_to_empty_and_accepts_valid_entries(self):
        doc = CompanyDoc(**company())
        self.assertEqual(doc.links, [])

        link_data = {
            "category": "deck",
            "title": "会社説明資料",
            "url": "https://speakerdeck.com/example/deck",
            "summary": "事業内容と技術スタックの解説",
            "material": "materials/deck.md",
            "fetched_at": "2026-10-28",
        }
        doc_with_links = CompanyDoc(**company(links=[link_data]))
        self.assertEqual(len(doc_with_links.links), 1)
        link = doc_with_links.links[0]
        self.assertEqual(link.category, LinkCategory.DECK)
        self.assertEqual(link.title, "会社説明資料")
        self.assertEqual(link.material, "materials/deck.md")
        self.assertEqual(link.fetched_at, dt.date(2026, 10, 28))

    def test_links_invalid_category_or_material_is_error(self):
        with self.assertRaises(ValidationError):
            CompanyDoc(**company(links=[{"category": "invalid_cat", "title": "t", "url": "https://example.com"}]))
        with self.assertRaises(ValidationError):
            CompanyDoc(**company(links=[{"category": "deck", "title": "t", "url": "https://example.com", "material": "/etc/passwd"}]))
        with self.assertRaises(ValidationError):
            CompanyDoc(**company(links=[{"category": "deck", "title": "t", "url": "https://example.com", "material": "../deck.md"}]))

    def test_links_unknown_field_is_error(self):
        with self.assertRaises(ValidationError):
            CompanyDoc(**company(links=[{"category": "blog", "title": "t", "url": "https://example.com", "unknown_key": "val"}]))


class TestOtherDocs(unittest.TestCase):
    def test_interview_without_company_is_allowed(self):
        doc = InterviewDoc(date="2026-10-15", stage="career-consultation")
        self.assertIsNone(doc.company_key)
        with self.assertRaises(ValidationError):
            InterviewDoc(date="2026-10-15", stage="tech")

    def test_recruiter(self):
        data = {
            "name": "山田 太郎",
            "recruiter_key": "bizreach_yamada-taro",
            "platform": "bizreach",
            "tracks": ["domestic"],
            "date": "2026-10-13",
            "updated_at": "2026-10-14",
            "introduced_companies": [
                {"company": "株式会社サンプル", "company_key": "sample", "date": "2026-10-13"},
                {"company": "社名非公開のAI企業", "job_title": "AI Engineer", "note": "想定年収〜1000万"},
            ],
        }
        doc = RecruiterDoc(**data)
        self.assertEqual(len(doc.introduced_companies), 2)
        self.assertEqual(doc.lint(), [])
        with self.assertRaises(ValidationError):
            RecruiterDoc(**{**data, "tracks": []})
        with self.assertRaises(ValidationError):
            RecruiterDoc(**{**data, "recruiter_key": "yamada-taro"})
        with self.assertRaises(ValidationError):
            RecruiterDoc(**{**data, "introduced_companies": [{"company": "x", "status": "declined"}]})

    def test_screening_requires_companies(self):
        doc = ScreeningBatchDoc(date="2026-10-14", topic="t", companies=[{"name": "A社", "reason": "受託"}])
        self.assertEqual(doc.type, "discarded_batch")
        with self.assertRaises(ValidationError):
            ScreeningBatchDoc(date="2026-10-14", topic="t", companies=[])
        with self.assertRaises(ValidationError):
            ScreeningBatchDoc(date="2026-10-14", topic="t", companies=["A社"])

    def test_employer(self):
        doc = EmployerDoc(company="株式会社前職", company_key="prev", date="2026-10-08", updated_at="2026-10-08", blacklisted=True)
        self.assertEqual(doc.status, "employer")
        with self.assertRaises(ValidationError):
            EmployerDoc(company="x", company_key="x", date="2026-10-08", updated_at="2026-10-08", status="declined")



class TestTechDocs(unittest.TestCase):
    def test_project_minimal_and_period(self):
        doc = TechProjectDoc(project_key="job-hunt", title="就活サポート", updated_at="2026-10-22")
        self.assertEqual((doc.areas, doc.visibility), ([], None))
        with self.assertRaises(ValidationError):
            TechProjectDoc(project_key="Job_Hunt", title="x", updated_at="2026-10-22")
        with self.assertRaises(ValidationError):
            TechProjectDoc(project_key="x", title="x", updated_at="2026-10-22", started_at="2026-10-01", ended_at="2026-09-01")
        with self.assertRaises(ValidationError):
            TechProjectDoc(project_key="x", title="x", updated_at="2026-10-22", areas=["Not A Key"])
        with self.assertRaises(ValidationError):
            TechProjectDoc(project_key="x", title="x", updated_at="2026-10-22", visibility="public")

    def test_project_done_without_end_warns(self):
        doc = TechProjectDoc(project_key="x", title="x", updated_at="2026-10-22", status="done")
        self.assertEqual(doc.lint(), ["status=done なのに ended_at が未記入"])
        doc = TechProjectDoc(project_key="x", title="x", updated_at="2026-10-22", status="done", ended_at="2026-10-01")
        self.assertEqual(doc.lint(), [])

    def test_area_requires_depth(self):
        doc = TechAreaDoc(area_key="rag", title="RAG", depth="practical", updated_at="2026-10-22", visibility="internal")
        self.assertEqual(doc.depth, TechDepth.PRACTICAL)
        self.assertEqual(label_of(doc.depth), "実用できる（実務・個人開発で動くものを作れる）")
        with self.assertRaises(ValidationError):
            TechAreaDoc(area_key="rag", title="RAG", updated_at="2026-10-22")
        with self.assertRaises(ValidationError):
            TechAreaDoc(area_key="rag", title="RAG", depth="expert", updated_at="2026-10-22")


class TestMaterialDoc(unittest.TestCase):
    def test_minimal_and_full(self):
        doc = MaterialDoc(title="会社説明資料", fetched_at="2026-10-20")
        self.assertEqual((doc.source_url, doc.raw_data, doc.raw_fetched_at), (None, [], None))
        self.assertEqual(doc.lint(), [])
        doc = MaterialDoc(
            title="会社説明資料", source_url="https://speakerdeck.com/example/deck", fetched_at="2026-10-20",
            raw_data=["data/speakerdeck/example/deck/"], raw_fetched_at="2026-10-19",
        )
        self.assertEqual(doc.raw_fetched_at, dt.date(2026, 10, 19))
        with self.assertRaises(ValidationError):
            MaterialDoc(title="x")  # fetched_at は必須

    def test_raw_data_must_be_under_data(self):
        for bad in ["vault/x.md", "/data/x", "C:/data/x", "data/../vault/x", "speakerdeck/x"]:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                MaterialDoc(title="x", fetched_at="2026-10-20", raw_data=[bad], raw_fetched_at="2026-10-20")

    def test_raw_data_without_date_warns(self):
        doc = MaterialDoc(title="x", fetched_at="2026-10-20", raw_data=["data/note/articles/x.md"])
        self.assertEqual(doc.lint(), ["raw_data があるのに raw_fetched_at が未記入"])


class TestSchemaDoc(unittest.TestCase):
    def test_every_kind_has_model_and_glob(self):
        self.assertEqual(set(MODEL_BY_KIND), set(KIND_GLOBS))

    def test_render_covers_models_and_enums(self):
        text = render_doc()
        for model in MODEL_BY_KIND.values():
            self.assertIn(f"### {model.__name__}", text)
        for enum_cls in ENUM_LABELS:
            for member in enum_cls:
                self.assertIn(f"`{member.value}`", text)

    def test_generated_doc_is_up_to_date(self):
        self.assertEqual(
            SCHEMA_DOC_PATH.read_text(encoding="utf-8"),
            render_doc(),
            "docs/vault/schema.md が古い。`uv run python scripts/vault/gen_schema_doc.py` で再生成する",
        )


if __name__ == "__main__":
    unittest.main()
