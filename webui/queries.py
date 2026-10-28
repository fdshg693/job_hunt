"""Web UI の SQL（一覧・フィルタ・集計）. ルーティング側には SQL を書かない.

索引のテーブル定義は scripts/vault/build_index.py の DDL を正とする。全文検索は build_index.search() を使う。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from scripts.vault.build_index import search
from scripts.vault.loader import load_doc
from scripts.vault.schema import ActionType, DocKind, MaterialDoc, RemoteType, StatusCategory


def _rows(conn: sqlite3.Connection, sql: str, params: list | tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params)]


def _in(column: str, values: list[str], params: list) -> str:
    params.extend(values)
    return f"{column} IN ({', '.join('?' * len(values))})"


def _search_ids(conn: sqlite3.Connection, q: str, kind: str) -> list[str]:
    return [hit.ref_id for hit in search(conn, q, kinds=[kind], limit=10000)]


# ---------------------------------------------------------------------------
# ダッシュボード
# ---------------------------------------------------------------------------


def action_items(conn: sqlite3.Connection, action: ActionType) -> list[dict]:
    """進行中の企業のうち、指定 action_type のもの（next_due 昇順、未設定は最後）."""
    return _rows(
        conn,
        """SELECT * FROM companies WHERE status_category = ? AND action_type = ?
           ORDER BY next_due IS NULL, next_due, status_order""",
        (str(StatusCategory.ACTIVE), str(action)),
    )


def status_counts(conn: sqlite3.Connection) -> list[dict]:
    """track × status の件数（status の並び順）."""
    return _rows(
        conn,
        """SELECT track, status, status_label, status_category, status_order, COUNT(*) AS n FROM companies
           GROUP BY track, status ORDER BY track, status_order""",
    )


def recent_companies(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    return _rows(conn, "SELECT * FROM companies ORDER BY updated_at DESC, company LIMIT ?", (limit,))


def issues(conn: sqlite3.Connection) -> list[dict]:
    return _rows(conn, "SELECT * FROM issues ORDER BY level, path")


def meta(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT key, value FROM meta").fetchall())


# ---------------------------------------------------------------------------
# 企業
# ---------------------------------------------------------------------------

# 並べ替えキー → ORDER BY 句（未記入は常に最後）
COMPANY_SORTS: dict[str, str] = {
    "company": "company {dir}",
    "status": "status_order {dir}",
    "fit": "fit_score_max IS NULL, fit_score_max {dir}, fit_score_min {dir}",
    "interest": "interest IS NULL, interest {dir}",
    "salary": "salary_max IS NULL AND salary_min IS NULL, COALESCE(salary_max, salary_min) {dir}",
    "office": "office_days IS NULL, office_days {dir}",
    "due": "next_due IS NULL, next_due {dir}",
    "updated": "updated_at {dir}",
}
DEFAULT_COMPANY_SORT = ("status", "asc")

# 出社日数: 未記入でも full_remote なら 0 とみなす
_OFFICE_DAYS = f"COALESCE(office_days_per_week, CASE WHEN remote_type = '{RemoteType.FULL_REMOTE}' THEN 0 END)"


@dataclass
class CompanyFilter:
    track: str | None = None
    statuses: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    fit_min: int | None = None  # fit_score_min >= N
    interest_min: int | None = None
    salary_min: int | None = None  # 年収上限（無ければ下限）が N 万円以上
    remote_types: list[str] = field(default_factory=list)
    office_days_max: float | None = None
    tag: str | None = None
    action_types: list[str] = field(default_factory=list)
    q: str | None = None
    sort: str = DEFAULT_COMPANY_SORT[0]
    dir: str = DEFAULT_COMPANY_SORT[1]


def companies(conn: sqlite3.Connection, f: CompanyFilter) -> list[dict]:
    where: list[str] = []
    params: list = []
    if f.track:
        where.append("track = ?")
        params.append(f.track)
    # status と category はどちらかに当てはまれば対象（「進行中すべて＋辞退」のような選び方ができる）
    status_terms = []
    if f.statuses:
        status_terms.append(_in("status", f.statuses, params))
    if f.categories:
        status_terms.append(_in("status_category", f.categories, params))
    if status_terms:
        where.append("(" + " OR ".join(status_terms) + ")")
    if f.fit_min is not None:
        where.append("fit_score_min >= ?")
        params.append(f.fit_min)
    if f.interest_min is not None:
        where.append("interest >= ?")
        params.append(f.interest_min)
    if f.salary_min is not None:
        where.append("COALESCE(salary_max, salary_min) >= ?")
        params.append(f.salary_min)
    if f.remote_types:
        where.append(_in("remote_type", f.remote_types, params))
    if f.office_days_max is not None:
        where.append(f"{_OFFICE_DAYS} <= ?")
        params.append(f.office_days_max)
    if f.tag:
        where.append("id IN (SELECT company_id FROM company_tags WHERE tag = ? COLLATE NOCASE)")
        params.append(f.tag)
    if f.action_types:
        where.append(_in("action_type", f.action_types, params))
    if f.q:
        where.append(_in("id", _search_ids(conn, f.q, "company"), params))

    direction = "DESC" if f.dir == "desc" else "ASC"
    order = COMPANY_SORTS.get(f.sort, COMPANY_SORTS[DEFAULT_COMPANY_SORT[0]]).format(dir=direction)
    sql = f"SELECT *, {_OFFICE_DAYS} AS office_days FROM companies"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {order}, status_order, company"
    return _rows(conn, sql, params)


def all_tags(conn: sqlite3.Connection) -> list[dict]:
    return _rows(conn, "SELECT tag, COUNT(*) AS n FROM company_tags GROUP BY tag ORDER BY n DESC, tag")


def tags_of(conn: sqlite3.Connection, company_ids: list[int]) -> dict[int, list[str]]:
    if not company_ids:
        return {}
    params: list = []
    sql = f"SELECT company_id, tag FROM company_tags WHERE {_in('company_id', [str(i) for i in company_ids], params)}"
    out: dict[int, list[str]] = {}
    for row in conn.execute(sql, params):
        out.setdefault(row["company_id"], []).append(row["tag"])
    return out


def company(conn: sqlite3.Connection, track: str, key: str) -> dict | None:
    row = conn.execute("SELECT * FROM companies WHERE track = ? AND company_key = ?", (track, key)).fetchone()
    return dict(row) if row else None


def company_by_id(conn: sqlite3.Connection, company_id: int | str) -> dict | None:
    row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    return dict(row) if row else None


def company_interviews(conn: sqlite3.Connection, company_id: int) -> list[dict]:
    return _rows(conn, "SELECT * FROM interviews WHERE company_id = ? ORDER BY date, path", (company_id,))


def jobs_of_company(conn: sqlite3.Connection, company_id: int) -> list[dict]:
    return _rows(conn, "SELECT * FROM jobs WHERE company_id = ? ORDER BY fetched_at DESC", (company_id,))


def recruiters_introducing(conn: sqlite3.Connection, company_id: int) -> list[dict]:
    return _rows(
        conn,
        """SELECT r.recruiter_key, r.name, r.agency, r.rating FROM recruiter_companies rc
           JOIN recruiters r USING (recruiter_key) WHERE rc.company_id = ? ORDER BY r.name""",
        (company_id,),
    )


# ---------------------------------------------------------------------------
# リクルーター
# ---------------------------------------------------------------------------


def recruiters(conn: sqlite3.Connection, *, ratings: list[str], statuses: list[str], q: str | None) -> list[dict]:
    where: list[str] = []
    params: list = []
    if ratings:
        where.append(_in("rating", ratings, params))
    if statuses:
        where.append(_in("status", statuses, params))
    if q:
        where.append(_in("recruiter_key", _search_ids(conn, q, "recruiter"), params))
    sql = """SELECT r.*, (SELECT COUNT(*) FROM recruiter_companies rc WHERE rc.recruiter_key = r.recruiter_key) AS n_companies
             FROM recruiters r"""
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY rating, updated_at DESC"
    return _rows(conn, sql, params)


def recruiter(conn: sqlite3.Connection, key: str) -> dict | None:
    row = conn.execute("SELECT * FROM recruiters WHERE recruiter_key = ?", (key,)).fetchone()
    return dict(row) if row else None


def recruiter_companies(conn: sqlite3.Connection, key: str) -> list[dict]:
    """紹介企業. 企業ログがあれば status・fit_score などは企業ログ側、圧縮済みなら見送り台帳の値を出す."""
    return _rows(
        conn,
        """SELECT rc.company AS introduced_name, rc.job_title AS introduced_title, rc.date AS introduced_date, rc.note,
                  c.id AS company_id, c.track, c.company_key, c.company, c.status, c.status_label, c.status_category,
                  c.fit_score_min, c.fit_score_max, c.salary_min, c.salary_max,
                  a.id AS archive_id, a.track AS archive_track, a.company_key AS archive_key,
                  a.status_label AS archive_status_label, a.closed_at AS archive_closed_at,
                  a.fit_score_min AS archive_fit_min, a.fit_score_max AS archive_fit_max
           FROM recruiter_companies rc LEFT JOIN companies c ON c.id = rc.company_id
                LEFT JOIN archive_entries a ON a.id = rc.archive_id
           WHERE rc.recruiter_key = ? ORDER BY rc.date DESC, rc.company""",
        (key,),
    )


def recruiter_interviews(conn: sqlite3.Connection, key: str) -> list[dict]:
    return _rows(conn, "SELECT * FROM interviews WHERE recruiter_key = ? ORDER BY date, path", (key,))


# ---------------------------------------------------------------------------
# スクリーニング
# ---------------------------------------------------------------------------


def screening(conn: sqlite3.Connection, *, track: str | None, q: str | None, batch: str | None) -> list[dict]:
    where: list[str] = []
    params: list = []
    if track:
        where.append("track = ?")
        params.append(track)
    if batch:
        where.append("path = ?")
        params.append(batch)
    if q:
        where.append(_in("id", _search_ids(conn, q, "screening"), params))
    sql = "SELECT * FROM screening_entries"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY batch_date DESC, path, id"
    return _rows(conn, sql, params)


# ---------------------------------------------------------------------------
# 見送り台帳
# ---------------------------------------------------------------------------


def archive(conn: sqlite3.Connection, *, track: str | None, q: str | None, key: str | None,
            statuses: list[str]) -> list[dict]:
    where: list[str] = []
    params: list = []
    if track:
        where.append("track = ?")
        params.append(track)
    if key:
        where.append("company_key = ?")
        params.append(key)
    if statuses:
        where.append(_in("status", statuses, params))
    if q:
        where.append(_in("id", _search_ids(conn, q, "archive"), params))
    sql = "SELECT * FROM archive_entries"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY closed_at DESC, name"
    return _rows(conn, sql, params)


# ---------------------------------------------------------------------------
# 求人（data/*/jobs）
# ---------------------------------------------------------------------------


@dataclass
class JobFilter:
    sources: list[str] = field(default_factory=list)
    salary_min: int | None = None  # 年収上限（無ければ下限）が N 万円以上
    remote_types: list[str] = field(default_factory=list)
    skill: str | None = None
    has_log: bool = False
    q: str | None = None
    limit: int = 300


def jobs(conn: sqlite3.Connection, f: JobFilter) -> list[dict]:
    where: list[str] = []
    params: list = []
    if f.sources:
        where.append(_in("j.source", f.sources, params))
    if f.salary_min is not None:
        where.append("COALESCE(j.salary_max, j.salary_min) >= ?")
        params.append(f.salary_min)
    if f.remote_types:
        where.append(_in("j.remote_type", f.remote_types, params))
    if f.skill:
        where.append("j.id IN (SELECT job_id FROM job_skills WHERE skill = ? COLLATE NOCASE)")
        params.append(f.skill)
    if f.has_log:
        where.append("j.company_id IS NOT NULL")
    if f.q:
        where.append(_in("j.id", _search_ids(conn, f.q, "job"), params))
    sql = """SELECT j.*, c.track AS company_track, c.company_key, c.status_label AS company_status_label,
                    c.status_category AS company_status_category
             FROM jobs j LEFT JOIN companies c ON c.id = j.company_id"""
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY j.fetched_at DESC, j.id LIMIT ?"
    params.append(f.limit)
    return _rows(conn, sql, params)


def job_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]


def job_sources(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT DISTINCT source FROM jobs ORDER BY source")]


def job_skills(conn: sqlite3.Connection, limit: int = 60) -> list[dict]:
    return _rows(
        conn, "SELECT skill, COUNT(*) AS n FROM job_skills GROUP BY skill COLLATE NOCASE ORDER BY n DESC LIMIT ?", (limit,)
    )


def job_by_path(conn: sqlite3.Connection, path: str) -> dict | None:
    row = conn.execute(
        """SELECT j.*, c.track AS company_track, c.company_key, c.status_label AS company_status_label
           FROM jobs j LEFT JOIN companies c ON c.id = j.company_id WHERE j.path = ?""",
        (path,),
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# 資料（materials）
# ---------------------------------------------------------------------------


def materials_of_path(doc_path: Path | str, root: Path) -> list[dict]:
    """対象ドキュメント（index.md）と同階層の materials/ 配下にある資料の一覧.

    日付（``fetched_at``: 要約の鮮度、``raw_fetched_at``: 生データの取得日）は資料のフロントマター（MaterialDoc）が正本。
    フロントマターが無い・検証に失敗した資料も、本文の見出しをタイトルにして表示する。
    """
    doc_abs = (root / doc_path).resolve()
    mat_dir = doc_abs.parent / "materials"
    if not mat_dir.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(mat_dir.glob("*.md")):
        doc, _ = load_doc(DocKind.MATERIAL, p, root)
        m = doc.model if isinstance(doc.model, MaterialDoc) else None
        title = m.title if m else next(
            (line.strip()[2:].strip() for line in doc.body.splitlines() if line.strip().startswith("# ")), p.stem
        )
        out.append(
            {
                "name": p.name,
                "stem": p.stem,
                "title": title,
                "path": doc.rel,
                "material_rel": f"materials/{p.name}",
                "anchor": f"mat-{p.stem}",
                "md": doc.body,
                "fetched_at": m.fetched_at if m else None,
                "raw_fetched_at": m.raw_fetched_at if m else None,
                "source_url": m.source_url if m else None,
            }
        )
    return out
