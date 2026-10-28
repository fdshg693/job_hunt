"""vault スキーマから docs/vault/schema.md を生成・差分検査する CLI.

scripts/vault/schema/ のモデル・enum から、ドキュメント種別ごとのフィールド表と enum 値表を Markdown で書き出します。
`--check` を付けると書き込まずに差分の有無だけを判定し、差分があれば終了コード1を返します（lefthook 用）。
.agents/rules/scripts-entrypoint.md 規約に準拠し、標準出力には生成（または検査）したファイルのパスのみを出力します。
"""

from __future__ import annotations

import datetime as dt
import sys
import types
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from annotated_types import Ge, Le, MaxLen, MinLen
from pydantic import BaseModel
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

# プロジェクトルートパス (scripts/vault/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import create_base_parser, entrypoint_guard, to_relative_path
from scripts.vault.schema import COMPANY_STATUS_META, ENUM_LABELS, KIND_GLOBS, MODEL_BY_KIND, CompanyStatus

SCHEMA_DOC_PATH = PROJECT_ROOT / "docs" / "vault" / "schema.md"

HEADER = """<!-- 自動生成ファイル: scripts/vault/gen_schema_doc.py が scripts/vault/schema/ から生成する。手で編集しない -->

# vault フロントマタースキーマ

vault 配下の Markdown のフロントマター仕様。正（SSOT）は [`scripts/vault/schema/`](../../scripts/vault/schema/)。
スキーマを変えたら `uv run python scripts/vault/gen_schema_doc.py` でこの文書を再生成する。

- 未知のキーはエラー（`extra="forbid"`）。空文字は未記入（`null`）と同じ扱い。
- 日付は `YYYY-MM-DD`。年収は**万円単位の整数**。
- 「必須」でないキーは省略してよい。省略時は既定値になる。
"""


def _enum_anchor(enum_cls: type[StrEnum]) -> str:
    return f"enum-{enum_cls.__name__.lower()}"


def _model_anchor(model: type[BaseModel]) -> str:
    return f"model-{model.__name__.lower()}"


def format_type(annotation: Any) -> str:
    """型注釈を文書用の短い表記にする（enum・ネストしたモデルは表へのリンク）."""
    origin = get_origin(annotation)
    if origin is Annotated:
        return format_type(get_args(annotation)[0])
    if origin in (Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        text = " / ".join(format_type(a) for a in args)
        return f"{text} / null" if len(args) < len(get_args(annotation)) else text
    if origin is list:
        return f"list[{format_type(get_args(annotation)[0])}]"
    if origin is Literal:
        return " / ".join(f"`{v}`" for v in get_args(annotation))
    if isinstance(annotation, type):
        if issubclass(annotation, StrEnum):
            return f"[{annotation.__name__}](#{_enum_anchor(annotation)})"
        if issubclass(annotation, BaseModel):
            return f"[{annotation.__name__}](#{_model_anchor(annotation)})"
        if annotation is dt.datetime:
            return "datetime (YYYY-MM-DD HH:MM)"
        if annotation is dt.date:
            return "date"
        return annotation.__name__
    return str(annotation)


def format_constraints(field: FieldInfo) -> str:
    parts: list[str] = []
    for meta in field.metadata:
        if isinstance(meta, Ge):
            parts.append(f"≥ {meta.ge}")
        elif isinstance(meta, Le):
            parts.append(f"≤ {meta.le}")
        elif isinstance(meta, MinLen):
            parts.append(f"{meta.min_length}件以上")
        elif isinstance(meta, MaxLen):
            parts.append(f"{meta.max_length}件以下")
        elif getattr(meta, "pattern", None):
            parts.append(f"`{meta.pattern}`")
    return ", ".join(parts)


def format_default(field: FieldInfo) -> str:
    if field.is_required():
        return ""
    if field.default_factory is not None:
        value = field.default_factory()  # type: ignore[call-arg]
    else:
        value = field.default
    if value is None or value is PydanticUndefined:
        return ""
    if isinstance(value, StrEnum):
        return f"`{value.value}`"
    if isinstance(value, bool):
        return f"`{str(value).lower()}`"
    if value == []:
        return "`[]`"
    return f"`{value}`"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_model_table(model: type[BaseModel]) -> list[str]:
    lines = [
        "| キー | 型 | 必須 | 既定値 | 制約 | 説明 |",
        "|---|---|---|---|---|---|",
    ]
    for name, field in model.model_fields.items():
        lines.append(
            f"| `{name}` | {_cell(format_type(field.annotation))} | {'✔' if field.is_required() else ''} | "
            f"{_cell(format_default(field))} | {_cell(format_constraints(field))} | {_cell(field.description or '')} |"
        )
    return lines


def _nested_models(model: type[BaseModel]) -> list[type[BaseModel]]:
    """フィールドの型に含まれるネストしたモデルを出現順に返す."""
    found: list[type[BaseModel]] = []

    def walk(annotation: Any) -> None:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            if annotation not in found:
                found.append(annotation)
            return
        for arg in get_args(annotation):
            walk(arg)

    for field in model.model_fields.values():
        walk(field.annotation)
    return found


def _doc_summary(model: type[BaseModel]) -> str:
    return " ".join(line.strip() for line in (model.__doc__ or "").strip().splitlines())


def render_enum_table(enum_cls: type[StrEnum]) -> list[str]:
    labels = ENUM_LABELS.get(enum_cls, {})
    lines = [f'<a id="{_enum_anchor(enum_cls)}"></a>', "", f"### {enum_cls.__name__}", ""]
    if enum_cls is CompanyStatus:
        lines += [
            "| 値 | ラベル | 分類 (category) | 並び順 | check_company の除外範囲 | 意味 |",
            "|---|---|---|---|---|---|",
        ]
        for member in sorted(CompanyStatus, key=lambda s: COMPANY_STATUS_META[s].order):
            m = COMPANY_STATUS_META[member]
            lines.append(
                f"| `{member.value}` | {m.label} | `{m.category.value}` | {m.order} | `{m.exclusion.value}` | {m.description} |"
            )
    else:
        lines += ["| 値 | ラベル |", "|---|---|"]
        for member in enum_cls:
            lines.append(f"| `{member.value}` | {_cell(labels.get(member, ''))} |")
    lines.append("")
    return lines


def render_doc() -> str:
    lines = [HEADER]

    lines += ["## ドキュメント種別", "", "| 種別 | モデル | 配置パス |", "|---|---|---|"]
    for kind, model in MODEL_BY_KIND.items():
        globs = "<br>".join(f"`{g}`" for g in KIND_GLOBS[kind])
        lines.append(f"| `{kind.value}` | [{model.__name__}](#{_model_anchor(model)}) | {globs} |")
    lines.append("")

    rendered: set[type[BaseModel]] = set()
    lines += ["## フィールド定義", ""]
    for model in MODEL_BY_KIND.values():
        queue = [model]
        while queue:
            current = queue.pop(0)
            if current in rendered:
                continue
            rendered.add(current)
            heading = "###" if current is model else "####"
            lines += [f'<a id="{_model_anchor(current)}"></a>', "", f"{heading} {current.__name__}", ""]
            if summary := _doc_summary(current):
                lines += [summary, ""]
            lines += render_model_table(current)
            lines.append("")
            queue += _nested_models(current)

    lines += ["## 列挙値", ""]
    for enum_cls in ENUM_LABELS:
        lines += render_enum_table(enum_cls)

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = create_base_parser(
        description="scripts/vault/schema/ から docs/vault/schema.md を生成する",
        examples=[
            "uv run python scripts/vault/gen_schema_doc.py  # スキーマ変更後に再生成",
            "uv run python scripts/vault/gen_schema_doc.py --check  # 差分があれば exit 1（lefthook 用）",
        ],
        related=[
            "scripts/vault/validate.py: スキーマ変更後に vault 全件を検証する",
        ],
    )
    parser.add_argument("--check", action="store_true", help="書き込まずに差分の有無だけを判定する（差分ありで終了コード1）")
    args = parser.parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        content = render_doc()
        current = SCHEMA_DOC_PATH.read_text(encoding="utf-8") if SCHEMA_DOC_PATH.exists() else None
        rel = to_relative_path(SCHEMA_DOC_PATH)
        if args.check:
            if current != content:
                ctx.error(f"{rel} がスキーマと一致しません。`uv run python scripts/vault/gen_schema_doc.py` で再生成してください")
                ctx.set_exit_code(1)
            else:
                ctx.info(f"{rel}: 最新")
        elif current != content:
            SCHEMA_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
            SCHEMA_DOC_PATH.write_text(content, encoding="utf-8", newline="\n")
            ctx.info(f"{rel}: 更新")
        else:
            ctx.info(f"{rel}: 変更なし")
        ctx.add_result_path(SCHEMA_DOC_PATH)
        sys.exit(ctx.flush_outputs(json_data={"path": rel, "check": args.check}))


if __name__ == "__main__":
    main()
