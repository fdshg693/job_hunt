"""求人Markdownの横断検索・フィルタCLIスクリプト.

data/ 配下の各サイト求人Markdown（data/*/jobs/*.md など）を走査し、
キーワード、企業名、技術スタック、年収、リモートワーク等の条件で検索・一覧表示します。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# プロジェクトルートパス設定 (sys.path に追加して絶対インポートを可能にする)
_CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _CURRENT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import PROJECT_ROOT, EntrypointContext, to_relative_path
from scripts.common.normalizers import (
    format_salary_display as normalize_salary_display,
    parse_salary_arg,
)

DEFAULT_DATA_DIR = Path("data")



@dataclass
class JobItem:
    """求人データ項目."""

    file_path: Path
    id: str
    source: str
    company: str
    title: str
    url: str
    fetched_at: str
    salary_min: int | None
    salary_max: int | None
    salary_text: str
    skills: list[str]
    job_roles: list[str]
    location: str
    remote_type: str
    tags: list[str]
    company_url: str
    raw_metadata: dict[str, Any]
    body: str

    @classmethod
    def from_file(cls, path: Path) -> JobItem | None:
        """Markdownファイルから求人データを生成する."""
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            print(f"警告: ファイル読み込み失敗 ({path}): {e}", file=sys.stderr)
            return None

        # フロントマターと本文を分離 (--- で囲まれたブロック)
        match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", content, re.DOTALL)
        if not match:
            return None

        raw_yaml, body = match.group(1), match.group(2)
        try:
            meta = yaml.safe_load(raw_yaml)
            if not isinstance(meta, dict):
                return None
        except Exception as e:
            print(f"警告: YAMLパース失敗 ({path}): {e}", file=sys.stderr)
            return None

        # メッセージやいいね、検索結果、プロフィール等の非求人Markdownを除外
        item_type = str(meta.get("type", "")).lower()
        if item_type in ("messages", "likes", "searches", "search", "plan", "plan step", "profile"):
            return None
        if not meta.get("title") and not meta.get("company"):
            return None

        # スキルやタグのリスト正規化
        def to_str_list(val: Any) -> list[str]:
            if isinstance(val, list):
                return [str(v).strip() for v in val if v is not None]
            if isinstance(val, str) and val.strip():
                return [val.strip()]
            return []

        salary_min = meta.get("salary_min")
        if salary_min is not None:
            try:
                salary_min = int(salary_min)
            except (ValueError, TypeError):
                salary_min = None

        salary_max = meta.get("salary_max")
        if salary_max is not None:
            try:
                salary_max = int(salary_max)
            except (ValueError, TypeError):
                salary_max = None

        return cls(
            file_path=path,
            id=str(meta.get("id", path.stem)),
            source=str(meta.get("source", "")),
            company=str(meta.get("company", "")),
            title=str(meta.get("title", "")),
            url=str(meta.get("url", "")),
            fetched_at=str(meta.get("fetched_at", "")),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_text=str(meta.get("salary_text", "")),
            skills=to_str_list(meta.get("skills")),
            job_roles=to_str_list(meta.get("job_roles")),
            location=str(meta.get("location", "")),
            remote_type=str(meta.get("remote_type", "")),
            tags=to_str_list(meta.get("tags")),
            company_url=str(meta.get("company_url", "")),
            raw_metadata=meta,
            body=body,
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON出力用の辞書表現に変換する."""
        return {
            "file_path": str(self.file_path).replace("\\", "/"),
            "id": self.id,
            "source": self.source,
            "company": self.company,
            "title": self.title,
            "url": self.url,
            "fetched_at": self.fetched_at,
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "salary_text": self.salary_text,
            "skills": self.skills,
            "job_roles": self.job_roles,
            "location": self.location,
            "remote_type": self.remote_type,
            "tags": self.tags,
            "company_url": self.company_url,
        }


def parse_salary_arg(val: str | None) -> int | None:
    """年収指定引数を円単位の整数に変換する.

    例: '700' -> 7000000 (10000未満は万円指定とみなす)
        '7000000' -> 7000000
    """
    if val is None:
        return None
    val_clean = val.replace(",", "").replace("万", "").replace("円", "").strip()
    try:
        num = int(float(val_clean))
        if num < 10000:
            return num * 10000
        return num
    except ValueError:
        raise argparse.ArgumentTypeError(f"不正な年収形式です: '{val}' (例: 700 または 7000000)")


def format_salary_display(job: JobItem) -> str:
    """年収を読みやすくフォーマットする."""
    return normalize_salary_display(job.salary_min, job.salary_max, job.salary_text)


def load_all_jobs(target_dir: Path) -> list[JobItem]:
    """指定ディレクトリ配下のすべての求人Markdownを読み込む."""
    if not target_dir.exists():
        return []

    jobs: list[JobItem] = []
    # target_dir が data 自体の場合は、各サイトの jobs フォルダまたは全体を走査
    for md_file in target_dir.rglob("*.md"):
        # ディレクトリ直下の説明用README.md等は除外
        if md_file.name.lower() in ("readme.md", "index.md"):
            continue
        job = JobItem.from_file(md_file)
        if job is not None:
            jobs.append(job)
    return jobs


def filter_jobs(
    jobs: list[JobItem],
    keywords: list[str] | None = None,
    company: str | None = None,
    title: str | None = None,
    skills: list[str] | None = None,
    min_salary: int | None = None,
    max_salary: int | None = None,
    remote: str | None = None,
    role: str | None = None,
    source: str | None = None,
    job_id: str | None = None,
) -> list[JobItem]:
    """条件に合致する求人を抽出する."""
    results: list[JobItem] = []

    for job in jobs:
        # ID指定
        if job_id and job.id != job_id:
            continue

        # 媒体指定
        if source and source.lower() not in job.source.lower():
            continue

        # 企業名
        if company and company.lower() not in job.company.lower():
            continue

        # タイトル
        if title and title.lower() not in job.title.lower():
            continue

        # リモート
        if remote and remote.lower() not in job.remote_type.lower():
            continue

        # 職種カテゴリ
        if role:
            role_lower = role.lower()
            if not any(role_lower in r.lower() for r in job.job_roles):
                continue

        # スキル指定 (指定した全スキルが含まれるか)
        if skills:
            job_skills_lower = [s.lower() for s in job.skills]
            has_all_skills = True
            for req_skill in skills:
                req_lower = req_skill.lower()
                if not any(req_lower in js for js in job_skills_lower):
                    has_all_skills = False
                    break
            if not has_all_skills:
                continue

        # 最低年収 (上限年収がmin_salary以上、または下限年収がmin_salary以上)
        if min_salary is not None:
            effective_max = job.salary_max if job.salary_max is not None else job.salary_min
            if effective_max is None or effective_max < min_salary:
                continue

        # 最高年収 (下限年収がmax_salary以下、または上限年収がmax_salary以下)
        if max_salary is not None:
            effective_min = job.salary_min if job.salary_min is not None else job.salary_max
            if effective_min is None or effective_min > max_salary:
                continue

        # 全文キーワード (AND検索: 本文、タイトル、企業名、タグ、スキルを走査)
        if keywords:
            search_blob = " ".join([
                job.title,
                job.company,
                " ".join(job.skills),
                " ".join(job.tags),
                " ".join(job.job_roles),
                job.location,
                job.remote_type,
                job.body,
            ]).lower()

            all_keywords_match = True
            for kw in keywords:
                if kw.lower() not in search_blob:
                    all_keywords_match = False
                    break
            if not all_keywords_match:
                continue

        results.append(job)

    return results


def sort_jobs(jobs: list[JobItem], sort_by: str, reverse: bool = False) -> list[JobItem]:
    """求人リストをソートする."""
    if sort_by == "salary_max":
        return sorted(jobs, key=lambda j: (j.salary_max or 0, j.salary_min or 0), reverse=reverse)
    elif sort_by == "salary_min":
        return sorted(jobs, key=lambda j: (j.salary_min or 0, j.salary_max or 0), reverse=reverse)
    elif sort_by == "company":
        return sorted(jobs, key=lambda j: j.company, reverse=reverse)
    elif sort_by == "title":
        return sorted(jobs, key=lambda j: j.title, reverse=reverse)
    elif sort_by == "fetched_at":
        return sorted(jobs, key=lambda j: j.fetched_at, reverse=reverse)
    return jobs


def print_terminal_view(jobs: list[JobItem], detail: bool = False) -> None:
    """求人一覧をターミナル向けに整形して表示する."""
    if not jobs:
        print("合致する求人は見つかりませんでした。")
        return

    print(f"\n===== 検索結果: {len(jobs)} 件 =====\n")

    for idx, job in enumerate(jobs, 1):
        salary_str = format_salary_display(job)
        skills_str = ", ".join(job.skills[:8]) if job.skills else "未指定"
        if len(job.skills) > 8:
            skills_str += f" 他{len(job.skills) - 8}件"
        remote_str = job.remote_type if job.remote_type else "未指定"

        print(f"[{idx}] {job.company} | {job.title}")
        print(f"    - ID: {job.id} ({job.source}) | 取得日: {job.fetched_at[:10] if job.fetched_at else '不明'}")
        print(f"    - 年収: {salary_str} | リモート: {remote_str} | 勤務地: {job.location or '未指定'}")
        print(f"    - スキル: {skills_str}")
        print(f"    - URL: {job.url}")
        print(f"    - ファイル: {job.file_path}")

        if detail:
            lines = [line.strip() for line in job.body.splitlines() if line.strip()]
            snippet_lines = []
            for l in lines:
                if l.startswith("#"):
                    continue
                snippet_lines.append(l)
                if len(snippet_lines) >= 3:
                    break
            snippet = "\n      ".join(snippet_lines)
            if snippet:
                print(f"    - 概要抜粋:\n      {snippet}")
        print("-" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ローカル求人Markdown（data/*/jobs/*.md）の横断検索・フィルタCLIツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "query",
        nargs="*",
        help="フリーワード検索キーワード（AND一致、タイトル/企業名/スキル/本文を走査）",
    )
    parser.add_argument(
        "-k",
        "--keyword",
        action="append",
        dest="keywords_opt",
        help="追加の検索キーワード（複数指定可）",
    )
    parser.add_argument(
        "-c",
        "--company",
        help="企業名（部分一致）",
    )
    parser.add_argument(
        "-t",
        "--title",
        help="求人タイトル（部分一致）",
    )
    parser.add_argument(
        "-s",
        "--skill",
        action="append",
        dest="skills",
        help="必要スキル（複数指定可、例: -s Python -s React）",
    )
    parser.add_argument(
        "--min-salary",
        type=parse_salary_arg,
        help="最低希望年収（例: 700, 700万, 7000000）",
    )
    parser.add_argument(
        "--max-salary",
        type=parse_salary_arg,
        help="最高希望年収（例: 1200, 1200万, 12000000）",
    )
    parser.add_argument(
        "-r",
        "--remote",
        help="リモート勤務条件（例: フルリモート, ハイブリッド）",
    )
    parser.add_argument(
        "--role",
        help="職種カテゴリ（例: バックエンド, フルスタック）",
    )
    parser.add_argument(
        "--source",
        help="求人媒体（findy, bizreach 等）",
    )
    parser.add_argument(
        "--id",
        help="求人ID（完全一致）",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"データ格納ディレクトリ (デフォルト: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--sort",
        choices=["fetched_at", "salary_max", "salary_min", "company", "title"],
        default="fetched_at",
        help="ソート項目 (デフォルト: fetched_at)",
    )
    parser.add_argument(
        "--asc",
        action="store_true",
        help="昇順ソート（指定しない場合は降順）",
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=None,
        help="表示件数の上限",
    )
    parser.add_argument(
        "-d",
        "--detail",
        action="store_true",
        help="求人の本文抜粋を含む詳細情報を表示",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="結果をJSON形式で出力",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="求人一覧のサマリテーブルをコンソールに整形表示する",
    )
    parser.add_argument(
        "--files-only",
        action="store_true",
        help="一致した求人のMarkdownファイルパスのみを1行ずつ出力 (デフォルト動作と同じ)",
    )

    args = parser.parse_args()

    keywords: list[str] = []
    if args.query:
        keywords.extend(args.query)
    if args.keywords_opt:
        keywords.extend(args.keywords_opt)

    flattened_skills: list[str] = []
    if args.skills:
        for s in args.skills:
            for item in s.split(","):
                clean = item.strip()
                if clean:
                    flattened_skills.append(clean)

    jobs = load_all_jobs(args.dir)

    filtered = filter_jobs(
        jobs=jobs,
        keywords=keywords if keywords else None,
        company=args.company,
        title=args.title,
        skills=flattened_skills if flattened_skills else None,
        min_salary=args.min_salary,
        max_salary=args.max_salary,
        remote=args.remote,
        role=args.role,
        source=args.source,
        job_id=args.id,
    )

    if args.asc:
        reverse = False
    else:
        reverse = args.sort in ("fetched_at", "salary_max", "salary_min")

    sorted_jobs = sort_jobs(filtered, sort_by=args.sort, reverse=reverse)

    if args.limit is not None and args.limit > 0:
        sorted_jobs = sorted_jobs[: args.limit]

    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)
    for job in sorted_jobs:
        ctx.add_result_path(job.file_path)

    out_list = [j.to_dict() for j in sorted_jobs] if args.json else None
    summary_fn = (lambda: print_terminal_view(sorted_jobs, detail=args.detail)) if args.summary else None
    exit_code = ctx.flush_outputs(summary_fn=summary_fn, json_data=out_list)
    if exit_code != 0:
        sys.exit(exit_code)


if __name__ == "__main__":
    main()

