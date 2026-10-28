"""data/ の生データ保持ポリシーとプルーナー.

data/ は外部媒体から取った使い捨てのキャッシュで、判断に必要な内容は vault の materials（要約）に残す
（links → materials → data の流れ。仕様は docs/vault/materials.md）。保持期間を過ぎた取得単位を削除する。

- 対象は ``RULES`` に載ったディレクトリだけ。載っていないもの・``_is_protected`` に当たるものは消さない。
- 削除単位は「取得単位」: 同じ stem の .md / .json の組、Speaker Deck ならスライドのディレクトリ。
- 取得日は data 側の ``fetched_at`` → ファイル名の日付 → mtime の順に判定し、単位内で最も新しい日を使う。
- vault 本文から参照されている取得単位は消さない（material の ``raw_data`` からの参照は保護しない。
  消えたら取り直す前提）。
- 自動実行（``maybe_prune``）は ``entrypoint_guard`` から呼び、状態ファイルの最終実行から 1 日以上経っていれば走る。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

import yaml

from scripts.common.paths import DATA_DIR, PRUNE_STATE_PATH, VAULT_DIR

DEFAULT_RETENTION_DAYS = 60
PRUNE_INTERVAL = dt.timedelta(days=1)
DISABLE_ENV = "JOB_HUNT_NO_PRUNE"  # "1" 等を入れると自動実行しない（手動の CLI は動く）


@dataclass(frozen=True)
class Rule:
    """保持ポリシー表の1行. ``pattern`` は data/ からの相対 glob."""

    pattern: str
    dir_unit: bool = False  # True: マッチしたディレクトリを1単位として丸ごと消す
    dated_only: bool = False  # True: ファイル名に日付が無いもの（固定名の現在値ファイル）は対象外


# 保持ポリシー表（ここに無いディレクトリは対象外）。保持期間は一律 DEFAULT_RETENTION_DAYS
RULES: tuple[Rule, ...] = (
    # 1 件 1 ファイルの取得物（ID 名。取得日はフロントマターの fetched_at）
    Rule("*/jobs/*"),
    Rule("openwork/reviews/*"),
    Rule("gmail/threads/*"),
    Rule("note/articles/*/*"),
    Rule("note/companies/*/*"),
    Rule("speakerdeck/*/*", dir_unit=True),
    Rule("web/searches/*", dir_unit=True),  # 1 回の呼び出し = index.md ＋結果ファイルのフォルダ
    Rule("web/extracts/*", dir_unit=True),
    Rule("automation/runs/*", dir_unit=True),  # 1 日分の実行ログ（runs/{YYYY-MM-DD}/）
    # 日付付きスナップショット（messages_all.json・profile.json 等の固定名は前回値として残す）
    Rule("*/searches/*", dated_only=True),
    Rule("*/messages/*", dated_only=True),
    Rule("*/messages/history/*", dated_only=True),
    Rule("*/likes/*", dated_only=True),
    Rule("*/recommends/*", dated_only=True),
    Rule("*/favorites/*", dated_only=True),
    Rule("*/resume/*", dated_only=True),
    Rule("*/profile/*", dated_only=True),
    Rule("linkedin/invitations/*", dated_only=True),
    Rule("gcal/calendars/*", dated_only=True),
    Rule("gcal/changes/*", dated_only=True),
    Rule("gcal/event/*", dated_only=True),
    Rule("gcal/events/*", dated_only=True),
    Rule("gcal/slots/*", dated_only=True),
    Rule("automation/briefs/*", dated_only=True),  # {YYYY-MM-DD}_{routine}.md / .json
)

# 2026-09-18 / 20261024_010329 / backup_20260918_... のような日付（前後が数字の ID は除く）
_FILENAME_DATE = re.compile(r"(?<!\d)(20\d{2})-?(0[1-9]|1[0-2])-?(0[1-9]|[12]\d|3[01])(?!\d)")
_MD_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_DATA_REF = re.compile(r"data/[^\s)\]\"'`<>|*]+")


@dataclass
class Unit:
    """取得単位（一緒に消すファイル群）."""

    key: Path  # data/ からの相対パス（ファイル単位は拡張子なし、ディレクトリ単位はディレクトリ）
    paths: list[Path] = field(default_factory=list)  # 絶対パス
    is_dir: bool = False
    fetched: dt.date | None = None
    date_source: str = ""  # fetched_at / filename / mtime
    protected_by: str = ""  # 保護理由（vault 参照元）。空なら削除可

    def rel_paths(self, data_dir: Path) -> list[str]:
        return [p.relative_to(data_dir.parent).as_posix() for p in self.paths]


def _is_protected(rel: Path) -> bool:
    """ポリシー表に当たっても消さないもの（安全装置・提出物・前回値・作業ファイル）."""
    parts = rel.parts
    name = rel.name
    return (
        parts[0] == "exports"  # 提出済みの PDF
        or "backups" in parts  # 外部媒体を更新する前の安全装置
        or name.startswith(("latest", "backup_"))  # 差分プレビューが読む前回値・バックアップ
        or name.startswith(".")  # .gitkeep・.tmp_*・状態ファイル
        or rel.as_posix() == "vault_index.sqlite"
    )


def _parse_date(value: object) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _fetched_at(path: Path) -> dt.date | None:
    """data 側に記録された取得日（JSON のキー / Markdown フロントマター）."""
    try:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            data = json.loads(text)
        elif path.suffix == ".md":
            match = _MD_FRONTMATTER.match(text)
            data = yaml.safe_load(match.group(1)) if match else None
        else:
            return None
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
        return None
    return _parse_date(data.get("fetched_at")) if isinstance(data, dict) else None


def filename_date(name: str) -> dt.date | None:
    match = _FILENAME_DATE.search(name)
    if not match:
        return None
    try:
        return dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _file_date(path: Path) -> tuple[dt.date, str]:
    if (d := _fetched_at(path)) is not None:
        return d, "fetched_at"
    if (d := filename_date(path.name)) is not None:
        return d, "filename"
    return dt.datetime.fromtimestamp(path.stat().st_mtime).date(), "mtime"


def collect_units(data_dir: Path = DATA_DIR) -> list[Unit]:
    """ポリシー表に当たる取得単位を列挙し、取得日を判定する（保護対象は除く）."""
    units: dict[Path, Unit] = {}
    for rule in RULES:
        for path in data_dir.glob(rule.pattern):
            rel = path.relative_to(data_dir)
            if _is_protected(rel):
                continue
            if rule.dir_unit:
                if not path.is_dir():
                    continue
                units.setdefault(rel, Unit(key=rel, paths=[path], is_dir=True))
                continue
            if not path.is_file() or (rule.dated_only and filename_date(path.name) is None):
                continue
            key = rel.with_suffix("")
            unit = units.setdefault(key, Unit(key=key))
            if path not in unit.paths:
                unit.paths.append(path)

    for unit in units.values():
        files = sorted(unit.paths[0].rglob("*")) if unit.is_dir else unit.paths
        dated = [_file_date(p) for p in files if p.is_file()]
        if dated:
            unit.fetched, unit.date_source = max(dated, key=lambda x: x[0])
    return sorted(units.values(), key=lambda u: u.key.as_posix())


def vault_data_refs_by_file(vault_dir: Path = VAULT_DIR) -> dict[str, list[str]]:
    """vault のファイル（リポジトリルート相対パス）→ 本文から参照している data/ パス（出現順・重複なし）.

    materials/*.md のフロントマター（``raw_data``）からの参照は数えない（消えても取り直す前提）。
    """
    by_file: dict[str, list[str]] = {}
    if not vault_dir.is_dir():
        return by_file
    for md in sorted(vault_dir.rglob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if md.parent.name == "materials" and (match := _MD_FRONTMATTER.match(text)):
            text = text[match.end() :]
        refs = [unquote(raw).rstrip("/.,;:") for raw in _DATA_REF.findall(text)]
        if refs:
            by_file[md.relative_to(vault_dir.parent).as_posix()] = list(dict.fromkeys(refs))
    return by_file


def vault_data_refs(vault_dir: Path = VAULT_DIR) -> dict[str, str]:
    """vault 本文から参照されている data/ パス → 参照元（最初に見つかったファイル）."""
    refs: dict[str, str] = {}
    for source, paths in vault_data_refs_by_file(vault_dir).items():
        for ref in paths:
            refs.setdefault(ref, source)
    return refs


def is_retained_ref(ref: str) -> bool:
    """``data/...`` のパスが保持ポリシーの対象（期間を過ぎたら消える取得単位かその中）か.

    ファイルの有無は見ない（パスの形だけで判定する）。ディレクトリ単位の中のファイルも対象に含める。
    """
    if not ref.startswith("data/"):
        return False
    rel = PurePosixPath(ref[len("data/") :].rstrip("/"))
    if not rel.parts or _is_protected(Path(rel)):
        return False
    for rule in RULES:
        pattern = PurePosixPath(rule.pattern).parts
        if rule.dir_unit:
            if len(rel.parts) >= len(pattern) and all(
                fnmatchcase(part, pat) for part, pat in zip(rel.parts, pattern, strict=False)
            ):
                return True
            continue
        if len(rel.parts) == len(pattern) and all(
            fnmatchcase(part, pat) for part, pat in zip(rel.parts, pattern, strict=True)
        ):
            if not rule.dated_only or filename_date(rel.name) is not None:
                return True
    return False


def _referenced_by(unit: Unit, data_dir: Path, refs: dict[str, str]) -> str:
    targets = {p.relative_to(data_dir.parent).as_posix() for p in unit.paths}
    if unit.is_dir:
        prefix = f"{data_dir.name}/{unit.key.as_posix()}"
        for ref, source in refs.items():
            if ref == prefix or ref.startswith(prefix + "/"):
                return source
        return ""
    for ref in refs:
        if ref in targets:
            return refs[ref]
    return ""


def find_expired(
    today: dt.date,
    days: int = DEFAULT_RETENTION_DAYS,
    data_dir: Path = DATA_DIR,
    vault_dir: Path = VAULT_DIR,
) -> list[Unit]:
    """保持期間を過ぎた取得単位（vault から参照されているものは ``protected_by`` 付き）を返す."""
    cutoff = today - dt.timedelta(days=days)
    refs = vault_data_refs(vault_dir)
    expired = [u for u in collect_units(data_dir) if u.fetched is not None and u.fetched < cutoff]
    for unit in expired:
        unit.protected_by = _referenced_by(unit, data_dir, refs)
    return expired


def delete_units(units: Iterable[Unit]) -> list[Unit]:
    """保護されていない単位を削除し、削除したものを返す."""
    deleted = []
    for unit in units:
        if unit.protected_by:
            continue
        for path in unit.paths:
            if unit.is_dir:
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        deleted.append(unit)
    return deleted


def read_last_run(state_path: Path = PRUNE_STATE_PATH) -> dt.datetime | None:
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return dt.datetime.fromisoformat(data["last_run"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_state(now: dt.datetime, deleted: int | None = None, state_path: Path = PRUNE_STATE_PATH) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {"last_run": now.isoformat(timespec="seconds")}
    if deleted is not None:
        data["deleted"] = deleted
    state_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def maybe_prune(
    log: Callable[[str], None],
    now: dt.datetime | None = None,
    data_dir: Path = DATA_DIR,
    vault_dir: Path = VAULT_DIR,
    state_path: Path = PRUNE_STATE_PATH,
) -> list[Unit] | None:
    """最終実行から PRUNE_INTERVAL 以上経っていれば保持期間切れを削除する. 実行しなければ None."""
    if os.environ.get(DISABLE_ENV) or not data_dir.is_dir():
        return None
    now = now or dt.datetime.now()
    last = read_last_run(state_path)
    if last is not None and now - last < PRUNE_INTERVAL:
        return None
    # 並行起動での二重実行を避けるため、削除より先に実行時刻を書く（失敗しても翌日に再試行される）
    write_state(now, state_path=state_path)
    deleted = delete_units(find_expired(now.date(), data_dir=data_dir, vault_dir=vault_dir))
    write_state(now, len(deleted), state_path=state_path)
    if deleted:
        log(f"[INFO] data/ の保持期間（{DEFAULT_RETENTION_DAYS} 日）切れの生データを {len(deleted)} 件削除しました")
    return deleted
