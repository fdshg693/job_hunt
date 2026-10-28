"""vault と data/*/jobs から SQLite の派生索引（data/vault_index.sqlite）を作る CLI.

- 正本は vault の Markdown（と媒体スナップショットの data/*/jobs/*.md）。索引はいつ消しても作り直せる派生キャッシュ。
- 差分更新はせず毎回全件作り直す。一時ファイルに書いてから ``os.replace`` で差し替えるので、
  読み手（Web UI 等）が途中の DB を読むことは無い。
- 全文検索は FTS5 の trigram トークナイザ。3文字未満の語を含む検索は LIKE にフォールバックする（``search()``）。
- ``ensure_index()`` は正本ファイルの件数・最終更新時刻が索引作成時と変わっていれば作り直す。

.agents/rules/scripts-entrypoint.md に従い、stdout には DB のパス（``-q`` 指定時はヒットした正本ファイルのパス）だけを出す。
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import sys
import time
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

# プロジェクトルートパス (scripts/vault/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import create_base_parser, entrypoint_guard
from scripts.common.normalizers import normalize_company_name
from scripts.common.paths import VAULT_INDEX_PATH
from scripts.common.search_local_jobs import JobItem
from scripts.vault.loader import Vault, load_vault
from scripts.vault.schema import (
    KIND_GLOBS,
    ArchiveDoc,
    CompanyDoc,
    InterviewDoc,
    RecruiterDoc,
    RemoteType,
    ScreeningBatchDoc,
    TechAreaDoc,
    TechProjectDoc,
    format_due,
    label_of,
    status_meta,
)
from scripts.vault.schema.enums import JOBS_REMOTE_TYPE_MAP

# テーブル構成を変えたら上げる（ensure_index が古い索引を作り直す）
SCHEMA_VERSION = 3

JOBS_GLOB = "data/*/jobs/*.md"

# FTS5 trigram はこの文字数未満の語にヒットしない
TRIGRAM_MIN = 3

DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE issues (level TEXT, path TEXT, message TEXT);

CREATE TABLE companies (
    id INTEGER PRIMARY KEY,
    track TEXT NOT NULL,
    company_key TEXT NOT NULL,
    company TEXT NOT NULL,
    status TEXT NOT NULL,
    status_label TEXT NOT NULL,
    status_category TEXT NOT NULL,
    status_order INTEGER NOT NULL,
    status_note TEXT,
    decline_reason TEXT,
    evidence_level TEXT,
    fit_score_min INTEGER,
    fit_score_max INTEGER,
    fit_summary TEXT,
    interest INTEGER,
    salary_min INTEGER,          -- 万円
    salary_max INTEGER,          -- 万円
    salary_note TEXT,
    remote_type TEXT,
    office_days_per_week REAL,
    remote_note TEXT,
    action_type TEXT NOT NULL,
    next_action TEXT,
    next_due TEXT,               -- YYYY-MM-DD または YYYY-MM-DD HH:MM（文字列順 = 時刻順）
    job_url TEXT,
    job_title TEXT,
    recruiter TEXT,
    date TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    UNIQUE (track, company_key)
);
CREATE INDEX companies_status ON companies (status_category, status_order);

CREATE TABLE company_tags (company_id INTEGER NOT NULL REFERENCES companies (id), tag TEXT NOT NULL);
CREATE INDEX company_tags_tag ON company_tags (tag);

-- 社名・別名と、その normalize_company_name 値（表記ゆれ吸収用）
CREATE TABLE company_aliases (
    company_id INTEGER NOT NULL REFERENCES companies (id),
    alias TEXT NOT NULL,
    normalized TEXT NOT NULL
);
CREATE INDEX company_aliases_normalized ON company_aliases (normalized);

CREATE TABLE interviews (
    id INTEGER PRIMARY KEY,
    company_id INTEGER REFERENCES companies (id),  -- 企業フォルダの面談ログ
    recruiter_key TEXT,                             -- リクルーターフォルダの面談ログ
    track TEXT,
    company TEXT,
    date TEXT NOT NULL,
    stage TEXT NOT NULL,
    stage_label TEXT NOT NULL,
    interviewer TEXT,
    result TEXT NOT NULL,
    result_label TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE
);

CREATE TABLE recruiters (
    recruiter_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    agency TEXT,
    platform TEXT NOT NULL,
    platform_label TEXT NOT NULL,
    status TEXT NOT NULL,
    status_label TEXT NOT NULL,
    rating TEXT NOT NULL,
    matching_accuracy TEXT,
    communication_quality TEXT,
    dealbreaker_adherence INTEGER,
    tracks TEXT NOT NULL,        -- カンマ区切り
    date TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE
);

CREATE TABLE recruiter_companies (
    recruiter_key TEXT NOT NULL REFERENCES recruiters (recruiter_key),
    company TEXT NOT NULL,
    company_key TEXT,
    company_id INTEGER REFERENCES companies (id),  -- 企業ログがあれば結合先
    archive_id INTEGER REFERENCES archive_entries (id),  -- 企業ログが無く、見送り台帳にあれば結合先
    job_title TEXT,
    date TEXT,
    note TEXT
);

CREATE TABLE screening_entries (
    id INTEGER PRIMARY KEY,
    track TEXT NOT NULL,
    batch_date TEXT NOT NULL,
    topic TEXT NOT NULL,
    name TEXT NOT NULL,
    normalized TEXT NOT NULL,
    aliases TEXT NOT NULL,       -- カンマ区切り
    reason TEXT NOT NULL,
    path TEXT NOT NULL
);

-- 見送り台帳（vault/tracks/{track}/archive.md）の 1 社 1 行
CREATE TABLE archive_entries (
    id INTEGER PRIMARY KEY,
    track TEXT NOT NULL,
    name TEXT NOT NULL,
    company_key TEXT,
    normalized TEXT NOT NULL,
    aliases TEXT NOT NULL,       -- カンマ区切り
    status TEXT NOT NULL,
    status_label TEXT NOT NULL,
    considered_at TEXT NOT NULL,
    closed_at TEXT NOT NULL,
    reached TEXT,
    reached_label TEXT,
    fit_score_min INTEGER,
    fit_score_max INTEGER,
    reason TEXT NOT NULL,
    reconsider_if TEXT,
    recruiter TEXT,
    source TEXT NOT NULL,
    path TEXT NOT NULL
);
CREATE INDEX archive_entries_key ON archive_entries (company_key);

CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL,
    source TEXT NOT NULL,
    company TEXT NOT NULL,
    normalized_company TEXT NOT NULL,
    company_id INTEGER REFERENCES companies (id),  -- 社名が一致する企業ログ（バッジ表示用）
    title TEXT NOT NULL,
    url TEXT,
    fetched_at TEXT,
    salary_min INTEGER,          -- 万円（元データは円）
    salary_max INTEGER,          -- 万円
    salary_text TEXT,
    remote_type TEXT NOT NULL,   -- RemoteType（元の日本語値は remote_text）
    remote_text TEXT,
    location TEXT,
    skills TEXT NOT NULL,        -- カンマ区切り（絞り込みは job_skills）
    job_roles TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE
);
CREATE TABLE job_skills (job_id INTEGER NOT NULL REFERENCES jobs (id), skill TEXT NOT NULL);
CREATE INDEX job_skills_skill ON job_skills (skill COLLATE NOCASE);

-- kind: company | interview | recruiter | screening | archive | job | tech。
-- ref_id は各テーブルの id（recruiter は recruiter_key、専用テーブルの無い tech はプロジェクト・領域のキー）
CREATE VIRTUAL TABLE search_fts USING fts5 (
    kind UNINDEXED,
    ref_id UNINDEXED,
    track UNINDEXED,
    path UNINDEXED,
    title,
    names,
    tags,
    body,
    tokenize = 'trigram'
);
"""

FTS_COLUMNS = ("title", "names", "tags", "body")


@dataclass
class BuildResult:
    path: Path
    counts: dict[str, int] = field(default_factory=dict)
    issues: int = 0


# ---------------------------------------------------------------------------
# 正本ファイルの指紋（ensure_index 用）
# ---------------------------------------------------------------------------


def source_files(root: Path) -> list[Path]:
    patterns = [p for globs in KIND_GLOBS.values() for p in globs] + [JOBS_GLOB]
    return sorted({p for pattern in patterns for p in root.glob(pattern) if p.is_file()})


def source_fingerprint(root: Path) -> str:
    """正本ファイルの件数と最終更新時刻. 追加・更新・削除のどれでも変わる."""
    files = source_files(root)
    latest = max((p.stat().st_mtime_ns for p in files), default=0)
    return f"{len(files)}:{latest}"


# ---------------------------------------------------------------------------
# 行の組み立て
# ---------------------------------------------------------------------------


def _iso(value: dt.date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _enum(value) -> str | None:
    return str(value) if value is not None else None


def _man_yen(value: int | None) -> int | None:
    """data/*/jobs の円単位を万円にする（vault と単位を揃える）."""
    return None if value is None else value // 10000


def _jobs_remote_type(text: str) -> RemoteType:
    return JOBS_REMOTE_TYPE_MAP.get(text.strip(), RemoteType.UNKNOWN)


def normalize_query(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


def _fts(conn: sqlite3.Connection, kind: str, ref_id, doc_track: str | None, path: str, *,
         title: str, names: Iterable[str] = (), tags: Iterable[str] = (), body: str = "") -> None:
    conn.execute(
        "INSERT INTO search_fts (kind, ref_id, track, path, title, names, tags, body) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (kind, ref_id, doc_track, path, normalize_query(title),
         normalize_query(" ".join(n for n in names if n)), normalize_query(" ".join(tags)), normalize_query(body)),
    )


def _insert_companies(conn: sqlite3.Connection, vault: Vault) -> dict[tuple[str, str], int]:
    ids: dict[tuple[str, str], int] = {}
    for doc in vault.companies:
        m = doc.model
        if not isinstance(m, CompanyDoc):
            continue  # スキーマ違反は issues テーブルに残る
        meta = status_meta(m.status)
        cur = conn.execute(
            """INSERT INTO companies (track, company_key, company, status, status_label, status_category, status_order,
                status_note, decline_reason, evidence_level, fit_score_min, fit_score_max, fit_summary, interest,
                salary_min, salary_max, salary_note, remote_type, office_days_per_week, remote_note,
                action_type, next_action, next_due, job_url, job_title, recruiter, date, updated_at, path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(m.track), m.company_key, m.company, str(m.status), meta.label, str(meta.category), meta.order,
             m.status_note, m.decline_reason, _enum(m.evidence_level), m.fit_score_min, m.fit_score_max,
             m.fit_summary, m.interest, m.salary_min, m.salary_max, m.salary_note, _enum(m.remote_type),
             m.office_days_per_week, m.remote_note, str(m.action_type), m.next_action, format_due(m.next_due),
             m.job_url, m.job_title, m.recruiter, _iso(m.date), _iso(m.updated_at), doc.rel),
        )
        company_id = cur.lastrowid
        ids[(str(m.track), m.company_key)] = company_id
        conn.executemany("INSERT INTO company_tags VALUES (?, ?)", [(company_id, t) for t in m.tags])
        names = [m.company, *m.aliases]
        conn.executemany(
            "INSERT INTO company_aliases VALUES (?, ?, ?)",
            [(company_id, n, normalize_company_name(n)) for n in dict.fromkeys(names)],
        )
        link_texts = [f"{link.title} {link.summary or ''}" for link in m.links]
        _fts(conn, "company", company_id, str(m.track), doc.rel, title=m.company,
             names=[*names, *(normalize_company_name(n) for n in names), m.company_key, m.job_title or ""],
             tags=m.tags,
             body="\n".join(filter(None, [m.status_note, m.fit_summary, m.decline_reason, *link_texts, doc.body])))
    return ids


def _insert_interviews(conn: sqlite3.Connection, vault: Vault, company_ids: dict[tuple[str, str], int]) -> None:
    for doc in vault.interviews:
        m = doc.model
        if not isinstance(m, InterviewDoc):
            continue
        in_company = doc.track is not None
        company_id = company_ids.get((doc.track, doc.folder_key)) if in_company else None
        cur = conn.execute(
            """INSERT INTO interviews (company_id, recruiter_key, track, company, date, stage, stage_label,
                interviewer, result, result_label, path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (company_id, None if in_company else doc.folder_key, doc.track, m.company, _iso(m.date), str(m.stage),
             m.stage_name or label_of(m.stage), m.interviewer, str(m.result), label_of(m.result), doc.rel),
        )
        _fts(conn, "interview", cur.lastrowid, doc.track, doc.rel,
             title=f"{m.company or doc.folder_key} {m.stage_name or label_of(m.stage)} ({m.date})",
             names=[m.company or "", m.interviewer or ""], tags=m.tags, body=doc.body)


def _insert_recruiters(conn: sqlite3.Connection, vault: Vault, company_ids: dict[tuple[str, str], int],
                       archive_ids: dict[tuple[str, str], int]) -> None:
    by_key: dict[str, int] = {}
    for (_, key), cid in sorted(company_ids.items()):
        by_key.setdefault(key, cid)  # company_key だけでは track が決まらないので、先に見つかったものに結合する
    archived_by_key: dict[str, int] = {}
    for (_, key), aid in sorted(archive_ids.items()):
        archived_by_key.setdefault(key, aid)
    for doc in vault.recruiters:
        m = doc.model
        if not isinstance(m, RecruiterDoc):
            continue
        conn.execute(
            """INSERT INTO recruiters (recruiter_key, name, agency, platform, platform_label, status, status_label,
                rating, matching_accuracy, communication_quality, dealbreaker_adherence, tracks, date, updated_at, path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (m.recruiter_key, m.name, m.agency, str(m.platform), label_of(m.platform), str(m.status),
             label_of(m.status), str(m.rating), _enum(m.matching_accuracy), m.communication_quality,
             None if m.dealbreaker_adherence is None else int(m.dealbreaker_adherence),
             ",".join(str(t) for t in m.tracks), _iso(m.date), _iso(m.updated_at), doc.rel),
        )
        conn.executemany(
            "INSERT INTO recruiter_companies VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(m.recruiter_key, ic.company, ic.company_key, by_key.get(ic.company_key or ""),
              None if ic.company_key in by_key else archived_by_key.get(ic.company_key or ""),
              ic.job_title, _iso(ic.date), ic.note) for ic in m.introduced_companies],
        )
        link_texts = [f"{link.title} {link.summary or ''}" for link in m.links]
        _fts(conn, "recruiter", m.recruiter_key, None, doc.rel, title=m.name,
             names=[m.name, m.agency or "", m.recruiter_key, *(ic.company for ic in m.introduced_companies)],
             tags=m.tags,
             body="\n".join(filter(None, [*link_texts, doc.body])))


def _insert_screening(conn: sqlite3.Connection, vault: Vault) -> None:
    for doc in vault.screening:
        m = doc.model
        if not isinstance(m, ScreeningBatchDoc):
            continue
        for c in m.companies:
            cur = conn.execute(
                """INSERT INTO screening_entries (track, batch_date, topic, name, normalized, aliases, reason, path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (doc.track, _iso(m.date), m.topic, c.name, normalize_company_name(c.name), ",".join(c.aliases),
                 c.reason, doc.rel),
            )
            names = [c.name, *c.aliases]
            _fts(conn, "screening", cur.lastrowid, doc.track, doc.rel, title=c.name,
                 names=[*names, *(normalize_company_name(n) for n in names)], tags=[m.topic], body=c.reason)


def _insert_archives(conn: sqlite3.Connection, vault: Vault) -> dict[tuple[str, str], int]:
    """見送り台帳のエントリを入れる. 戻り値は (track, company_key) → archive_entries.id（キーのあるエントリのみ）."""
    ids: dict[tuple[str, str], int] = {}
    for doc in vault.archives:
        m = doc.model
        if not isinstance(m, ArchiveDoc):
            continue
        for c in m.companies:
            cur = conn.execute(
                """INSERT INTO archive_entries (track, name, company_key, normalized, aliases, status, status_label,
                    considered_at, closed_at, reached, reached_label, fit_score_min, fit_score_max, reason,
                    reconsider_if, recruiter, source, path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (doc.track, c.name, c.company_key, normalize_company_name(c.name), ",".join(c.aliases), str(c.status),
                 label_of(c.status), _iso(c.considered_at), _iso(c.closed_at), _enum(c.reached),
                 status_meta(c.reached).label if c.reached else None, c.fit_score_min, c.fit_score_max, c.reason,
                 c.reconsider_if, c.recruiter, str(c.source), doc.rel),
            )
            if c.company_key:
                ids[(str(doc.track), c.company_key)] = cur.lastrowid
            names = [c.name, *c.aliases]
            _fts(conn, "archive", cur.lastrowid, doc.track, doc.rel, title=c.name,
                 names=[*names, *(normalize_company_name(n) for n in names), c.company_key or ""],
                 body="\n".join(filter(None, [c.reason, c.reconsider_if])))
    return ids


def _insert_tech(conn: sqlite3.Connection, vault: Vault) -> None:
    """技術ノート（プロジェクト・領域）. 専用テーブルは作らず FTS だけに入れる（internal のノートも入れる）."""
    for doc in [*vault.tech_projects, *vault.tech_areas]:
        m = doc.model
        if isinstance(m, TechProjectDoc):
            key, extra_names, related = m.project_key, [m.role or ""], [*m.tech_stack, *m.areas]
        elif isinstance(m, TechAreaDoc):
            key, extra_names, related = m.area_key, [], m.projects
        else:
            continue
        _fts(conn, "tech", key, None, doc.rel, title=m.title, names=[m.title, key, *extra_names],
             tags=[*m.tags, *related], body=doc.body)


def _company_id_by_name(conn: sqlite3.Connection) -> dict[str, int]:
    """normalize_company_name 値 → 企業ログ id（同名が両 track にあれば先に作った方）."""
    lookup: dict[str, int] = {}
    for normalized, company_id in conn.execute("SELECT normalized, company_id FROM company_aliases ORDER BY company_id"):
        if normalized:
            lookup.setdefault(normalized.lower(), company_id)
    return lookup


def _insert_jobs(conn: sqlite3.Connection, root: Path) -> None:
    lookup = _company_id_by_name(conn)
    for path in sorted(root.glob(JOBS_GLOB)):
        job = JobItem.from_file(path)
        if job is None:
            continue
        rel = path.relative_to(root).as_posix()
        normalized = normalize_company_name(job.company)
        cur = conn.execute(
            """INSERT INTO jobs (job_id, source, company, normalized_company, company_id, title, url, fetched_at,
                salary_min, salary_max, salary_text, remote_type, remote_text, location, skills, job_roles, path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job.id, job.source, job.company, normalized, lookup.get(normalized.lower()), job.title, job.url,
             job.fetched_at, _man_yen(job.salary_min), _man_yen(job.salary_max), job.salary_text,
             str(_jobs_remote_type(job.remote_type)), job.remote_type, job.location, ",".join(job.skills),
             ",".join(job.job_roles), rel),
        )
        job_row = cur.lastrowid
        conn.executemany("INSERT INTO job_skills VALUES (?, ?)", [(job_row, s) for s in dict.fromkeys(job.skills)])
        _fts(conn, "job", job_row, None, rel, title=job.title, names=[job.company, normalized],
             tags=[*job.skills, *job.job_roles, *job.tags], body=job.body)


# ---------------------------------------------------------------------------
# ビルド・差し替え
# ---------------------------------------------------------------------------


def default_db_path(root: Path) -> Path:
    return root / VAULT_INDEX_PATH.relative_to(PROJECT_ROOT)


def _replace_with_retry(src: Path, dst: Path, attempts: int = 5, delay: float = 0.2) -> None:
    """Windows では読み手が DB を開いている瞬間に置換が PermissionError になるので、短い間隔でリトライする."""
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def build_index(root: Path | None = None, db_path: Path | None = None, *, vault: Vault | None = None) -> BuildResult:
    """索引を全件作り直す. root は vault/ と data/ を含むディレクトリ（既定: リポジトリルート）."""
    root = (root or PROJECT_ROOT).resolve()
    db_path = db_path or default_db_path(root)
    fingerprint = source_fingerprint(root)  # 読み込み前に取る（読み込み中の更新は次回の ensure_index で拾う）
    vault = vault or load_vault(root)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_name(db_path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(DDL)
        company_ids = _insert_companies(conn, vault)
        _insert_interviews(conn, vault, company_ids)
        archive_ids = _insert_archives(conn, vault)
        _insert_recruiters(conn, vault, company_ids, archive_ids)
        _insert_screening(conn, vault)
        _insert_tech(conn, vault)
        _insert_jobs(conn, root)
        conn.executemany(
            "INSERT INTO issues VALUES (?, ?, ?)", [(str(i.level), i.path, i.message) for i in vault.issues]
        )
        conn.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [
                ("schema_version", str(SCHEMA_VERSION)),
                ("built_at", dt.datetime.now().isoformat(timespec="seconds")),
                ("source_fingerprint", fingerprint),
            ],
        )
        conn.commit()
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("companies", "interviews", "recruiters", "screening_entries", "archive_entries", "jobs", "issues")
        }
    finally:
        conn.close()
    _replace_with_retry(tmp, db_path)
    return BuildResult(db_path, counts, counts["issues"])


def _read_meta(db_path: Path) -> dict[str, str]:
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        try:
            return dict(conn.execute("SELECT key, value FROM meta"))
        finally:
            conn.close()
    except sqlite3.Error:
        return {}


def is_stale(root: Path | None = None, db_path: Path | None = None) -> bool:
    root = (root or PROJECT_ROOT).resolve()
    db_path = db_path or default_db_path(root)
    if not db_path.exists():
        return True
    meta = _read_meta(db_path)
    return meta.get("schema_version") != str(SCHEMA_VERSION) or meta.get("source_fingerprint") != source_fingerprint(root)


def ensure_index(root: Path | None = None, db_path: Path | None = None) -> Path:
    """索引が無い・古い場合だけ作り直し、DB のパスを返す（毎リクエスト呼んでよい軽さ）."""
    root = (root or PROJECT_ROOT).resolve()
    db_path = db_path or default_db_path(root)
    if is_stale(root, db_path):
        build_index(root, db_path)
    return db_path


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """索引を読み取り専用で開く（Row ファクトリ付き）. 使い終わったらすぐ閉じる（Windows の置換と競合させない）."""
    db_path = db_path or VAULT_INDEX_PATH
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# 全文検索
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchHit:
    kind: str
    ref_id: str
    track: str | None
    path: str
    title: str


def search(conn: sqlite3.Connection, query: str, *, kinds: Iterable[str] | None = None, limit: int = 50) -> list[SearchHit]:
    """空白区切りの語の AND 検索. 全語が3文字以上なら FTS5 MATCH（関連度順）、それ以外は LIKE で探す."""
    terms = normalize_query(query).split()
    if not terms:
        return []
    kinds = list(kinds or [])
    kind_sql = f" AND kind IN ({', '.join('?' * len(kinds))})" if kinds else ""

    if all(len(t) >= TRIGRAM_MIN for t in terms):
        match = " ".join('"' + t.replace('"', '""') + '"' for t in terms)
        sql = f"SELECT kind, ref_id, track, path, title FROM search_fts WHERE search_fts MATCH ?{kind_sql} ORDER BY rank LIMIT ?"
        params: list = [match, *kinds, limit]
    else:
        any_column = "(" + " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in FTS_COLUMNS) + ")"
        sql = (
            f"SELECT kind, ref_id, track, path, title FROM search_fts WHERE "
            f"{' AND '.join([any_column] * len(terms))}{kind_sql} LIMIT ?"
        )
        params = []
        for t in terms:
            pattern = "%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            params += [pattern] * len(FTS_COLUMNS)
        params += [*kinds, limit]
    return [SearchHit(*(str(v) if v is not None else None for v in row)) for row in conn.execute(sql, params)]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

KINDS = ("company", "interview", "recruiter", "screening", "archive", "job", "tech")


def main() -> None:
    parser = create_base_parser(
        description="vault と data/*/jobs から SQLite 索引（data/vault_index.sqlite）を作り直す",
        default_limit=50,
        examples=[
            "uv run python scripts/vault/build_index.py -s  # 索引を作り直す",
            'uv run python scripts/vault/build_index.py -q "週3出社" -s  # 索引を最新にして全文検索',
            'uv run python scripts/vault/build_index.py -q "Rust" --kind company --kind job',
        ],
        related=[
            "scripts/common/search_local_jobs.py: 求人だけを年収・リモート等の条件で絞り込む",
        ],
    )
    parser.add_argument(
        "--root", type=Path, default=PROJECT_ROOT, help="vault/ と data/ を含むディレクトリ（既定: リポジトリルート）"
    )
    parser.add_argument("--db", type=Path, default=None, help="出力先 DB（既定: {root}/data/vault_index.sqlite）")
    parser.add_argument("--if-stale", action="store_true", help="正本が索引作成後に変わっている場合だけ作り直す")
    parser.add_argument("-q", "--query", help="索引を作った上で全文検索し、ヒットした正本ファイルのパスを出す")
    parser.add_argument("--kind", action="append", choices=KINDS, help="-q の検索対象種別（複数指定可。既定: 全種別）")
    args = parser.parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        root = args.root.resolve()
        db_path = (args.db or default_db_path(root)).resolve()
        result: BuildResult | None = None
        if args.if_stale or args.query:
            if is_stale(root, db_path):
                result = build_index(root, db_path)
        else:
            result = build_index(root, db_path)
        ctx.info(f"{'索引を作り直した' if result else '索引は最新'}: {db_path}")

        if args.query:
            conn = connect(db_path)
            try:
                hits = search(conn, args.query, kinds=args.kind, limit=args.limit)
            finally:
                conn.close()
            for hit in hits:
                ctx.add_result_path(root / hit.path)

            def print_summary() -> None:
                print(f"「{args.query}」: {len(hits)} 件")
                for hit in hits:
                    print(f"  [{hit.kind}] {hit.title}  ({hit.path})")

            json_data = [hit.__dict__ for hit in hits]
        else:
            ctx.add_result_path(db_path)

            def print_summary() -> None:
                print(f"{db_path}")
                if result is None:
                    print("  索引は最新（作り直していない）")
                    return
                for table, count in result.counts.items():
                    print(f"  {table}: {count}")

            json_data = {"path": str(db_path), "rebuilt": result is not None, "counts": result.counts if result else None}
        sys.exit(ctx.flush_outputs(summary_fn=print_summary, json_data=json_data))


if __name__ == "__main__":
    main()
