"""企業名を vault の企業ログ・見送り台帳と照合し重複・除外を判定する CLI.

企業一覧取得および表記ゆれ対応・重複チェック共通モジュール & CLI.

.agents/rules/company-log.md, .agents/rules/goal.md, .agents/rules/scripts-entrypoint.md 規約に準拠し、
vault/ 配下（vault/tracks/*/companies, vault/tracks/*/screening, vault/tracks/*/archive.md（見送り台帳）,
vault/tracks/*/ratings.md, vault/profile/employers）から検討中、辞退・見送り（declined）、不合格（rejected）、一次スクリーニング打ち切り（discarded）、
出禁・ブラックリスト（blacklisted）、前職・現職（employer）の全社情報を集約・照合します。

企業ログ・スクリーニング・見送り台帳・前職/現職の読み込みは共通ローダー（scripts/vault/loader.py）、
ステータスの分類と除外範囲はスキーマ（scripts/vault/schema/）に従います。
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# プロジェクトルートパス設定 (sys.path に追加して絶対インポートを可能にする)
_CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _CURRENT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import PROJECT_ROOT, build_epilog, entrypoint_guard, to_relative_path
from scripts.common.normalizers import normalize_company_name
from scripts.common.paths import TRACKS
from scripts.vault import frontmatter
from scripts.vault.loader import VaultDoc, load_vault
from scripts.vault.schema import (
    COMPANY_STATUS_META,
    EMPLOYER_EXCLUSION,
    SCREENING_EXCLUSION,
    ArchiveDoc,
    CompanyDoc,
    CompanyStatus,
    EmployerDoc,
    ExclusionScope,
    ScreeningBatchDoc,
    StatusCategory,
)

# 照会 track の既定値（全 track を同一扱いで照合）
ALL_TRACKS = "all"

# 企業ステータス（CompanyStatus）以外に、照合エントリが取りうるステータス
DISCARDED = "discarded"  # スクリーニング集約ログで打ち切った企業
EMPLOYER = "employer"  # 前職・現職

# 企業ログの status が読めなかった場合の扱い（validate.py ではエラーになる）
FALLBACK_STATUS = CompanyStatus.RESEARCHING.value


def exclusion_scope(status: str) -> ExclusionScope:
    """ステータスごとの除外範囲（スキーマ由来）. 未知のステータスは除外しない."""
    if status == DISCARDED:
        return SCREENING_EXCLUSION
    if status == EMPLOYER:
        return EMPLOYER_EXCLUSION
    try:
        return COMPANY_STATUS_META[CompanyStatus(status)].exclusion
    except ValueError:
        return ExclusionScope.NONE


def status_category(status: str) -> str:
    """一覧の絞り込みカテゴリ: 'employer' / 'exclusion' / 'active' / 'other'."""
    if status == EMPLOYER:
        return "employer"
    if exclusion_scope(status) != ExclusionScope.NONE:
        return "exclusion"
    try:
        if COMPANY_STATUS_META[CompanyStatus(status)].category == StatusCategory.ACTIVE:
            return "active"
    except ValueError:
        pass
    return "other"


def status_priority(status: str) -> int:
    """同一企業に複数の記録がある場合に、どのステータスを代表にするか（大きいほど優先）."""
    if status == CompanyStatus.BLACKLISTED:
        return 100
    if status == EMPLOYER:
        return 60
    category = status_category(status)
    if category == "exclusion":
        return 70 if status == DISCARDED else 80
    if category == "active":
        return 50
    return 10


def canonical_key(name: str) -> str:
    """法人格除去・全角半角正規化・英小文字化・記号空白除去を行い、比較用の一意キーを生成する.

    例:
        '株式会社ラクス' -> 'ラクス'
        '（株）メルカリ' -> 'メルカリ'
        'BALUS Co., Ltd.' -> 'balus'
        'KDDIアジャイル開発センター株式会社' -> 'kddiアジャイル開発センター'
        '株式会社on call' -> 'oncall'
        'SecureNavi 株式会社' -> 'securenavi'
    """
    if not name:
        return ""

    # 1. normalizers の法人格除去
    clean = normalize_company_name(name)

    # 2. NFKC 正規化 (全角英数・記号の半角化)
    clean = unicodedata.normalize("NFKC", clean)

    # 3. 小文字化
    clean = clean.lower()

    # 4. 英語法人格・略記（co., ltd., inc., llc, corp., etc.）の除去
    clean = re.sub(r"\b(co\.,?\s*ltd\.?|inc\.?|llc\.?|corp\.?|corporation)\b", "", clean)

    # 5. 空白・句読点・記号（ハイフン、ピリオド、アンダースコア、括弧等）の完全除去
    clean = re.sub(r"[\s　\-_·・,\./\(\)（）\[\]【】「」]+", "", clean)

    return clean.strip()


def _as_list(value: Any) -> list[str]:
    """frontmatter の生の値（文字列 / リスト / None）を文字列リストにする."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return []


@dataclass
class CompanyEntry:
    """登録企業メタデータモデル."""

    name: str  # 代表企業名 (例: '株式会社ラクス')
    status: str  # CompanyStatus の値、または discarded / employer
    category: str = "other"  # 'exclusion', 'active', 'employer', 'other'（status_category）
    track: str = ""  # 'domestic', 'overseas'（前職・現職など track 非依存は空文字）
    log_path: str = ""  # 企業ログ本体（companies/{key}/index.md 等。プロジェクトルート相対パス）
    aliases: list[str] = field(default_factory=list)  # 表記ゆれ・別名・略称・英名
    reason: str = ""  # 却下・見送り・除外・打ち切り理由やメモ
    notes: str = ""  # 補足情報
    closed_at: str = ""  # 見送り日（見送り台帳のエントリのみ）
    reconsider_if: str = ""  # 再検討してよい条件（見送り台帳のエントリのみ）
    source_files: list[str] = field(default_factory=list)  # 参照ファイル一覧（プロジェクトルート相対パス）
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def canonical_name(self) -> str:
        return canonical_key(self.name)

    @property
    def canonical_aliases(self) -> set[str]:
        return {canonical_key(a) for a in self.aliases if a and canonical_key(a)}

    @property
    def all_canonical_keys(self) -> set[str]:
        keys = {self.canonical_name} if self.canonical_name else set()
        keys.update(self.canonical_aliases)
        return keys

    @property
    def exclusion_scope(self) -> ExclusionScope:
        return exclusion_scope(self.status)

    @property
    def is_exclusion(self) -> bool:
        return self.exclusion_scope != ExclusionScope.NONE

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "category": self.category,
            "track": self.track,
            "log_path": self.log_path,
            "aliases": self.aliases,
            "reason": self.reason,
            "notes": self.notes,
            "closed_at": self.closed_at,
            "reconsider_if": self.reconsider_if,
            "source_files": self.source_files,
            "is_exclusion": self.is_exclusion,
        }


@dataclass
class CompanyMatch:
    """重複チェック・照合結果."""

    entry: CompanyEntry
    match_type: str  # 'exact', 'alias_exact', 'substring', 'alias_substring', 'fuzzy'
    matched_name: str  # ヒットした文字列
    score: float  # 類似度スコア (1.0 = 完全一致)
    query_track: str = ALL_TRACKS  # 照会した track（'all' は全 track を同一扱い）

    @property
    def is_other_track(self) -> bool:
        """照会 track とは別の track でのヒットか（track 非依存エントリは常に False）."""
        if self.query_track == ALL_TRACKS or not self.entry.track:
            return False
        return self.entry.track != self.query_track

    @property
    def is_exclusion(self) -> bool:
        """除外判定. 他 track の履歴は情報提示に留め、全 track 除外（blacklisted 等）のみ他 track でも除外する."""
        scope = self.entry.exclusion_scope
        return scope == ExclusionScope.ALL_TRACKS or (scope == ExclusionScope.SAME_TRACK and not self.is_other_track)

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_type": self.match_type,
            "matched_name": self.matched_name,
            "score": round(self.score, 3),
            "is_exclusion": self.is_exclusion,
            "is_other_track": self.is_other_track,
            "entry": self.entry.to_dict(),
        }


class CompanyRegistry:
    """プロジェクト内の全企業データを集約・インデックス化するレジストリクラス."""

    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = root_dir or PROJECT_ROOT
        # 同一企業でも track が異なれば別エントリとして保持する（key: "{track}:{canonical_name}"）
        self.entries: dict[str, CompanyEntry] = {}
        self.alias_to_entry: dict[str, str] = {}  # "{track}:{alias_canonical}" -> entries の key

    def load_all(self) -> None:
        """vault/ 配下の企業ログ・スクリーニングログ・格付け・前職/現職を読み込む.

        ステータスはフロントマターのみから取得する（フォルダ名からの推測はしない）。
        スキーマ違反のファイルも、読めた範囲（社名・status・aliases）で登録する。
        """
        self.entries.clear()
        self.alias_to_entry.clear()

        vault = load_vault(self.root_dir)
        invalid = [d.rel for d in (*vault.companies, *vault.screening, *vault.archives, *vault.employers) if not d.ok]
        if invalid:
            print(
                "[WARN] スキーマ違反のファイルがあります（読めた範囲で照合）。"
                f"`uv run python scripts/vault/validate.py` で確認してください: {', '.join(invalid)}",
                file=sys.stderr,
            )

        # 1. 企業ログ (vault/tracks/{track}/companies/{key}/index.md)
        for doc in vault.companies:
            self._load_company_doc(doc)

        # 2. スクリーニング打ち切り集約ログ (vault/tracks/{track}/screening/*.md)
        for doc in vault.screening:
            self._load_screening_doc(doc)

        # 2b. 見送り台帳 (vault/tracks/{track}/archive.md。圧縮済みの終了企業・古いスクリーニング)
        for doc in vault.archives:
            self._load_archive_doc(doc)

        # 3. 企業格付け・出禁・辞退メモ (vault/tracks/{track}/ratings.md。スキーマ対象外の internal ファイル)
        for track in TRACKS:
            ratings = self.root_dir / "vault" / "tracks" / track / "ratings.md"
            if ratings.exists():
                self._load_profile_companies_file(ratings, track=track)

        # 4. 前職・現職 (vault/profile/employers/*.md。track 非依存)
        for doc in vault.employers:
            self._load_employer_doc(doc)

    def add_or_update_entry(
        self,
        name: str,
        status: str,
        aliases: Sequence[str] | None = None,
        reason: str = "",
        notes: str = "",
        source_file: Path | str | None = None,
        raw_metadata: dict[str, Any] | None = None,
        track: str = "",
    ) -> CompanyEntry:
        """企業エントリを登録または既存情報と安全にマージする（マージは同一 track 内のみ）."""
        clean_name = name.strip()
        c_key = canonical_key(clean_name)
        if not c_key:
            return CompanyEntry(name=clean_name, status=status, track=track)

        rel_source = to_relative_path(source_file) if source_file else ""

        # 既存エントリの検索 (canonical_name 直接一致、または登録済み別名経由)
        existing_key = f"{track}:{c_key}"
        if existing_key not in self.entries and existing_key in self.alias_to_entry:
            existing_key = self.alias_to_entry[existing_key]

        if existing_key in self.entries:
            entry = self.entries[existing_key]

            # ステータスの優先度更新
            if status_priority(status) > status_priority(entry.status):
                entry.status = status
                entry.category = status_category(status)

            # aliases のマージ
            if aliases:
                for a in aliases:
                    a_clean = a.strip()
                    if a_clean and a_clean not in entry.aliases and a_clean != entry.name:
                        entry.aliases.append(a_clean)

            # reason の補完
            if reason and not entry.reason:
                entry.reason = reason.strip()
            elif reason and reason.strip() not in entry.reason:
                entry.reason = f"{entry.reason} / {reason.strip()}".strip(" /")

            # notes の補完
            if notes and not entry.notes:
                entry.notes = notes.strip()

            # source_files の追加
            if rel_source and rel_source not in entry.source_files:
                entry.source_files.append(rel_source)

            # raw_metadata の更新
            if raw_metadata:
                entry.raw_metadata.update(raw_metadata)

            # エイリアスマッピングの更新
            for ak in entry.canonical_aliases:
                self.alias_to_entry[f"{track}:{ak}"] = existing_key

            return entry

        # 新規エントリ作成
        alias_list = [a.strip() for a in (aliases or []) if a.strip() and a.strip() != clean_name]
        entry = CompanyEntry(
            name=clean_name,
            status=status,
            category=status_category(status),
            track=track,
            aliases=alias_list,
            reason=reason.strip(),
            notes=notes.strip(),
            source_files=[rel_source] if rel_source else [],
            raw_metadata=raw_metadata or {},
        )
        entry_key = f"{track}:{c_key}"
        self.entries[entry_key] = entry
        for ak in entry.canonical_aliases:
            self.alias_to_entry[f"{track}:{ak}"] = entry_key

        return entry

    def _register_doc(self, doc: VaultDoc, name: str, status: str, aliases: Sequence[str], reason: str) -> None:
        entry = self.add_or_update_entry(
            name=name,
            status=status,
            aliases=aliases,
            reason=reason,
            source_file=doc.path,
            raw_metadata=doc.data,
            track=doc.track or "",
        )
        if not entry.log_path:
            entry.log_path = to_relative_path(doc.path)

    def _load_company_doc(self, doc: VaultDoc) -> None:
        """企業ログ（companies/{key}/index.md）を登録する."""
        m = doc.model
        if isinstance(m, CompanyDoc):
            reason = m.decline_reason or m.status_note or m.fit_summary or ""
            self._register_doc(doc, m.company, m.status.value, m.aliases, reason)
            return
        raw = doc.data
        reason = raw.get("decline_reason") or raw.get("status_note") or raw.get("fit_summary") or ""
        self._register_doc(
            doc,
            str(raw.get("company") or doc.folder_key),
            str(raw.get("status") or FALLBACK_STATUS),
            _as_list(raw.get("aliases")),
            str(reason),
        )

    def _load_employer_doc(self, doc: VaultDoc) -> None:
        """前職・現職ログ（vault/profile/employers/{key}.md）を登録する（全 track で除外）."""
        m = doc.model
        if isinstance(m, EmployerDoc):
            self._register_doc(doc, m.company, EMPLOYER, m.aliases, m.blacklist_reason or m.fit_summary or "")
            return
        raw = doc.data
        reason = raw.get("blacklist_reason") or raw.get("fit_summary") or ""
        self._register_doc(
            doc, str(raw.get("company") or doc.folder_key), EMPLOYER, _as_list(raw.get("aliases")), str(reason)
        )

    def _load_screening_doc(self, doc: VaultDoc) -> None:
        """screening/{file}.md の companies を打ち切り企業（discarded）として登録する."""
        if isinstance(doc.model, ScreeningBatchDoc):
            items = [(c.name, c.aliases, c.reason) for c in doc.model.companies]
        else:
            raw_items = doc.data.get("companies")
            items = [
                (str(c.get("name") or ""), _as_list(c.get("aliases")), str(c.get("reason") or ""))
                for c in (raw_items if isinstance(raw_items, list) else [])
                if isinstance(c, dict)
            ]
        for name, aliases, reason in items:
            if name:
                self.add_or_update_entry(
                    name=name,
                    status=DISCARDED,
                    aliases=aliases,
                    reason=reason,
                    source_file=doc.path,
                    track=doc.track or "",
                )

    def _load_archive_doc(self, doc: VaultDoc) -> None:
        """archive.md の companies を、エントリの status（declined / rejected / blacklisted / discarded）で登録する.

        元の企業フォルダのキー（company_key）でも照合できるよう別名に含める。
        スキーマ違反の台帳は照合に使わない（見送り日・理由が信用できないため。validate.py で直す）。
        """
        m = doc.model
        if not isinstance(m, ArchiveDoc):
            return
        for c in m.companies:
            period = f"{c.considered_at}〜{c.closed_at}"
            reached = f" / 到達: {COMPANY_STATUS_META[c.reached].label}" if c.reached else ""
            entry = self.add_or_update_entry(
                name=c.name,
                status=str(c.status),
                aliases=[*c.aliases, *([c.company_key] if c.company_key else [])],
                reason=c.reason,
                notes=f"見送り台帳（圧縮済み）: {period}{reached}",
                source_file=doc.path,
                raw_metadata=c.model_dump(mode="json"),
                track=doc.track or "",
            )
            if not entry.log_path:
                entry.log_path = to_relative_path(doc.path)
            entry.closed_at = entry.closed_at or c.closed_at.isoformat()
            entry.reconsider_if = entry.reconsider_if or (c.reconsider_if or "")

    def _load_profile_companies_file(self, path: Path, track: str = "") -> None:
        """tracks/{track}/ratings.md を解析して内部格付け・除外企業を登録する."""
        try:
            fm = frontmatter.read(path).data
        except Exception as e:  # noqa: BLE001 - internal メモの記入ミスで照合全体を止めない
            print(f"[WARN] {to_relative_path(path)} を読み込めません: {e}", file=sys.stderr)
            return

        # 1. benchmark_baseline (現職・基準企業)
        baseline = fm.get("benchmark_baseline")
        if baseline and isinstance(baseline, str):
            self.add_or_update_entry(
                name=baseline,
                status=EMPLOYER,
                notes="現職ベースライン企業",
                source_file=path,
            )

        # 2. target_companies (tier_1, tier_2: 検討中)
        target = fm.get("target_companies", {})
        if isinstance(target, dict):
            for tier in ["tier_1", "tier_2"]:
                for item in target.get(tier, []):
                    if isinstance(item, dict) and "name" in item:
                        self.add_or_update_entry(
                            name=item["name"],
                            status=CompanyStatus.CONSIDERING.value,
                            notes=item.get("memo", f"Target {tier}"),
                            source_file=path,
                            track=track,
                        )

        # 3. declined_companies (見送り確定)
        for item in fm.get("declined_companies", []):
            if isinstance(item, dict) and "name" in item:
                self.add_or_update_entry(
                    name=item["name"],
                    status=CompanyStatus.DECLINED.value,
                    reason=item.get("reason", ""),
                    source_file=path,
                    track=track,
                )

        # 4. blacklisted_companies (出禁・ブラックリスト)
        for item in fm.get("blacklisted_companies", []):
            if isinstance(item, dict) and "name" in item:
                self.add_or_update_entry(
                    name=item["name"],
                    status=CompanyStatus.BLACKLISTED.value,
                    aliases=_as_list(item.get("aliases")),
                    reason=item.get("reason", ""),
                    notes="出禁・ブラックリスト",
                    source_file=path,
                    track=track,
                )

    def find_matches(
        self,
        query: str,
        min_fuzzy_ratio: float = 0.75,
        min_sub_len: int = 3,
        track: str = ALL_TRACKS,
    ) -> list[CompanyMatch]:
        """企業名クエリに対して、完全一致・別名一致・部分一致・ファジー一致を判定してスコア順に返す.

        track を指定すると、別 track のヒットは is_other_track=True（全 track 除外のもの以外は除外扱いしない）となる。
        """
        q_clean = query.strip()
        q_key = canonical_key(q_clean)
        if not q_key:
            return []

        matches: list[CompanyMatch] = []

        for entry in self.entries.values():
            # 1. 完全一致 (代表名 → 別名の順)
            if q_key == entry.canonical_name:
                matches.append(
                    CompanyMatch(entry=entry, match_type="exact", matched_name=entry.name, score=1.0, query_track=track)
                )
                continue
            if q_key in entry.canonical_aliases:
                # どの別名と一致したかを特定
                matched_alias = next(
                    (a for a in entry.aliases if canonical_key(a) == q_key),
                    entry.name,
                )
                matches.append(
                    CompanyMatch(
                        entry=entry,
                        match_type="alias_exact",
                        matched_name=matched_alias,
                        score=1.0,
                        query_track=track,
                    )
                )
                continue

            # 2. 部分一致 (substring) および ファジー検索 (SequenceMatcher)
            entry_keys = entry.all_canonical_keys
            best_match_for_entry: CompanyMatch | None = None

            for target_k in entry_keys:
                if not target_k:
                    continue

                # 部分一致（包含関係）
                # 短すぎるキー（例: 2文字未満）は部分一致の誤爆を避ける
                if len(q_key) >= min_sub_len and len(target_k) >= min_sub_len:
                    if q_key in target_k or target_k in q_key:
                        m_type = "substring" if target_k == entry.canonical_name else "alias_substring"
                        # 部分一致のスコア計算（長さ比率）
                        shorter = min(len(q_key), len(target_k))
                        longer = max(len(q_key), len(target_k))
                        sub_score = 0.85 + 0.1 * (shorter / longer)
                        match_candidate = CompanyMatch(
                            entry=entry,
                            match_type=m_type,
                            matched_name=entry.name,
                            score=sub_score,
                            query_track=track,
                        )
                        if best_match_for_entry is None or match_candidate.score > best_match_for_entry.score:
                            best_match_for_entry = match_candidate
                        continue

                # ファジー類似度照合
                # 長さの差が大きすぎる場合はファジー計算をスキップ
                if abs(len(q_key) - len(target_k)) <= 6:
                    ratio = difflib.SequenceMatcher(None, q_key, target_k).ratio()
                    if ratio >= min_fuzzy_ratio:
                        match_candidate = CompanyMatch(
                            entry=entry,
                            match_type="fuzzy",
                            matched_name=entry.name,
                            score=ratio,
                            query_track=track,
                        )
                        if best_match_for_entry is None or match_candidate.score > best_match_for_entry.score:
                            best_match_for_entry = match_candidate

            if best_match_for_entry:
                matches.append(best_match_for_entry)

        # スコア降順（同スコアなら完全一致優先、さらに照会 track 内のヒット優先）でソート
        type_priority = {
            "exact": 5,
            "alias_exact": 4,
            "substring": 3,
            "alias_substring": 2,
            "fuzzy": 1,
        }
        matches.sort(
            key=lambda m: (m.score, type_priority.get(m.match_type, 0), not m.is_other_track),
            reverse=True,
        )
        return matches

    def is_excluded(self, query: str, track: str = ALL_TRACKS) -> tuple[bool, CompanyMatch | None]:
        """指定企業が除外対象（却下・不合格・打ち切り・出禁・前職/現職）かどうか判定する."""
        matches = self.find_matches(query, track=track)
        for m in matches:
            if m.is_exclusion:
                return True, m
        return False, None

    def list_entries(
        self,
        category: str | None = None,
        status_filter: set[str] | None = None,
        track: str = ALL_TRACKS,
    ) -> list[CompanyEntry]:
        """条件に合致する登録企業一覧をソートして返す（track 指定時は track 非依存エントリも含む）."""
        results: list[CompanyEntry] = []
        for entry in self.entries.values():
            if category and category.lower() != "all" and entry.category != category.lower():
                continue
            if status_filter and entry.status.lower() not in status_filter:
                continue
            if track != ALL_TRACKS and entry.track and entry.track != track:
                continue
            results.append(entry)

        # ソート: ステータス優先度降順、社名昇順
        results.sort(
            key=lambda e: (-status_priority(e.status), e.name),
        )
        return results


def check_company(
    query: str,
    root_dir: Path | None = None,
    track: str = ALL_TRACKS,
) -> list[CompanyMatch]:
    """モジュール用ヘルパー関数: クエリを指定して重複・照合結果を取得する."""
    registry = CompanyRegistry(root_dir=root_dir)
    registry.load_all()
    return registry.find_matches(query, track=track)


def parse_args(args: Sequence[str] | None = None) -> argparse.Namespace:
    """CLI 引数を定義・解析する."""
    parser = argparse.ArgumentParser(
        description="却下済・除外企業一覧取得および重複チェックCLIツール",
        epilog=build_epilog(
            examples=[
                "uv run python scripts/common/check_company.py --track domestic -s <会社名>  # 相談開始時の重複・除外判定",
                "uv run python scripts/common/check_company.py --list --category exclusion -s  # 除外企業の一覧",
                "uv run python scripts/common/check_company.py --check-file data/findy/jobs/<id>.md -s  # 求人の会社名で判定",
            ],
            related=[
                "scripts/vault/compact_closed.py: 見送り企業を台帳に圧縮する（台帳も照合対象）",
                "scripts/vault/build_pipeline.py: 企業ログ作成・更新後に pipeline.md を再生成する",
            ],
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # 検索クエリ
    parser.add_argument(
        "query",
        nargs="*",
        help="判定対象の企業名（例: ラクス、バルス株式会社、KDDI）",
    )
    parser.add_argument(
        "-q",
        "--query-opt",
        dest="query_opt",
        help="判定対象の企業名（オプション指定用）",
    )

    # 一覧表示・フィルタ
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="登録企業一覧を表示する",
    )
    parser.add_argument(
        "--status",
        help=f"絞り込みステータス (カンマ区切り: {', '.join([*CompanyStatus, DISCARDED, EMPLOYER])})",
    )
    parser.add_argument(
        "--category",
        choices=["exclusion", "active", "employer", "all"],
        default="all",
        help="絞り込みカテゴリ (exclusion: 除外・却下群, active: 検討中, employer: 現職・前職, all: 全件)",
    )
    parser.add_argument(
        "--track",
        choices=[ALL_TRACKS, *TRACKS],
        default=ALL_TRACKS,
        help="照会する転職 track（既定: all）。指定時、別 track の辞退・不合格・打ち切りは除外扱いせず [OTHER TRACK] として提示（blacklisted・前職/現職は全 track で除外）",
    )

    # 求人Markdown自動判定
    parser.add_argument(
        "--check-file",
        help="求人Markdownファイルパスを指定し、フロントマターの company を自動抽出して重複チェックする",
    )

    # 出力制御規約
    parser.add_argument(
        "-s",
        "--summary",
        action="store_true",
        help="コンソール向け整形サマリ・判定結果表示（指定しない場合は関連ファイルパスのみ出力）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="結果をJSON形式で標準出力に出力",
    )
    parser.add_argument(
        "--strict-exit",
        action="store_true",
        help="除外企業（exclusion）にヒットした場合、終了コード 2 で終了する（スクリプト自動判定用）",
    )

    return parser.parse_args(args)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI エントリポイント."""
    args = parse_args(argv)

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        registry = CompanyRegistry()
        registry.load_all()

        # 1. --check-file 指定時の企業名抽出
        target_queries: list[str] = []
        if args.check_file:
            target_path = Path(args.check_file)
            if not target_path.exists():
                ctx.error(f"指定されたファイルが存在しません: {args.check_file}")
                return 1
            c_name = frontmatter.read(target_path).data.get("company")
            if not c_name:
                ctx.error(f"ファイルから 'company' フロントマターを検出できませんでした: {args.check_file}")
                return 1
            target_queries.append(c_name)

        # 2. クエリの解決
        if args.query_opt:
            target_queries.append(args.query_opt)
        if args.query:
            target_queries.append(" ".join(args.query))

        # --- A. 一覧表示モード (--list) ---
        if args.list or (not target_queries and not args.check_file):
            status_filter: set[str] | None = None
            if args.status:
                status_filter = {s.strip().lower() for s in args.status.split(",") if s.strip()}

            entries = registry.list_entries(
                category=args.category,
                status_filter=status_filter,
                track=args.track,
            )

            # JSON 出力
            if args.json:
                data = {
                    "total_count": len(entries),
                    "category": args.category,
                    "track": args.track,
                    "companies": [e.to_dict() for e in entries],
                }
                return ctx.flush_outputs(json_data=data)

            # サマリ表示
            if args.summary:
                def print_summary_list() -> None:
                    print("=" * 80)
                    print(f"登録企業一覧 (合計: {len(entries)} 社 / カテゴリ: {args.category} / track: {args.track})")
                    print("=" * 80)
                    for idx, e in enumerate(entries, start=1):
                        ex_mark = "【除外】" if e.is_exclusion else "【検討】"
                        alias_str = f" (別名: {', '.join(e.aliases)})" if e.aliases else ""
                        track_str = f"[{e.track}] " if e.track else ""
                        print(f"{idx:3d}. {ex_mark} {track_str}[{e.status.upper()}] {e.name}{alias_str}")
                        if e.reason:
                            print(f"     理由: {e.reason}")
                        if e.source_files:
                            print(f"     ソース: {', '.join(e.source_files)}")
                    print("=" * 80)

                return ctx.flush_outputs(summary_fn=print_summary_list)

            # デフォルト: 関連ファイルパスを 1 行 1 パスで出力
            for e in entries:
                for sf in e.source_files:
                    ctx.add_result_path(sf)
            return ctx.flush_outputs()

        # --- B. 重複チェックモード (クエリ指定時) ---
        query_str = target_queries[0]
        matches = registry.find_matches(query_str, track=args.track)

        has_exclusion = any(m.is_exclusion for m in matches)
        has_other_track = any(m.is_other_track for m in matches)
        if args.strict_exit and has_exclusion:
            ctx.set_exit_code(2)

        # JSON 出力
        if args.json:
            data = {
                "query": query_str,
                "track": args.track,
                "matched": len(matches) > 0,
                "has_exclusion": has_exclusion,
                "has_other_track": has_other_track,
                "matches": [m.to_dict() for m in matches],
            }
            return ctx.flush_outputs(json_data=data)

        # サマリ表示
        if args.summary:
            def print_check_summary() -> None:
                print("=" * 80)
                print(f"企業重複チェック結果: '{query_str}' (track: {args.track})")
                print("=" * 80)
                if not matches:
                    print("【判定】新規企業（未登録）: 過去の相談・除外ログに該当はありません。")
                    print("=" * 80)
                    return

                # 判定は照会 track 内（および track 非依存）のヒットを優先し、無ければ他 track のヒットを提示する
                same_track = [m for m in matches if not m.is_other_track]
                top = same_track[0] if same_track else matches[0]
                status_upper = top.entry.status.upper()
                if top.is_exclusion:
                    print(f"【判定】🚨 除外・見送り企業に該当します（ステータス: {status_upper}）")
                elif top.is_other_track:
                    print(
                        f"【判定】ℹ️ [OTHER TRACK] 他track（{top.entry.track}）で履歴あり（ステータス: {status_upper}）。"
                        "この track では除外対象外のため、過去の経緯を踏まえて検討してください。"
                    )
                else:
                    print(f"【判定】ℹ️ 登録済みの企業です（ステータス: {status_upper}）")

                print(f"- 該当社名: {top.entry.name} (照合一致: {top.matched_name}, 種別: {top.match_type})")
                if top.entry.track:
                    print(f"- track: {top.entry.track}")
                if top.entry.aliases:
                    print(f"- 別名: {', '.join(top.entry.aliases)}")
                if top.entry.reason:
                    print(f"- 理由・背景: {top.entry.reason}")
                if top.entry.notes:
                    print(f"- 補足: {top.entry.notes}")
                if top.entry.reconsider_if:
                    print(f"- 再検討の条件: {top.entry.reconsider_if}")
                if top.entry.source_files:
                    print(f"- 参照ファイル: {', '.join(top.entry.source_files)}")

                others = [m for m in matches if m is not top]
                if others:
                    print(f"\n[その他類似ヒット: {len(others)} 件]")
                    for extra in others[:3]:
                        if extra.is_exclusion:
                            ex_tag = "除外"
                        elif extra.is_other_track:
                            ex_tag = f"OTHER TRACK: {extra.entry.track}"
                        else:
                            ex_tag = "検討"
                        print(f"  - [{ex_tag} / {extra.entry.status}] {extra.entry.name} (一致: {extra.matched_name}, スコア: {extra.score:.2f})")
                print("=" * 80)

            return ctx.flush_outputs(summary_fn=print_check_summary)

        # デフォルト: ヒットした企業の source_files を 1 行 1 パスで標準出力
        for m in matches:
            for sf in m.entry.source_files:
                ctx.add_result_path(sf)

        return ctx.flush_outputs()


if __name__ == "__main__":
    sys.exit(main())
