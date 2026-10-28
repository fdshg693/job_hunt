"""vault フロントマタースキーマ（SSOT）の公開 API.

キー・型・許容値の正はこのパッケージ。一覧は生成物 docs/vault/schema.md を参照
（`uv run python scripts/vault/gen_schema_doc.py` で再生成する）。
"""

from __future__ import annotations

from enum import StrEnum

from scripts.vault.schema.enums import (
    ARCHIVED_STATUS_EXCLUSION,
    COMPANY_STATUS_META,
    EMPLOYER_EXCLUSION,
    ENUM_LABELS,
    LINK_CATEGORY_LABELS,
    REMOTE_TYPE_SHORT_LABELS,
    SCREENING_EXCLUSION,
    ActionType,
    ArchivedStatus,
    ArchiveSource,
    CompanyStatus,
    CompanyStatusMeta,
    EvidenceLevel,
    ExclusionScope,
    InterviewResult,
    InterviewStage,
    LinkCategory,
    MatchingAccuracy,
    Platform,
    Rating,
    RecruiterStatus,
    RemoteType,
    StatusCategory,
    TechDepth,
    TechProjectStatus,
    TechProjectType,
    Track,
    label_of,
)
from scripts.vault.schema.models import (
    ARCHIVE_REASON_MAX,
    ArchivedCompany,
    ArchiveDoc,
    CompanyDoc,
    EmployerDoc,
    InterviewDoc,
    IntroducedCompany,
    MaterialDoc,
    PipelineDoc,
    RecruiterDoc,
    ReferenceLink,
    RelatedJob,
    ScreenedCompany,
    ScreeningBatchDoc,
    TechAreaDoc,
    TechProjectDoc,
    VaultModel,
    format_due,
)


class DocKind(StrEnum):
    COMPANY = "company"
    INTERVIEW = "interview"
    RECRUITER = "recruiter"
    SCREENING = "screening"
    PIPELINE = "pipeline"
    EMPLOYER = "employer"
    ARCHIVE = "archive"
    TECH_PROJECT = "tech_project"
    TECH_AREA = "tech_area"
    MATERIAL = "material"


MODEL_BY_KIND: dict[DocKind, type[VaultModel]] = {
    DocKind.COMPANY: CompanyDoc,
    DocKind.INTERVIEW: InterviewDoc,
    DocKind.RECRUITER: RecruiterDoc,
    DocKind.SCREENING: ScreeningBatchDoc,
    DocKind.PIPELINE: PipelineDoc,
    DocKind.EMPLOYER: EmployerDoc,
    DocKind.ARCHIVE: ArchiveDoc,
    DocKind.TECH_PROJECT: TechProjectDoc,
    DocKind.TECH_AREA: TechAreaDoc,
    DocKind.MATERIAL: MaterialDoc,
}

# ドキュメント種別ごとの配置パス（リポジトリルート相対の glob）
KIND_GLOBS: dict[DocKind, tuple[str, ...]] = {
    DocKind.COMPANY: ("vault/tracks/*/companies/*/index.md",),
    DocKind.INTERVIEW: (
        "vault/tracks/*/companies/*/????-??-??_*.md",
        "vault/recruiters/*/????-??-??_*.md",
    ),
    DocKind.RECRUITER: ("vault/recruiters/*/index.md",),
    DocKind.SCREENING: ("vault/tracks/*/screening/*.md",),
    DocKind.PIPELINE: ("vault/tracks/*/pipeline.md",),
    DocKind.EMPLOYER: ("vault/profile/employers/*.md",),
    DocKind.ARCHIVE: ("vault/tracks/*/archive.md",),
    # tech/README.md は説明文書なので対象外
    DocKind.TECH_PROJECT: ("vault/profile/tech/projects/*.md",),
    DocKind.TECH_AREA: ("vault/profile/tech/areas/*.md",),
    DocKind.MATERIAL: (
        "vault/tracks/*/companies/*/materials/*.md",
        "vault/recruiters/*/materials/*.md",
    ),
}


def status_meta(status: CompanyStatus | str) -> CompanyStatusMeta:
    return COMPANY_STATUS_META[CompanyStatus(status)]


def statuses_in(category: StatusCategory) -> frozenset[CompanyStatus]:
    """指定分類に属する企業ステータスの集合."""
    return frozenset(s for s, m in COMPANY_STATUS_META.items() if m.category == category)


def is_excluded(status: CompanyStatus | str, *, same_track: bool) -> bool:
    """check_company で「除外済み」とするか. same_track は照会 track と企業ログの track が同じか."""
    scope = status_meta(status).exclusion
    return scope == ExclusionScope.ALL_TRACKS or (scope == ExclusionScope.SAME_TRACK and same_track)


def sorted_by_status(statuses: list[CompanyStatus]) -> list[CompanyStatus]:
    """pipeline の並び順（選考が進んでいるものほど先）に並べる."""
    return sorted(statuses, key=lambda s: COMPANY_STATUS_META[s].order)


__all__ = [
    "ARCHIVED_STATUS_EXCLUSION",
    "ARCHIVE_REASON_MAX",
    "COMPANY_STATUS_META",
    "EMPLOYER_EXCLUSION",
    "ENUM_LABELS",
    "KIND_GLOBS",
    "LINK_CATEGORY_LABELS",
    "LinkCategory",
    "MODEL_BY_KIND",
    "REMOTE_TYPE_SHORT_LABELS",
    "SCREENING_EXCLUSION",
    "ActionType",
    "ArchiveDoc",
    "ArchiveSource",
    "ArchivedCompany",
    "ArchivedStatus",
    "CompanyDoc",
    "CompanyStatus",
    "CompanyStatusMeta",
    "DocKind",
    "EmployerDoc",
    "EvidenceLevel",
    "ExclusionScope",
    "InterviewDoc",
    "InterviewResult",
    "InterviewStage",
    "IntroducedCompany",
    "MatchingAccuracy",
    "MaterialDoc",
    "PipelineDoc",
    "Platform",
    "Rating",
    "RecruiterDoc",
    "RecruiterStatus",
    "ReferenceLink",
    "RelatedJob",
    "RemoteType",
    "ScreenedCompany",
    "ScreeningBatchDoc",
    "StatusCategory",
    "TechAreaDoc",
    "TechDepth",
    "TechProjectDoc",
    "TechProjectStatus",
    "TechProjectType",
    "Track",
    "VaultModel",
    "format_due",
    "is_excluded",
    "label_of",
    "sorted_by_status",
    "status_meta",
    "statuses_in",
]
