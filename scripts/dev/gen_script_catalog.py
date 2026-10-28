"""エントリポイントの docstring からスクリプト一覧 docs/scripts/catalog.md を生成・差分検査する CLI.

scripts/ 配下の ``if __name__ == "__main__"`` を持つスクリプトを AST で走査し（起動はしない）、
モジュール docstring の 1 行目をディレクトリ（媒体・カテゴリ）ごとの表にして書き出します。
一覧の正本は各スクリプトの docstring 1 行目で、catalog.md は生成物です（手で編集しない）。
`--check` を付けると書き込まずに差分の有無だけを判定し、差分があれば終了コード1を返します（lefthook 用）。
.agents/rules/scripts-entrypoint.md 規約に準拠し、標準出力には生成（または検査）したファイルのパスのみを出力します。
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

# プロジェクトルートパス (scripts/dev/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import create_base_parser, entrypoint_guard, to_relative_path  # noqa: E402

SCRIPTS_DIR = PROJECT_ROOT / "scripts"
DOCS_DIR = PROJECT_ROOT / "docs"
CATALOG_PATH = DOCS_DIR / "scripts" / "catalog.md"

DEPRECATED_PREFIX = "非推奨:"

# カテゴリ（表示順）と、属する scripts/ 直下のディレクトリ（表示順）
CATEGORIES: list[tuple[str, list[str]]] = [
    (
        "求人媒体（取得・検索・プロフィール管理）",
        [
            "findy",
            "bizreach",
            "openwork",
            "forkwell",
            "linkedin",
            "levtech_direct",
            "green",
            "youtrust",
            "wellfound",
            "herp",
        ],
    ),
    ("記事・スライド", ["note", "speakerdeck"]),
    ("Google（Gmail・カレンダー）", ["google", "gmail", "gcal"]),
    ("Web 調査（Tavily）", ["web"]),
    ("vault 道具", ["vault"]),
    ("求人・企業の横断ツール", ["common"]),
    ("プロフィール出力・同期", ["profile"]),
    ("定期実行（無人ブリーフ）", ["automation"]),
    ("開発・メンテナンス", ["dev", "templates"]),
]
OTHER_CATEGORY = "その他"

# docs/{dir}/README.md が無いディレクトリの詳細ドキュメント（docs/ からの相対パス）
DOC_OVERRIDES: dict[str, list[str]] = {
    "vault": ["vault/schema.md", "vault/chores.md", "vault/materials.md"],
    "templates": ["guides/new_site_scraper_guide.md"],
}

HEADER = """<!-- 自動生成ファイル: scripts/dev/gen_script_catalog.py が各スクリプトの docstring 1 行目から生成する。手で編集しない -->

# スクリプト一覧

`scripts/` 配下の CLI エントリポイントの一覧。説明の正（SSOT）は各スクリプトのモジュール docstring の 1 行目。
スクリプトを追加・改名したら `uv run python scripts/dev/gen_script_catalog.py` でこの文書を再生成する。

- オプション・使用例・関連スクリプトは各スクリプトの `--help`、サイト構造や詳しい手順は各ディレクトリの docs を見る。
- 出力規約（stdout はパス・`-s` でサマリ等）は [`.agents/rules/scripts-entrypoint.md`](../../.agents/rules/scripts-entrypoint.md)。
- 「非推奨:」の行は互換ラッパー。新しく使わず、書かれた代わりのスクリプトを使う。
"""


@dataclass(frozen=True)
class ScriptEntry:
    path: str  # scripts_dir の親からの相対パス（例: scripts/findy/fetch_job.py）
    group: str  # scripts/ 直下のディレクトリ名
    summary: str

    @property
    def deprecated(self) -> bool:
        return self.summary.startswith(DEPRECATED_PREFIX)


def _is_main_guard(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    names = [node.test.left, *node.test.comparators]
    return any(isinstance(n, ast.Name) and n.id == "__name__" for n in names) and any(
        isinstance(n, ast.Constant) and n.value == "__main__" for n in names
    )


def _summary(doc: str | None) -> str:
    first = (doc or "").strip().splitlines()[0].strip() if (doc or "").strip() else ""
    return first.rstrip("。.")


def collect_entries(scripts_dir: Path = SCRIPTS_DIR) -> list[ScriptEntry]:
    """エントリポイントを走査し、docstring 1 行目を集める（パス順）."""
    entries: list[ScriptEntry] = []
    for path in sorted(scripts_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if not any(_is_main_guard(node) for node in tree.body):
            continue
        rel = path.relative_to(scripts_dir)
        group = rel.parts[0] if len(rel.parts) > 1 else ""
        entries.append(
            ScriptEntry(
                path=(Path(scripts_dir.name) / rel).as_posix(),
                group=group,
                summary=_summary(ast.get_docstring(tree)),
            )
        )
    return entries


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _doc_links(group: str, docs_dir: Path) -> list[str]:
    candidates = DOC_OVERRIDES.get(group, [f"{group}/README.md"])
    return [c for c in candidates if (docs_dir / c).exists()]


def _grouped(entries: list[ScriptEntry]) -> list[tuple[str, list[tuple[str, list[ScriptEntry]]]]]:
    by_group: dict[str, list[ScriptEntry]] = {}
    for entry in entries:
        by_group.setdefault(entry.group, []).append(entry)

    result: list[tuple[str, list[tuple[str, list[ScriptEntry]]]]] = []
    known: set[str] = set()
    for category, groups in CATEGORIES:
        known.update(groups)
        sections = [(g, by_group[g]) for g in groups if g in by_group]
        if sections:
            result.append((category, sections))
    others = [(g, by_group[g]) for g in sorted(by_group) if g not in known]
    if others:
        result.append((OTHER_CATEGORY, others))
    return result


def render_catalog(entries: list[ScriptEntry], docs_dir: Path = DOCS_DIR) -> str:
    lines = [HEADER]
    grouped = _grouped(entries)

    lines += ["## 目次", ""]
    for category, sections in grouped:
        names = ", ".join(f"`{g or 'scripts'}`" for g, _ in sections)
        lines.append(f"- {category}: {names}")
    lines.append("")

    for category, sections in grouped:
        lines += [f"## {category}", ""]
        for group, items in sections:
            lines += [f"### `scripts/{group}/`" if group else "### `scripts/`", ""]
            if links := _doc_links(group, docs_dir):
                lines += ["詳細: " + "、".join(f"[`docs/{link}`](../{link})" for link in links), ""]
            lines += ["| スクリプト | 説明 |", "|---|---|"]
            # 非推奨の互換ラッパーは表の末尾に回す
            for entry in sorted(items, key=lambda e: (e.deprecated, e.path)):
                lines.append(f"| `{entry.path}` | {_cell(entry.summary)} |")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = create_base_parser(
        examples=[
            "uv run python scripts/dev/gen_script_catalog.py  # スクリプト追加・改名・docstring 変更後に再生成",
            "uv run python scripts/dev/gen_script_catalog.py --check  # 差分があれば exit 1（lefthook 用）",
        ],
        related=[
            "scripts/vault/gen_schema_doc.py: 同じ「正本から docs を生成する」パターンのスキーマ文書版",
        ],
    )
    parser.add_argument(
        "--check", action="store_true", help="書き込まずに差分の有無だけを判定する（差分ありで終了コード1）"
    )
    args = parser.parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        entries = collect_entries()
        content = render_catalog(entries)
        current = CATALOG_PATH.read_text(encoding="utf-8") if CATALOG_PATH.exists() else None
        rel = to_relative_path(CATALOG_PATH)
        if args.check:
            if current != content:
                ctx.error(
                    f"{rel} がスクリプトの docstring と一致しません。`uv run python scripts/dev/gen_script_catalog.py` で再生成してください"
                )
                ctx.set_exit_code(1)
            else:
                ctx.info(f"{rel}: 最新")
        elif current != content:
            CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CATALOG_PATH.write_text(content, encoding="utf-8", newline="\n")
            ctx.info(f"{rel}: 更新")
        else:
            ctx.info(f"{rel}: 変更なし")
        ctx.add_result_path(CATALOG_PATH)
        sys.exit(ctx.flush_outputs(json_data={"path": rel, "check": args.check, "scripts": len(entries)}))


if __name__ == "__main__":
    main()
