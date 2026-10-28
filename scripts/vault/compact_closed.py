"""終了企業・古いスクリーニングを見送り台帳 archive.md に圧縮する CLI.

終了した企業フォルダ（declined / rejected / blacklisted）と古いスクリーニング集約ログを、
track ごとの見送り台帳に 1 社数行のエントリとして畳み込み、元のフォルダ・ファイルを ``git rm`` する。
エントリの「本質」（見送り理由の核心・再検討の条件）は AI が書いてユーザーが確認する。この CLI は機械的な部分だけを担う。

サブコマンド:
- ``list``: 圧縮候補（終了して ``--older-than-days`` 日以上経った企業フォルダ・スクリーニングバッチ）
- ``draft --key K``: 企業フォルダのフロントマターから台帳エントリの下書きを作る（reason / reconsider_if 以外）
- ``apply --key K [--reason ...]``: 台帳にエントリがあることを確かめて企業フォルダを ``git rm`` する。
  台帳に無ければ ``--reason`` から下書き＋上書き値でエントリを追記してから消す
- ``apply --screening FILE``: スクリーニングバッチの各社を台帳エントリに変換・追記し、バッチを ``git rm`` する

.agents/rules/scripts-entrypoint.md 規約に準拠し、標準出力にはファイルパスのみを出力する
（list: 候補のパス / draft: 要約の材料になるファイル / apply: 台帳のパス）。
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# プロジェクトルートパス (scripts/vault/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import create_base_parser, entrypoint_guard
from scripts.common.paths import TRACKS
from scripts.vault import display, frontmatter
from scripts.vault.loader import Vault, VaultDoc, load_vault
from scripts.vault.schema import (
    COMPANY_STATUS_META,
    ArchivedCompany,
    ArchiveDoc,
    ArchivedStatus,
    ArchiveSource,
    CompanyDoc,
    CompanyStatus,
    InterviewDoc,
    InterviewStage,
    RecruiterDoc,
    ScreeningBatchDoc,
    StatusCategory,
)

DEFAULT_OLDER_THAN_DAYS = 14

# 圧縮できる企業ステータス（終了した企業のうち承諾以外）
COMPACTABLE_STATUSES = {
    CompanyStatus.DECLINED: ArchivedStatus.DECLINED,
    CompanyStatus.REJECTED: ArchivedStatus.REJECTED,
    CompanyStatus.BLACKLISTED: ArchivedStatus.BLACKLISTED,
}

# 面談ログの stage → 到達した企業ステータス（reached の下書きに使う）
STAGE_REACHED = {
    InterviewStage.CASUAL: CompanyStatus.CASUAL_INTERVIEW,
    InterviewStage.FIRST_INTERVIEW: CompanyStatus.FIRST_INTERVIEW,
    InterviewStage.SECOND_INTERVIEW: CompanyStatus.SECOND_INTERVIEW,
    InterviewStage.FINAL: CompanyStatus.FINAL_INTERVIEW,
    InterviewStage.OFFER: CompanyStatus.OFFER,
}

REASON_PLACEHOLDER = "TODO: 見送り理由の核心（条件の言葉で 1〜2 文）"

ARCHIVE_BODY = """
# 見送り台帳（{track}）

終了（見送り・不合格・ブラックリスト）した企業フォルダと、古いスクリーニング集約ログを 1 社数行に圧縮した台帳。
正はフロントマターの `companies`（本文に一覧表は書かない。一覧は Web UI の見送り台帳ページで見る）。
追記・圧縮は `uv run python scripts/vault/compact_closed.py` で行う。圧縮前の詳細は git 履歴に残っている。
"""


class CompactionError(Exception):
    """圧縮の前提条件を満たさない（誤操作防止の拒否を含む）."""


# ---------------------------------------------------------------------------
# パス・git
# ---------------------------------------------------------------------------


def archive_path(root: Path, track: str) -> Path:
    return root / "vault" / "tracks" / track / "archive.md"


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise CompactionError(f"git {' '.join(args)} に失敗: {result.stderr.strip()}")
    return result.stdout


def ensure_committed(root: Path, target: Path) -> None:
    """target（ファイル・フォルダ）が git 管理下で、未コミットの変更が無いことを確かめる.

    git 履歴を保険にする前提なので、履歴に残っていない内容は消さない。
    """
    rel = target.relative_to(root).as_posix()
    if not _git(root, "ls-files", "--", rel).strip():
        raise CompactionError(f"{rel} は git 管理下に無い。先にコミットしてから圧縮する")
    dirty = _git(root, "status", "--porcelain", "--untracked-files=all", "--", rel).strip()
    if dirty:
        raise CompactionError(f"{rel} に未コミットの変更がある。先にコミットしてから圧縮する:\n{dirty}")


def git_remove(root: Path, target: Path) -> None:
    _git(root, "rm", "-r", "-q", "--", target.relative_to(root).as_posix())


# ---------------------------------------------------------------------------
# 候補抽出・下書き
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    """圧縮候補（企業フォルダまたはスクリーニングバッチ）."""

    kind: str  # "company" / "screening"
    track: str
    doc: VaultDoc
    closed_on: dt.date  # 判定に使った日付（企業は updated_at、スクリーニングはバッチの date）
    interviews: list[VaultDoc] = field(default_factory=list)

    @property
    def label(self) -> str:
        m = self.doc.model
        if isinstance(m, CompanyDoc):
            return f"{m.company}（{self.doc.folder_key}）"
        if isinstance(m, ScreeningBatchDoc):
            return f"{m.topic}（{len(m.companies)}社）"
        return self.doc.rel


def _closed_company(doc: VaultDoc) -> CompanyDoc | None:
    m = doc.model
    return m if isinstance(m, CompanyDoc) and m.status in COMPACTABLE_STATUSES else None


def list_candidates(vault: Vault, track: str | None, today: dt.date, older_than_days: int) -> list[Candidate]:
    """終了して older_than_days 日以上経った企業フォルダとスクリーニングバッチ（日付の古い順）."""
    limit = today - dt.timedelta(days=older_than_days)
    candidates: list[Candidate] = []
    for doc in vault.companies:
        m = _closed_company(doc)
        if m is None or (track and doc.track != track) or m.updated_at > limit:
            continue
        candidates.append(Candidate("company", doc.track or "", doc, m.updated_at, vault.interviews_of(doc)))
    for doc in vault.screening:
        m = doc.model
        if not isinstance(m, ScreeningBatchDoc) or (track and doc.track != track) or m.date > limit:
            continue
        candidates.append(Candidate("screening", doc.track or "", doc, m.date))
    candidates.sort(key=lambda c: (c.closed_on, c.doc.rel))
    return candidates


def find_company(vault: Vault, key: str, track: str | None) -> VaultDoc:
    """--key の企業フォルダを引き、圧縮してよい企業か確かめる（選考中・検討中は拒否）."""
    matches = [c for c in vault.companies if c.folder_key == key and (track is None or c.track == track)]
    if not matches:
        raise CompactionError(f"企業フォルダ companies/{key}/ が見つからない（track={track or 'all'}）")
    if len(matches) > 1:
        raise CompactionError(f"companies/{key}/ が複数 track にある。--track で指定する")
    doc = matches[0]
    m = doc.model
    if not isinstance(m, CompanyDoc):
        raise CompactionError(f"{doc.rel} がスキーマ違反。validate.py で直してから圧縮する")
    if m.status not in COMPACTABLE_STATUSES:
        category = COMPANY_STATUS_META[m.status].category
        why = "選考中・検討中" if category == StatusCategory.ACTIVE else "圧縮対象外のステータス"
        raise CompactionError(f"{doc.rel} は status={m.status}（{why}）なので圧縮しない")
    return doc


def reached_from_interviews(interviews: list[VaultDoc]) -> CompanyStatus | None:
    """面談ログの stage から、到達した最も進んだ段階を返す（面談ログが無ければ None）."""
    reached = [
        STAGE_REACHED[i.model.stage]
        for i in interviews
        if isinstance(i.model, InterviewDoc) and i.model.stage in STAGE_REACHED
    ]
    return min(reached, key=lambda s: COMPANY_STATUS_META[s].order) if reached else None


def draft_entry(vault: Vault, doc: VaultDoc, **overrides: object) -> ArchivedCompany:
    """企業ログから台帳エントリを作る. reason 等の AI が書く項目は overrides で渡す（無ければ仮置き）."""
    m = doc.model
    assert isinstance(m, CompanyDoc)
    data: dict[str, object] = {
        "name": m.company,
        "company_key": m.company_key,
        "aliases": m.aliases,
        "status": COMPACTABLE_STATUSES[m.status],
        "considered_at": m.date,
        "closed_at": m.updated_at,  # 見送り日の専用フィールドは無いので updated_at を既定値にする
        "reached": reached_from_interviews(vault.interviews_of(doc)),
        "fit_score_min": m.fit_score_min,
        "fit_score_max": m.fit_score_max,
        "reason": REASON_PLACEHOLDER,
        "recruiter": m.recruiter,
        "source": ArchiveSource.COMPANY_LOG,
    }
    data.update({k: v for k, v in overrides.items() if v is not None})
    return ArchivedCompany.model_validate(data)


def screening_entries(doc: VaultDoc) -> list[ArchivedCompany]:
    """スクリーニングバッチの各社を台帳エントリ（discarded）に変換する."""
    m = doc.model
    assert isinstance(m, ScreeningBatchDoc)
    return [
        ArchivedCompany(
            name=c.name,
            aliases=c.aliases,
            status=ArchivedStatus.DISCARDED,
            considered_at=m.date,
            closed_at=m.date,
            reason=c.reason,
            source=ArchiveSource.SCREENING,
        )
        for c in m.companies
    ]


def recruiters_without_note(vault: Vault, key: str) -> list[str]:
    """company_key=key を紹介企業に持ち、note が空のリクルーターキー."""
    return [
        r.folder_key or ""
        for r in vault.recruiters
        if isinstance(r.model, RecruiterDoc)
        and any(ic.company_key == key and not ic.note for ic in r.model.introduced_companies)
    ]


# ---------------------------------------------------------------------------
# 台帳への追記・適用
# ---------------------------------------------------------------------------


def load_archive(vault: Vault, root: Path, track: str) -> tuple[ArchiveDoc, frontmatter.MarkdownDoc | None]:
    """台帳を読む（無ければ空の台帳）. スキーマ違反の台帳には書き足さない."""
    doc = vault.archive(track)
    if doc is None:
        return ArchiveDoc(track=track, updated_at=dt.date.today(), companies=[]), None
    if not isinstance(doc.model, ArchiveDoc):
        raise CompactionError(f"{doc.rel} がスキーマ違反。validate.py で直してから追記する")
    return doc.model.model_copy(deep=True), frontmatter.read(archive_path(root, track))


def write_archive(root: Path, track: str, archive: ArchiveDoc, md: frontmatter.MarkdownDoc | None, today: dt.date) -> Path:
    path = archive_path(root, track)
    archive.updated_at = today
    validated = ArchiveDoc.model_validate(archive.model_dump())  # 追記後のキー重複などを検査する
    if md is None:
        path.write_text(frontmatter.render(validated, ARCHIVE_BODY.format(track=track)), encoding="utf-8")
    else:
        frontmatter.write(path, validated, md)
    return path


@dataclass
class ApplyResult:
    archive: Path
    removed: Path
    added: list[ArchivedCompany]
    skipped: list[str] = field(default_factory=list)  # 既に台帳にあって追記しなかった社名


def apply_company(
    vault: Vault,
    root: Path,
    key: str,
    *,
    track: str | None = None,
    overrides: dict[str, object] | None = None,
    today: dt.date | None = None,
    dry_run: bool = False,
) -> ApplyResult:
    """企業フォルダを圧縮する.

    台帳に company_key のエントリがあればそれを正とし、フォルダを消すだけ。
    無ければ overrides（reason 必須）から下書きを作って追記してから消す。
    """
    today = today or dt.date.today()
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    doc = find_company(vault, key, track)
    track = doc.track or ""
    folder = doc.path.parent
    archive, md = load_archive(vault, root, track)
    existing = next((e for e in archive.companies if e.company_key == key), None)

    added: list[ArchivedCompany] = []
    if existing is not None:
        if overrides:
            raise CompactionError(
                f"台帳に company_key={key} のエントリが既にある。内容を直すなら台帳を編集し、--reason 等は付けずに apply する"
            )
    else:
        if "reason" not in overrides:
            raise CompactionError(
                f"台帳に company_key={key} のエントリが無い。要約（--reason）を書いてから apply する（下書きは draft --key {key} --summary）"
            )
        added.append(draft_entry(vault, doc, **overrides))

    ensure_committed(root, folder)
    path = archive_path(root, track)
    if not dry_run:
        if added:
            archive.companies.extend(added)
            write_archive(root, track, archive, md, today)
        git_remove(root, folder)
    return ApplyResult(path, folder, added)


def apply_screening(
    vault: Vault, root: Path, file: Path, *, today: dt.date | None = None, dry_run: bool = False
) -> ApplyResult:
    """スクリーニングバッチの各社を台帳に追記し（同じバッチ由来の既存エントリは飛ばす）、バッチを消す."""
    today = today or dt.date.today()
    target = file.resolve()
    doc = next((d for d in vault.screening if d.path.resolve() == target), None)
    if doc is None:
        raise CompactionError(f"スクリーニング集約ログとして読み込めない: {file}")
    if not isinstance(doc.model, ScreeningBatchDoc):
        raise CompactionError(f"{doc.rel} がスキーマ違反。validate.py で直してから圧縮する")
    track = doc.track or ""
    archive, md = load_archive(vault, root, track)

    existing = {
        (e.name, e.considered_at) for e in archive.companies if e.source == ArchiveSource.SCREENING
    }
    added: list[ArchivedCompany] = []
    skipped: list[str] = []
    for entry in screening_entries(doc):
        if (entry.name, entry.considered_at) in existing:
            skipped.append(entry.name)
        else:
            added.append(entry)

    ensure_committed(root, doc.path)
    path = archive_path(root, track)
    if not dry_run:
        if added:
            archive.companies.extend(added)
            write_archive(root, track, archive, md, today)
        git_remove(root, doc.path)
    return ApplyResult(path, doc.path, added, skipped)


# ---------------------------------------------------------------------------
# 表示
# ---------------------------------------------------------------------------


def entry_yaml(entry: ArchivedCompany) -> str:
    """台帳の companies に貼れる形（リスト要素）の YAML."""
    lines = frontmatter.dump_frontmatter(entry).rstrip("\n").split("\n")
    return "\n".join(("  - " if i == 0 else "    ") + line for i, line in enumerate(lines))


def candidate_dict(c: Candidate) -> dict:
    data: dict = {"kind": c.kind, "track": c.track, "path": c.doc.rel, "closed_on": c.closed_on.isoformat()}
    m = c.doc.model
    if isinstance(m, CompanyDoc):
        data |= {
            "company": m.company,
            "company_key": m.company_key,
            "aliases": m.aliases,
            "status": str(m.status),
            "considered_at": m.date.isoformat(),
            "reached": reached_from_interviews(c.interviews),
            "fit": display.format_fit(m.fit_score_min, m.fit_score_max),
            "decline_reason": m.decline_reason,
            "recruiter": m.recruiter,
            "interviews": [i.rel for i in c.interviews],
        }
    elif isinstance(m, ScreeningBatchDoc):
        data |= {"topic": m.topic, "companies": [c.name for c in m.companies]}
    return data


def main() -> None:
    parser = create_base_parser(
        description="終了した企業フォルダ・古いスクリーニング集約ログを見送り台帳（archive.md）に圧縮する",
        examples=[
            "uv run python scripts/vault/compact_closed.py list --track domestic --summary  # 圧縮候補",
            "uv run python scripts/vault/compact_closed.py draft --key <company-key> --summary  # 要約の材料とエントリ下書き",
            'uv run python scripts/vault/compact_closed.py apply --key <company-key> --reason "..." --reconsider-if "..."',
        ],
        related=[
            "scripts/vault/find_chores.py: 圧縮候補を他の雑務と一緒に洗い出す（compact）",
            "scripts/vault/build_pipeline.py: apply の後に validate.py と合わせて流す",
        ],
    )
    parser.add_argument("command", choices=["list", "draft", "apply"], help="list: 候補一覧 / draft: エントリ下書き / apply: 確定（git rm）")
    parser.add_argument("--track", choices=["all", *TRACKS], default="all", help="対象 track（既定: all）")
    parser.add_argument(
        "--older-than-days",
        type=int,
        default=DEFAULT_OLDER_THAN_DAYS,
        help=f"list: 終了から何日経ったものを候補にするか（既定: {DEFAULT_OLDER_THAN_DAYS}）",
    )
    parser.add_argument("--today", type=dt.date.fromisoformat, default=None, help="基準日 YYYY-MM-DD（既定: 今日）")
    parser.add_argument("--key", help="draft / apply: 企業フォルダのキー（期間に関係なく個別に圧縮できる）")
    parser.add_argument("--screening", type=Path, help="apply: 畳み込むスクリーニング集約ログのパス")
    parser.add_argument("--reason", help="apply: 台帳に無い場合に追記するエントリの見送り理由（1〜2 文）")
    parser.add_argument("--reconsider-if", help="apply: 再検討してよい条件")
    parser.add_argument("--closed-at", type=dt.date.fromisoformat, help="apply: 見送り日（既定: 企業ログの updated_at）")
    parser.add_argument("--reached", choices=[s.value for s in CompanyStatus], help="apply: 到達段階（既定: 面談ログから推定）")
    parser.add_argument("--dry-run", action="store_true", help="apply: 検査だけ行い、台帳への追記・git rm はしない")
    args = parser.parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        track = None if args.track == "all" else args.track
        today = args.today or dt.date.today()
        vault = load_vault(PROJECT_ROOT)

        try:
            if args.command == "list":
                candidates = list_candidates(vault, track, today, args.older_than_days)
                if args.limit:
                    candidates = candidates[: args.limit]
                for c in candidates:
                    ctx.add_result_path(c.doc.path)
                ctx.info(f"圧縮候補: {len(candidates)}件（{args.older_than_days}日以上前に終了。基準日 {today}）")

                def print_list() -> None:
                    if not candidates:
                        print("圧縮候補なし")
                    for c in candidates:
                        d = candidate_dict(c)
                        print(f"- [{c.track}] {c.label}  終了: {d['closed_on']}  {d['path']}")
                        if c.kind == "company":
                            print(f"    status={d['status']} / 到達={d['reached'] or '-'} / fit={d['fit'] or '-'} / recruiter={d['recruiter'] or '-'}")
                            print(f"    decline_reason: {d['decline_reason'] or '-'}")
                            for i in d["interviews"]:
                                print(f"    面談ログ: {i}")
                        else:
                            print(f"    {', '.join(d['companies'])}")

                sys.exit(ctx.flush_outputs(print_list, {"candidates": [candidate_dict(c) for c in candidates]}))

            if args.command == "draft":
                if not args.key:
                    raise CompactionError("draft には --key が必要")
                doc = find_company(vault, args.key, track)
                entry = draft_entry(vault, doc)
                interviews = vault.interviews_of(doc)
                ctx.add_result_paths([doc.path, *(i.path for i in interviews)])
                for r in recruiters_without_note(vault, args.key):
                    ctx.info(f"リクルーター {r} の introduced_companies（{args.key}）の note が空。所感を残すか検討する")
                m = doc.model
                assert isinstance(m, CompanyDoc)

                def print_draft() -> None:
                    print(f"# {doc.rel} の台帳エントリ下書き（reason / reconsider_if は面談ログまで読んで書く）")
                    print(f"# decline_reason: {m.decline_reason or '-'}")
                    print(f"# status_note: {m.status_note or '-'}")
                    for i in interviews:
                        print(f"# 面談ログ: {i.rel}")
                    print(entry_yaml(entry))

                json_data = {
                    "entry": entry.model_dump(mode="json", exclude_none=True),
                    "decline_reason": m.decline_reason,
                    "status_note": m.status_note,
                    "materials": ctx.result_paths,
                }
                sys.exit(ctx.flush_outputs(print_draft, json_data))

            # apply
            if bool(args.key) == bool(args.screening):
                raise CompactionError("apply には --key か --screening のどちらか一方が必要")
            if args.key:
                overrides = {
                    "reason": args.reason,
                    "reconsider_if": args.reconsider_if,
                    "closed_at": args.closed_at,
                    "reached": args.reached,
                }
                result = apply_company(
                    vault, PROJECT_ROOT, args.key, track=track, overrides=overrides, today=today, dry_run=args.dry_run
                )
                for r in recruiters_without_note(vault, args.key):
                    ctx.info(f"リクルーター {r} の introduced_companies（{args.key}）の note が空。所感を残すか検討する")
            else:
                result = apply_screening(vault, PROJECT_ROOT, args.screening, today=today, dry_run=args.dry_run)
        except CompactionError as e:
            ctx.error(str(e))
            sys.exit(1)

        prefix = "[dry-run] " if args.dry_run else ""
        rel_removed = result.removed.relative_to(PROJECT_ROOT).as_posix()
        for entry in result.added:
            ctx.info(f"{prefix}台帳に追記: {entry.name}")
        for name in result.skipped:
            ctx.info(f"{prefix}台帳に既にあるため追記しない: {name}")
        ctx.info(f"{prefix}git rm: {rel_removed}")
        if not args.dry_run:
            track_name = result.archive.parent.name
            ctx.info(
                "続けて `uv run python scripts/vault/validate.py` と "
                f"`uv run python scripts/vault/build_pipeline.py --track {track_name}` を実行する"
            )
        ctx.add_result_path(result.archive)

        def print_apply() -> None:
            print(f"{prefix}{rel_removed} → {ctx.result_paths[0]}（追記 {len(result.added)}件 / 既存 {len(result.skipped)}件）")
            for entry in result.added:
                print(entry_yaml(entry))

        json_data = {
            "dry_run": args.dry_run,
            "archive": ctx.result_paths[0],
            "removed": rel_removed,
            "added": [e.model_dump(mode="json", exclude_none=True) for e in result.added],
            "skipped": result.skipped,
        }
        sys.exit(ctx.flush_outputs(print_apply, json_data))


if __name__ == "__main__":
    main()
