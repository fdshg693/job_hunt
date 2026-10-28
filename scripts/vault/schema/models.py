"""vault フロントマターの Pydantic モデル（SSOT）.

- 型・必須/任意・許容値の誤りは ValidationError（エラー）とする。
- 運用ルール上の推奨違反（fit_score に幅が無い等）は ``lint()`` が返す警告文字列とする。
  エラーにしないのは、記入途中のファイルでも読み込み・検索を止めないため。
- 期限切れの ``next_due`` やリンク先キーの存在確認など、他ファイルや今日の日付に依存する検査はローダー側で行う。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator, model_validator

from scripts.vault.schema.enums import (
    COMPANY_STATUS_META,
    ActionType,
    ArchivedStatus,
    ArchiveSource,
    CompanyStatus,
    EvidenceLevel,
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
)

COMPANY_KEY_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
RECRUITER_KEY_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*(?:_[a-z0-9]+(?:-[a-z0-9]+)*)+$"
TECH_KEY_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


class VaultModel(BaseModel):
    """全モデル共通の設定. 未知キーは禁止し、空文字は「未記入（None）」として扱う."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, use_enum_values=False)

    @model_validator(mode="before")
    @classmethod
    def _blank_strings_to_none(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: _blank_to_none(v) for k, v in data.items()}
        return data

    def lint(self) -> list[str]:
        """ルール上の推奨違反（警告）を返す. 既定は無し."""
        return []


def format_due(value: dt.date | dt.datetime | None) -> str | None:
    """next_due を YYYY-MM-DD / YYYY-MM-DD HH:MM の文字列にする."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return value.isoformat()


# 日付のみ（YYYY-MM-DD）と日時（YYYY-MM-DD HH:MM）の両方を受け、書き出し時はその形式の文字列に戻す
DueDate = Annotated[dt.date | dt.datetime, PlainSerializer(format_due, return_type=str, when_used="json")]


# ---------------------------------------------------------------------------
# 企業ログ・前職/現職ログ
# ---------------------------------------------------------------------------


class ReferenceLink(VaultModel):
    """外部リソース・資料リンク."""

    category: LinkCategory = Field(description="リソースの種別（コーポレート・デック・ブログ・口コミ等）")
    title: str = Field(description="リンクまたは資料のタイトル")
    url: str = Field(description="外部リソースのURL")
    summary: str | None = Field(default=None, description="要約・概要・着目ポイント")
    material: str | None = Field(
        default=None, description="同フォルダ配下の要約・資料Markdownパス（例: materials/pitch_deck.md）"
    )
    fetched_at: dt.date | None = Field(default=None, description="資料取得日・確認日")

    @field_validator("material")
    @classmethod
    def _validate_material(cls, v: str | None) -> str | None:
        if v is None:
            return None
        p = Path(v)
        if p.is_absolute() or v.startswith(("/", "\\")) or ".." in p.parts:
            raise ValueError("material は同フォルダ配下の相対パス（例: materials/deck.md）で指定してください")
        return v


def _check_relative_path(v: str, *, base: str | None = None) -> None:
    """絶対パス・``..`` を拒否する. base を渡すとその接頭辞（例: data/）で始まることも求める."""
    p = Path(v)
    if p.is_absolute() or v.startswith(("/", "\\")) or ".." in p.parts:
        raise ValueError(f"{v}: 絶対パスや .. を含むパスは使えない")
    if base is not None and (not p.parts or p.parts[0] != base):
        raise ValueError(f"{v}: {base}/ で始まるリポジトリルート相対パスで指定してください")


class MaterialDoc(VaultModel):
    """外部資料の要約: vault/tracks/{track}/companies/{company_key}/materials/{slug}.md
    または vault/recruiters/{recruiter_key}/materials/{slug}.md

    links（入口）→ materials（永続する要約）→ data/（使い捨ての生データ）の中段。
    所属する企業・リクルーターは配置フォルダから決まるので書かない。
    material から辿られる link 側には fetched_at を書かない（日付の正本はこちら）。
    """

    title: str = Field(description="資料のタイトル")
    source_url: str | None = Field(
        default=None, description="元資料のURL（親 index.md の links[].url と揃える。手書きの資料なら省略可）"
    )
    fetched_at: dt.date = Field(description="要約を書いた・見直した日（要約の鮮度）")
    raw_data: list[str] = Field(
        default_factory=list,
        description="生データの場所（data/ で始まるリポジトリルート相対パス）。保持期間を過ぎると消えるのは正常",
    )
    raw_fetched_at: dt.date | None = Field(default=None, description="生データを取得した日（生データの鮮度）")

    @field_validator("raw_data")
    @classmethod
    def _validate_raw_data(cls, v: list[str]) -> list[str]:
        for path in v:
            _check_relative_path(path, base="data")
        return v

    def lint(self) -> list[str]:
        if self.raw_data and self.raw_fetched_at is None:
            return ["raw_data があるのに raw_fetched_at が未記入"]
        return []


class RelatedJob(VaultModel):
    title: str = Field(description="求人タイトル")
    url: str = Field(description="求人URL")


class CompanyResearchBase(VaultModel):
    """企業の調査結果（企業ログと前職・現職ログで共通の項目）."""

    company: str = Field(description="正式社名（例: 株式会社〇〇）")
    company_key: str = Field(pattern=COMPANY_KEY_PATTERN, description="kebab-case の企業キー。フォルダ名／ファイル名と一致させる")
    aliases: list[str] = Field(default_factory=list, description="別名・略称・英語表記（check_company の照合に使う）")
    date: dt.date = Field(description="初回相談日")
    updated_at: dt.date = Field(description="最終更新日")

    job_url: str | None = Field(default=None, description="対象求人URL（主となる1件）")
    job_title: str | None = Field(default=None, description="対象求人の職種名")
    sources: list[str] = Field(default_factory=list, description="参照した情報源（findy, openwork, corporate_site 等）")
    evidence_level: EvidenceLevel | None = Field(default=None, description="調査の深さ")
    verified_items: list[str] = Field(default_factory=list, description="確認できた事項")
    unverified_items: list[str] = Field(default_factory=list, description="未検証・今後確かめる事項")
    tags: list[str] = Field(default_factory=list, description="技術スタック・業界・勤務形態などの検索用タグ")

    salary_min: int | None = Field(default=None, ge=0, description="提示年収の下限（万円）")
    salary_max: int | None = Field(default=None, ge=0, description="提示年収の上限（万円）。上限なしは未記入")
    salary_note: str | None = Field(default=None, description="年収の補足（固定残業込み、手当別途 等）")

    remote_type: RemoteType | None = Field(default=None, description="勤務形態の分類")
    office_days_per_week: float | None = Field(
        default=None, ge=0, le=7, description="週あたりの出社日数（月1回なら 0.25）。不明なら未記入"
    )
    remote_note: str | None = Field(default=None, description="勤務形態の補足（勤務地、出社曜日、フレックス等）")

    fit_score_min: int | None = Field(default=None, ge=0, le=100, description="適合度スコアの下限（0〜100）")
    fit_score_max: int | None = Field(default=None, ge=0, le=100, description="適合度スコアの上限（0〜100）")
    fit_summary: str | None = Field(default=None, description="適合度の要約と、レンジの理由")

    @model_validator(mode="after")
    def _check_ranges(self) -> CompanyResearchBase:
        if (self.fit_score_min is None) != (self.fit_score_max is None):
            raise ValueError("fit_score_min と fit_score_max は両方記入するか、両方未記入にする")
        if self.fit_score_min is not None and self.fit_score_min > self.fit_score_max:  # type: ignore[operator]
            raise ValueError("fit_score_min が fit_score_max より大きい")
        if self.salary_min is not None and self.salary_max is not None and self.salary_min > self.salary_max:
            raise ValueError("salary_min が salary_max より大きい")
        return self

    def lint(self) -> list[str]:
        warnings: list[str] = []
        if self.remote_type == RemoteType.FULL_REMOTE and self.office_days_per_week:
            warnings.append("remote_type が full_remote なのに office_days_per_week が 0 より大きい")
        if self.salary_min is not None and self.salary_min >= 10000:
            warnings.append(f"salary_min={self.salary_min} は円単位の疑い（万円で書く）")
        if self.salary_max is not None and self.salary_max >= 10000:
            warnings.append(f"salary_max={self.salary_max} は円単位の疑い（万円で書く）")
        return warnings


class CompanyDoc(CompanyResearchBase):
    """企業ログ: vault/tracks/{track}/companies/{company_key}/index.md"""

    track: Track = Field(description="配置先 track と一致させる")
    status: CompanyStatus = Field(description="選考・検討ステータス")
    status_note: str | None = Field(default=None, description="現状の一言メモ")
    decline_reason: str | None = Field(default=None, description="declined / rejected / blacklisted の理由")
    interest: int | None = Field(default=None, ge=1, le=5, description="主観的な志望度（1〜5、任意）。fit_score は AI の評価")

    recruiter: str | None = Field(
        default=None, pattern=RECRUITER_KEY_PATTERN, description="紹介元リクルーターのキー（vault/recruiters/{key}/）"
    )
    thread_url: str | None = Field(default=None, description="スカウト・やり取りのスレッドURL")
    related_jobs: list[RelatedJob] = Field(default_factory=list, description="job_url 以外の関連求人")
    links: list[ReferenceLink] = Field(default_factory=list, description="外部リソース・資料リンク一覧")

    action_type: ActionType = Field(default=ActionType.NONE, description="直近アクションの種類")
    next_action: str | None = Field(default=None, description="直近の具体的アクション")
    next_due: DueDate | None = Field(
        default=None, description="期日または予定日時（YYYY-MM-DD または YYYY-MM-DD HH:MM）"
    )

    @property
    def status_category(self) -> StatusCategory:
        return COMPANY_STATUS_META[self.status].category

    def lint(self) -> list[str]:
        warnings = super().lint()
        active = self.status_category == StatusCategory.ACTIVE
        if active and self.fit_score_min is not None and self.fit_score_min == self.fit_score_max:
            warnings.append(
                f"選考中・検討中なのに fit_score に幅が無い（{self.fit_score_min}）。必ずレンジで書く"
            )
        if active and self.fit_score_min is None:
            warnings.append("fit_score_min / fit_score_max が未記入")
        if not active and self.status != CompanyStatus.ACCEPTED and not self.decline_reason:
            warnings.append(f"status={self.status} なのに decline_reason が未記入")
        if self.action_type != ActionType.NONE and not self.next_action:
            warnings.append(f"action_type={self.action_type} なのに next_action が未記入")
        if self.action_type in (ActionType.ACTION_REQUIRED, ActionType.SCHEDULED) and self.next_due is None:
            warnings.append(f"action_type={self.action_type} なのに next_due が未記入")
        if not active and self.action_type != ActionType.NONE:
            warnings.append(f"status={self.status} で終了しているのに action_type={self.action_type} が残っている")
        return warnings


class EmployerDoc(CompanyResearchBase):
    """前職・現職ログ: vault/profile/employers/{company_key}.md（全 track で check_company の除外対象）"""

    status: Literal["employer"] = Field(default="employer", description="常に employer")
    blacklisted: bool = Field(default=False, description="退職済みで二度と関わらない企業なら true")
    blacklist_reason: str | None = Field(default=None, description="blacklisted の理由")


# ---------------------------------------------------------------------------
# 面談・選考詳細ログ
# ---------------------------------------------------------------------------


class InterviewDoc(VaultModel):
    """面談ログ: vault/tracks/{track}/companies/{company_key}/{YYYY-MM-DD}_{stage}.md
    または vault/recruiters/{recruiter_key}/{YYYY-MM-DD}_{stage}.md"""

    company: str | None = Field(default=None, description="社名（リクルーター面談では省略可）")
    company_key: str | None = Field(default=None, pattern=COMPANY_KEY_PATTERN, description="企業キー（リクルーター面談では省略可）")
    track: Track | None = Field(default=None, description="省略時は配置フォルダから決まる")
    date: dt.date = Field(description="面談日（ファイル名の日付と一致させる）")
    stage: InterviewStage = Field(description="面談ステージ（ファイル名の stage と一致させる）")
    stage_name: str | None = Field(default=None, description="表示名を stage の標準ラベルから変えたい場合のみ")
    interviewer: str | None = Field(default=None, description="面談相手（役職・氏名）")
    result: InterviewResult = Field(default=InterviewResult.PENDING, description="この回の結果")
    tags: list[str] = Field(default_factory=list, description="検索用タグ")


# ---------------------------------------------------------------------------
# リクルーター評価ログ
# ---------------------------------------------------------------------------


class IntroducedCompany(VaultModel):
    """リクルーターから紹介された企業. 企業ログがある場合は company_key で結合し、status / fit_score は企業ログ側を見る."""

    company: str = Field(description="社名（非公開なら「〇〇業界の企業（社名非公開）」等）")
    company_key: str | None = Field(
        default=None, pattern=COMPANY_KEY_PATTERN, description="企業ログがある場合のキー"
    )
    job_title: str | None = Field(default=None, description="紹介された職種")
    date: dt.date | None = Field(default=None, description="紹介された日")
    note: str | None = Field(default=None, description="想定年収・所感など（企業ログが無い場合の記録先）")


class RecruiterDoc(VaultModel):
    """リクルーター評価ログ: vault/recruiters/{recruiter_key}/index.md"""

    name: str = Field(description="担当者氏名")
    recruiter_key: str = Field(pattern=RECRUITER_KEY_PATTERN, description="{agency-or-platform}_{name}。フォルダ名と一致させる")
    agency: str | None = Field(default=None, description="所属企業・エージェント名")
    platform: Platform = Field(description="接触した媒体")
    platform_user_id: str | None = Field(default=None, description="媒体上のプロフィールURL・スレッドURL・ID")
    status: RecruiterStatus = Field(default=RecruiterStatus.ACTIVE, description="付き合いの状態")
    tracks: list[Track] = Field(min_length=1, description="扱う track")
    rating: Rating = Field(default=Rating.B, description="総合評価")
    matching_accuracy: MatchingAccuracy | None = Field(default=None, description="希望条件・志向への理解度")
    communication_quality: str | None = Field(default=None, description="コミュニケーションの所感（丁寧・迅速 / 事務的 / 強引・定型文 等）")
    dealbreaker_adherence: bool | None = Field(default=None, description="足切り条件を尊重しているか")
    tags: list[str] = Field(default_factory=list, description="検索用タグ")
    introduced_companies: list[IntroducedCompany] = Field(default_factory=list, description="紹介・提案された企業")
    links: list[ReferenceLink] = Field(default_factory=list, description="外部リソース・資料リンク一覧")
    date: dt.date = Field(description="初回接触日")
    updated_at: dt.date = Field(description="最終更新日")

    def lint(self) -> list[str]:
        warnings: list[str] = []
        if self.status == RecruiterStatus.BLACKLISTED and self.rating != Rating.D:
            warnings.append(f"status=blacklisted なのに rating={self.rating}（通常は D）")
        if self.status == RecruiterStatus.TRUSTED and self.rating not in (Rating.S, Rating.A):
            warnings.append(f"status=trusted なのに rating={self.rating}（通常は S / A）")
        return warnings


# ---------------------------------------------------------------------------
# スクリーニング集約ログ・pipeline
# ---------------------------------------------------------------------------


class ScreenedCompany(VaultModel):
    name: str = Field(description="社名")
    aliases: list[str] = Field(default_factory=list, description="別名・略称（check_company の照合に使う）")
    reason: str = Field(description="打ち切り理由")


class ScreeningBatchDoc(VaultModel):
    """スクリーニング集約ログ: vault/tracks/{track}/screening/{YYYY-MM-DD}_{topic}.md（同一 track で除外対象）"""

    date: dt.date = Field(description="スクリーニング実施日")
    type: Literal["discarded_batch"] = Field(default="discarded_batch", description="常に discarded_batch")
    topic: str = Field(description="スクリーニングのテーマ")
    companies: list[ScreenedCompany] = Field(min_length=1, description="打ち切った企業（漏れなく列挙）")


# ---------------------------------------------------------------------------
# 見送り台帳（終了した企業フォルダ・古いスクリーニングバッチを圧縮したもの）
# ---------------------------------------------------------------------------

# 見送り理由は「何が合わなかったか」を 1〜2 文で。これを超えたら本質を絞れていないサインとして警告する
ARCHIVE_REASON_MAX = 120


class ArchivedCompany(VaultModel):
    """見送り台帳の 1 社. 再相談のときに判断に効く情報だけを残す（その時点の年収・勤務形態などは持たない）."""

    name: str = Field(description="社名（企業ログ由来なら元の company）")
    company_key: str | None = Field(
        default=None,
        pattern=COMPANY_KEY_PATTERN,
        description="元の企業フォルダのキー。企業ログ由来では必須（リクルーターログの company_key 参照をここで解決する）",
    )
    aliases: list[str] = Field(default_factory=list, description="別名・略称（check_company の照合に使う）")
    status: ArchivedStatus = Field(description="見送りの種別（除外範囲は元の企業ステータス・スクリーニングと同じ）")
    considered_at: dt.date = Field(description="初回検討日（企業ログの date、スクリーニングはバッチの date）")
    closed_at: dt.date = Field(description="見送り日")
    reached: CompanyStatus | None = Field(default=None, description="見送り前に到達した段階（casual_interview 等）")
    fit_score_min: int | None = Field(default=None, ge=0, le=100, description="見送り時点の適合度スコアの下限")
    fit_score_max: int | None = Field(default=None, ge=0, le=100, description="見送り時点の適合度スコアの上限")
    reason: str = Field(description=f"見送り理由の核心。条件の言葉で 1〜2 文（目安 {ARCHIVE_REASON_MAX} 字以内）")
    reconsider_if: str | None = Field(default=None, description="再検討してよい条件（例: 出社が週1以下になったら）")
    recruiter: str | None = Field(default=None, pattern=RECRUITER_KEY_PATTERN, description="紹介元リクルーターのキー")
    source: ArchiveSource = Field(description="圧縮元")

    @model_validator(mode="after")
    def _check_entry(self) -> ArchivedCompany:
        if self.source == ArchiveSource.COMPANY_LOG and not self.company_key:
            raise ValueError("source=company_log のエントリには company_key が必要")
        if (self.fit_score_min is None) != (self.fit_score_max is None):
            raise ValueError("fit_score_min と fit_score_max は両方記入するか、両方未記入にする")
        if self.fit_score_min is not None and self.fit_score_min > self.fit_score_max:  # type: ignore[operator]
            raise ValueError("fit_score_min が fit_score_max より大きい")
        if self.considered_at > self.closed_at:
            raise ValueError("considered_at が closed_at より後")
        return self

    def lint(self) -> list[str]:
        if len(self.reason) > ARCHIVE_REASON_MAX:
            return [f"{self.name}: reason が {len(self.reason)} 字（目安 {ARCHIVE_REASON_MAX} 字以内。核心だけに絞る）"]
        return []


class ArchiveDoc(VaultModel):
    """見送り台帳: vault/tracks/{track}/archive.md（同一 track で除外対象。blacklisted は全 track で除外）"""

    type: Literal["closed_archive"] = Field(default="closed_archive", description="常に closed_archive")
    track: Track = Field(description="配置先 track と一致させる")
    updated_at: dt.date = Field(description="最終更新日")
    companies: list[ArchivedCompany] = Field(default_factory=list, description="圧縮した企業（本文に一覧表は書かない）")

    @model_validator(mode="after")
    def _check_unique_keys(self) -> ArchiveDoc:
        keys = [c.company_key for c in self.companies if c.company_key]
        duplicated = sorted({k for k in keys if keys.count(k) > 1})
        if duplicated:
            raise ValueError(f"company_key が重複している: {', '.join(duplicated)}")
        return self

    def lint(self) -> list[str]:
        return [w for c in self.companies for w in c.lint()]


class PipelineDoc(VaultModel):
    """選考ダッシュボード: vault/tracks/{track}/pipeline.md（一覧部分は build_pipeline.py が生成）"""

    title: str = Field(description="見出し")
    track: Track = Field(description="対象 track")
    updated_at: dt.date = Field(description="最終更新日")
    phase: str | None = Field(default=None, description="活動フェーズ（情報収集中 等）")
    target_timing: str | None = Field(default=None, description="転職目標時期")
    next_action: str | None = Field(default=None, description="track 全体の次回アクション")
    next_due: dt.date | None = Field(default=None, description="next_action の期日")


# ---------------------------------------------------------------------------
# 技術詳細ノート（resume.md / skills.md の要約に対する一次情報）
# ---------------------------------------------------------------------------

TechKey = Annotated[str, Field(pattern=TECH_KEY_PATTERN)]


class TechProjectDoc(VaultModel):
    """技術ノート（プロジェクト）: vault/profile/tech/projects/{project_key}.md"""

    project_key: str = Field(pattern=TECH_KEY_PATTERN, description="kebab-case のプロジェクトキー。ファイル名と一致させる")
    title: str = Field(description="プロジェクト名")
    project_type: TechProjectType | None = Field(default=None, description="個人開発・実務・OSS の別")
    status: TechProjectStatus | None = Field(default=None, description="進行状態")
    started_at: dt.date | None = Field(default=None, description="開始日（月までしか分からなければ 1 日で書く）")
    ended_at: dt.date | None = Field(default=None, description="終了日（進行中は未記入）")
    tech_stack: list[str] = Field(default_factory=list, description="使った言語・フレームワーク・サービス")
    role: str | None = Field(default=None, description="自分の役割・担当範囲")
    areas: list[TechKey] = Field(default_factory=list, description="関連する技術領域のキー（vault/profile/tech/areas/{key}.md）")
    tags: list[str] = Field(default_factory=list, description="検索用タグ")
    visibility: Literal["internal"] | None = Field(default=None, description="外部に出さない本音を含むなら internal")
    updated_at: dt.date = Field(description="最終更新日")

    @model_validator(mode="after")
    def _check_period(self) -> TechProjectDoc:
        if self.started_at is not None and self.ended_at is not None and self.started_at > self.ended_at:
            raise ValueError("started_at が ended_at より後")
        return self

    def lint(self) -> list[str]:
        if self.status == TechProjectStatus.DONE and self.ended_at is None:
            return ["status=done なのに ended_at が未記入"]
        return []


class TechAreaDoc(VaultModel):
    """技術ノート（領域）: vault/profile/tech/areas/{area_key}.md"""

    area_key: str = Field(pattern=TECH_KEY_PATTERN, description="kebab-case の領域キー。ファイル名と一致させる")
    title: str = Field(description="技術領域の名前")
    depth: TechDepth = Field(description="現在の理解度（補足は本文に書く）")
    last_used: dt.date | None = Field(default=None, description="最後に実際に使った時期（月までしか分からなければ 1 日で書く）")
    projects: list[TechKey] = Field(
        default_factory=list, description="この領域を使ったプロジェクトのキー（vault/profile/tech/projects/{key}.md）"
    )
    tags: list[str] = Field(default_factory=list, description="検索用タグ")
    visibility: Literal["internal"] | None = Field(default=None, description="外部に出さない本音を含むなら internal")
    updated_at: dt.date = Field(description="最終更新日")
