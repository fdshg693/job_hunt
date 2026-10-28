"""人間用の閲覧 Web UI（読み取り専用）. 起動: ``uv run python -m webui`` → http://127.0.0.1:8765

- 一覧・検索は SQLite 索引（scripts/vault/build_index.py）、詳細画面の本文は共通ローダー（scripts/vault/loader.py）から読む。
- 各リクエストの最初に ``ensure_index()`` を呼ぶ。AI が vault を更新しても、ブラウザをリロードすれば反映される。
- vault には書き込まない。書き込みに当たる操作は索引の作り直し（POST /reindex）だけ。
- 待ち受けは 127.0.0.1 固定。internal ファイル（criteria.md / ratings.md / profile/internal/）は表示しない。
"""

from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
from pathlib import Path
from typing import Iterator
from urllib.parse import urlencode, urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import QueryParams

from scripts.common.cli import PROJECT_ROOT
from scripts.common.search_local_jobs import JobItem
from scripts.vault import display
from scripts.vault.build_index import build_index, connect, default_db_path, ensure_index, search
from scripts.vault.loader import load_doc
from scripts.vault.schema import (
    COMPANY_STATUS_META,
    ENUM_LABELS,
    ActionType,
    ArchivedStatus,
    DocKind,
    LinkCategory,
    MatchingAccuracy,
    Rating,
    RecruiterStatus,
    RemoteType,
    StatusCategory,
    Track,
    label_of,
)
from webui import links, queries
from webui.markdown import render as render_markdown

HOST = "127.0.0.1"
DEFAULT_PORT = 8765

WEBUI_DIR = Path(__file__).resolve().parent

# 横断検索の結果をまとめる見出し（search_fts の kind）
SEARCH_KIND_TITLES = {
    "company": "企業",
    "interview": "面談ログ",
    "recruiter": "リクルーター",
    "screening": "スクリーニング",
    "archive": "見送り台帳",
    "job": "求人",
}


# ---------------------------------------------------------------------------
# クエリパラメータ
# ---------------------------------------------------------------------------


def _str(params: QueryParams, name: str) -> str | None:
    value = (params.get(name) or "").strip()
    return value or None


def _int(params: QueryParams, name: str) -> int | None:
    try:
        return int(_str(params, name) or "")
    except ValueError:
        return None


def _float(params: QueryParams, name: str) -> float | None:
    try:
        return float(_str(params, name) or "")
    except ValueError:
        return None


def _list(params: QueryParams, name: str, allowed) -> list[str]:
    allowed_values = {str(v) for v in allowed}
    return [v for v in dict.fromkeys(params.getlist(name)) if v in allowed_values]


def with_query(params: QueryParams, **updates) -> str:
    """現在のクエリに updates を上書きした "?..." を返す（値が None のキーは消す）."""
    items = [(k, v) for k, v in params.multi_items() if k not in updates]
    items += [(k, v) for k, v in updates.items() if v is not None]
    return "?" + urlencode(items) if items else "?"


def _enum_options(enum_cls) -> list[tuple[str, str]]:
    return [(str(v), label) for v, label in ENUM_LABELS[enum_cls].items()]


# ---------------------------------------------------------------------------
# アプリ
# ---------------------------------------------------------------------------


def create_app(root: Path | None = None, db_path: Path | None = None) -> FastAPI:
    """root は vault/ と data/ を含むディレクトリ（既定: リポジトリルート。テストでは一時ディレクトリ）."""
    root = (root or PROJECT_ROOT).resolve()
    db_path = (db_path or default_db_path(root)).resolve()

    app = FastAPI(title="job-hunt vault", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=WEBUI_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=WEBUI_DIR / "templates")
    templates.env.globals.update(
        label_of=label_of,
        label=lambda enum_cls, value: label_of(enum_cls(value)) if value is not None else "",
        Rating=Rating,
        MatchingAccuracy=MatchingAccuracy,
        LinkCategory=LinkCategory,
        display=display,
        links=links,
        with_query=with_query,
        status_meta=COMPANY_STATUS_META,
        StatusCategory=StatusCategory,
        ActionType=ActionType,
        RemoteType=RemoteType,
        Track=Track,
        track_options=_enum_options(Track),
        category_options=_enum_options(StatusCategory),
        status_options=[(str(s), m.label, str(m.category)) for s, m in sorted(COMPANY_STATUS_META.items(), key=lambda x: x[1].order)],
        action_options=_enum_options(ActionType),
        remote_options=_enum_options(RemoteType),
        rating_options=_enum_options(Rating),
        recruiter_status_options=_enum_options(RecruiterStatus),
        archived_status_options=_enum_options(ArchivedStatus),
    )

    def get_conn() -> Iterator[sqlite3.Connection]:
        # 接続はリクエストごとに開いて閉じる（索引の os.replace と Windows のファイルロックを競合させない）
        ensure_index(root, db_path)
        conn = connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    def page(request: Request, name: str, partial: str | None = None, **context) -> HTMLResponse:
        """htmx からの部分更新要求（HX-Request ヘッダ）なら partial テンプレートだけを返す."""
        template = partial if partial and request.headers.get("HX-Request") else name
        return templates.TemplateResponse(request, template, {"query": request.query_params, **context})

    def load(kind: DocKind, rel: str):
        doc, _ = load_doc(kind, root / rel, root)
        return doc

    def vscode_url(rel: str) -> str:
        return "vscode://file/" + (root / rel).as_posix()

    templates.env.globals["vscode_url"] = vscode_url

    @app.exception_handler(404)
    async def not_found(request: Request, exc: HTTPException) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "error.html", {"query": request.query_params, "message": exc.detail}, status_code=404
        )

    # --- ダッシュボード ---------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        counts = queries.status_counts(conn)
        tracks = sorted({c["track"] for c in counts})
        return page(
            request,
            "dashboard.html",
            sections=[
                (ActionType.ACTION_REQUIRED, queries.action_items(conn, ActionType.ACTION_REQUIRED)),
                (ActionType.SCHEDULED, queries.action_items(conn, ActionType.SCHEDULED)),
                (ActionType.WAITING, queries.action_items(conn, ActionType.WAITING)),
            ],
            counts=counts,
            tracks=tracks,
            recent=queries.recent_companies(conn),
            issues=queries.issues(conn),
            meta=queries.meta(conn),
            today=dt.date.today().isoformat(),
        )

    @app.post("/reindex")
    def reindex(request: Request):
        build_index(root, db_path)
        referer = urlsplit(request.headers.get("referer", ""))
        target = (referer.path or "/") + (f"?{referer.query}" if referer.query else "")
        return RedirectResponse(target if target.startswith("/") else "/", status_code=303)

    # --- 企業 -----------------------------------------------------------

    @app.get("/companies", response_class=HTMLResponse)
    def company_list(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        p = request.query_params
        statuses = _list(p, "status", COMPANY_STATUS_META)
        categories = _list(p, "category", StatusCategory)
        if not p:
            # 条件なしで開いたときだけ進行中に絞る。フォームでステータスを全部外した場合は全件（チェック状態と表示を一致させる）
            categories = [str(StatusCategory.ACTIVE)]
        f = queries.CompanyFilter(
            track=_str(p, "track") if _str(p, "track") in {str(t) for t in Track} else None,
            statuses=statuses,
            categories=categories,
            fit_min=_int(p, "fit_min"),
            interest_min=_int(p, "interest_min"),
            salary_min=_int(p, "salary_min"),
            remote_types=_list(p, "remote_type", RemoteType),
            office_days_max=_float(p, "office_days_max"),
            tag=_str(p, "tag"),
            action_types=_list(p, "action_type", ActionType),
            q=_str(p, "q"),
            sort=_str(p, "sort") if _str(p, "sort") in queries.COMPANY_SORTS else queries.DEFAULT_COMPANY_SORT[0],
            dir="desc" if _str(p, "dir") == "desc" else "asc",
        )
        rows = queries.companies(conn, f)
        return page(
            request,
            "companies/list.html",
            partial="companies/_table.html",
            f=f,
            rows=rows,
            tags_by_id=queries.tags_of(conn, [r["id"] for r in rows]),
            all_tags=queries.all_tags(conn),
        )

    @app.get("/companies/{track}/{key}", response_class=HTMLResponse)
    def company_detail(track: str, key: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        row = queries.company(conn, track, key)
        if row is None:
            raise HTTPException(404, f"企業ログが見つからない: {track}/{key}")
        doc = load(DocKind.COMPANY, row["path"])
        interviews = [
            {**iv, "doc": load(DocKind.INTERVIEW, iv["path"]), "anchor": links.interview_anchor(Path(iv["path"]).stem)}
            for iv in queries.company_interviews(conn, row["id"])
        ]
        materials = [
            {**m, "body": render_markdown(m["md"], m["path"])}
            for m in queries.materials_of_path(row["path"], root)
        ]
        recruiter_row = queries.recruiter(conn, row["recruiter"]) if row["recruiter"] else None
        return page(
            request,
            "companies/detail.html",
            c=row,
            model=doc.model,
            body=render_markdown(doc.body, row["path"]),
            interviews=[{**iv, "body": render_markdown(iv["doc"].body, iv["path"])} for iv in interviews],
            materials=materials,
            recruiter=recruiter_row,
            introducers=queries.recruiters_introducing(conn, row["id"]),
            jobs=queries.jobs_of_company(conn, row["id"]),
        )

    # --- リクルーター ------------------------------------------------------

    @app.get("/recruiters", response_class=HTMLResponse)
    def recruiter_list(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        p = request.query_params
        ratings = _list(p, "rating", Rating)
        statuses = _list(p, "status", RecruiterStatus)
        rows = queries.recruiters(conn, ratings=ratings, statuses=statuses, q=_str(p, "q"))
        return page(request, "recruiters/list.html", partial="recruiters/_table.html", rows=rows,
                    ratings=ratings, statuses=statuses)

    @app.get("/recruiters/{key}", response_class=HTMLResponse)
    def recruiter_detail(key: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        row = queries.recruiter(conn, key)
        if row is None:
            raise HTTPException(404, f"リクルーターログが見つからない: {key}")
        doc = load(DocKind.RECRUITER, row["path"])
        interviews = [
            {**iv, "anchor": links.interview_anchor(Path(iv["path"]).stem),
             "body": render_markdown(load(DocKind.INTERVIEW, iv["path"]).body, iv["path"])}
            for iv in queries.recruiter_interviews(conn, key)
        ]
        materials = [
            {**m, "body": render_markdown(m["md"], m["path"])}
            for m in queries.materials_of_path(row["path"], root)
        ]
        return page(
            request,
            "recruiters/detail.html",
            r=row,
            model=doc.model,
            body=render_markdown(doc.body, row["path"]),
            companies=queries.recruiter_companies(conn, key),
            interviews=interviews,
            materials=materials,
        )

    # --- スクリーニング・見送り台帳・求人 ---------------------------------------

    @app.get("/screening", response_class=HTMLResponse)
    def screening(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        p = request.query_params
        track = _str(p, "track") if _str(p, "track") in {str(t) for t in Track} else None
        rows = queries.screening(conn, track=track, q=_str(p, "q"), batch=_str(p, "batch"))
        return page(request, "screening.html", partial="_screening_table.html", rows=rows, track=track)

    @app.get("/archive", response_class=HTMLResponse)
    def archive(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        p = request.query_params
        track = _str(p, "track") if _str(p, "track") in {str(t) for t in Track} else None
        statuses = _list(p, "status", ArchivedStatus)
        rows = queries.archive(conn, track=track, q=_str(p, "q"), key=_str(p, "key"), statuses=statuses)
        return page(request, "archive.html", partial="_archive_table.html", rows=rows, track=track, statuses=statuses)

    @app.get("/jobs", response_class=HTMLResponse)
    def job_list(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        p = request.query_params
        sources = queries.job_sources(conn)
        f = queries.JobFilter(
            sources=_list(p, "source", sources),
            salary_min=_int(p, "salary_min"),
            remote_types=_list(p, "remote_type", RemoteType),
            skill=_str(p, "skill"),
            has_log=_str(p, "has_log") == "1",
            q=_str(p, "q"),
        )
        return page(
            request,
            "jobs.html",
            partial="_jobs_table.html",
            f=f,
            rows=queries.jobs(conn, f),
            total=queries.job_count(conn),
            source_options=[(s, s) for s in sources],
            skills=queries.job_skills(conn),
        )

    @app.get("/jobs/{source}/{stem}", response_class=HTMLResponse)
    def job_detail(source: str, stem: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        rel = f"data/{source}/jobs/{stem}.md"
        row = queries.job_by_path(conn, rel)
        if row is None:
            raise HTTPException(404, f"求人が見つからない: {rel}")
        job = JobItem.from_file(root / rel)
        return page(request, "job_detail.html", j=row, body=render_markdown(job.body if job else "", rel))

    # --- 横断検索 ---------------------------------------------------------

    @app.get("/search", response_class=HTMLResponse)
    def search_all(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        q = _str(request.query_params, "q")
        groups: dict[str, list] = {kind: [] for kind in SEARCH_KIND_TITLES}
        # 表示しない種別（技術ノート等のプロフィール）は検索対象から外す
        for hit in search(conn, q, kinds=SEARCH_KIND_TITLES, limit=200) if q else []:
            groups[hit.kind].append({"hit": hit, "url": links.ui_url(hit.path)})
        return page(request, "search.html", q=q, groups=groups, titles=SEARCH_KIND_TITLES)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="vault 閲覧用 Web UI（127.0.0.1 のみで待ち受け）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"待ち受けポート（既定: {DEFAULT_PORT}）")
    args = parser.parse_args()

    import uvicorn

    print(f"http://{HOST}:{args.port}", file=sys.stderr)
    uvicorn.run(create_app(), host=HOST, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
