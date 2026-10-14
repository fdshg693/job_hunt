"""企業一覧取得および表記ゆれ対応・重複チェック共通モジュール & CLI.

.agents/rules/chat-log.md, .agents/rules/goal.md, .agents/rules/scripts-entrypoint.md 規約に準拠し、
検討中、辞退・見送り（declined）、不合格（rejected）、一次スクリーニング打ち切り（discarded）、
出禁・ブラックリスト（blacklisted）、前職・現職（employer）の全社情報を集約・照合します。
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

import yaml

# プロジェクトルートパス設定 (sys.path に追加して絶対インポートを可能にする)
_CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _CURRENT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import PROJECT_ROOT, EntrypointContext, entrypoint_guard, to_relative_path
from scripts.common.normalizers import normalize_company_name

# 除外・見送り扱いとするステータス群 (SSOT)
EXCLUSION_STATUSES: set[str] = {
    "declined",
    "rejected",
    "discarded",
    "blacklisted",
}

# 検討中・進行中ステータス群
ACTIVE_STATUSES: set[str] = {
    "active",
    "considering",
    "interested",
    "applied",
    "casual_interview",
    "first_interview",
    "second_interview",
    "final_interview",
    "passed",
    "offer",
    "on_hold",
    "researching",
    "unverified",
}

# 現職・前職ステータス群
EMPLOYER_STATUSES: set[str] = {
    "employer",
}


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
    clean = re.sub(r"[\s\u3000\-_·・,\./\(\)（）\[\]【】「」]+", "", clean)

    return clean.strip()


@dataclass
class CompanyEntry:
    """登録企業メタデータモデル."""

    name: str  # 代表企業名 (例: '株式会社ラクス')
    status: str  # ステータス文字列 (declined, active, discarded, etc.)
    category: str = "other"  # 'exclusion', 'active', 'employer', 'other'
    aliases: list[str] = field(default_factory=list)  # 表記ゆれ・別名・略称・英名
    reason: str = ""  # 却下・見送り・除外・打ち切り理由やメモ
    notes: str = ""  # 補足情報
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
    def is_exclusion(self) -> bool:
        return self.status.lower() in EXCLUSION_STATUSES or self.category == "exclusion"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "category": self.category,
            "aliases": self.aliases,
            "reason": self.reason,
            "notes": self.notes,
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

    @property
    def is_exclusion(self) -> bool:
        return self.entry.is_exclusion

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_type": self.match_type,
            "matched_name": self.matched_name,
            "score": round(self.score, 3),
            "is_exclusion": self.is_exclusion,
            "entry": self.entry.to_dict(),
        }


def extract_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Markdown テキストから YAML フロントマターと本文を分離して返す."""
    pattern = r"^---\s*\n(.*?)\n---\s*(?:\n|$)"
    match = re.match(pattern, content, flags=re.DOTALL)
    if not match:
        return {}, content

    yaml_text = match.group(1)
    body = content[match.end() :]
    try:
        data = yaml.safe_load(yaml_text) or {}
        if isinstance(data, dict):
            return data, body
        return {}, body
    except Exception:
        return {}, body


class CompanyRegistry:
    """プロジェクト内の全企業データを集約・インデックス化するレジストリクラス."""

    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = root_dir or PROJECT_ROOT
        self.entries: dict[str, CompanyEntry] = {}  # key: canonical_name
        self.alias_to_entry: dict[str, str] = {}  # alias_canonical -> primary_canonical

    def load_all(self) -> None:
        """chat/ 配下の全ログおよび profile/internal/companies.md を読み込む."""
        self.entries.clear()
        self.alias_to_entry.clear()

        # 1. chat/ 配下の個別ログ (active, declined, rejected, employer)
        chat_dir = self.root_dir / "chat"
        if chat_dir.exists():
            for folder_name in ["declined", "rejected", "employer", "active"]:
                sub_dir = chat_dir / folder_name
                if sub_dir.exists():
                    for md_file in sub_dir.glob("*.md"):
                        self._load_chat_file(md_file, default_status=folder_name)

            # 2. chat/discarded/ バッチ打ち切りログ
            discarded_dir = chat_dir / "discarded"
            if discarded_dir.exists():
                for md_file in discarded_dir.glob("*.md"):
                    self._load_discarded_file(md_file)

        # 3. profile/internal/companies.md (内部格付け・出禁・辞退メモ)
        profile_companies = self.root_dir / "profile" / "internal" / "companies.md"
        if profile_companies.exists():
            self._load_profile_companies_file(profile_companies)

    def _determine_category(self, status: str) -> str:
        s = status.lower()
        if s in EXCLUSION_STATUSES:
            return "exclusion"
        if s in ACTIVE_STATUSES:
            return "active"
        if s in EMPLOYER_STATUSES:
            return "employer"
        return "other"

    def _status_priority(self, status: str) -> int:
        """ステータスの優先度（除外判定やより重要な状態を上位にする）."""
        s = status.lower()
        if s == "blacklisted":
            return 100
        if s in ("declined", "rejected"):
            return 80
        if s == "discarded":
            return 70
        if s == "employer":
            return 60
        if s in ACTIVE_STATUSES:
            return 50
        return 10

    def add_or_update_entry(
        self,
        name: str,
        status: str,
        aliases: Sequence[str] | None = None,
        reason: str = "",
        notes: str = "",
        source_file: Path | str | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> CompanyEntry:
        """企業エントリを登録または既存情報と安全にマージする."""
        clean_name = name.strip()
        c_key = canonical_key(clean_name)
        if not c_key:
            return CompanyEntry(name=clean_name, status=status)

        rel_source = to_relative_path(source_file) if source_file else ""

        # 既存エントリの検索 (canonical_name 直接一致、または登録済み別名経由)
        existing_key = c_key
        if existing_key not in self.entries and c_key in self.alias_to_entry:
            existing_key = self.alias_to_entry[c_key]

        if existing_key in self.entries:
            entry = self.entries[existing_key]

            # ステータスの優先度更新
            if self._status_priority(status) > self._status_priority(entry.status):
                entry.status = status
                entry.category = self._determine_category(status)

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
                self.alias_to_entry[ak] = existing_key

            return entry

        # 新規エントリ作成
        category = self._determine_category(status)
        alias_list = [a.strip() for a in (aliases or []) if a.strip() and a.strip() != clean_name]
        entry = CompanyEntry(
            name=clean_name,
            status=status,
            category=category,
            aliases=alias_list,
            reason=reason.strip(),
            notes=notes.strip(),
            source_files=[rel_source] if rel_source else [],
            raw_metadata=raw_metadata or {},
        )
        self.entries[c_key] = entry
        for ak in entry.canonical_aliases:
            self.alias_to_entry[ak] = c_key

        return entry

    def _load_chat_file(self, path: Path, default_status: str) -> None:
        """chat/{status}/{company}.md を解析してエントリを登録する."""
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return

        fm, body = extract_frontmatter(content)
        company_name = fm.get("company")
        if not company_name:
            # フロントマターに社名がない場合はファイル名や本文H1から抽出を試みる
            h1_match = re.search(r"^#\s+(.*?)(?:\s+求人|\s+面談|\s+調査|\s*$)", body, flags=re.MULTILINE)
            company_name = h1_match.group(1).strip() if h1_match else path.stem

        status = fm.get("status", default_status)
        aliases = fm.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [aliases]

        # 理由の抽出 (decline_reason, status_note, fit_summary, reason の順)
        reason = (
            fm.get("decline_reason")
            or fm.get("status_note")
            or fm.get("fit_summary")
            or fm.get("reason")
            or ""
        )

        self.add_or_update_entry(
            name=company_name,
            status=status,
            aliases=aliases,
            reason=str(reason),
            source_file=path,
            raw_metadata=fm,
        )

    def _load_discarded_file(self, path: Path) -> None:
        """chat/discarded/{file}.md を解析して打ち切り企業群を登録する."""
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return

        fm, body = extract_frontmatter(content)
        companies_data = fm.get("companies", [])
        if not isinstance(companies_data, list):
            return

        # 本文の見出しから企業ごとの理由（### 社名 or ## 数字. 社名）を抽出する
        # 例: ### KDDIアジャイル開発センター株式会社
        #     - **主な理由**: **出社前提 ＆ 大企業SI気質**
        #     - **詳細背景**: ...
        reasons_by_name: dict[str, str] = {}
        section_pattern = re.compile(
            r"^(?:###|##\s+\d+\.)\s+(.+?)\s*$\n(.*?)(?=(?:^###|^##\s+\d+\.|\Z))",
            flags=re.MULTILINE | re.DOTALL,
        )
        for sec_match in section_pattern.finditer(body):
            sec_name = sec_match.group(1).strip()
            sec_body = sec_match.group(2)

            main_reason = ""
            m_reason = re.search(r"-\s+\*\*主な理由\*\*:\s*(.+?)$", sec_body, flags=re.MULTILINE)
            if m_reason:
                main_reason = m_reason.group(1).replace("**", "").strip()

            detail_bg = ""
            m_detail = re.search(r"-\s+\*\*詳細背景\*\*:\s*(.+?)$", sec_body, flags=re.MULTILINE)
            if m_detail:
                detail_bg = m_detail.group(1).strip()

            combined = f"{main_reason}: {detail_bg}".strip(": ") if main_reason and detail_bg else (main_reason or detail_bg)
            if combined:
                reasons_by_name[canonical_key(sec_name)] = combined

        for item in companies_data:
            if isinstance(item, str):
                name = item
                aliases: list[str] = []
                reason = reasons_by_name.get(canonical_key(name), "")
            elif isinstance(item, dict):
                name = item.get("name", "")
                aliases = item.get("aliases", [])
                if isinstance(aliases, str):
                    aliases = [aliases]
                reason = item.get("reason", "") or reasons_by_name.get(canonical_key(name), "")
            else:
                continue

            if name:
                self.add_or_update_entry(
                    name=name,
                    status="discarded",
                    aliases=aliases,
                    reason=reason,
                    source_file=path,
                )

    def _load_profile_companies_file(self, path: Path) -> None:
        """profile/internal/companies.md を解析して内部格付け・除外企業を登録する."""
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return

        fm, _ = extract_frontmatter(content)

        # 1. benchmark_baseline (現職・基準企業)
        baseline = fm.get("benchmark_baseline")
        if baseline and isinstance(baseline, str):
            self.add_or_update_entry(
                name=baseline,
                status="employer",
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
                            status="active",
                            notes=item.get("memo", f"Target {tier}"),
                            source_file=path,
                        )

        # 3. declined_companies (見送り確定)
        for item in fm.get("declined_companies", []):
            if isinstance(item, dict) and "name" in item:
                self.add_or_update_entry(
                    name=item["name"],
                    status="declined",
                    reason=item.get("reason", ""),
                    source_file=path,
                )

        # 4. blacklisted_companies (出禁・ブラックリスト)
        for item in fm.get("blacklisted_companies", []):
            if isinstance(item, dict) and "name" in item:
                self.add_or_update_entry(
                    name=item["name"],
                    status="blacklisted",
                    reason=item.get("reason", ""),
                    notes="出禁・ブラックリスト",
                    source_file=path,
                )

    def find_matches(
        self,
        query: str,
        min_fuzzy_ratio: float = 0.75,
        min_sub_len: int = 3,
    ) -> list[CompanyMatch]:
        """企業名クエリに対して、完全一致・別名一致・部分一致・ファジー一致を判定してスコア順に返す."""
        q_clean = query.strip()
        q_key = canonical_key(q_clean)
        if not q_key:
            return []

        matches: list[CompanyMatch] = []
        seen_keys: set[str] = set()

        # 1. 完全一致の検索 (代表名 or aliases)
        # 代表名完全一致
        if q_key in self.entries:
            entry = self.entries[q_key]
            matches.append(
                CompanyMatch(
                    entry=entry,
                    match_type="exact",
                    matched_name=entry.name,
                    score=1.0,
                )
            )
            seen_keys.add(entry.canonical_name)

        # 別名完全一致
        if q_key in self.alias_to_entry:
            primary_key = self.alias_to_entry[q_key]
            if primary_key in self.entries and primary_key not in seen_keys:
                entry = self.entries[primary_key]
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
                    )
                )
                seen_keys.add(entry.canonical_name)

        # 2. 部分一致 (substring) および ファジー検索 (SequenceMatcher)
        for entry in self.entries.values():
            if entry.canonical_name in seen_keys:
                continue

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
                        )
                        if best_match_for_entry is None or match_candidate.score > best_match_for_entry.score:
                            best_match_for_entry = match_candidate

            if best_match_for_entry:
                matches.append(best_match_for_entry)
                seen_keys.add(entry.canonical_name)

        # スコア降順（同スコアなら完全一致優先）でソート
        type_priority = {
            "exact": 5,
            "alias_exact": 4,
            "substring": 3,
            "alias_substring": 2,
            "fuzzy": 1,
        }
        matches.sort(
            key=lambda m: (m.score, type_priority.get(m.match_type, 0)),
            reverse=True,
        )
        return matches

    def is_excluded(self, query: str) -> tuple[bool, CompanyMatch | None]:
        """指定企業が除外対象（却下・不合格・打ち切り・出禁）かどうか判定する."""
        matches = self.find_matches(query)
        for m in matches:
            if m.is_exclusion:
                return True, m
        return False, None

    def list_entries(
        self,
        category: str | None = None,
        status_filter: set[str] | None = None,
    ) -> list[CompanyEntry]:
        """条件に合致する登録企業一覧をソートして返す."""
        results: list[CompanyEntry] = []
        for entry in self.entries.values():
            if category and category.lower() != "all" and entry.category != category.lower():
                continue
            if status_filter and entry.status.lower() not in status_filter:
                continue
            results.append(entry)

        # ソート: ステータス優先度降順、社名昇順
        results.sort(
            key=lambda e: (-self._status_priority(e.status), e.name),
        )
        return results


def check_company(
    query: str,
    root_dir: Path | None = None,
) -> list[CompanyMatch]:
    """モジュール用ヘルパー関数: クエリを指定して重複・照合結果を取得する."""
    registry = CompanyRegistry(root_dir=root_dir)
    registry.load_all()
    return registry.find_matches(query)


def parse_args(args: Sequence[str] | None = None) -> argparse.Namespace:
    """CLI 引数を定義・解析する."""
    parser = argparse.ArgumentParser(
        description="却下済・除外企業一覧取得および重複チェックCLIツール",
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
        help="絞り込みステータス (カンマ区切り: declined,rejected,discarded,blacklisted,active,employer 等)",
    )
    parser.add_argument(
        "--category",
        choices=["exclusion", "active", "employer", "all"],
        default="all",
        help="絞り込みカテゴリ (exclusion: 除外・却下群, active: 検討中, employer: 現職・前職, all: 全件)",
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
            content = target_path.read_text(encoding="utf-8")
            fm, _ = extract_frontmatter(content)
            c_name = fm.get("company")
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
            )

            # JSON 出力
            if args.json:
                data = {
                    "total_count": len(entries),
                    "category": args.category,
                    "companies": [e.to_dict() for e in entries],
                }
                return ctx.flush_outputs(json_data=data)

            # サマリ表示
            if args.summary:
                def print_summary_list() -> None:
                    print("=" * 80)
                    print(f"登録企業一覧 (合計: {len(entries)} 社 / カテゴリ: {args.category})")
                    print("=" * 80)
                    for idx, e in enumerate(entries, start=1):
                        ex_mark = "【除外】" if e.is_exclusion else "【検討】"
                        alias_str = f" (別名: {', '.join(e.aliases)})" if e.aliases else ""
                        print(f"{idx:3d}. {ex_mark} [{e.status.upper()}] {e.name}{alias_str}")
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
        matches = registry.find_matches(query_str)

        has_exclusion = any(m.is_exclusion for m in matches)
        if args.strict_exit and has_exclusion:
            ctx.set_exit_code(2)

        # JSON 出力
        if args.json:
            data = {
                "query": query_str,
                "matched": len(matches) > 0,
                "has_exclusion": has_exclusion,
                "matches": [m.to_dict() for m in matches],
            }
            return ctx.flush_outputs(json_data=data)

        # サマリ表示
        if args.summary:
            def print_check_summary() -> None:
                print("=" * 80)
                print(f"企業重複チェック結果: '{query_str}'")
                print("=" * 80)
                if not matches:
                    print("【判定】新規企業（未登録）: 過去の相談・除外ログに該当はありません。")
                    print("=" * 80)
                    return

                top = matches[0]
                if top.is_exclusion:
                    print(f"【判定】🚨 除外・見送り企業に該当します（ステータス: {top.entry.status.upper()}）")
                else:
                    print(f"【判定】ℹ️ 登録済みの企業です（ステータス: {top.entry.status.upper()}）")

                print(f"- 該当社名: {top.entry.name} (照合一致: {top.matched_name}, 種別: {top.match_type})")
                if top.entry.aliases:
                    print(f"- 別名: {', '.join(top.entry.aliases)}")
                if top.entry.reason:
                    print(f"- 理由・背景: {top.entry.reason}")
                if top.entry.source_files:
                    print(f"- 参照ファイル: {', '.join(top.entry.source_files)}")

                if len(matches) > 1:
                    print(f"\n[その他類似ヒット: {len(matches) - 1} 件]")
                    for extra in matches[1:4]:
                        ex_tag = "除外" if extra.is_exclusion else "検討"
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
