""".agents/（正本）から .claude/ を生成・差分検査する同期 CLI.

`.agents/`（Antigravity 形式・正本）から `.claude/`（Claude Code 形式）を生成する同期スクリプト。

対象:
    .agents/rules/*.md   -> .claude/rules/*.md   （trigger フロントマターを paths 形式へ変換）
    .agents/skills/**    -> .claude/skills/**    （形式互換のためそのままコピー。SKILL.md のみ自動生成注記を挿入）
    .agents/agents/*.md  -> .claude/agents/*.md  （ツール名・フロントマターを Claude Code 形式へ変換）

使い方:
    uv run python scripts/dev/sync_agents.py          # .claude/ を再生成
    uv run python scripts/dev/sync_agents.py --check  # 差分があれば一覧を出して exit 1（lefthook pre-commit 用）

同期しないもの（Antigravity 専用スキル等）は同階層の sync_agents.yaml の exclude で指定する。
`.claude/{rules,skills,agents}` は生成物。編集は必ず `.agents/` 側に行い、本スクリプトで同期すること。
gitignore 対象のファイル（.env, node_modules 等）は同期対象外。
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.common.cli import build_epilog  # noqa: E402

SRC = ROOT / ".agents"
DST = ROOT / ".claude"
TARGETS = ("rules", "skills", "agents")
CONFIG_PATH = Path(__file__).with_suffix(".yaml")

# Antigravity のツール名 -> Claude Code のツール名
TOOL_MAP = {
    "view_file": "Read",
    "view_file_outline": "Read",
    "view_code_item": "Read",
    "grep_search": "Grep",
    "find_by_name": "Glob",
    "list_dir": "Glob",
    "codebase_search": "Grep",
    "run_command": "Bash",
    "command_status": "Bash",
    "write_to_file": "Write",
    "replace_file_content": "Edit",
    "multi_replace_file_content": "Edit",
    "search_web": "WebSearch",
    "read_url_content": "WebFetch",
}


def notice(src: Path) -> str:
    rel = src.relative_to(ROOT).as_posix()
    return (
        f"<!-- 自動生成ファイル: {rel} から scripts/dev/sync_agents.py で生成。"
        f"直接編集せず {rel} を編集して再同期すること -->\n"
    )


def warn(msg: str) -> None:
    print(f"[sync_agents] WARN: {msg}", file=sys.stderr)


def split_frontmatter(text: str) -> tuple[dict, str]:
    """先頭の YAML フロントマターを (dict, 本文) に分離する。無ければ ({}, 全文)。"""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    meta = yaml.safe_load(text[4:end]) or {}
    return meta, text[end + len("\n---\n") :]


def insert_notice_after_frontmatter(text: str, src: Path) -> str:
    """フロントマターの内容は一切変えずに、直後へ自動生成注記を差し込む（SKILL.md 用）。"""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            head = text[: end + len("\n---\n")]
            return head + "\n" + notice(src) + text[len(head) :]
    return notice(src) + text


def dump_frontmatter(meta: dict) -> str:
    if not meta:
        return ""
    body = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, width=10_000)
    return f"---\n{body}---\n\n"


def listed_files(base: Path) -> list[Path]:
    """git 管理下 + 未追跡（ただし gitignore 対象外）で実在するファイル一覧。"""
    if not base.exists():
        return []
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", base.relative_to(ROOT).as_posix()],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    paths = {ROOT / p for p in out.split("\0") if p}
    return sorted(p for p in paths if p.is_file())


def read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


# ---------------------------------------------------------------------------
# 同期設定
# ---------------------------------------------------------------------------


def load_config(path: Path = CONFIG_PATH) -> dict[str, list[str]]:
    """sync_agents.yaml を読み、{ターゲット: 除外パターン} を返す。ファイルが無ければ除外なし。"""
    excludes: dict[str, list[str]] = {t: [] for t in TARGETS}
    if not path.exists():
        return excludes
    data = yaml.safe_load(read_text(path)) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: トップレベルはマッピングにしてください")
    for target, conf in data.items():
        if target not in TARGETS:
            raise ValueError(f"{path.name}: 未知のターゲット {target!r}（{', '.join(TARGETS)} のいずれか）")
        if conf is None:
            continue
        if not isinstance(conf, dict):
            raise ValueError(f"{path.name}: {target} はマッピングにしてください")
        unknown = set(conf) - {"exclude"}
        if unknown:
            raise ValueError(f"{path.name}: {target} に未知のキー {sorted(unknown)}（exclude のみ）")
        patterns = conf.get("exclude") or []
        if not isinstance(patterns, list) or not all(isinstance(p, str) and p for p in patterns):
            raise ValueError(f"{path.name}: {target}.exclude は空でない文字列のリストにしてください")
        excludes[target] = patterns
    return excludes


def is_excluded(top: str, patterns: list[str], used: set[str]) -> bool:
    """トップレベル名 top がいずれかのパターンに一致するか。一致したパターンを used に記録する。"""
    hits = [p for p in patterns if fnmatch.fnmatchcase(top, p)]
    used.update(hits)
    return bool(hits)


# ---------------------------------------------------------------------------
# 変換
# ---------------------------------------------------------------------------


def convert_rule(src: Path) -> str | None:
    meta, body = split_frontmatter(read_text(src))
    trigger = meta.get("trigger", "always_on")
    out_meta: dict = {}
    lead = ""

    if trigger == "always_on":
        pass
    elif trigger == "glob":
        globs = meta.get("globs") or []
        if isinstance(globs, str):
            globs = [g.strip() for g in globs.split(",") if g.strip()]
        if not globs:
            warn(f"{src.name}: trigger: glob だが globs が空のため常時読み込みにします")
        else:
            out_meta["paths"] = globs
    elif trigger == "model_decision":
        # Claude Code の rules には「モデル判断で読む」相当がないため常時読み込みにし、適用条件を明記する
        desc = (meta.get("description") or "").strip()
        if desc:
            lead = f"> **適用条件**: {desc}\n\n"
    elif trigger == "manual":
        warn(f"{src.name}: trigger: manual は Claude Code に相当機能がないためスキップします")
        return None
    else:
        raise ValueError(f"{src}: 未知の trigger: {trigger!r}")

    return dump_frontmatter(out_meta) + notice(src) + "\n" + lead + body.lstrip("\n")


def convert_agent(src: Path) -> str:
    meta, body = split_frontmatter(read_text(src))
    out_meta: dict = {}
    for key in ("name", "description"):
        if key not in meta:
            raise ValueError(f"{src}: 必須フィールド {key} がありません")
        out_meta[key] = meta[key]

    tools: list[str] = []
    for tool in meta.get("tools") or []:
        mapped = TOOL_MAP.get(tool)
        if mapped is None:
            warn(f"{src.name}: Antigravity ツール {tool!r} に対応する Claude Code ツールがないため除外します")
        elif mapped not in tools:
            tools.append(mapped)
    if tools:
        out_meta["tools"] = ", ".join(tools)

    # inherit 以外（flash / pro）は Claude のモデル体系と対応しないため親を継承させる
    out_meta["model"] = "inherit"

    skills = [s.rstrip("/").split("/")[-1] for s in meta.get("skills") or []]
    if skills:
        out_meta["skills"] = skills

    return dump_frontmatter(out_meta) + notice(src) + "\n" + body.lstrip("\n")


def build_expected(excludes: dict[str, list[str]] | None = None) -> dict[Path, bytes]:
    """生成されるべき .claude/ 配下の {パス: 内容} を返す。excludes 省略時は sync_agents.yaml を読む。"""
    if excludes is None:
        excludes = load_config()
    expected: dict[Path, bytes] = {}
    used: dict[str, set[str]] = {t: set() for t in TARGETS}

    for src in listed_files(SRC / "rules"):
        if src.suffix != ".md":
            continue
        rel = src.relative_to(SRC / "rules")
        if is_excluded(rel.parts[0], excludes["rules"], used["rules"]):
            continue
        converted = convert_rule(src)
        if converted is not None:
            expected[DST / "rules" / rel] = converted.encode("utf-8")

    for src in listed_files(SRC / "skills"):
        rel = src.relative_to(SRC / "skills")
        if is_excluded(rel.parts[0], excludes["skills"], used["skills"]):
            continue
        if src.name == "SKILL.md":
            expected[DST / "skills" / rel] = insert_notice_after_frontmatter(read_text(src), src).encode("utf-8")
        else:
            expected[DST / "skills" / rel] = src.read_bytes()

    for src in listed_files(SRC / "agents"):
        if src.suffix != ".md":
            continue
        rel = src.relative_to(SRC / "agents")
        if is_excluded(rel.parts[0], excludes["agents"], used["agents"]):
            continue
        # .agents/agents/<name>/agent.md 形式は .claude/agents/<name>.md へ平坦化
        out_name = f"{rel.parent.name}.md" if src.name == "agent.md" and rel.parent.name else rel.name
        expected[DST / "agents" / out_name] = convert_agent(src).encode("utf-8")

    for t in TARGETS:
        for pattern in excludes[t]:
            if pattern not in used[t]:
                warn(f"{CONFIG_PATH.name}: {t}.exclude の {pattern!r} はどのソースにも一致しません")

    return expected


# ---------------------------------------------------------------------------
# 比較・書き込み
# ---------------------------------------------------------------------------


def same(a: bytes, b: bytes) -> bool:
    # autocrlf による改行コード差は無視する
    return a.replace(b"\r\n", b"\n") == b.replace(b"\r\n", b"\n")


def diff(expected: dict[Path, bytes]) -> tuple[list[Path], list[Path], list[Path]]:
    actual = {p for t in TARGETS for p in listed_files(DST / t)}
    missing = sorted(p for p in expected if p not in actual)
    changed = sorted(p for p in expected if p in actual and not same(p.read_bytes(), expected[p]))
    extra = sorted(actual - expected.keys())
    return missing, changed, extra


def unstaged() -> list[str]:
    """.claude/ 生成物のうち、ステージされていない変更（未追跡含む）があるパス。"""
    out = subprocess.run(
        ["git", "status", "--porcelain", "-z", "--untracked-files=all", "--", *(f".claude/{t}" for t in TARGETS)],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    # porcelain v1: "XY path"。Y（作業ツリー側）が空白でなければ未ステージ。
    # -z ではリネーム/コピー（X か Y が R/C）の後に XY 無しの旧パスが別フィールドで続くので読み飛ばす
    entries = iter(out.split("\0"))
    paths = []
    for e in entries:
        if len(e) <= 3:
            continue
        if "R" in e[:2] or "C" in e[:2]:
            next(entries, None)
        if e[1] != " ":
            paths.append(e[3:])
    return sorted(paths)


def prune_empty_dirs() -> None:
    for t in TARGETS:
        base = DST / t
        if not base.exists():
            continue
        for d in sorted((p for p in base.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            if not any(d.iterdir()):
                d.rmdir()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=".agents/ から .claude/ を生成する",
        epilog=build_epilog(
            examples=[
                "uv run python scripts/dev/sync_agents.py  # .agents/ 編集後に .claude/ を再生成",
                "uv run python scripts/dev/sync_agents.py --check  # 差分があれば exit 1（pre-commit 用）",
            ],
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--check", action="store_true", help="書き込まずに差分のみ検査し、差分があれば exit 1")
    args = parser.parse_args()

    expected = build_expected()
    missing, changed, extra = diff(expected)
    rel = lambda p: p.relative_to(ROOT).as_posix()  # noqa: E731

    if args.check:
        not_added = unstaged()
        if not (missing or changed or extra or not_added):
            return 0
        print("[sync_agents] .claude/ が .agents/ と同期されていません:", file=sys.stderr)
        for label, paths in (("未生成", missing), ("内容差分", changed), ("余剰", extra)):
            for p in paths:
                print(f"  {label}: {rel(p)}", file=sys.stderr)
        for p in not_added:
            print(f"  未ステージ: {p}", file=sys.stderr)
        print(
            "\n.claude/ は生成物です。編集は .agents/ 側に行い、以下を実行して git add してください:\n"
            "  uv run python scripts/dev/sync_agents.py",
            file=sys.stderr,
        )
        return 1

    for p in missing + changed:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(expected[p])
    for p in extra:
        p.unlink()
    prune_empty_dirs()

    for label, paths in (("created", missing), ("updated", changed), ("removed", extra)):
        for p in paths:
            print(f"{label}: {rel(p)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
