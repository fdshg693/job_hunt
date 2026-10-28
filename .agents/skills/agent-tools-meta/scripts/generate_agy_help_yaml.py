"""Generate a YAML snapshot of the `agy` CLI's `--help` output.

Antigravity's `agy` CLI is a Go binary. Its help layout differs from Claude
Code's commander.js (`claude --help`) and from Codex's clap:

- Top level (`agy --help` / `agy help`): a `Usage of agy.exe:` header, then
  2-space-indented flag lines (`  --flag  description [(default ...)]`), a blank
  line, then `Available subcommands:` with 2-space-indented
  `  name  description` lines.
- Subcommands (`agy help <sub>`): a `Usage: agy.exe <sub> ...` line, an optional
  one-line description, then either a `Flags:` section
  (`  --flag  description`) or a `Commands:` section (`  name  description`).

Notable quirks (the reason this skill generates a snapshot instead of relying on
live help invocations at answer time):

- `agy` writes help text to **stderr** and exits with code **1** (Go's flag
  package behavior). The generator captures stdout+stderr combined and does NOT
  treat exit 1 as failure for help invocations.
- Running a subcommand **bare** (e.g. `agy agent`, `agy models`, `agy agents`)
  starts an interactive/auth flow and hangs. The generator NEVER runs bare
  subcommands — it only ever runs the `agy --help` / `agy help <sub>` forms,
  which always terminate.

The output YAML records a `fetched_at` timestamp. On rerun, generation is
skipped if the existing output was fetched within the last 24 hours; pass
`--force` to regenerate regardless of age.
"""

from __future__ import annotations

import argparse
import copy
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = SKILL_DIR / "output" / "antigravity" / "help_result.yaml"

SPLIT_RE = re.compile(r" {2,}")
DEFAULT_RE = re.compile(r"\s*\(default (.+)\)\s*$")
FRESHNESS = timedelta(days=1)

# Subcommands that are aliases of another; `agy help <alias>` may not resolve,
# so we reuse the canonical subcommand's parsed help.
ALIASES = {"plugins": "plugin", "agents": "agent"}


def read_fetched_at(path: Path) -> datetime | None:
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("fetched_at")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def run_agy(*args: str) -> str:
    """Run `agy <args>` and return combined stdout+stderr.

    `agy` writes help to stderr and exits 1; we don't treat that as an error.
    """
    executable = shutil.which("agy") or "agy"
    result = subprocess.run(
        [executable, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return (result.stdout or "") + (result.stderr or "")


def split_entry(text: str) -> tuple[str, str]:
    parts = SPLIT_RE.split(text, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return parts[0].strip(), ""


def parse_default(description: str) -> tuple[str, str | None]:
    """Extract a trailing `(default ...)` marker into a separate `default` field."""
    m = DEFAULT_RE.search(description)
    if m:
        return description[: m.start()].strip(), m.group(1)
    return description, None


def make_flag_entry(text: str) -> dict:
    name, description = split_entry(text)
    description, default = parse_default(description)
    entry: dict = {"name": name, "description": description}
    if default is not None:
        entry["default"] = default
    return entry


def normalize_usage(text: str) -> str:
    # The Go binary uppercases its own extension to "agy.EXE" when launched via
    # subprocess (a launch-context quirk); in a real terminal it shows as
    # "agy.exe". Normalize so the snapshot matches what users actually see.
    return re.sub(r"agy\.exe", "agy.exe", text, flags=re.IGNORECASE)


def parse_top_level(text: str) -> dict:
    """Parse `agy --help` top-level output into usage/options/subcommands."""
    usage = ""
    options: list[dict] = []
    subcommands: list[dict] = []
    section: str | None = None  # "options" | "sub" | None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("Usage of") or stripped.startswith("Usage:"):
            usage = normalize_usage(stripped)
            section = "options"
            continue
        if stripped == "Available subcommands:":
            section = "sub"
            continue
        if section == "options":
            options.append(make_flag_entry(stripped))
        elif section == "sub":
            name, description = split_entry(stripped)
            subcommands.append({"name": name, "description": description})
    return {"usage": usage, "options": options, "subcommands": subcommands}


def parse_subcommand_help(text: str) -> dict:
    """Parse `agy help <sub>` output into usage/description/flags/commands."""
    result: dict = {"usage": "", "description": "", "flags": [], "commands": []}
    section: str | None = None
    other: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("Usage of") or stripped.startswith("Usage:"):
            result["usage"] = normalize_usage(stripped)
            section = "desc"
            continue
        if stripped == "Flags:":
            section = "flags"
            continue
        if stripped == "Commands:":
            section = "commands"
            continue
        if section == "desc":
            result["description"] = (result["description"] + " " + stripped).strip()
        elif section == "flags":
            result["flags"].append(make_flag_entry(stripped))
        elif section == "commands":
            name, description = split_entry(stripped)
            result["commands"].append({"name": name, "description": description})
        else:
            other.append(stripped)
    if not result["usage"]:
        # No usage line -> not a help response (e.g. `agy help help` errors).
        return {"error": " ".join(other).strip() or "no usage line found", "raw": text.strip()}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"YAML output path (default: {DEFAULT_OUTPUT.relative_to(SKILL_DIR)})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even if the existing output was fetched less than a day ago.",
    )
    args = parser.parse_args()

    if not args.force:
        fetched_at = read_fetched_at(args.output)
        if fetched_at is not None and datetime.now(timezone.utc) - fetched_at < FRESHNESS:
            print(
                f"{args.output}: すでに最新が取得済みです（取得時刻: {fetched_at.isoformat()}）。"
                "--force で上書きできます。"
            )
            return

    version = run_agy("--version").splitlines()[0].strip() or "unknown"
    top = parse_top_level(run_agy("--help"))

    subcommand_help: dict[str, dict] = {}
    for sub in top["subcommands"]:
        name = sub["name"]
        if name in ALIASES:
            continue  # filled after the canonical subcommand is parsed
        if name == "help":
            # `agy help help` is not a valid help target (returns an error);
            # record a clear note instead of capturing the bogus error text.
            subcommand_help[name] = {
                "note": "`agy help help` は未対応。トップレベル使い方を見るには `agy help`（引数なし）を実行すること。"
            }
            continue
        subcommand_help[name] = parse_subcommand_help(run_agy("help", name))

    for alias, canon in ALIASES.items():
        if canon in subcommand_help:
            subcommand_help[alias] = {"alias_for": canon, **copy.deepcopy(subcommand_help[canon])}
        else:
            subcommand_help[alias] = {"alias_for": canon}

    data = {
        "version": version,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "command": "agy",
        "usage": top["usage"],
        "options": top["options"],
        "subcommands": top["subcommands"],
        "subcommand_help": subcommand_help,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        yaml.dump(
            data, f, allow_unicode=True, sort_keys=False, default_flow_style=False, width=100000
        )

    try:
        display_path = args.output.resolve().relative_to(SKILL_DIR)
    except ValueError:
        display_path = args.output
    print(f"Wrote {display_path}")


if __name__ == "__main__":
    main()
