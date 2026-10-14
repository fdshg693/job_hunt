"""求人データ永続化・Frontmatter生成パイプライン (storage.py).

.agents/rules/job-data-format.md 仕様に完全準拠した
求人Markdownおよび検索結果Markdown/JSONの生成・ファイル保存を提供します。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from scripts.common.cli import PROJECT_ROOT, to_relative_path
from scripts.common.normalizers import (
    detect_remote_type,
    extract_skills_from_text,
    format_salary_display,
    format_salary_text,
    parse_salary_range,
)


@dataclass
class JobData:
    """求人データモデル (job-data-format.md 仕様準拠)."""

    # 共通必須項目
    id: str
    source: str
    company: str
    title: str
    url: str
    fetched_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    # 共通任意項目
    salary_min: int | None = None
    salary_max: int | None = None
    salary_text: str = ""
    skills: list[str] = field(default_factory=list)
    job_roles: list[str] = field(default_factory=list)
    location: str = ""
    remote_type: str = "出社"
    tags: list[str] = field(default_factory=list)
    company_url: str = ""

    # 本文セクション
    description: str = ""
    must_skills: str = ""
    desired_skills: str = ""
    development_environment: str = ""
    rewarding: str = ""
    personality: str = ""
    conditions: str = ""
    raw_body: str = ""  # フリーフォーマットまたは未構造化本文

    # 拡張メタデータ
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    def to_frontmatter_dict(self) -> dict[str, Any]:
        """フロントマター用の辞書を生成する (None や空要素の不要キーを除外)."""
        fm: dict[str, Any] = {
            "id": self.id,
            "source": self.source.lower(),
            "company": self.company or "（企業名非公開）",
            "title": self.title or "（タイトルなし）",
            "url": self.url,
            "fetched_at": self.fetched_at,
        }

        if self.salary_min is not None:
            fm["salary_min"] = self.salary_min
        if self.salary_max is not None:
            fm["salary_max"] = self.salary_max
        if self.salary_text:
            fm["salary_text"] = self.salary_text
        if self.skills:
            fm["skills"] = self.skills
        if self.job_roles:
            fm["job_roles"] = self.job_roles
        if self.location:
            fm["location"] = self.location
        if self.remote_type:
            fm["remote_type"] = self.remote_type
        if self.tags:
            fm["tags"] = self.tags
        if self.company_url:
            fm["company_url"] = self.company_url

        if self.extra_metadata:
            for k, v in self.extra_metadata.items():
                if v is not None and k not in fm:
                    fm[k] = v

        return fm

    def to_markdown(self) -> str:
        """frontmatter 付き完全 Markdown 文字列を生成する."""
        fm_dict = self.to_frontmatter_dict()
        fm_yaml = yaml.dump(
            fm_dict,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ).strip()

        # 本文の組み立て
        if self.raw_body and not any([
            self.description,
            self.must_skills,
            self.desired_skills,
            self.development_environment,
            self.rewarding,
            self.personality,
            self.conditions,
        ]):
            body = self.raw_body.strip()
        else:
            body_parts: list[str] = [f"# {self.title or '求人情報'}", ""]

            if self.description:
                body_parts.extend(["## 概要・仕事内容", self.description.strip(), ""])
            if self.must_skills:
                body_parts.extend(["## 必須要件 (Must)", self.must_skills.strip(), ""])
            if self.desired_skills:
                body_parts.extend(["## 歓迎要件 (Desired)", self.desired_skills.strip(), ""])
            if self.development_environment:
                body_parts.extend(["## 開発環境", self.development_environment.strip(), ""])
            if self.rewarding:
                body_parts.extend(["## 仕事の魅力・特徴", self.rewarding.strip(), ""])
            if self.personality:
                body_parts.extend(["## 求める人物像", self.personality.strip(), ""])
            if self.conditions:
                body_parts.extend(["## 勤務地・就業条件・福利厚生", self.conditions.strip(), ""])

            body = "\n".join(body_parts).strip()

        return f"---\n{fm_yaml}\n---\n\n{body}\n"

    def to_dict(self) -> dict[str, Any]:
        """JSON 出力用の辞書表現."""
        d = self.to_frontmatter_dict()
        if self.description:
            d["description"] = self.description
        return d


def save_json(path: Path, data: Any) -> Path:
    """指定パスに JSON データを UTF-8 で保存する."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_job_markdown(
    job: JobData,
    output_dir: Path | None = None,
    force: bool = False,
) -> tuple[Path, bool]:
    """求人情報を Markdown ファイルとして保存する.

    戻り値: (ファイルパス, 新規保存/上書きが行われたか)
    """
    target_dir = output_dir or (PROJECT_ROOT / "data" / job.source.lower() / "jobs")
    target_dir.mkdir(parents=True, exist_ok=True)

    file_path = target_dir / f"{job.id}.md"

    if file_path.exists() and not force:
        return file_path, False

    md_content = job.to_markdown()
    file_path.write_text(md_content, encoding="utf-8")
    return file_path, True


def sanitize_filename(name: str) -> str:
    """ファイル名として安全な文字列に変換する."""
    s = re.sub(r'[\\/*?:"<>|]', "_", name)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s or "unnamed"


def save_search_result(
    source: str,
    keyword: str,
    jobs: list[dict[str, Any]],
    total_count: int | None = None,
    returned_count: int | None = None,
    output_dir: Path | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    """検索結果一覧を Markdown および JSON として保存する.

    戻り値: (md_path, json_path)
    """
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d-%H%M%S")
    kw_slug = sanitize_filename(keyword) if keyword else "all"

    target_dir = output_dir or (PROJECT_ROOT / "data" / source.lower() / "searches")
    target_dir.mkdir(parents=True, exist_ok=True)

    base_name = f"{date_str}_{kw_slug}"
    md_path = target_dir / f"{base_name}.md"
    json_path = target_dir / f"{base_name}.json"

    # Frontmatter
    fm: dict[str, Any] = {
        "source": source.lower(),
        "type": "searches",
        "keyword": keyword or "",
        "total_count": total_count if total_count is not None else len(jobs),
        "returned_count": returned_count if returned_count is not None else len(jobs),
        "matched_count": len(jobs),
        "fetched_at": now.isoformat(timespec="seconds"),
    }
    if metadata:
        fm.update({k: v for k, v in metadata.items() if v is not None})

    # Markdown 本文
    lines = [
        f"# {source.capitalize()} 求人検索結果: {keyword or '（全件）'}",
        "",
        f"- 取得日時: {now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 該当件数: {len(jobs)} 件 (全体: {total_count if total_count is not None else '不明'} 件)",
        "",
        "## 検索結果一覧",
        "",
        "| No | 企業名 | タイトル | 年収 | リモート | URL |",
        "|---|---|---|---|---|---|",
    ]

    for idx, j in enumerate(jobs, start=1):
        c_name = j.get("company", "").replace("|", "\\|")
        t_title = j.get("title", "").replace("|", "\\|")
        s_text = j.get("salary_text") or format_salary_display(j.get("salary_min"), j.get("salary_max"))
        r_type = j.get("remote_type", "")
        u_url = j.get("url", "")
        lines.append(f"| {idx} | {c_name} | {t_title} | {s_text} | {r_type} | [リンク]({u_url}) |")

    lines.append("")

    # 保存
    fm_yaml = yaml.dump(fm, allow_unicode=True, sort_keys=False).strip()
    md_content = f"---\n{fm_yaml}\n---\n\n" + "\n".join(lines)
    md_path.write_text(md_content, encoding="utf-8")

    # JSON 保存
    json_payload = {
        **fm,
        "jobs": jobs,
    }
    save_json(json_path, json_payload)

    return md_path, json_path
