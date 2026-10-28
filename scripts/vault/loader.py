"""vault 全体を読み込み、スキーマで型付けしたオブジェクトにする共通ローダー.

- 配置パスは ``KIND_GLOBS``、型・許容値は ``MODEL_BY_KIND``（scripts/vault/schema/）に従う。
- 1ファイルの記入ミスで全体を止めないよう、検証エラーは例外にせず ``Vault.issues`` に集める。
  エラーのあるファイルも ``VaultDoc.data``（生の dict）と本文は読めた範囲で返す（``model`` は None）。
- 他ファイルや今日の日付に依存する検査（フォルダ名・ファイル名とキーの一致、面談ファイル名と frontmatter の一致、
  リンク先キーの存在、期限切れの next_due）はここで行う。モデル単体の推奨違反は ``model.lint()`` を集める。
- 索引（SQLite）には依存しない。CLI が常に最新の正本を見られるよう、毎回 Markdown を直接読む。
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from scripts.common.cli import PROJECT_ROOT
from scripts.vault import frontmatter
from scripts.vault.schema import (
    KIND_GLOBS,
    MODEL_BY_KIND,
    ActionType,
    ArchivedCompany,
    ArchiveDoc,
    CompanyDoc,
    DocKind,
    EmployerDoc,
    InterviewDoc,
    MaterialDoc,
    PipelineDoc,
    RecruiterDoc,
    ReferenceLink,
    StatusCategory,
    TechAreaDoc,
    TechProjectDoc,
    VaultModel,
)

_INTERVIEW_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+)$")


class IssueLevel(StrEnum):
    ERROR = "error"  # スキーマ違反・配置との不一致。validate.py は常に失敗にする
    WARNING = "warning"  # 運用ルール上の推奨違反。validate.py --strict のときだけ失敗にする


@dataclass(frozen=True)
class Issue:
    level: IssueLevel
    path: str  # 読み込みルート相対（スラッシュ区切り）
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass
class VaultDoc:
    """vault の1ファイル."""

    kind: DocKind
    path: Path
    rel: str  # 読み込みルート相対（例: vault/tracks/domestic/companies/rakus/index.md）
    data: dict[str, Any]  # フロントマターの生の値（検証に失敗しても読めた範囲で入る）
    body: str
    model: VaultModel | None  # 検証に失敗したら None
    track: str | None = None  # 配置パスから決まる track（tracks 配下以外は None）
    folder_key: str | None = None  # 配置パスから決まるキー（企業フォルダ名・リクルーターフォルダ名・employer / 技術ノートのファイル名）

    @property
    def ok(self) -> bool:
        return self.model is not None


@dataclass
class Vault:
    root: Path
    companies: list[VaultDoc] = field(default_factory=list)
    interviews: list[VaultDoc] = field(default_factory=list)
    recruiters: list[VaultDoc] = field(default_factory=list)
    screening: list[VaultDoc] = field(default_factory=list)
    pipelines: list[VaultDoc] = field(default_factory=list)
    employers: list[VaultDoc] = field(default_factory=list)
    archives: list[VaultDoc] = field(default_factory=list)
    tech_projects: list[VaultDoc] = field(default_factory=list)
    tech_areas: list[VaultDoc] = field(default_factory=list)
    materials: list[VaultDoc] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == IssueLevel.ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == IssueLevel.WARNING]

    def docs(self) -> Iterator[VaultDoc]:
        for group in (
            self.companies, self.interviews, self.recruiters, self.screening, self.pipelines, self.employers, self.archives,
            self.tech_projects, self.tech_areas, self.materials,
        ):
            yield from group

    # --- 関連解決 -----------------------------------------------------------

    def company(self, key: str, track: str | None = None) -> VaultDoc | None:
        """企業フォルダ名で企業ログを引く（track 省略時は最初に見つかったもの）."""
        return next(
            (c for c in self.companies if c.folder_key == key and (track is None or c.track == track)),
            None,
        )

    def interviews_of(self, company: VaultDoc) -> list[VaultDoc]:
        """企業フォルダに同居する面談ログ（日付昇順）."""
        return [
            i
            for i in self.interviews
            if i.track == company.track and i.folder_key == company.folder_key and not _is_recruiter_path(i.rel)
        ]

    def recruiter(self, key: str) -> VaultDoc | None:
        return next((r for r in self.recruiters if r.folder_key == key), None)

    def recruiter_of(self, company: VaultDoc) -> VaultDoc | None:
        key = company.model.recruiter if isinstance(company.model, CompanyDoc) else company.data.get("recruiter")
        return self.recruiter(key) if key else None

    def recruiter_interviews(self, recruiter: VaultDoc) -> list[VaultDoc]:
        return [i for i in self.interviews if _is_recruiter_path(i.rel) and i.folder_key == recruiter.folder_key]

    def companies_introduced_by(self, recruiter: VaultDoc) -> list[VaultDoc]:
        """リクルーターの introduced_companies のうち、企業ログがあるもの."""
        if not isinstance(recruiter.model, RecruiterDoc):
            return []
        keys = {ic.company_key for ic in recruiter.model.introduced_companies if ic.company_key}
        return [c for c in self.companies if c.folder_key in keys]

    def materials_of(self, owner: VaultDoc) -> list[VaultDoc]:
        """企業ログ・リクルーターログのフォルダ配下の materials/*.md."""
        folder = owner.path.parent / "materials"
        return [m for m in self.materials if m.path.parent == folder]

    def pipeline(self, track: str) -> VaultDoc | None:
        return next((p for p in self.pipelines if p.track == track), None)

    def archive(self, track: str) -> VaultDoc | None:
        """track の見送り台帳（archive.md。無ければ None）."""
        return next((a for a in self.archives if a.track == track), None)

    def archived_entries(self, track: str | None = None) -> list[tuple[VaultDoc, ArchivedCompany]]:
        """見送り台帳のエントリ（track 省略時は全 track）. スキーマ違反の台帳は含めない."""
        return [
            (doc, entry)
            for doc in self.archives
            if isinstance(doc.model, ArchiveDoc) and (track is None or doc.track == track)
            for entry in doc.model.companies
        ]

    def archived(self, key: str, track: str | None = None) -> tuple[VaultDoc, ArchivedCompany] | None:
        """company_key で台帳エントリを引く（圧縮済みの企業フォルダの代わり）."""
        return next(((d, e) for d, e in self.archived_entries(track) if e.company_key == key), None)


def _is_recruiter_path(rel: str) -> bool:
    return rel.split("/")[1] == "recruiters"


def _location(kind: DocKind, rel: str) -> tuple[str | None, str | None]:
    """配置パスから (track, folder_key) を決める."""
    parts = rel.split("/")
    track = parts[2] if parts[1] == "tracks" else None
    if kind in (DocKind.COMPANY, DocKind.INTERVIEW, DocKind.MATERIAL) and parts[1] == "tracks":
        return track, parts[4]
    if kind in (DocKind.RECRUITER, DocKind.INTERVIEW, DocKind.MATERIAL):
        return None, parts[2]
    if kind in (DocKind.EMPLOYER, DocKind.TECH_PROJECT, DocKind.TECH_AREA):
        return None, Path(rel).stem
    return track, None


def _format_validation_error(exc: ValidationError) -> list[str]:
    messages = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(全体)"
        messages.append(f"{loc}: {err['msg']}")
    return messages


def load_doc(kind: DocKind, path: Path, root: Path) -> tuple[VaultDoc, list[Issue]]:
    """1ファイルを読み込み、スキーマで検証する."""
    rel = path.relative_to(root).as_posix()
    track, folder_key = _location(kind, rel)
    issues: list[Issue] = []

    def err(message: str) -> None:
        issues.append(Issue(IssueLevel.ERROR, rel, message))

    try:
        md = frontmatter.read(path)
    except (yaml.YAMLError, ValueError, UnicodeDecodeError, OSError) as e:
        err(f"フロントマターを読み込めない: {e}")
        return VaultDoc(kind, path, rel, {}, "", None, track, folder_key), issues

    doc = VaultDoc(kind, path, rel, md.data, md.body, None, track, folder_key)
    if not md.has_frontmatter:
        err("フロントマターが無い")
        return doc, issues

    try:
        doc.model = MODEL_BY_KIND[kind].model_validate(md.data)
    except ValidationError as e:
        for message in _format_validation_error(e):
            err(message)
        return doc, issues

    issues += [Issue(IssueLevel.WARNING, rel, w) for w in doc.model.lint()]
    issues += [Issue(IssueLevel.ERROR, rel, m) for m in _check_location(doc)]
    return doc, issues


def _check_location(doc: VaultDoc) -> list[str]:
    """配置パス（フォルダ名・ファイル名・track）と frontmatter の一致を検査する."""
    m = doc.model
    problems: list[str] = []
    if isinstance(m, CompanyDoc):
        if m.company_key != doc.folder_key:
            problems.append(f"company_key={m.company_key} がフォルダ名 {doc.folder_key} と一致しない")
        if m.track != doc.track:
            problems.append(f"track={m.track} が配置先 track {doc.track} と一致しない")
    elif isinstance(m, EmployerDoc):
        if m.company_key != doc.folder_key:
            problems.append(f"company_key={m.company_key} がファイル名 {doc.folder_key} と一致しない")
    elif isinstance(m, TechProjectDoc):
        if m.project_key != doc.folder_key:
            problems.append(f"project_key={m.project_key} がファイル名 {doc.folder_key} と一致しない")
    elif isinstance(m, TechAreaDoc):
        if m.area_key != doc.folder_key:
            problems.append(f"area_key={m.area_key} がファイル名 {doc.folder_key} と一致しない")
    elif isinstance(m, RecruiterDoc):
        if m.recruiter_key != doc.folder_key:
            problems.append(f"recruiter_key={m.recruiter_key} がフォルダ名 {doc.folder_key} と一致しない")
    elif isinstance(m, InterviewDoc):
        name = _INTERVIEW_NAME.match(doc.path.stem)
        if name:
            if name.group(1) != m.date.isoformat():
                problems.append(f"date={m.date} がファイル名の日付 {name.group(1)} と一致しない")
            if name.group(2) != m.stage:
                problems.append(f"stage={m.stage} がファイル名の stage {name.group(2)} と一致しない")
        if doc.track is not None:
            if m.company_key is not None and m.company_key != doc.folder_key:
                problems.append(f"company_key={m.company_key} が企業フォルダ名 {doc.folder_key} と一致しない")
            if m.track is not None and m.track != doc.track:
                problems.append(f"track={m.track} が配置先 track {doc.track} と一致しない")
    elif isinstance(m, (PipelineDoc, ArchiveDoc)):
        if m.track != doc.track:
            problems.append(f"track={m.track} が配置先 track {doc.track} と一致しない")
    return problems


def overdue_date(company: CompanyDoc, today: dt.date) -> dt.date | None:
    """選考中企業の要対応・確定予定の next_due が today より前なら、その日付を返す（期限切れでなければ None）."""
    if (
        company.status_category != StatusCategory.ACTIVE
        or company.action_type not in (ActionType.ACTION_REQUIRED, ActionType.SCHEDULED)
        or company.next_due is None
    ):
        return None
    due = company.next_due.date() if isinstance(company.next_due, dt.datetime) else company.next_due
    return due if due < today else None


def _check_links(vault: Vault, today: dt.date | None) -> list[Issue]:
    """ファイル間のリンク（企業 ↔ 面談 ↔ リクルーター ↔ 見送り台帳、技術ノートのプロジェクト ↔ 領域）と期限切れの next_due を検査する.

    リンク切れ・期限切れは警告。台帳と企業フォルダに同じキーがある（どちらが正か曖昧）のはエラー。
    """
    issues: list[Issue] = []
    recruiter_keys = {r.folder_key for r in vault.recruiters}
    company_keys = {c.folder_key for c in vault.companies}
    archived = vault.archived_entries()
    # リクルーターの紹介企業は、圧縮済み（台帳）のキーでも解決できればよい
    known_company_keys = company_keys | {e.company_key for _, e in archived if e.company_key}

    materials = {d.path.resolve(): d for d in vault.materials}

    def warn(doc: VaultDoc, message: str) -> None:
        issues.append(Issue(IssueLevel.WARNING, doc.rel, message))

    for doc in vault.companies:
        m = doc.model
        if not isinstance(m, CompanyDoc):
            continue
        if m.recruiter and m.recruiter not in recruiter_keys:
            warn(doc, f"recruiter={m.recruiter} のリクルーターログ（vault/recruiters/{m.recruiter}/index.md）が無い")
        _check_material_links(doc, m.links, materials, warn)
        due = overdue_date(m, today) if today is not None else None
        if due is not None:
            warn(doc, f"next_due={due} を過ぎている（action_type={m.action_type}）。next_action / next_due を更新する")

    for doc in vault.recruiters:
        m = doc.model
        if not isinstance(m, RecruiterDoc):
            continue
        for ic in m.introduced_companies:
            if ic.company_key and ic.company_key not in known_company_keys:
                warn(doc, f"introduced_companies の company_key={ic.company_key} の企業ログ・台帳エントリが無い")
        _check_material_links(doc, m.links, materials, warn)

    folders = {(c.track, c.folder_key) for c in vault.companies}
    for doc, entry in archived:
        if entry.company_key and (doc.track, entry.company_key) in folders:
            issues.append(Issue(
                IssueLevel.ERROR, doc.rel,
                f"company_key={entry.company_key} が台帳と企業フォルダ（companies/{entry.company_key}/）の両方にある。"
                "再検討するなら台帳エントリを消す",
            ))
        if entry.recruiter and entry.recruiter not in recruiter_keys:
            warn(doc, f"{entry.name}: recruiter={entry.recruiter} のリクルーターログが無い")

    for doc in vault.interviews:
        if doc.track is not None and doc.folder_key not in company_keys:
            warn(doc, f"同じフォルダに企業ログ index.md が無い（{doc.folder_key}）")

    # 技術ノートは片側だけ先に書くことが多いので、相互参照の欠けは問わずリンク切れだけを警告する
    project_keys = {d.folder_key for d in vault.tech_projects}
    area_keys = {d.folder_key for d in vault.tech_areas}
    for doc in vault.tech_projects:
        if isinstance(doc.model, TechProjectDoc):
            for key in doc.model.areas:
                if key not in area_keys:
                    warn(doc, f"areas の {key} の領域ノート（vault/profile/tech/areas/{key}.md）が無い")
    for doc in vault.tech_areas:
        if isinstance(doc.model, TechAreaDoc):
            for key in doc.model.projects:
                if key not in project_keys:
                    warn(doc, f"projects の {key} のプロジェクトノート（vault/profile/tech/projects/{key}.md）が無い")
    return issues


def _check_material_links(
    doc: VaultDoc,
    links: list[ReferenceLink],
    materials: dict[Path, VaultDoc],
    warn: Callable[[VaultDoc, str], None],
) -> None:
    """links[].material の資料ファイルの存在と、日付・元 URL の整合（警告）を検査する.

    material の生データ（raw_data）が消えているのは保持期間による正常な状態なので、ここでは問わない。
    """
    for link in links:
        if not link.material:
            continue
        mat = materials.get((doc.path.parent / link.material).resolve())
        if mat is None:
            warn(doc, f"links の material={link.material} の資料ファイルが無い")
            continue
        if link.fetched_at is not None:
            warn(doc, f"links の material={link.material} に fetched_at がある（日付は資料側の fetched_at に書く）")
        if isinstance(mat.model, MaterialDoc) and mat.model.source_url and mat.model.source_url != link.url:
            warn(doc, f"links の material={link.material} の url が資料の source_url（{mat.model.source_url}）と一致しない")


_GROUP_BY_KIND = {
    DocKind.COMPANY: "companies",
    DocKind.INTERVIEW: "interviews",
    DocKind.RECRUITER: "recruiters",
    DocKind.SCREENING: "screening",
    DocKind.PIPELINE: "pipelines",
    DocKind.EMPLOYER: "employers",
    DocKind.ARCHIVE: "archives",
    DocKind.TECH_PROJECT: "tech_projects",
    DocKind.TECH_AREA: "tech_areas",
    DocKind.MATERIAL: "materials",
}


def load_vault(root: Path | None = None, *, today: dt.date | None = None) -> Vault:
    """vault 全体を読み込む.

    root は ``vault/`` を含むディレクトリ（既定: リポジトリルート。雛形なら ``templates/``）。
    today を渡すと、選考中企業の期限切れ next_due を警告にする。
    """
    root = (root or PROJECT_ROOT).resolve()
    vault = Vault(root=root)
    for kind, patterns in KIND_GLOBS.items():
        group: list[VaultDoc] = getattr(vault, _GROUP_BY_KIND[kind])
        paths = sorted({p for pattern in patterns for p in root.glob(pattern) if p.is_file()})
        for path in paths:
            doc, issues = load_doc(kind, path, root)
            group.append(doc)
            vault.issues += issues
    vault.issues += _check_links(vault, today)
    return vault


__all__ = [
    "Issue",
    "IssueLevel",
    "Vault",
    "VaultDoc",
    "load_doc",
    "load_vault",
    "overdue_date",
]
