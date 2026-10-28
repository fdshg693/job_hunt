"""求人共通データモデル (scripts.common.models.job).

JobPosting Pydantic v2 モデルを提供し、既存の JobData (dataclass) との
相互運用性および下位互換性を担保します。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from scripts.common.storage import JobData


class JobPosting(BaseModel):
    """求人データの Pydantic v2 モデル (job-data-format.md 仕様準拠)."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    # 共通必須項目
    id: str
    source: str
    company: str = ""
    title: str = ""
    url: str = ""
    fetched_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    # 共通任意項目
    salary_min: int | None = None
    salary_max: int | None = None
    salary_text: str = ""
    skills: list[str] = Field(default_factory=list)
    job_roles: list[str] = Field(default_factory=list)
    location: str = ""
    remote_type: str = "出社"
    tags: list[str] = Field(default_factory=list)
    company_url: str = ""

    # 本文セクション
    description: str = ""
    must_skills: str = ""
    desired_skills: str = ""
    development_environment: str = ""
    rewarding: str = ""
    personality: str = ""
    conditions: str = ""
    raw_body: str = ""

    # 拡張メタデータ
    extra_metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_job_data(cls, job_data: JobData) -> JobPosting:
        """既存の JobData dataclass から JobPosting を生成する."""
        return cls(
            id=job_data.id,
            source=job_data.source,
            company=job_data.company,
            title=job_data.title,
            url=job_data.url,
            fetched_at=job_data.fetched_at,
            salary_min=job_data.salary_min,
            salary_max=job_data.salary_max,
            salary_text=job_data.salary_text,
            skills=list(job_data.skills),
            job_roles=list(job_data.job_roles),
            location=job_data.location,
            remote_type=job_data.remote_type,
            tags=list(job_data.tags),
            company_url=job_data.company_url,
            description=job_data.description,
            must_skills=job_data.must_skills,
            desired_skills=job_data.desired_skills,
            development_environment=job_data.development_environment,
            rewarding=job_data.rewarding,
            personality=job_data.personality,
            conditions=job_data.conditions,
            raw_body=job_data.raw_body,
            extra_metadata=dict(job_data.extra_metadata),
        )

    def to_job_data(self) -> JobData:
        """JobData dataclass へ変換する."""
        return JobData(
            id=self.id,
            source=self.source,
            company=self.company,
            title=self.title,
            url=self.url,
            fetched_at=self.fetched_at,
            salary_min=self.salary_min,
            salary_max=self.salary_max,
            salary_text=self.salary_text,
            skills=list(self.skills),
            job_roles=list(self.job_roles),
            location=self.location,
            remote_type=self.remote_type,
            tags=list(self.tags),
            company_url=self.company_url,
            description=self.description,
            must_skills=self.must_skills,
            desired_skills=self.desired_skills,
            development_environment=self.development_environment,
            rewarding=self.rewarding,
            personality=self.personality,
            conditions=self.conditions,
            raw_body=self.raw_body,
            extra_metadata=dict(self.extra_metadata),
        )

    def to_frontmatter_dict(self) -> dict[str, Any]:
        """フロントマター用の辞書を生成する (JobData.to_frontmatter_dict 互換)."""
        return self.to_job_data().to_frontmatter_dict()

    def to_markdown(self) -> str:
        """frontmatter 付き完全 Markdown 文字列を生成する (JobData.to_markdown 互換)."""
        return self.to_job_data().to_markdown()

    def to_dict(self) -> dict[str, Any]:
        """JSON 出力用の辞書表現 (JobData.to_dict 互換)."""
        return self.to_job_data().to_dict()
