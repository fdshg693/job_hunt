"""vault にたまった雑務（記録の更新漏れ・放置）を洗い出す CLI.

検出器ごとに雑務の候補と根拠を出すだけで、vault は書き換えない。判断・処理は sweep-chores スキルで行う。
- 判定は既存のものを import して使う（期限切れ: ``loader.overdue_date``、圧縮候補: ``compact_closed.list_candidates``、
  英語版の未同期: ``sync_en.check_sync_status``、vault からの data/ 参照: ``data_retention``、その他の警告: ``load_vault`` の警告）。
- 雑務には安定した ID（``{検出器}:{対象}``）・処理区分（auto / confirm / ask）・優先度を付ける。
- 雑務があっても終了コードは 0（雑務は失敗ではない）。

検出器・閾値・処理区分・JSON の形は docs/vault/chores.md が正本。
.agents/rules/scripts-entrypoint.md に従い、stdout には雑務のあるファイルのパスだけを出す
（``--summary`` で優先度順の一覧、``--json`` で雑務オブジェクトの配列）。
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from enum import IntEnum, StrEnum
from pathlib import Path

# プロジェクトルートパス (scripts/vault/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import create_base_parser, entrypoint_guard
from scripts.common.data_retention import is_retained_ref, vault_data_refs_by_file
from scripts.common.paths import TRACKS
from scripts.profile.sync_en import check_sync_status
from scripts.vault.compact_closed import DEFAULT_OLDER_THAN_DAYS, list_candidates
from scripts.vault.loader import Vault, VaultDoc, load_vault, overdue_date
from scripts.vault.schema import (
    ActionType,
    CompanyDoc,
    InterviewDoc,
    InterviewResult,
    MaterialDoc,
    PipelineDoc,
    RecruiterDoc,
    RecruiterStatus,
    ScreeningBatchDoc,
    StatusCategory,
)

DEFAULT_WAITING_DAYS = 7
DEFAULT_IDLE_DAYS = 14
DEFAULT_RECRUITER_DAYS = 30
DEFAULT_MATERIAL_DAYS = 60


class Handling(StrEnum):
    """雑務の処理区分."""

    AUTO = "auto"  # AI が直して差分を見せる
    CONFIRM = "confirm"  # 案を示して承認を取る
    ASK = "ask"  # ユーザーに聞かないと進まない


HANDLING_LABELS: dict[Handling, str] = {
    Handling.AUTO: "AIが修正",
    Handling.CONFIRM: "要承認",
    Handling.ASK: "要回答",
}


class Priority(IntEnum):
    """処理順（小さいほど先）. 放置すると実害が出る順."""

    DEADLINE = 1  # 期限・予定に絡むもの
    RECORD = 2  # 記録の欠落
    FRESHNESS = 3  # ダッシュボード・状態の鮮度
    TIDY = 4  # 整理（圧縮・英語版同期）


PRIORITY_LABELS: dict[Priority, str] = {
    Priority.DEADLINE: "期限・予定",
    Priority.RECORD: "記録の欠落",
    Priority.FRESHNESS: "鮮度",
    Priority.TIDY: "整理",
}


@dataclass(frozen=True)
class Chore:
    id: str  # {検出器}:{対象}。再実行しても同じ雑務は同じ ID になる
    detector: str
    handling: Handling
    priority: Priority
    path: str  # 読み込みルート相対（スラッシュ区切り）
    target: str  # 人間向けの対象名（社名・担当者名・ファイル名）
    reason: str  # 検出の根拠
    suggestion: str  # 推奨アクション
    since: dt.date | None = None  # 同じ優先度の中で古いものを先にするための日付
    track: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["handling"] = str(self.handling)
        d["priority"] = int(self.priority)
        d["since"] = self.since.isoformat() if self.since else None
        return d


@dataclass(frozen=True)
class Thresholds:
    waiting_days: int = DEFAULT_WAITING_DAYS
    idle_days: int = DEFAULT_IDLE_DAYS
    recruiter_days: int = DEFAULT_RECRUITER_DAYS
    compact_days: int = DEFAULT_OLDER_THAN_DAYS
    material_days: int = DEFAULT_MATERIAL_DAYS


# --- 面談メモ未記入の判定 ----------------------------------------------------

_MEMO_HEADING = re.compile(r"^##\s+(?:\d+\.\s*)?[^#]*面談メモ")
_BULLET = re.compile(r"^(?:[-*+]|\d+\.)\s*(?:\[[ xX]\]\s*)?")
_LABEL_VALUE = re.compile(r"^(?:\*\*(?P<bold>.+?)\*\*|(?P<plain>[^:：*]{1,40}))\s*[:：]\s*(?P<value>.*)$")
# 面談の日時・相手は事前に書かれるので、記入済みの根拠にしない
_META_LABELS = {"面談日時", "日時", "実施日時", "面談相手", "形式"}


def memo_section(body: str) -> str | None:
    """本文の「面談メモ」節（見出しの次行から次の ## 見出しの手前まで）. 節が無ければ None."""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if _MEMO_HEADING.match(line):
            end = next((j for j in range(i + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
            return "\n".join(lines[i + 1 : end])
    return None


def _is_substantive(line: str) -> bool:
    """テンプレートのプレースホルダ・事前記入のメタ情報ではない、記入された内容の行か."""
    s = line.strip()
    if not s or s.startswith(("#", "---", "※", ">")):
        return False
    s = _BULLET.sub("", s).strip()
    if not s or re.fullmatch(r"[（(].*[）)]", s):  # （面談後に記入）（例: ...）
        return False
    if re.fullmatch(r"\*\*.+\*\*", s):  # テンプレートの質問見出し（**Q1. ...？**）
        return False
    m = _LABEL_VALUE.match(s)
    if m:
        label = (m.group("bold") or m.group("plain") or "").strip()
        value = m.group("value").strip()
        if not value or value.startswith(("（例", "(例")) or label in _META_LABELS:
            return False
    return True


def is_memo_unfilled(body: str) -> bool:
    """面談メモ節がテンプレートのまま（記入された行が無い）か. 節が無ければ判定しない（False）."""
    section = memo_section(body)
    return section is not None and not any(_is_substantive(line) for line in section.splitlines())


# --- 検出器 -------------------------------------------------------------------


def _days(today: dt.date, since: dt.date) -> int:
    return (today - since).days


class _Finder:
    def __init__(self, vault: Vault, today: dt.date, track: str | None, th: Thresholds) -> None:
        self.vault, self.today, self.track, self.th = vault, today, track, th
        self.chores: list[Chore] = []
        # 同じ企業キーが複数 track にあるときだけ ID に track を付ける
        counts = Counter(c.folder_key for c in vault.companies)
        self._multi_track = {k for k, n in counts.items() if n > 1}

    def in_track(self, doc: VaultDoc) -> bool:
        return self.track is None or doc.track is None or doc.track == self.track

    def company_ref(self, doc: VaultDoc) -> str:
        key = doc.folder_key or ""
        return f"{key}@{doc.track}" if key in self._multi_track else key

    def add(self, **kwargs) -> None:
        self.chores.append(Chore(**kwargs))

    def companies(self) -> list[tuple[VaultDoc, CompanyDoc]]:
        return [(d, d.model) for d in self.vault.companies if isinstance(d.model, CompanyDoc) and self.in_track(d)]

    # 期限切れアクション・予定日が過ぎた scheduled
    def overdue(self) -> None:
        for doc, m in self.companies():
            due = overdue_date(m, self.today)
            if due is None:
                continue
            if m.action_type == ActionType.SCHEDULED:
                self.add(
                    id=f"past-scheduled:{self.company_ref(doc)}", detector="past-scheduled", handling=Handling.ASK,
                    priority=Priority.DEADLINE, path=doc.rel, target=m.company, since=due, track=doc.track,
                    reason=f"予定日 {due} を過ぎている（next_action: {m.next_action or '-'}）",
                    suggestion="実施できたか・結果と感想を聞き、面談ログ・status・next_action を更新する",
                )
            else:
                self.add(
                    id=f"overdue-action:{self.company_ref(doc)}", detector="overdue-action", handling=Handling.ASK,
                    priority=Priority.DEADLINE, path=doc.rel, target=m.company, since=due, track=doc.track,
                    reason=f"期限 {due} を過ぎている（next_action: {m.next_action or '-'}）",
                    suggestion="対応済みか・どうするかを聞き、next_action / next_due を更新する",
                )

    # 連絡待ちの長期化・検討中の放置
    def stale_companies(self) -> None:
        for doc, m in self.companies():
            if m.status_category != StatusCategory.ACTIVE:
                continue
            days = _days(self.today, m.updated_at)
            if m.action_type == ActionType.WAITING and days >= self.th.waiting_days:
                self.add(
                    id=f"waiting-stale:{self.company_ref(doc)}", detector="waiting-stale", handling=Handling.CONFIRM,
                    priority=Priority.DEADLINE, path=doc.rel, target=m.company, since=m.updated_at, track=doc.track,
                    reason=f"連絡待ちのまま {days} 日更新なし（next_action: {m.next_action or '-'}）",
                    suggestion="フォローの連絡をするか、見送るかを決める",
                )
            elif m.action_type == ActionType.NONE and days >= self.th.idle_days:
                self.add(
                    id=f"idle-company:{self.company_ref(doc)}", detector="idle-company", handling=Handling.CONFIRM,
                    priority=Priority.FRESHNESS, path=doc.rel, target=m.company, since=m.updated_at, track=doc.track,
                    reason=f"status={m.status} でアクション無しのまま {days} 日更新なし",
                    suggestion="応募する・面談を申し込む・見送るのいずれかを決める",
                )

    # 面談結果の放置・面談メモ未記入・面談ログの未リンク
    def interviews(self) -> None:
        for doc in self.vault.interviews:
            m = doc.model
            if not isinstance(m, InterviewDoc) or not self.in_track(doc):
                continue
            ref = f"{self.company_ref(doc) if doc.track else doc.folder_key}/{doc.path.stem}"
            target = m.company or doc.folder_key or doc.rel
            past = m.date < self.today
            if past and m.result == InterviewResult.PENDING:
                self.add(
                    id=f"interview-result:{ref}", detector="interview-result", handling=Handling.ASK,
                    priority=Priority.RECORD, path=doc.rel, target=target, since=m.date, track=doc.track,
                    reason=f"{m.date} の面談（{m.stage}）の result が pending のまま",
                    suggestion="結果（通過・不合格・辞退、合否の無い面談なら not_applicable）を聞いて result を更新する",
                )
            if past and is_memo_unfilled(doc.body):
                self.add(
                    id=f"interview-memo:{ref}", detector="interview-memo", handling=Handling.ASK,
                    priority=Priority.RECORD, path=doc.rel, target=target, since=m.date, track=doc.track,
                    reason=f"{m.date} の面談（{m.stage}）の面談メモ節がテンプレートのまま",
                    suggestion="面談の内容・感想を聞いて面談メモと所感を記入し、index.md のサマリに反映する",
                )
            parent = (
                self.vault.company(doc.folder_key or "", doc.track) if doc.track
                else self.vault.recruiter(doc.folder_key or "")
            )
            if parent is not None and doc.path.name not in parent.body:
                self.add(
                    id=f"interview-unlinked:{ref}", detector="interview-unlinked", handling=Handling.AUTO,
                    priority=Priority.RECORD, path=parent.rel, target=target, since=m.date, track=doc.track,
                    reason=f"{doc.path.name} が {parent.path.name} からリンクされていない",
                    suggestion=f"{parent.path.name} のサマリ節に面談ログへの相対リンクを追記する",
                )

    # pipeline 手書き部の鮮度
    def pipelines(self) -> None:
        for doc in self.vault.pipelines:
            m = doc.model
            if not isinstance(m, PipelineDoc) or not self.in_track(doc):
                continue
            reasons = []
            if m.next_due is not None and m.next_due < self.today:
                reasons.append(f"next_due={m.next_due} を過ぎている（next_action: {m.next_action or '-'}）")
            latest = max(
                (c.model.updated_at for c in self.vault.companies if c.track == doc.track and isinstance(c.model, CompanyDoc)),
                default=None,
            )
            if latest is not None and m.updated_at < latest:
                reasons.append(f"updated_at={m.updated_at} が同 track の企業ログの最新更新 {latest} より古い")
            if reasons:
                self.add(
                    id=f"pipeline-stale:{doc.track}", detector="pipeline-stale", handling=Handling.AUTO,
                    priority=Priority.FRESHNESS, path=doc.rel, target=f"{doc.track} pipeline.md", since=m.updated_at,
                    track=doc.track, reason=" / ".join(reasons),
                    suggestion="build_pipeline.py で一覧を再生成し、手書き部（フェーズ・next_action・チェックリスト）を企業ログに合わせる",
                )

    # リクルーターの放置
    def recruiters(self) -> None:
        for doc in self.vault.recruiters:
            m = doc.model
            if not isinstance(m, RecruiterDoc) or m.status != RecruiterStatus.ACTIVE:
                continue
            if self.track is not None and self.track not in m.tracks:
                continue
            days = _days(self.today, m.updated_at)
            if days >= self.th.recruiter_days:
                self.add(
                    id=f"recruiter-stale:{doc.folder_key}", detector="recruiter-stale", handling=Handling.CONFIRM,
                    priority=Priority.FRESHNESS, path=doc.rel, target=f"{m.name}（{m.agency or m.platform}）",
                    since=m.updated_at, reason=f"status=active のまま {days} 日更新なし",
                    suggestion="やり取りが続いているか確認し、終わっていれば declined にする",
                )

    # 圧縮候補
    def compact(self) -> None:
        for c in list_candidates(self.vault, self.track, self.today, self.th.compact_days):
            m = c.doc.model
            if isinstance(m, ScreeningBatchDoc):
                ref, target = f"screening/{c.doc.path.stem}", f"スクリーニング: {m.topic}"
            else:
                ref, target = self.company_ref(c.doc), getattr(m, "company", c.doc.rel)
            self.add(
                id=f"compact:{ref}", detector="compact", handling=Handling.CONFIRM, priority=Priority.TIDY,
                path=c.doc.rel, target=target, since=c.closed_on, track=c.track,
                reason=f"{c.closed_on} に終了して {self.th.compact_days} 日以上経過",
                suggestion="compact_closed.py draft で要約を作り、承認を取って apply する",
            )

    # 外部資料（material）の鮮度・生データの欠落
    def materials(self) -> None:
        for doc in self.vault.materials:
            m = doc.model
            if not isinstance(m, MaterialDoc) or not self.in_track(doc):
                continue
            owner = (
                self.vault.company(doc.folder_key or "", doc.track) if doc.track
                else self.vault.recruiter(doc.folder_key or "")
            )
            if owner is None or not self._is_live_owner(owner):
                continue  # 終了した企業・リクルーターの資料が古いのは問題ではない
            days = _days(self.today, m.fetched_at)
            if days < self.th.material_days:
                continue  # 生データが消えているだけなら正常（保持期間による削除）
            owner_ref = self.company_ref(owner) if doc.track else doc.folder_key
            ref = f"{owner_ref}/{doc.path.stem}"
            target = f"{getattr(owner.model, 'company', None) or getattr(owner.model, 'name', owner.rel)}: {m.title}"
            missing = [p for p in m.raw_data if not (self.vault.root / p).exists()]
            if missing:
                self.add(
                    id=f"material-raw-missing:{ref}", detector="material-raw-missing", handling=Handling.CONFIRM,
                    priority=Priority.FRESHNESS, path=doc.rel, target=target, since=m.fetched_at, track=doc.track,
                    reason=f"要約が {days} 日前（fetched_at={m.fetched_at}）で、生データ {', '.join(missing)} が残っていない",
                    suggestion="add_material.py --refresh で生データを取り直し、要約を見直して fetched_at を今日にする",
                )
            else:
                self.add(
                    id=f"material-stale:{ref}", detector="material-stale", handling=Handling.CONFIRM,
                    priority=Priority.FRESHNESS, path=doc.rel, target=target, since=m.fetched_at, track=doc.track,
                    reason=f"要約が {days} 日前（fetched_at={m.fetched_at}）のまま",
                    suggestion="add_material.py --refresh で取り直して要約を見直す（変化が無ければ fetched_at だけ今日にする）",
                )

    def _is_live_owner(self, owner: VaultDoc) -> bool:
        m = owner.model
        if isinstance(m, CompanyDoc):
            return m.status_category == StatusCategory.ACTIVE
        if isinstance(m, RecruiterDoc):
            return m.status == RecruiterStatus.ACTIVE and (self.track is None or self.track in m.tracks)
        return False

    # vault 本文からの data/ 直接参照（保持期間で消える生データを指しているもの）
    def data_refs(self) -> None:
        for path, refs in vault_data_refs_by_file(self.vault.root / "vault").items():
            parts = path.split("/")
            track = parts[2] if len(parts) > 2 and parts[1] == "tracks" else None
            if self.track is not None and track is not None and track != self.track:
                continue
            retained = [r for r in refs if is_retained_ref(r)]
            if not retained:
                continue
            examples = ", ".join(retained[:3]) + (f" ほか {len(retained) - 3} 件" if len(retained) > 3 else "")
            self.add(
                id=f"data-ref:{path}", detector="data-ref", handling=Handling.CONFIRM, priority=Priority.TIDY,
                path=path, target=path, track=track,
                reason=f"保持期間で消える生データを本文から直接参照している（{examples}）",
                suggestion="判断に使った内容を本文か material（add_material.py）に要約し、data/ への直接参照を外す",
            )

    # 英語版の未同期
    def english(self) -> None:
        profile_dir = self.vault.root / "vault" / "profile"
        en_dir = profile_dir / "en"
        if not en_dir.is_dir():  # 英語版を使っていない vault では検出しない
            return
        for s in check_sync_status(profile_dir=profile_dir, en_dir=en_dir):
            if s["status"] not in ("STALE", "MISSING", "UNTRACKED"):
                continue
            self.add(
                id=f"en-sync:{s['file']}", detector="en-sync", handling=Handling.CONFIRM, priority=Priority.TIDY,
                path=s["en_path"], target=s["en_path"], reason=(
                    f"{s['status']}（日本語版 {s['source_updated_at'] or '-'} / 英語版の同期元 {s['target_source_updated_at'] or '-'}）"
                ),
                suggestion="日本語版との差分を英訳して見せ、承認後に反映して sync_en.py update-meta する",
            )


# その他の validate 警告のうち、AI が直してよい（判断が要らない）もの
_AUTO_WARNING_PATTERNS = ("で終了しているのに action_type=",)


def _other_warnings(finder: _Finder, base: Vault) -> None:
    """期限切れ以外の loader 警告（today 無しで読んだ警告）をファイル単位にまとめる."""
    by_path: dict[str, list[str]] = {}
    tracks: dict[str, str | None] = {}
    docs = {d.rel: d for d in base.docs()}
    for issue in base.warnings:
        doc = docs.get(issue.path)
        if doc is not None and not finder.in_track(doc):
            continue
        by_path.setdefault(issue.path, []).append(issue.message)
        tracks[issue.path] = doc.track if doc else None
    for path, messages in by_path.items():
        auto = all(any(p in msg for p in _AUTO_WARNING_PATTERNS) for msg in messages)
        finder.add(
            id=f"validate-warning:{path}", detector="validate-warning",
            handling=Handling.AUTO if auto else Handling.CONFIRM, priority=Priority.FRESHNESS,
            path=path, target=path, track=tracks[path], reason=" / ".join(messages),
            suggestion="validate.py の警告を解消する",
        )


def find_chores(
    root: Path, today: dt.date, track: str | None = None, thresholds: Thresholds | None = None
) -> list[Chore]:
    """雑務を優先度順（同じ優先度の中は古い順）に返す."""
    # today 無しで読むと期限切れ警告が出ない。期限切れは overdue 検出器で拾うので、その他の警告と二重にならない
    vault = load_vault(root)
    finder = _Finder(vault, today, track, thresholds or Thresholds())
    finder.overdue()
    finder.stale_companies()
    finder.interviews()
    finder.pipelines()
    finder.recruiters()
    finder.materials()
    finder.compact()
    finder.data_refs()
    finder.english()
    _other_warnings(finder, vault)
    return sorted(finder.chores, key=lambda c: (c.priority, c.since or dt.date.max, c.id))


def main() -> None:
    parser = create_base_parser(
        description="vault にたまった雑務（更新漏れ・放置）を優先度順に洗い出す",
        examples=[
            "uv run python scripts/vault/find_chores.py --summary  # 優先度順の一覧（根拠・推奨アクション付き）",
            "uv run python scripts/vault/find_chores.py --json  # 雑務オブジェクトの配列",
            "uv run python scripts/vault/find_chores.py --track domestic --today 2026-10-30 --summary",
        ],
        related=[
            "scripts/vault/compact_closed.py: compact の雑務を見送り台帳に畳む",
            "scripts/vault/prune_data.py: data/ の古い生データを消す",
        ],
    )
    parser.add_argument("--track", choices=["all", *TRACKS], default="all", help="対象 track（既定: all。track に属さない雑務は常に含む）")
    parser.add_argument(
        "--root", type=Path, default=PROJECT_ROOT, help="vault/ を含むディレクトリ（既定: リポジトリルート）"
    )
    parser.add_argument(
        "--today", type=dt.date.fromisoformat, default=dt.date.today(), help="基準日（YYYY-MM-DD、既定: 今日）"
    )
    parser.add_argument("--waiting-days", type=int, default=DEFAULT_WAITING_DAYS, help=f"連絡待ちの長期化とみなす日数（既定: {DEFAULT_WAITING_DAYS}）")
    parser.add_argument("--idle-days", type=int, default=DEFAULT_IDLE_DAYS, help=f"検討中の放置とみなす日数（既定: {DEFAULT_IDLE_DAYS}）")
    parser.add_argument("--recruiter-days", type=int, default=DEFAULT_RECRUITER_DAYS, help=f"リクルーターの放置とみなす日数（既定: {DEFAULT_RECRUITER_DAYS}）")
    parser.add_argument("--compact-days", type=int, default=DEFAULT_OLDER_THAN_DAYS, help=f"圧縮候補とみなす終了後の日数（既定: {DEFAULT_OLDER_THAN_DAYS}）")
    parser.add_argument("--material-days", type=int, default=DEFAULT_MATERIAL_DAYS, help=f"外部資料の要約が古いとみなす日数（既定: {DEFAULT_MATERIAL_DAYS}）")
    args = parser.parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        root = args.root if args.root.is_absolute() else PROJECT_ROOT / args.root
        track = None if args.track == "all" else args.track
        thresholds = Thresholds(args.waiting_days, args.idle_days, args.recruiter_days, args.compact_days, args.material_days)
        chores = find_chores(root, args.today, track, thresholds)
        if args.limit:
            chores = chores[: args.limit]

        for path in dict.fromkeys(c.path for c in chores):
            ctx.add_result_path(root / path)
        counts = Counter(c.handling for c in chores)
        ctx.info(
            f"雑務 {len(chores)} 件（基準日 {args.today}）: "
            + " / ".join(f"{HANDLING_LABELS[h]} {counts[h]}" for h in Handling)
        )

        def print_summary() -> None:
            if not chores:
                print(f"雑務なし（基準日 {args.today}）")
                return
            current = None
            for n, c in enumerate(chores, 1):
                if c.priority != current:
                    current = c.priority
                    print(f"\n## {int(c.priority)}. {PRIORITY_LABELS[c.priority]}")
                print(f"{n:>2}. [{HANDLING_LABELS[c.handling]}] {c.id}  {c.target}")
                print(f"      根拠: {c.reason}")
                print(f"      対応: {c.suggestion}")
                print(f"      {c.path}")

        json_data = {"today": args.today.isoformat(), "root": str(root), "chores": [c.to_dict() for c in chores]}
        sys.exit(ctx.flush_outputs(summary_fn=print_summary, json_data=json_data))


if __name__ == "__main__":
    main()
