"""正本ファイルのパス（リポジトリルート相対）→ Web UI 内の URL.

UI で表示できるファイル（企業ログ・面談ログ・リクルーターログ・スクリーニング・見送り台帳・求人）だけを URL にする。
internal ファイル（criteria.md 等）やプロフィールなど v1 で表示しないファイルは None を返す。
"""

from __future__ import annotations

import re
from urllib.parse import quote, urlencode

_COMPANY = re.compile(r"^vault/tracks/([^/]+)/companies/([^/]+)/index\.md$")
_COMPANY_INTERVIEW = re.compile(r"^vault/tracks/([^/]+)/companies/([^/]+)/(\d{4}-\d{2}-\d{2}_[^/]+)\.md$")
_RECRUITER = re.compile(r"^vault/recruiters/([^/]+)/index\.md$")
_RECRUITER_INTERVIEW = re.compile(r"^vault/recruiters/([^/]+)/(\d{4}-\d{2}-\d{2}_[^/]+)\.md$")
_SCREENING = re.compile(r"^vault/tracks/([^/]+)/screening/[^/]+\.md$")
_ARCHIVE = re.compile(r"^vault/tracks/([^/]+)/archive\.md$")
_JOB = re.compile(r"^data/([^/]+)/jobs/([^/]+)\.md$")


def interview_anchor(stem: str) -> str:
    """面談ログのタブ id（例: iv-2026-10-15_casual）."""
    return f"iv-{stem}"


def company_url(track: str, key: str) -> str:
    return f"/companies/{quote(track)}/{quote(key)}"


def recruiter_url(key: str) -> str:
    return f"/recruiters/{quote(key)}"


def archive_url(track: str, key: str | None = None) -> str:
    """見送り台帳の一覧（key を渡すとその企業の行だけ）."""
    return "/archive?" + urlencode({"track": track, **({"key": key} if key else {})})


def job_url(source: str, stem: str) -> str:
    return f"/jobs/{quote(source)}/{quote(stem)}"


def ui_url(rel: str) -> str | None:
    if m := _COMPANY.match(rel):
        return company_url(*m.groups())
    if m := _COMPANY_INTERVIEW.match(rel):
        return f"{company_url(m[1], m[2])}#{interview_anchor(m[3])}"
    if m := _RECRUITER.match(rel):
        return recruiter_url(m[1])
    if m := _RECRUITER_INTERVIEW.match(rel):
        return f"{recruiter_url(m[1])}#{interview_anchor(m[2])}"
    if m := _SCREENING.match(rel):
        return "/screening?" + urlencode({"track": m[1], "batch": rel})
    if m := _ARCHIVE.match(rel):
        return archive_url(m[1])
    if m := _JOB.match(rel):
        return job_url(*m.groups())
    return None
