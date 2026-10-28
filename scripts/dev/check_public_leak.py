"""公開対象パスに個人情報（禁止語）が混入していないか検査する CLI.

公開リポジトリ（fdshg693/job_hunt）に同期されるホワイトリストパスを対象に、
指定された禁止語リスト（正規表現 1行1件）でスキャンします。
個人情報の漏洩を防止するため、ヒットした値自体はログに出力せず、
ヒットしたファイルパスと行番号のみを出力して exit 1 します。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.common.cli import build_epilog  # noqa: E402

# 公開ホワイトリストのディレクトリ・ファイル
PUBLIC_DIRS = [
    "scripts",
    "docs",
    "tests",
    "templates",
    "webui",
    ".agents/rules",
    ".agents/skills",
    ".agents/agents",
    ".claude/rules",
    ".claude/skills",
    ".claude/agents",
    "ai/tools",
]

PUBLIC_FILES = [
    "pyproject.toml",
    "uv.lock",
    ".gitignore",
    ".env.example",
    "README.md",
    "QUICKSTART.md",
    "LICENSE",
]

# スキャン対象から除外する拡張子・パス要素
IGNORE_EXTENSIONS = {
    ".pyc",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
}

IGNORE_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".git",
    "node_modules",
}


def load_denylist(
    denylist_path: Path | None = None,
    raw_denylist: str | None = None,
) -> list[tuple[int, re.Pattern[str]]]:
    """禁止語リストを読み込み、(行番号, コンパイル済み正規表現) のリストを返す."""
    lines: list[str] = []
    if raw_denylist is not None:
        lines.extend(raw_denylist.splitlines())
    elif denylist_path is not None and denylist_path.exists():
        lines.extend(denylist_path.read_text(encoding="utf-8").splitlines())
    else:
        raise FileNotFoundError(f"禁止語リストが見つかりません: {denylist_path}")

    patterns: list[tuple[int, re.Pattern[str]]] = []
    for idx, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            pat = re.compile(line)
            patterns.append((idx, pat))
        except re.error as e:
            raise ValueError(f"禁止語リスト {idx} 行目の正規表現が無効です: {line} ({e})") from e

    if not patterns:
        raise ValueError("禁止語リストに有効なパターンが含まれていません")
    return patterns


def collect_target_files(target_dir: Path, is_standalone_sync_dir: bool = False) -> list[Path]:
    """スキャン対象のファイルリストを収集する."""
    files: list[Path] = []

    if is_standalone_sync_dir:
        # すでにホワイトリスト抽出済みのディレクトリ全体を走査
        for path in target_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() in IGNORE_EXTENSIONS:
                continue
            if any(part in IGNORE_PARTS for part in path.parts):
                continue
            files.append(path)
        return sorted(files)

    # リポジトリルートからホワイトリストのみを走査
    for dir_rel in PUBLIC_DIRS:
        d = target_dir / dir_rel
        if not d.exists():
            continue
        for path in d.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() in IGNORE_EXTENSIONS:
                continue
            if any(part in IGNORE_PARTS for part in path.parts):
                continue
            files.append(path)

    for file_rel in PUBLIC_FILES:
        f = target_dir / file_rel
        if f.is_file():
            files.append(f)

    # 重複除去
    unique_files = list(dict.fromkeys(files))
    return sorted(unique_files)


def scan_files(
    files: list[Path],
    patterns: list[tuple[int, re.Pattern[str]]],
    base_dir: Path,
) -> list[str]:
    """ファイルをスキャンし、ヒットした箇所の文字列リスト (ファイル:行 (rule #N)) を返す."""
    hits: list[str] = []

    for path in files:
        try:
            rel_path = path.relative_to(base_dir).as_posix()
        except ValueError:
            rel_path = str(path)

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        for line_no, line in enumerate(content.splitlines(), 1):
            for rule_idx, pat in patterns:
                if pat.search(line):
                    hits.append(f"{rel_path}:{line_no} (rule #{rule_idx})")

    return hits


def main() -> int:
    parser = argparse.ArgumentParser(
        description="公開対象パスの個人情報（禁止語）混入スキャン",
        epilog=build_epilog(
            examples=[
                "uv run python scripts/dev/check_public_leak.py  # リポジトリの公開対象パスを既定の禁止語でスキャン",
                "uv run python scripts/dev/check_public_leak.py --target-dir <同期用ディレクトリ> --standalone-sync-dir",
                "uv run python scripts/dev/check_public_leak.py --denylist <禁止語ファイル>",
            ],
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=ROOT,
        help="スキャン対象のルートディレクトリ（デフォルト: リポジトリルート）",
    )
    parser.add_argument(
        "--standalone-sync-dir",
        action="store_true",
        help="対象ディレクトリがホワイトリスト抽出後の独立ディレクトリである場合に指定",
    )
    parser.add_argument(
        "--denylist",
        type=Path,
        default=None,
        help="禁止語リストファイルへのパス（未指定時は環境変数 PUBLIC_DENYLIST または vault 既定パス）",
    )

    args = parser.parse_args()

    # 禁止語の読み込み元決定
    raw_denylist = os.environ.get("PUBLIC_DENYLIST")
    denylist_file = args.denylist
    if denylist_file is None and not raw_denylist:
        env_path = os.environ.get("PUBLIC_DENYLIST_PATH")
        if env_path:
            denylist_file = Path(env_path)
        else:
            default_path = ROOT / "vault" / "profile" / "internal" / "public_denylist.txt"
            if default_path.exists():
                denylist_file = default_path

    if denylist_file is None and not raw_denylist:
        print(
            "::error::禁止語リストが指定されていません（--denylist, PUBLIC_DENYLIST, または vault/profile/internal/public_denylist.txt）",
            file=sys.stderr,
        )
        return 1

    try:
        patterns = load_denylist(denylist_path=denylist_file, raw_denylist=raw_denylist)
    except Exception as e:
        print(f"::error::禁止語リストの読み込みに失敗しました: {e}", file=sys.stderr)
        return 1

    target_dir = args.target_dir.resolve()
    is_standalone = args.standalone_sync_dir or (target_dir != ROOT.resolve())
    files = collect_target_files(target_dir, is_standalone_sync_dir=is_standalone)

    hits = scan_files(files, patterns, base_dir=target_dir)

    if hits:
        print(
            f"::error::公開対象パスに個人情報（禁止語）の混入が {len(hits)} 件検出されました！",
            file=sys.stderr,
        )
        for hit in hits:
            print(f"[LEAK DETECTED] {hit}", file=sys.stderr)
        return 1

    print(f"[OK] No leaks detected across {len(files)} public files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
