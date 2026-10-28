"""track 別 pipeline.md の選考企業一覧を企業ログから再生成する CLI.

各 track の companies/*/index.md を共通ローダー（scripts/vault/loader.py）で読み込み、
ステータスの並び順・ラベル・分類はスキーマ（scripts/vault/schema/）に従って選考企業一覧テーブルを組み立て、
pipeline.md 内のマーカー（<!-- pipeline:begin --> 〜 <!-- pipeline:end -->）間のみを上書きします。
マーカー外の手書き部分（次回アクション・メモ等）は変更しません。
.agents/rules/scripts-entrypoint.md 規約に準拠し、標準出力には更新した pipeline.md のパスのみを出力します。
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# プロジェクトルートパス (scripts/vault/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import create_base_parser, entrypoint_guard, to_relative_path
from scripts.common.paths import TRACKS
from scripts.vault import display
from scripts.vault.loader import Vault, load_vault
from scripts.vault.schema import (
    COMPANY_STATUS_META,
    ActionType,
    CompanyDoc,
    StatusCategory,
    format_due,
    status_meta,
)

BEGIN_MARKER = "<!-- pipeline:begin -->"
END_MARKER = "<!-- pipeline:end -->"

JOB_TITLE_MAX = 40

@dataclass
class PipelineCompany:
    """pipeline 一覧の1行分（企業フォルダ名＋検証済みの企業ログ）."""

    key: str  # 企業フォルダ名（companies/{key}/）
    doc: CompanyDoc

    @property
    def is_active(self) -> bool:
        return self.doc.status_category == StatusCategory.ACTIVE

    @property
    def status_label(self) -> str:
        return status_meta(self.doc.status).label

    @property
    def link(self) -> str:
        return f"companies/{self.key}/index.md"

    @property
    def updated_at(self) -> str:
        return self.doc.updated_at.isoformat()

    @property
    def next_due(self) -> str:
        return format_due(self.doc.next_due) or ""

    def to_dict(self) -> dict:
        return {"key": self.key, "status_label": self.status_label, **self.doc.model_dump(mode="json")}


# ---------------------------------------------------------------------------
# セル表記
# ---------------------------------------------------------------------------


def format_salary(doc: CompanyDoc) -> str:
    return display.format_salary(doc.salary_min, doc.salary_max)


def format_remote(doc: CompanyDoc) -> str:
    return display.format_remote(doc.remote_type, doc.office_days_per_week)


def format_fit(doc: CompanyDoc) -> str:
    return display.format_fit(doc.fit_score_min, doc.fit_score_max)


def format_interest(doc: CompanyDoc) -> str:
    return display.format_interest(doc.interest)


def _cell(text: str, max_len: int | None = None) -> str:
    """Markdown テーブルのセル用に改行・パイプをエスケープし、必要なら切り詰める."""
    clean = re.sub(r"\s+", " ", text or "").strip().replace("|", "\\|")
    if max_len and len(clean) > max_len:
        clean = clean[: max_len - 1] + "…"
    return clean or "-"


# ---------------------------------------------------------------------------
# 読み込み・生成
# ---------------------------------------------------------------------------


def load_companies(root: Path, track: str, *, vault: Vault | None = None) -> tuple[list[PipelineCompany], list[str]]:
    """track の企業ログを読み込む. 戻り値は (企業一覧, 警告メッセージ一覧).

    スキーマ違反の企業ログは一覧に載せず、警告にする（validate.py で詳細を確認する）。
    """
    vault = vault or load_vault(root)
    companies: list[PipelineCompany] = []
    warnings: list[str] = []
    for doc in vault.companies:
        if doc.track != track:
            continue
        if isinstance(doc.model, CompanyDoc):
            companies.append(PipelineCompany(key=doc.folder_key or "", doc=doc.model))
        else:
            warnings.append(
                f"スキーマ違反のため一覧から除外: {doc.rel}（`uv run python scripts/vault/validate.py` で確認）"
            )
    return companies, warnings


def sort_active(companies: list[PipelineCompany]) -> list[PipelineCompany]:
    """選考中・検討中の企業をステータス順 → 同ステータス内は更新日の新しい順で返す."""
    active = sorted((c for c in companies if c.is_active), key=lambda c: c.updated_at, reverse=True)
    active.sort(key=lambda c: COMPANY_STATUS_META[c.doc.status].order)
    return active


def _render_action_section(
    title: str,
    companies: list[PipelineCompany],
    action_col_name: str,
    date_col_name: str,
    date_field: str,
) -> list[str]:
    """進行中アクションの1セクション（見出し＋テーブル、または なし）を生成する."""
    lines = [f"### {title}", ""]
    if not companies:
        lines.append("なし")
        lines.append("")
        return lines

    lines.append(f"| 企業名 | ステータス | {action_col_name} | {date_col_name} |")
    lines.append("|---|---|---|---|")
    for c in companies:
        date_val = getattr(c, date_field)
        lines.append(
            f"| [{_cell(c.doc.company)}]({c.link}) | {c.status_label} | {_cell(c.doc.next_action or '')} | {_cell(date_val)} |"
        )
    lines.append("")
    return lines


def count_archived(vault: Vault, track: str) -> int:
    """track の見送り台帳（archive.md）に圧縮済みの企業数."""
    return len(vault.archived_entries(track))


def render_block(companies: list[PipelineCompany], archived: int = 0) -> str:
    """マーカー間に挿入する一覧ブロック（マーカー含む）を生成する.

    archived は見送り台帳に圧縮済みの企業数。圧縮で企業フォルダの終了社数が減るので、混同しないよう別枠で出す。
    """
    active = sort_active(companies)

    # 進行中アクション（active な企業のみ対象）
    def by_action(action: ActionType) -> list[PipelineCompany]:
        return [c for c in active if c.doc.action_type == action]

    action_required = sorted(by_action(ActionType.ACTION_REQUIRED), key=lambda c: c.next_due or "9999-99-99")
    scheduled = sorted(by_action(ActionType.SCHEDULED), key=lambda c: c.next_due or "9999-99-99")
    waiting = sorted(by_action(ActionType.WAITING), key=lambda c: c.updated_at, reverse=True)

    lines = [
        BEGIN_MARKER,
        "<!-- scripts/vault/build_pipeline.py による自動生成。この区間は再生成で上書きされるため手で編集しない -->",
        "",
    ]

    # 進行中アクションセクション
    lines += _render_action_section("🔴 要対応（自分ボール）", action_required, "次回アクション", "期日", "next_due")
    lines += _render_action_section("📅 確定済予定", scheduled, "予定内容", "日時", "next_due")
    lines += _render_action_section("⏳ 結果・連絡待ち（相手ボール）", waiting, "待ち内容", "更新日", "updated_at")

    # 全体選考企業一覧
    lines += [
        "### 📋 選考・検討中企業一覧",
        "",
        "| 企業名 | ステータス | 職種 | 年収 | 働き方 | fit_score | 志望度 | 状況メモ | 更新日 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c in active:
        d = c.doc
        lines.append(
            f"| [{_cell(d.company)}]({c.link}) | {c.status_label} | {_cell(d.job_title or '', JOB_TITLE_MAX)} | "
            f"{_cell(format_salary(d))} | {_cell(format_remote(d))} | {_cell(format_fit(d))} | "
            f"{_cell(format_interest(d))} | {_cell(d.status_note or '')} | {_cell(c.updated_at)} |"
        )
    if not active:
        lines.append("| - | - | - | - | - | - | - | - | - |")

    # 終了・除外した企業は一覧に載せず、ステータスごとの件数のみ表示する
    closed = Counter(c.doc.status for c in companies if not c.is_active)
    counts = [
        f"{status_meta(status).label}: {closed[status]}社"
        for status in sorted(closed, key=lambda s: COMPANY_STATUS_META[s].order)
    ]
    summary = " / ".join([f"選考中・検討中: {len(active)}社", *counts])
    if archived:
        summary += f"（ほかに見送り台帳: {archived}社）"
    lines += ["", summary, END_MARKER]
    return "\n".join(lines)


def replace_block(text: str, block: str) -> str:
    """pipeline.md 本文のマーカー区間を block で置き換える. マーカーが無い場合は ValueError."""
    pattern = re.compile(re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER), flags=re.DOTALL)
    if not pattern.search(text):
        raise ValueError(f"マーカー（{BEGIN_MARKER} 〜 {END_MARKER}）が見つかりません")
    return pattern.sub(lambda _: block, text, count=1)


def pipeline_path(root: Path, track: str) -> Path:
    return root / "vault" / "tracks" / track / "pipeline.md"


def build_pipeline(track: str, root: Path = PROJECT_ROOT) -> tuple[Path, list[PipelineCompany], list[str], bool]:
    """track の pipeline.md を再生成する. 戻り値は (パス, 企業一覧, 警告, 変更有無)."""
    pipeline_md = pipeline_path(root, track)
    vault = load_vault(root)
    companies, warnings = load_companies(root, track, vault=vault)
    original = pipeline_md.read_bytes().decode("utf-8")
    block = render_block(companies, count_archived(vault, track))
    updated = replace_block(original, block.replace("\n", "\r\n" if "\r\n" in original else "\n"))
    changed = updated != original
    if changed:
        pipeline_md.write_bytes(updated.encode("utf-8"))
    return pipeline_md, companies, warnings, changed


def main() -> None:
    parser = create_base_parser(
        description="track 別 pipeline.md の選考企業一覧を companies/*/index.md から再生成する",
        examples=[
            "uv run python scripts/vault/build_pipeline.py --track domestic  # 企業ログ更新後に再生成",
            "uv run python scripts/vault/build_pipeline.py -s  # 全 track を再生成して一覧を表示",
        ],
        related=[
            "scripts/vault/validate.py: 再生成の前に企業ログのフロントマターを検証する",
            "scripts/vault/find_chores.py: pipeline.md 手書き部の停滞などの雑務を洗い出す",
        ],
    )
    parser.add_argument(
        "--track",
        choices=["all", *TRACKS],
        default="all",
        help="対象 track（既定: all。pipeline.md が存在する track のみ処理）",
    )
    args = parser.parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        tracks = list(TRACKS) if args.track == "all" else [args.track]
        results: list[dict] = []
        for name in tracks:
            path = pipeline_path(PROJECT_ROOT, name)
            if not path.exists():
                if args.track != "all":
                    ctx.error(f"pipeline.md が存在しません: {to_relative_path(path)}")
                    ctx.set_exit_code(1)
                continue
            try:
                path, companies, warnings, changed = build_pipeline(name)
            except ValueError as e:
                ctx.error(f"{to_relative_path(path)}: {e}")
                ctx.set_exit_code(1)
                continue
            for w in warnings:
                ctx.warn(w)
            ctx.info(f"{to_relative_path(path)}: {'更新' if changed else '変更なし'}")
            ctx.add_result_path(path)
            results.append(
                {
                    "track": name,
                    "path": to_relative_path(path),
                    "changed": changed,
                    "active": sort_active(companies),
                }
            )

        def print_summary() -> None:
            for r in results:
                print(f"[{r['track']}] {r['path']} ({'更新' if r['changed'] else '変更なし'})")
                active_list: list[PipelineCompany] = r["active"]
                req = [c for c in active_list if c.doc.action_type == ActionType.ACTION_REQUIRED]
                sch = [c for c in active_list if c.doc.action_type == ActionType.SCHEDULED]
                wait = [c for c in active_list if c.doc.action_type == ActionType.WAITING]
                print(f"  アクション状況: 要対応 {len(req)}社 / 確定予定 {len(sch)}社 / 結果待ち {len(wait)}社")
                for c in req:
                    print(f"    - 🔴 {c.doc.company}: {c.doc.next_action} (期日: {c.next_due or '-'})")
                for c in sch:
                    print(f"    - 📅 {c.doc.company}: {c.doc.next_action} (日時: {c.next_due or '-'})")
                for c in wait:
                    print(f"    - ⏳ {c.doc.company}: {c.doc.next_action} (更新: {c.updated_at})")
                print("  選考中・検討中企業:")
                for c in active_list:
                    print(f"    - {c.status_label}: {c.doc.company} ({format_fit(c.doc) or '-'})")

        json_data = {"tracks": [{**r, "active": [c.to_dict() for c in r["active"]]} for r in results]}
        sys.exit(ctx.flush_outputs(summary_fn=print_summary, json_data=json_data))


if __name__ == "__main__":
    main()
