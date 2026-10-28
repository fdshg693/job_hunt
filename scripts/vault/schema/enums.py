"""vault フロントマターの列挙値（SSOT）.

各 enum の表示ラベル・並び順・分類などのメタデータは、enum メンバーに直接持たせず
``*_META`` の dict に分けて持つ（Pydantic のシリアライズを素の文字列のまま保つため）。
ラベルは pipeline・Web UI・生成文書（docs/vault/schema.md）で共有する。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Track(StrEnum):
    DOMESTIC = "domestic"
    OVERSEAS = "overseas"


TRACK_LABELS: dict[Track, str] = {
    Track.DOMESTIC: "国内（日本法人に雇用）",
    Track.OVERSEAS: "海外（国外法人に雇用・契約）",
}


class StatusCategory(StrEnum):
    """企業ステータスの大分類."""

    ACTIVE = "active"  # 調査・検討・選考が進行中
    CLOSED = "closed"  # 選考が終わった（承諾・辞退・不合格）
    EXCLUDED = "excluded"  # 二度と検討しない


STATUS_CATEGORY_LABELS: dict[StatusCategory, str] = {
    StatusCategory.ACTIVE: "進行中（調査・検討・選考）",
    StatusCategory.CLOSED: "終了（承諾・辞退・不合格）",
    StatusCategory.EXCLUDED: "除外（ブラックリスト）",
}


class ExclusionScope(StrEnum):
    """check_company で「除外済み」と判定する track の範囲."""

    NONE = "none"  # 除外しない
    SAME_TRACK = "same_track"  # 同一 track でのみ除外（別 track では参考提示）
    ALL_TRACKS = "all_tracks"  # 全 track で除外


class CompanyStatus(StrEnum):
    RESEARCHING = "researching"
    CONSIDERING = "considering"
    LOW_PRIORITY = "low_priority"
    ON_HOLD = "on_hold"
    APPLIED = "applied"
    CASUAL_INTERVIEW = "casual_interview"
    FIRST_INTERVIEW = "first_interview"
    SECOND_INTERVIEW = "second_interview"
    FINAL_INTERVIEW = "final_interview"
    OFFER = "offer"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    REJECTED = "rejected"
    BLACKLISTED = "blacklisted"


@dataclass(frozen=True)
class CompanyStatusMeta:
    label: str
    category: StatusCategory
    order: int  # pipeline の並び順（小さいほど選考が進んでいる）
    exclusion: ExclusionScope
    description: str


COMPANY_STATUS_META: dict[CompanyStatus, CompanyStatusMeta] = {
    CompanyStatus.OFFER: CompanyStatusMeta(
        "内定・オファー", StatusCategory.ACTIVE, 0, ExclusionScope.NONE, "内定・条件提示を受けた"
    ),
    CompanyStatus.FINAL_INTERVIEW: CompanyStatusMeta(
        "最終面接", StatusCategory.ACTIVE, 1, ExclusionScope.NONE, "最終・役員面接の段階"
    ),
    CompanyStatus.SECOND_INTERVIEW: CompanyStatusMeta(
        "2次面接", StatusCategory.ACTIVE, 2, ExclusionScope.NONE, "2次面接の段階"
    ),
    CompanyStatus.FIRST_INTERVIEW: CompanyStatusMeta(
        "1次面接", StatusCategory.ACTIVE, 3, ExclusionScope.NONE, "1次面接（技術面接等）の段階"
    ),
    CompanyStatus.CASUAL_INTERVIEW: CompanyStatusMeta(
        "カジュアル面談", StatusCategory.ACTIVE, 4, ExclusionScope.NONE, "カジュアル面談の調整・実施段階"
    ),
    CompanyStatus.APPLIED: CompanyStatusMeta(
        "応募済", StatusCategory.ACTIVE, 5, ExclusionScope.NONE, "応募し、書類選考の結果待ち"
    ),
    CompanyStatus.CONSIDERING: CompanyStatusMeta(
        "検討中", StatusCategory.ACTIVE, 6, ExclusionScope.NONE, "調査済みで、応募・面談するか検討中"
    ),
    CompanyStatus.RESEARCHING: CompanyStatusMeta(
        "調査中", StatusCategory.ACTIVE, 7, ExclusionScope.NONE, "調査に着手したばかり・未検証"
    ),
    CompanyStatus.ON_HOLD: CompanyStatusMeta(
        "保留", StatusCategory.ACTIVE, 8, ExclusionScope.NONE, "一時的に止めている（時期待ち等）"
    ),
    CompanyStatus.LOW_PRIORITY: CompanyStatusMeta(
        "優先度低", StatusCategory.ACTIVE, 9, ExclusionScope.NONE, "見送りではないが優先度が低い"
    ),
    CompanyStatus.ACCEPTED: CompanyStatusMeta(
        "内定承諾", StatusCategory.CLOSED, 20, ExclusionScope.NONE, "内定を承諾した"
    ),
    CompanyStatus.DECLINED: CompanyStatusMeta(
        "見送り・辞退", StatusCategory.CLOSED, 21, ExclusionScope.SAME_TRACK, "自分から見送り・辞退した"
    ),
    CompanyStatus.REJECTED: CompanyStatusMeta(
        "不合格", StatusCategory.CLOSED, 22, ExclusionScope.SAME_TRACK, "企業側から不合格・お見送りとされた"
    ),
    CompanyStatus.BLACKLISTED: CompanyStatusMeta(
        "ブラックリスト", StatusCategory.EXCLUDED, 30, ExclusionScope.ALL_TRACKS, "二度と関わらない企業"
    ),
}

# スクリーニング集約ログ（discarded）と前職・現職（employer）は企業 status ではないが、
# check_company の除外判定では同じ枠組みで扱う
SCREENING_EXCLUSION = ExclusionScope.SAME_TRACK
EMPLOYER_EXCLUSION = ExclusionScope.ALL_TRACKS


class ArchivedStatus(StrEnum):
    """見送り台帳（archive.md）のエントリのステータス. 企業ログ由来は元の status、スクリーニング由来は discarded."""

    DECLINED = "declined"
    REJECTED = "rejected"
    BLACKLISTED = "blacklisted"
    DISCARDED = "discarded"


ARCHIVED_STATUS_LABELS: dict[ArchivedStatus, str] = {
    ArchivedStatus.DECLINED: COMPANY_STATUS_META[CompanyStatus.DECLINED].label,
    ArchivedStatus.REJECTED: COMPANY_STATUS_META[CompanyStatus.REJECTED].label,
    ArchivedStatus.BLACKLISTED: COMPANY_STATUS_META[CompanyStatus.BLACKLISTED].label,
    ArchivedStatus.DISCARDED: "スクリーニングで打ち切り",
}

# 台帳エントリの除外範囲は、元になった企業ステータス・スクリーニングと同じにする
ARCHIVED_STATUS_EXCLUSION: dict[ArchivedStatus, ExclusionScope] = {
    ArchivedStatus.DECLINED: COMPANY_STATUS_META[CompanyStatus.DECLINED].exclusion,
    ArchivedStatus.REJECTED: COMPANY_STATUS_META[CompanyStatus.REJECTED].exclusion,
    ArchivedStatus.BLACKLISTED: COMPANY_STATUS_META[CompanyStatus.BLACKLISTED].exclusion,
    ArchivedStatus.DISCARDED: SCREENING_EXCLUSION,
}


class ArchiveSource(StrEnum):
    COMPANY_LOG = "company_log"
    SCREENING = "screening"


ARCHIVE_SOURCE_LABELS: dict[ArchiveSource, str] = {
    ArchiveSource.COMPANY_LOG: "企業ログから圧縮",
    ArchiveSource.SCREENING: "スクリーニング集約ログから畳み込み",
}


class ActionType(StrEnum):
    ACTION_REQUIRED = "action_required"
    SCHEDULED = "scheduled"
    WAITING = "waiting"
    NONE = "none"


ACTION_TYPE_LABELS: dict[ActionType, str] = {
    ActionType.ACTION_REQUIRED: "要対応（自分ボール）",
    ActionType.SCHEDULED: "確定済予定",
    ActionType.WAITING: "結果・連絡待ち（相手ボール）",
    ActionType.NONE: "タスクなし",
}


class EvidenceLevel(StrEnum):
    JOB_POST_ONLY = "job_post_only"
    WEB_RESEARCHED = "web_researched"
    REVIEWS_VERIFIED = "reviews_verified"
    INTERVIEW_VERIFIED = "interview_verified"


EVIDENCE_LEVEL_LABELS: dict[EvidenceLevel, str] = {
    EvidenceLevel.JOB_POST_ONLY: "求人票のみ",
    EvidenceLevel.WEB_RESEARCHED: "Web調査済",
    EvidenceLevel.REVIEWS_VERIFIED: "口コミ確認済",
    EvidenceLevel.INTERVIEW_VERIFIED: "面談で確認済",
}


class RemoteType(StrEnum):
    FULL_REMOTE = "full_remote"
    MOSTLY_REMOTE = "mostly_remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


REMOTE_TYPE_LABELS: dict[RemoteType, str] = {
    RemoteType.FULL_REMOTE: "フルリモート",
    RemoteType.MOSTLY_REMOTE: "リモート中心（出社は月数回程度）",
    RemoteType.HYBRID: "ハイブリッド（週1日以上の出社）",
    RemoteType.ONSITE: "出社（原則出社）",
    RemoteType.UNKNOWN: "不明・要確認",
}

# 一覧表の「働き方」列などで使う短い表記
REMOTE_TYPE_SHORT_LABELS: dict[RemoteType, str] = {
    RemoteType.FULL_REMOTE: "フルリモート",
    RemoteType.MOSTLY_REMOTE: "リモート中心",
    RemoteType.HYBRID: "ハイブリッド",
    RemoteType.ONSITE: "出社",
    RemoteType.UNKNOWN: "不明",
}

# data/*/jobs の remote_type（normalizers.detect_remote_type の日本語値）→ RemoteType
JOBS_REMOTE_TYPE_MAP: dict[str, RemoteType] = {
    "フルリモート": RemoteType.FULL_REMOTE,
    "ハイブリッド": RemoteType.HYBRID,
    "出社": RemoteType.ONSITE,
}


class InterviewStage(StrEnum):
    CASUAL = "casual"
    FIRST_INTERVIEW = "1st-interview"
    SECOND_INTERVIEW = "2nd-interview"
    FINAL = "final"
    OFFER = "offer"
    RETRO = "retro"
    CAREER_CONSULTATION = "career-consultation"
    JOB_INTRODUCTION = "job-introduction"


INTERVIEW_STAGE_LABELS: dict[InterviewStage, str] = {
    InterviewStage.CASUAL: "カジュアル面談",
    InterviewStage.FIRST_INTERVIEW: "1次面接",
    InterviewStage.SECOND_INTERVIEW: "2次面接",
    InterviewStage.FINAL: "最終面接",
    InterviewStage.OFFER: "オファー面談",
    InterviewStage.RETRO: "振り返り",
    InterviewStage.CAREER_CONSULTATION: "キャリア相談（エージェント）",
    InterviewStage.JOB_INTRODUCTION: "求人紹介（エージェント）",
}


class InterviewResult(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    REJECTED = "rejected"
    DECLINED = "declined"
    NOT_APPLICABLE = "not_applicable"


INTERVIEW_RESULT_LABELS: dict[InterviewResult, str] = {
    InterviewResult.PENDING: "結果待ち",
    InterviewResult.PASSED: "通過",
    InterviewResult.REJECTED: "不合格",
    InterviewResult.DECLINED: "辞退",
    InterviewResult.NOT_APPLICABLE: "合否なし",
}


class RecruiterStatus(StrEnum):
    ACTIVE = "active"
    TRUSTED = "trusted"
    DECLINED = "declined"
    BLACKLISTED = "blacklisted"


RECRUITER_STATUS_LABELS: dict[RecruiterStatus, str] = {
    RecruiterStatus.ACTIVE: "やり取り中",
    RecruiterStatus.TRUSTED: "信頼できるパートナー",
    RecruiterStatus.DECLINED: "見送り・連絡終了",
    RecruiterStatus.BLACKLISTED: "要注意・NG",
}


class Rating(StrEnum):
    S = "S"
    A = "A"
    B = "B"
    C = "C"
    D = "D"


RATING_LABELS: dict[Rating, str] = {
    Rating.S: "最優良・パートナー",
    Rating.A: "優良",
    Rating.B: "通常・検証中",
    Rating.C: "微妙・ズレあり",
    Rating.D: "悪質・NG",
}


class MatchingAccuracy(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    SPAM = "spam"


MATCHING_ACCURACY_LABELS: dict[MatchingAccuracy, str] = {
    MatchingAccuracy.HIGH: "高い",
    MatchingAccuracy.MEDIUM: "普通",
    MatchingAccuracy.LOW: "低い",
    MatchingAccuracy.SPAM: "スパム（希望を無視）",
}


class Platform(StrEnum):
    BIZREACH = "bizreach"
    LINKEDIN = "linkedin"
    FINDY = "findy"
    LEVTECH_DIRECT = "levtech_direct"
    FORKWELL = "forkwell"
    GREEN = "green"
    OPENWORK = "openwork"
    YOUTRUST = "youtrust"
    WELLFOUND = "wellfound"
    DIRECT = "direct"
    EMAIL = "email"
    OTHER = "other"


PLATFORM_LABELS: dict[Platform, str] = {
    Platform.BIZREACH: "ビズリーチ",
    Platform.LINKEDIN: "LinkedIn",
    Platform.FINDY: "Findy",
    Platform.LEVTECH_DIRECT: "レバテックダイレクト",
    Platform.FORKWELL: "Forkwell",
    Platform.GREEN: "Green",
    Platform.OPENWORK: "OpenWork",
    Platform.YOUTRUST: "YOUTRUST",
    Platform.WELLFOUND: "Wellfound",
    Platform.DIRECT: "企業から直接",
    Platform.EMAIL: "メール",
    Platform.OTHER: "その他",
}

class TechDepth(StrEnum):
    """技術領域の理解度（浅い順）."""

    AWARE = "aware"
    TRIED = "tried"
    PRACTICAL = "practical"
    DESIGN = "design"
    TEACH = "teach"


TECH_DEPTH_LABELS: dict[TechDepth, str] = {
    TechDepth.AWARE: "知っている（概要・用語を説明できる）",
    TechDepth.TRIED: "触った（チュートリアル・小さな検証レベル）",
    TechDepth.PRACTICAL: "実用できる（実務・個人開発で動くものを作れる）",
    TechDepth.DESIGN: "設計判断まで説明できる（選定理由・トレードオフを語れる）",
    TechDepth.TEACH: "人に教えられる（レビュー・指導・発信ができる）",
}


class TechProjectType(StrEnum):
    PERSONAL = "personal"
    WORK = "work"
    OSS = "oss"


TECH_PROJECT_TYPE_LABELS: dict[TechProjectType, str] = {
    TechProjectType.PERSONAL: "個人開発",
    TechProjectType.WORK: "実務",
    TechProjectType.OSS: "OSS",
}


class TechProjectStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    DONE = "done"


TECH_PROJECT_STATUS_LABELS: dict[TechProjectStatus, str] = {
    TechProjectStatus.ACTIVE: "進行中",
    TechProjectStatus.PAUSED: "休止",
    TechProjectStatus.DONE: "完了",
}


class LinkCategory(StrEnum):
    CORPORATE = "corporate"
    ENTRANCE_BOOK = "entrance_book"
    DECK = "deck"
    BLOG = "blog"
    REVIEW = "review"
    INTERVIEW = "interview"
    NEWS = "news"
    SNS = "sns"
    OTHER = "other"


LINK_CATEGORY_LABELS: dict[LinkCategory, str] = {
    LinkCategory.CORPORATE: "コーポレート・会社概要",
    LinkCategory.ENTRANCE_BOOK: "採用・Entrance Book",
    LinkCategory.DECK: "会社説明資料・ピッチデック",
    LinkCategory.BLOG: "技術ブログ・記事",
    LinkCategory.REVIEW: "口コミ・転職評判",
    LinkCategory.INTERVIEW: "インタビュー・登壇",
    LinkCategory.NEWS: "プレスリリース・ニュース",
    LinkCategory.SNS: "SNS・公式アカウント",
    LinkCategory.OTHER: "その他リソース",
}

# 生成文書・UI で enum を一覧するための登録表（enum → ラベル dict）
ENUM_LABELS: dict[type[StrEnum], dict] = {
    Track: TRACK_LABELS,
    StatusCategory: STATUS_CATEGORY_LABELS,
    CompanyStatus: {k: v.label for k, v in COMPANY_STATUS_META.items()},
    ArchivedStatus: ARCHIVED_STATUS_LABELS,
    ArchiveSource: ARCHIVE_SOURCE_LABELS,
    ActionType: ACTION_TYPE_LABELS,
    EvidenceLevel: EVIDENCE_LEVEL_LABELS,
    RemoteType: REMOTE_TYPE_LABELS,
    InterviewStage: INTERVIEW_STAGE_LABELS,
    InterviewResult: INTERVIEW_RESULT_LABELS,
    RecruiterStatus: RECRUITER_STATUS_LABELS,
    Rating: RATING_LABELS,
    MatchingAccuracy: MATCHING_ACCURACY_LABELS,
    Platform: PLATFORM_LABELS,
    TechDepth: TECH_DEPTH_LABELS,
    TechProjectType: TECH_PROJECT_TYPE_LABELS,
    TechProjectStatus: TECH_PROJECT_STATUS_LABELS,
    LinkCategory: LINK_CATEGORY_LABELS,
}


def label_of(value: StrEnum) -> str:
    """enum 値の日本語表示ラベルを返す（未登録なら値そのもの）."""
    return ENUM_LABELS.get(type(value), {}).get(value, str(value))
