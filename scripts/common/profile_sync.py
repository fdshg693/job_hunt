"""ユーザー情報のSSOT（vault/profile/）共通パーサーおよびプロファイル安全ガードモジュール.

各媒体スクリプト（Levtech Direct, Bizreach, Forkwell, Green, LinkedIn, Youtrust 等）向けに:
1. vault/profile/ (resume.md, skills.md, preferences.md, strategy.md) を構造化データとして抽出するパーサー
2. 更新前のプロファイルデータをタイムスタンプ付きで自動保存するバックアップ機構
3. --dry-run 時に変更前後の差異を人間可読に表示するUnified Diff/差分プレビュー機構
を提供します。
"""

from __future__ import annotations

import difflib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.common.cli import PROJECT_ROOT, to_relative_path
from scripts.common.paths import (
    PREFERENCES_PATH,
    PROFILE_SITES_DIR,
    RESUME_PATH,
    SKILLS_PATH,
    track_dir,
)
from scripts.vault import frontmatter


@dataclass
class ProjectExperience:
    """職務経歴中の1プロジェクト."""

    name: str
    period_str: str = ""
    start_year: str | None = None
    start_month: str | None = None
    end_year: str | None = None
    end_month: str | None = None
    is_current: bool = False
    phases: str = ""
    technologies: str = ""
    description: str = ""
    bullets: list[str] = field(default_factory=list)


@dataclass
class CompanyExperience:
    """職歴中の1企業."""

    company_name: str
    period_str: str = ""
    start_year: str | None = None
    start_month: str | None = None
    end_year: str | None = None
    end_month: str | None = None
    is_current: bool = False
    employment_type: str = "正社員"
    role: str = ""
    projects: list[ProjectExperience] = field(default_factory=list)


@dataclass
class EducationRecord:
    """学歴レコード."""

    school_name: str
    faculty: str = ""
    department: str = ""
    graduation_date: str = ""
    start_year: str | None = None
    start_month: str | None = None
    end_year: str | None = None
    end_month: str | None = None
    degree: str = "学士"
    raw_text: str = ""


@dataclass
class LanguageSkill:
    """言語スキル."""

    name: str
    years: float = 0.0
    level: str = ""


@dataclass
class VaultProfile:
    """vault/profile/ から読み込んだSSOTプロフィールデータモデル."""

    # 基本情報 (resume.md)
    name: str = ""
    name_en: str = ""
    kana_last: str = ""
    kana_first: str = ""
    birth_date: str = ""
    gender: str = ""
    location: str = ""
    email: str = ""
    phone: str = ""
    current_company: str = ""
    current_role: str = ""
    current_annual_income: int | None = None
    english_skill: str = ""
    toeic_score: int | None = None
    certifications: list[str] = field(default_factory=list)
    primary_skills: list[str] = field(default_factory=list)
    links: dict[str, str] = field(default_factory=dict)

    # 本文テキスト
    summary: str = ""
    companies: list[CompanyExperience] = field(default_factory=list)
    education: list[EducationRecord] = field(default_factory=list)
    extracurricular: str = ""

    # スキル情報 (skills.md)
    languages: list[LanguageSkill] = field(default_factory=list)
    frameworks_libraries: list[str] = field(default_factory=list)
    infrastructure_cloud: list[str] = field(default_factory=list)
    ai_llm_tools: list[str] = field(default_factory=list)
    skills_body: str = ""

    # 希望条件 (preferences.md)
    target_roles: list[str] = field(default_factory=list)
    tech_interests: list[str] = field(default_factory=list)
    domain_preference: list[str] = field(default_factory=list)
    disqualifiers: list[str] = field(default_factory=list)
    preferences_body: str = ""

    # 国内戦略 (tracks/domestic/strategy.md)
    target_annual_income_min: int | None = None
    target_annual_income_ideal: int | None = None
    remote_preference: str = ""
    work_style_raw: dict[str, Any] = field(default_factory=dict)

    # 生のフロントマター・辞書
    raw_resume_fm: dict[str, Any] = field(default_factory=dict)
    raw_skills_fm: dict[str, Any] = field(default_factory=dict)
    raw_preferences_fm: dict[str, Any] = field(default_factory=dict)
    raw_strategy_fm: dict[str, Any] = field(default_factory=dict)

    def get_name_parts(self) -> tuple[str, str]:
        """氏名を (姓, 名) に分割して返す."""
        parts = self.name.split()
        if len(parts) >= 2:
            return parts[0], " ".join(parts[1:])
        return self.name, ""

    def get_kana_parts(self) -> tuple[str, str]:
        """ふりがなを (セイ, メイ) に分割して返す."""
        if self.kana_last or self.kana_first:
            return self.kana_last, self.kana_first
        # 基本情報本文からフォールバック
        return "", ""

    def get_latest_education(self) -> EducationRecord | None:
        """最終学歴レコードを返す."""
        if not self.education:
            return None
        # 卒業年月が最新のものを探す（通常末尾）
        return self.education[-1]

    def generate_resume_summary(self) -> str:
        """各媒体向けフリーフォーマット職務要約テキストを生成する."""
        if self.summary:
            return self.summary.strip()
        return (
            "Webアプリケーションのフルスタック開発および生成AI・LLMを活用した機能開発・PoC検証・業務効率化基盤構築に従事。\n"
            "フロントエンド・バックエンドからインフラ（Azure/IaC/Docker/K8s/AKS）まで一貫対応できるフルスタック力と、"
            "最新のAgentic AI・自動化技術を開発プロセスに組み込む生産性向上力を強みとしています。"
        )

    def generate_combined_resume_text(self) -> str:
        """職務要約、活かせる技術、職歴要約をまとめた統合職務経歴書テキストを生成する."""
        parts: list[str] = []

        # 1. 職務要約
        parts.append("【職務要約】")
        parts.append(self.generate_resume_summary())

        # 2. 保有スキル・活かせる技術スタック
        parts.append("\n【保有スキル・活かせる技術スタック】")
        lang_names = [f"{lang.name} ({lang.years}年)" if lang.years else lang.name for lang in self.languages]
        parts.append(f"・主要言語: {', '.join(lang_names) if lang_names else 'Python, TypeScript, C#, Java, Go, SQL'}")
        if self.frameworks_libraries:
            parts.append(f"・フレームワーク/ライブラリ: {', '.join(self.frameworks_libraries)}")
        if self.infrastructure_cloud:
            parts.append(f"・クラウド/インフラ/CI・CD: {', '.join(self.infrastructure_cloud)}")
        if self.ai_llm_tools:
            parts.append(f"・AI/LLM/エージェント技術: {', '.join(self.ai_llm_tools)}")

        # 3. 職務経歴詳細
        parts.append("\n【職務経歴詳細】")
        for _idx, comp in enumerate(self.companies, 1):
            parts.append(f"\n■ {comp.company_name} ({comp.period_str})")
            parts.append(f"  雇用形態: {comp.employment_type} / 役職: {comp.role}")
            for p in comp.projects:
                parts.append(f"  ● プロジェクト: {p.name}")
                if p.period_str:
                    parts.append(f"    期間: {p.period_str}")
                if p.technologies:
                    parts.append(f"    使用技術: {p.technologies}")
                if p.phases:
                    parts.append(f"    担当フェーズ: {p.phases}")
                if p.bullets:
                    for b in p.bullets:
                        parts.append(f"    ・{b}")
                elif p.description:
                    for line in p.description.splitlines():
                        parts.append(f"    {line}")

        # 4. 学歴・語学・資格
        parts.append("\n【学歴・語学・資格】")
        if self.education:
            latest = self.education[-1]
            edu_str = f"{latest.school_name} {latest.faculty} {latest.department}"
            if latest.graduation_date:
                edu_str += f" ({latest.graduation_date} 卒業)"
            parts.append(f"・学歴: {edu_str}")
        if self.english_skill:
            parts.append(f"・語学: {self.english_skill}")
        elif self.toeic_score:
            parts.append(f"・語学: TOEIC {self.toeic_score}点")
        if self.certifications:
            parts.append(f"・資格: {', '.join(self.certifications)}")

        return "\n".join(parts) + "\n"

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換してシリアライズ可能にする."""
        return {
            "name": self.name,
            "name_en": self.name_en,
            "kana_last": self.kana_last,
            "kana_first": self.kana_first,
            "birth_date": self.birth_date,
            "gender": self.gender,
            "location": self.location,
            "email": self.email,
            "phone": self.phone,
            "current_company": self.current_company,
            "current_role": self.current_role,
            "current_annual_income": self.current_annual_income,
            "english_skill": self.english_skill,
            "toeic_score": self.toeic_score,
            "certifications": self.certifications,
            "primary_skills": self.primary_skills,
            "links": self.links,
            "summary": self.summary,
            "companies": [
                {
                    "company_name": c.company_name,
                    "period_str": c.period_str,
                    "start_year": c.start_year,
                    "start_month": c.start_month,
                    "end_year": c.end_year,
                    "end_month": c.end_month,
                    "is_current": c.is_current,
                    "employment_type": c.employment_type,
                    "role": c.role,
                    "projects": [
                        {
                            "name": p.name,
                            "period_str": p.period_str,
                            "start_year": p.start_year,
                            "start_month": p.start_month,
                            "end_year": p.end_year,
                            "end_month": p.end_month,
                            "is_current": p.is_current,
                            "phases": p.phases,
                            "technologies": p.technologies,
                            "description": p.description,
                            "bullets": p.bullets,
                        }
                        for p in c.projects
                    ],
                }
                for c in self.companies
            ],
            "education": [
                {
                    "school_name": e.school_name,
                    "faculty": e.faculty,
                    "department": e.department,
                    "graduation_date": e.graduation_date,
                    "start_year": e.start_year,
                    "start_month": e.start_month,
                    "end_year": e.end_year,
                    "end_month": e.end_month,
                    "degree": e.degree,
                }
                for e in self.education
            ],
            "languages": [
                {"name": lang.name, "years": lang.years, "level": lang.level}
                for lang in self.languages
            ],
            "frameworks_libraries": self.frameworks_libraries,
            "infrastructure_cloud": self.infrastructure_cloud,
            "ai_llm_tools": self.ai_llm_tools,
            "target_roles": self.target_roles,
            "tech_interests": self.tech_interests,
            "domain_preference": self.domain_preference,
            "disqualifiers": self.disqualifiers,
            "target_annual_income_min": self.target_annual_income_min,
            "target_annual_income_ideal": self.target_annual_income_ideal,
            "remote_preference": self.remote_preference,
        }


# ==============================================================================
# パーサー実装
# ==============================================================================


def _parse_period_string(period_str: str) -> tuple[str | None, str | None, str | None, str | None, bool]:
    """「2025年8月〜在職中」等の期間文字列から (start_year, start_month, end_year, end_month, is_current) を抽出する."""
    is_current = "在職中" in period_str or "現在" in period_str
    # 年月パターン検索 (例: 2025年8月, 2024/04, 2026-07)
    dates = re.findall(r"(\d{4})[年/\-](\d{1,2})", period_str)
    start_year = dates[0][0] if len(dates) >= 1 else None
    start_month = str(int(dates[0][1])) if len(dates) >= 1 else None
    end_year = None
    end_month = None
    if not is_current and len(dates) >= 2:
        end_year = dates[1][0]
        end_month = str(int(dates[1][1]))
    return start_year, start_month, end_year, end_month, is_current


def _parse_resume_body(body: str) -> tuple[str, list[CompanyExperience], list[EducationRecord], tuple[str, str]]:
    """resume.md の本文 Markdown をセクションごとに解析する."""
    lines = body.splitlines()

    # 1. ふりがな解析（基本情報セクションから）
    kana_last = ""
    kana_first = ""
    kana_match = re.search(r"氏名\*\*:\s*.*?[（\(]([ァ-ヶー\s]+)[）\)]", body)
    if kana_match:
        kana_full = kana_match.group(1).strip().split()
        if len(kana_full) >= 2:
            kana_last, kana_first = kana_full[0], " ".join(kana_full[1:])
        elif kana_full:
            kana_last = kana_full[0]

    # 2. 職務要約セクション
    summary_lines: list[str] = []
    in_summary = False
    for line in lines:
        if re.match(r"^##\s+職務要約", line):
            in_summary = True
            continue
        if in_summary:
            if line.startswith("## ") or line.startswith("---"):
                break
            summary_lines.append(line)
    summary = "\n".join(summary_lines).strip()

    # 3. 職務経歴セクション
    companies: list[CompanyExperience] = []
    current_company: CompanyExperience | None = None
    current_project: ProjectExperience | None = None

    in_work_history = False
    for line in lines:
        if re.match(r"^##\s+職務経歴", line):
            in_work_history = True
            continue
        if in_work_history and line.startswith("## ") and not line.startswith("### "):
            # 次の大見出し（学歴等）に来たら終了
            break
        if not in_work_history:
            continue

        # 会社ヘッダー: ### 1. 株式会社ヘッドウォータース（2025年8月〜在職中）
        comp_m = re.match(r"^###\s+\d*\.?\s*([^\(（]+)[（\(]([^\)）]+)[）\)]", line)
        if comp_m:
            c_name = comp_m.group(1).strip()
            c_period = comp_m.group(2).strip()
            sy, sm, ey, em, cur = _parse_period_string(c_period)
            current_company = CompanyExperience(
                company_name=c_name,
                period_str=c_period,
                start_year=sy,
                start_month=sm,
                end_year=ey,
                end_month=em,
                is_current=cur,
            )
            companies.append(current_company)
            current_project = None
            continue

        if current_company is None:
            continue

        # 会社属性
        if line.startswith("- **雇用形態**:"):
            current_company.employment_type = line.replace("- **雇用形態**:", "").strip()
            continue
        if line.startswith("- **役職/役割**:"):
            current_company.role = line.replace("- **役職/役割**:", "").strip()
            continue

        # プロジェクトヘッダー: #### プロジェクト1: 業務効率化ワークフロー...
        proj_m = re.match(r"^####\s+(?:プロジェクト\d*:?\s*)?(.+)", line)
        if proj_m:
            p_name = proj_m.group(1).strip()
            current_project = ProjectExperience(name=p_name)
            current_company.projects.append(current_project)
            continue

        if current_project is None:
            continue

        # プロジェクト属性
        if line.startswith("- **期間**:"):
            p_period = line.replace("- **期間**:", "").strip()
            current_project.period_str = p_period
            sy, sm, ey, em, cur = _parse_period_string(p_period)
            current_project.start_year = sy
            current_project.start_month = sm
            current_project.end_year = ey
            current_project.end_month = em
            current_project.is_current = cur
            continue
        if line.startswith("- **担当フェーズ**:"):
            current_project.phases = line.replace("- **担当フェーズ**:", "").strip()
            continue
        if line.startswith("- **使用技術**:"):
            current_project.technologies = line.replace("- **使用技術**:", "").strip()
            continue
        if line.startswith("  - ") or line.startswith("    - "):
            bullet_clean = re.sub(r"^\s*-\s*", "", line).strip()
            if bullet_clean and not bullet_clean.startswith("**業務内容"):
                current_project.bullets.append(bullet_clean)
                current_project.description += bullet_clean + "\n"

    # 4. 学歴セクション
    education: list[EducationRecord] = []
    in_education = False
    for line in lines:
        if re.match(r"^##\s+学歴", line):
            in_education = True
            continue
        if in_education and line.startswith("## "):
            break
        if not in_education:
            continue

        # 学歴行例: - **2024年3月 東京大学 文学部 西洋古典学専修 卒業**
        # または: - 2016年4月 東京大学 入学（教養学部 前期課程、3年在籍）
        line_clean = line.strip().strip("*").strip("-").strip()
        if not line_clean:
            continue

        m_edu = re.search(r"(\d{4})年(\d{1,2})月\s+([^\s]+)\s+(.+)", line_clean)
        if m_edu:
            year, month, school, rest = m_edu.groups()
            fac = ""
            dept = ""
            # 学部・専修の分解
            fac_m = re.search(r"([^\s]+学部)\s*([^\s]+)?", rest)
            if fac_m:
                fac = fac_m.group(1).strip()
                dept = (fac_m.group(2) or "").replace("卒業", "").strip()

            grad_str = f"{year}年{month}月"
            is_grad = "卒業" in line_clean
            rec = EducationRecord(
                school_name=school,
                faculty=fac,
                department=dept,
                graduation_date=grad_str if is_grad else "",
                end_year=year if is_grad else None,
                end_month=month if is_grad else None,
                raw_text=line_clean,
            )
            education.append(rec)

    return summary, companies, education, (kana_last, kana_first)


def load_vault_profile(
    vault_root: Path | None = None,
    include_strategy: bool = True,
) -> VaultProfile:
    """vault/profile/ および国内track戦略ファイルをパースして VaultProfile オブジェクトを返す."""
    if vault_root is None:
        resume_file = RESUME_PATH
        skills_file = SKILLS_PATH
        pref_file = PREFERENCES_PATH
        strategy_file = track_dir("domestic") / "strategy.md"
    else:
        resume_file = vault_root / "vault" / "profile" / "resume.md"
        skills_file = vault_root / "vault" / "profile" / "skills.md"
        pref_file = vault_root / "vault" / "profile" / "preferences.md"
        strategy_file = vault_root / "vault" / "tracks" / "domestic" / "strategy.md"

    if not resume_file.exists():
        raise FileNotFoundError(f"職務経歴書マスターが見つかりません: {resume_file}")

    profile = VaultProfile()

    # 1. resume.md のパース
    res_doc = frontmatter.read(resume_file)
    rfm = res_doc.data
    profile.raw_resume_fm = rfm
    profile.name = str(rfm.get("name", ""))
    profile.name_en = str(rfm.get("name_en", ""))
    profile.birth_date = str(rfm.get("birth_date", ""))
    profile.gender = str(rfm.get("gender", ""))
    profile.location = str(rfm.get("location", ""))
    profile.email = str(rfm.get("email", ""))
    profile.phone = str(rfm.get("phone", ""))
    profile.current_company = str(rfm.get("current_company", ""))
    profile.current_role = str(rfm.get("current_role", ""))
    profile.english_skill = str(rfm.get("english_skill", ""))

    if "current_annual_income" in rfm:
        try:
            profile.current_annual_income = int(rfm["current_annual_income"])
        except (ValueError, TypeError):
            pass

    if "toeic_score" in rfm:
        try:
            profile.toeic_score = int(rfm["toeic_score"])
        except (ValueError, TypeError):
            pass

    certs = rfm.get("certifications", [])
    if isinstance(certs, list):
        profile.certifications = [str(c) for c in certs]
    elif isinstance(certs, str):
        profile.certifications = [certs]

    prim_skills = rfm.get("primary_skills", [])
    if isinstance(prim_skills, list):
        profile.primary_skills = [str(s) for s in prim_skills]

    links = rfm.get("links", {})
    if isinstance(links, dict):
        profile.links = {str(k): str(v) for k, v in links.items()}

    summary, companies, education, kana_tuple = _parse_resume_body(res_doc.body)
    profile.summary = summary
    profile.companies = companies
    profile.education = education
    profile.kana_last, profile.kana_first = kana_tuple

    # 2. skills.md のパース
    if skills_file.exists():
        sk_doc = frontmatter.read(skills_file)
        sfm = sk_doc.data
        profile.raw_skills_fm = sfm
        profile.skills_body = sk_doc.body
        cats = sfm.get("skill_categories", {})
        if isinstance(cats, dict):
            langs = cats.get("languages", [])
            if isinstance(langs, list):
                for lang_item in langs:
                    if isinstance(lang_item, dict):
                        profile.languages.append(
                            LanguageSkill(
                                name=str(lang_item.get("name", "")),
                                years=float(lang_item.get("years", 0.0)),
                                level=str(lang_item.get("level", "")),
                            )
                        )
            fw = cats.get("frameworks_libraries", [])
            if isinstance(fw, list):
                profile.frameworks_libraries = [str(x) for x in fw]
            infra = cats.get("infrastructure_cloud", [])
            if isinstance(infra, list):
                profile.infrastructure_cloud = [str(x) for x in infra]
            ai_tools = cats.get("ai_llm_tools", [])
            if isinstance(ai_tools, list):
                profile.ai_llm_tools = [str(x) for x in ai_tools]

    # 3. preferences.md のパース
    if pref_file.exists():
        pf_doc = frontmatter.read(pref_file)
        pfm = pf_doc.data
        profile.raw_preferences_fm = pfm
        profile.preferences_body = pf_doc.body
        for field_name in ("target_roles", "tech_interests", "domain_preference", "disqualifiers"):
            vals = pfm.get(field_name, [])
            if isinstance(vals, list):
                setattr(profile, field_name, [str(v) for v in vals])

    # 4. strategy.md (国内track希望条件) のパース
    if include_strategy and strategy_file.exists():
        st_doc = frontmatter.read(strategy_file)
        stfm = st_doc.data
        profile.raw_strategy_fm = stfm
        if "target_annual_income_min" in stfm:
            try:
                profile.target_annual_income_min = int(stfm["target_annual_income_min"])
            except (ValueError, TypeError):
                pass
        if "target_annual_income_ideal" in stfm:
            try:
                profile.target_annual_income_ideal = int(stfm["target_annual_income_ideal"])
            except (ValueError, TypeError):
                pass
        ws = stfm.get("work_style", {})
        if isinstance(ws, dict):
            profile.work_style_raw = ws
            profile.remote_preference = str(ws.get("remote_preference", ""))

    return profile


def load_site_data(
    site: str,
    vault_root: Path | None = None,
) -> tuple[dict[str, Any], str]:
    """vault/profile/sites/{site}.md をパースして (フロントマター辞書, 本文テキスト) を返す."""
    if vault_root is None:
        target_path = PROFILE_SITES_DIR / f"{site}.md"
    else:
        target_path = vault_root / "vault" / "profile" / "sites" / f"{site}.md"

    if not target_path.exists():
        raise FileNotFoundError(f"媒体プロフィールファイルが見つかりません: {target_path}")

    doc = frontmatter.read(target_path)
    body = doc.body.strip()
    return doc.data, body


def load_site_text(
    site: str,
    vault_root: Path | None = None,
) -> str:
    """vault/profile/sites/{site}.md の本文テキストを返す. ファイルまたは本文が空の場合はエラー."""
    _, body = load_site_data(site, vault_root=vault_root)
    if not body:
        raise ValueError(f"媒体プロフィールファイル本文が空です: {site}")
    return body


# ==============================================================================
# 安全ガード（自動バックアップ・差分プレビュー）
# ==============================================================================


def save_profile_backup(
    site: str,
    section: str,
    data: dict[str, Any] | str,
    backup_dir: Path | None = None,
    timestamp: datetime | None = None,
    silent: bool = False,
) -> Path:
    """更新前のプロファイルデータをタイムスタンプ付きJSONで保存する.

    保存先規約: backups/{site}/YYYY-MM-DD_HHMMSS_profile_{section}.json
    backup_dir が明示された場合はそちらを優先（各媒体の既存backupフォルダとの互換用）。
    """
    now = timestamp or datetime.now()
    ts = now.strftime("%Y-%m-%d_%H%M%S")

    if backup_dir is not None:
        target_dir = Path(backup_dir)
        filename = f"{section}_{ts}.json" if not section.startswith("backup") else f"{ts}.json"
    else:
        target_dir = PROJECT_ROOT / "backups" / site
        filename = f"{ts}_profile_{section}.json"

    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename

    if isinstance(data, (dict, list)):
        content = json.dumps(data, ensure_ascii=False, indent=2)
    else:
        content = str(data)

    target_path.write_text(content, encoding="utf-8")

    if not silent:
        print(
            f"[安全ガード] 変更前バックアップを保存しました: {to_relative_path(target_path)}",
            file=sys.stderr,
        )

    return target_path


def print_profile_diff(
    before: dict[str, Any] | str,
    after: dict[str, Any] | str,
    title: str = "プロフィール変更差分",
    from_label: str = "現在の設定 (Current)",
    to_label: str = "更新後の設定 (Updated)",
    stream: Any = sys.stderr,
) -> bool:
    """変更前後の差分を Unified Diff でプレビュー出力する.

    Returns:
        bool: 差分が存在した場合は True、完全一致（差分なし）の場合は False。
    """
    if isinstance(before, (dict, list)):
        before_text = json.dumps(before, ensure_ascii=False, indent=2)
    else:
        before_text = str(before).strip()

    if isinstance(after, (dict, list)):
        after_text = json.dumps(after, ensure_ascii=False, indent=2)
    else:
        after_text = str(after).strip()

    diff_lines = list(
        difflib.unified_diff(
            before_text.splitlines(keepends=True),
            after_text.splitlines(keepends=True),
            fromfile=from_label,
            tofile=to_label,
            lineterm="",
        )
    )

    if not diff_lines:
        print(f"\n[{title}] 登録内容に変更はありません（差分なし）。\n", file=stream)
        return False

    print(f"\n--- {title} (Unified Diff) ---", file=stream)
    for line in diff_lines:
        line_clean = line.rstrip("\r\n")
        if line_clean.startswith("+++") or line_clean.startswith("---"):
            print(f"\033[1m{line_clean}\033[0m", file=stream)
        elif line_clean.startswith("+"):
            print(f"\033[32m{line_clean}\033[0m", file=stream)
        elif line_clean.startswith("-"):
            print(f"\033[31m{line_clean}\033[0m", file=stream)
        elif line_clean.startswith("@@"):
            print(f"\033[36m{line_clean}\033[0m", file=stream)
        else:
            print(line_clean, file=stream)
    print("-----------------------------------------\n", file=stream)
    return True
