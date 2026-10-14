"""Download Playwright's bundled agent skills into output/ via `gh api`.

Mirrors the skill sources that `playwright-cli install --skills` / `npx playwright
init-skills` copy onto disk, so browser automation from the shell is driven by the
real upstream instructions instead of recalled ones:

  packages/playwright-core/src/tools/skills/playwright-cli/**
      -> output/playwright-cli/   (SKILL.md is stored as playwright-cli-skill.md)

The upstream `SKILL.md` is renamed on the way in: a file literally named SKILL.md
below `.claude/skills/` risks being picked up as a second, competing skill. Its
`references/...` links keep working because the directory layout is preserved.

After fetching, writes a generated output/summary.md index.

Skips the whole snapshot when output/_meta.json was written within the last
7 days unless --force is passed. Requires the `gh` CLI (authenticated for
higher rate limits; public reads work without auth).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SKILL_DIR / "output"
META_PATH = OUTPUT_DIR / "_meta.json"
SUMMARY_REL = "summary.md"

REPO = "microsoft/playwright"
REF = "main"

SKILLS_ROOT = "packages/playwright-core/src/tools/skills"

# (repo directory, output subdirectory, allowed suffixes)
DIR_SOURCES: list[tuple[str, str, tuple[str, ...]]] = [
    (SKILLS_ROOT + "/playwright-cli", "playwright-cli", (".md",)),
]

# (repo file, output relative path)
FILE_SOURCES: list[tuple[str, str]] = []

# output relative path -> replacement, applied after the sources above are mapped.
RENAMES: dict[str, str] = {
    "playwright-cli/SKILL.md": "playwright-cli/playwright-cli-skill.md",
}

# Skills move with releases, but not hourly; a week is plenty.
FRESHNESS = timedelta(days=7)
# Fail fast rather than hang on a stalled gh/network call.
GH_TIMEOUT_SECONDS = 60

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def run_gh(args: list[str], repo_file_path: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GH_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "gh CLI not found on PATH. Install GitHub CLI and ensure `gh` is available."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"gh api timed out after {GH_TIMEOUT_SECONDS}s for {repo_file_path}"
        ) from exc


def check_gh(result: subprocess.CompletedProcess[str], repo_file_path: str) -> None:
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"gh api failed for {repo_file_path}: {err}")


def gh_raw(repo_file_path: str) -> str:
    """Fetch a single file's raw contents via `gh api` (Contents API + raw Accept)."""
    endpoint = f"repos/{REPO}/contents/{repo_file_path}?ref={REF}"
    result = run_gh(
        ["gh", "api", endpoint, "-H", "Accept: application/vnd.github.raw"],
        repo_file_path,
    )
    check_gh(result, repo_file_path)
    return result.stdout


def gh_json(repo_file_path: str) -> object:
    """Fetch Contents API JSON (directory listing or a single file object)."""
    endpoint = f"repos/{REPO}/contents/{repo_file_path}?ref={REF}"
    result = run_gh(["gh", "api", endpoint], repo_file_path)
    check_gh(result, repo_file_path)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh api returned non-JSON for {repo_file_path}") from exc


def list_dir_files(repo_dir: str, suffixes: tuple[str, ...], rel_dir: str = "") -> list[str]:
    """Walk the Contents API and return matching paths relative to repo_dir."""
    repo_path = (repo_dir + "/" + rel_dir).rstrip("/") if rel_dir else repo_dir
    items = gh_json(repo_path)
    if not isinstance(items, list):
        raise RuntimeError(f"expected a directory listing for {repo_path}")

    paths: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        typ = item.get("type")
        if not isinstance(name, str) or not isinstance(typ, str):
            continue
        child_rel = (rel_dir + "/" + name).lstrip("/") if rel_dir else name
        if ".." in Path(child_rel).parts:
            continue
        if typ == "dir":
            paths.extend(list_dir_files(repo_dir, suffixes, child_rel))
        elif typ == "file" and name.endswith(suffixes):
            paths.append(child_rel)
    return paths


def parse_frontmatter_fields(body: str) -> tuple[str, str]:
    """Return (name/title, description) from YAML frontmatter; empty strings if absent."""
    match = FRONTMATTER_RE.match(body)
    if not match:
        return "", ""
    label = ""
    description = ""
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        value = value.strip().strip("'\"")
        if key in ("name", "title") and not label:
            label = value
        elif key == "description" and not description:
            description = value
    return label, description


def describe(rel: str, body: str) -> tuple[str, str]:
    """Best-effort (label, description) for one fetched file."""
    if rel.endswith(".md"):
        label, description = parse_frontmatter_fields(body)
        if label:
            return label, description
        for line in body.splitlines():
            if line.startswith("# "):
                return line[2:].strip(), description
        return Path(rel).stem, description
    return Path(rel).name, ""


def write_summary(pages: list[tuple[str, str, str]]) -> None:
    """Write a generated index grouped by first path segment."""
    groups: dict[str, list[tuple[str, str, str]]] = {}
    for rel, label, description in pages:
        group = rel.split("/", 1)[0] if "/" in rel else "(root)"
        groups.setdefault(group, []).append((rel, label, description))

    lines = [
        "# Playwright bundled skills index",
        "",
        f"Generated from `{REPO}` (`{REF}`).",
        "This file is not upstream; it is built from each file's frontmatter / first heading.",
        "",
    ]
    for group in sorted(groups):
        lines.append(f"## {group if group != '(root)' else 'root'}")
        lines.append("")
        for rel, label, description in sorted(groups[group]):
            if description:
                lines.append(f"- [{label}]({rel}) — {description}")
            else:
                lines.append(f"- [{label}]({rel})")
        lines.append("")

    (OUTPUT_DIR / SUMMARY_REL).write_text("\n".join(lines), encoding="utf-8", newline="\n")


def read_fetched_at(meta_path: Path) -> datetime | None:
    if not meta_path.is_file():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw = data.get("fetched_at")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def write_meta(sources: list[tuple[str, str]]) -> None:
    payload = {
        "source_repo": REPO,
        "ref": REF,
        "dir_sources": [src for src, _, _ in DIR_SOURCES],
        "file_sources": [src for src, _ in FILE_SOURCES],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "files": [{"output": out, "source": src} for out, src in sources],
    }
    META_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def remove_stale_outputs(keep: set[str]) -> None:
    for path in OUTPUT_DIR.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(OUTPUT_DIR).as_posix()
        if rel not in keep:
            path.unlink()
            print(f"  Removed stale {rel}")


def fetch(repo_path: str, out_rel: str) -> tuple[str, str, str]:
    print(f"Fetching {repo_path} ...")
    body = gh_raw(repo_path)
    out_path = OUTPUT_DIR / out_rel
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8", newline="\n")
    print(f"  Wrote {out_path.relative_to(SKILL_DIR)}")
    label, description = describe(out_rel, body)
    return out_rel, label, description


def download_all() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pages: list[tuple[str, str, str]] = []
    sources: list[tuple[str, str]] = []  # (output rel, repo path)

    for repo_dir, out_dir, suffixes in DIR_SOURCES:
        print(f"Listing {repo_dir} ...")
        rel_paths = sorted(set(list_dir_files(repo_dir, suffixes)))
        if not rel_paths:
            raise RuntimeError(f"no matching files found under {repo_dir}")
        for rel in rel_paths:
            mapped = out_dir + "/" + rel
            out_rel = RENAMES.get(mapped, mapped)
            pages.append(fetch(repo_dir + "/" + rel, out_rel))
            sources.append((out_rel, repo_dir + "/" + rel))

    for repo_path, mapped in FILE_SOURCES:
        out_rel = RENAMES.get(mapped, mapped)
        pages.append(fetch(repo_path, out_rel))
        sources.append((out_rel, repo_path))

    write_summary(pages)
    print(f"  Wrote {SUMMARY_REL}")

    indexed = {rel for rel, _, _ in pages} | {SUMMARY_REL}
    remove_stale_outputs(indexed | {"_meta.json"})
    write_meta(sorted(sources))
    print(f"Wrote {META_PATH.relative_to(SKILL_DIR)} ({len(indexed)} files)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if the snapshot is still within the freshness window.",
    )
    args = parser.parse_args()

    if not args.force:
        fetched_at = read_fetched_at(META_PATH)
        if fetched_at is not None:
            age = datetime.now(timezone.utc) - fetched_at
            if age < FRESHNESS:
                print(
                    f"Snapshot already fresh (fetched_at={fetched_at.isoformat()}, "
                    f"age={age}). Use --force to refetch."
                )
                return 0

    try:
        download_all()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
