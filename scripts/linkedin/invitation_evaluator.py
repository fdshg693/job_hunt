"""LinkedIn 受信招待（つながり申請）の価値評価モジュール.

ユーザーのプロファイル（profile/preferences.md, profile/skills.md, profile/internal/criteria.md）
と申請者情報（肩書き、添付メッセージ、プロフィール詳細等）を照合し、
属性分類（カテゴリ）、マッチ度スコア、推奨ランク（S/A/B/C）、推奨アクション、
および詳細コメントを算出します。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EvaluationResult:
    """つながり申請の評価結果."""

    category: str  # corporate_hr, recruiter_agent, engineer_tech, sales_business, other
    category_label: str  # 日本語表示名
    rank: str  # S, A, B, C
    rank_label: str  # 例: "S (高推奨)"
    score: int  # 0 - 100
    action: str  # 推奨アクション
    match_points: list[str] = field(default_factory=list)
    caution_points: list[str] = field(default_factory=list)
    summary_comment: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def categorize_invitation(headline: str, message: str, company: str = "", about: str = "") -> tuple[str, str]:
    """申請者の属性カテゴリを判定する."""
    full_text = f"{headline} {company} {message} {about}".lower()

    # エージェント・人材紹介系キーワード判定
    agent_keywords = [
        "consulting", "headhunter", "recruitment", "recruiting consultant",
        "recruiting partner", "managing partner", "executive search",
        "talent partner", "staffing", "人材紹介", "転職エージェント", "キャリアアドバイザー",
        "エージェント", "サーチファーム",
    ]
    # 企業人事・採用担当判定
    hr_keywords = [
        "talent acquisition", "recruiter", "people partner", "people ops",
        "hr", "採用担当", "採用", "人事", "人事部", "head of talent", "人事担当",
    ]
    # エンジニア・技術者判定
    tech_keywords = [
        "engineer", "developer", "architect", "cto", "vpoe", "tech lead",
        "engineering manager", "sre", "data scientist", "エンジニア", "開発",
        "アーキテクト", "テックリード", "プログラマー", "ai researcher",
    ]
    # 営業・ビジネス判定
    sales_keywords = [
        "account executive", "sales", "business development", "bizdev",
        "営業", "セールス", "マーケティング", "事業開発", "代表取締役",
    ]

    # 1. エージェント（HRより優先してチェック）
    if any(k in full_text for k in agent_keywords):
        return "recruiter_agent", "転職エージェント / ヘッドハンター"

    # 2. 企業人事・採用担当
    if any(k in full_text for k in hr_keywords):
        return "corporate_hr", "企業人事 / 採用担当"

    # 3. エンジニア・技術者
    if any(k in full_text for k in tech_keywords):
        return "engineer_tech", "エンジニア / 技術者"

    # 4. 営業・ビジネス
    if any(k in full_text for k in sales_keywords):
        return "sales_business", "営業 / ビジネス / 勧誘"

    return "other", "その他 / 未分類"


def evaluate_invitation(invitation: dict[str, Any]) -> EvaluationResult:
    """単一の招待データに対してユーザープロファイル照合・評価を行う."""
    name = invitation.get("name") or "申請者"
    headline = invitation.get("headline") or ""
    message = invitation.get("message") or ""
    profile_details = invitation.get("profileDetails") or {}
    company = profile_details.get("currentCompany") or ""
    about = profile_details.get("about") or ""
    experiences = profile_details.get("experiences") or []
    skills = profile_details.get("skills") or []
    mutual_count = invitation.get("mutualCount") or 0

    exp_text = " ".join([f"{e.get('role', '')} {e.get('company', '')}" for e in experiences])
    skills_text = " ".join(skills)
    full_text = f"{headline} {message} {company} {about} {exp_text} {skills_text}".strip()
    full_lower = full_text.lower()

    category, category_label = categorize_invitation(headline, message, company, about)

    score = 50
    match_points: list[str] = []
    caution_points: list[str] = []

    # --- ポジティブ要因判定 ---
    # 1. メッセージの有無
    if message:
        score += 10
        match_points.append("パーソナライズされた個別メッセージが添付されている")

    # 2. 技術スタック・領域（ユーザー希望: AI/LLM, Cloud, Go, Python, Kubernetes等）
    tech_matches = []
    if re.search(r"\b(ai|llm|agent|machine learning|機械学習|生成ai)\b", full_lower):
        tech_matches.append("AI / LLM / 機械学習")
    if re.search(r"\b(cloud|aws|gcp|azure|クラウド)\b", full_lower):
        tech_matches.append("Cloud (AWS/GCP/Azure)")
    if re.search(r"\b(go|golang|python|kubernetes|k8s|microservices|fastapi)\b", full_lower):
        tech_matches.append("モダンバックエンド (Go/Python/K8s)")
    if re.search(r"\b(software engineer|backend|バックエンド|フルサイクル)\b", full_lower):
        tech_matches.append("バックエンド / ソフトウェアエンジニア")

    if tech_matches:
        score += min(len(tech_matches) * 8, 20)
        match_points.append(f"希望技術領域に合致: {', '.join(tech_matches)}")

    # 3. 働き方（リモート/WFH/フルフレックス）
    remote_matches = []
    if re.search(r"\b(remote|wfh|work from home|fully flex|リモート|在宅|フルフレックス)\b", full_lower):
        remote_matches.append("リモート / WFH / フルフレックス")
    if remote_matches:
        score += 15
        match_points.append("希望の柔軟な働き方（リモート/WFH/フレックス）に言及あり")

    # 4. 企業タイプ・成長分野（スタートアップ, SaaS, Fintech等）
    biz_matches = []
    if re.search(r"\b(startup|スタートアップ|saas|fintech|engineering-first|自社プロダクト|自社開発)\b", full_lower):
        biz_matches.append("スタートアップ / SaaS / Fintech / 自社開発")
    if biz_matches:
        score += 10
        match_points.append("志向する企業フェーズ・文化（スタートアップ/自社プロダクト）に合致")

    # 5. グローバル / 英語環境（TOEIC 955点保持）
    if re.search(r"^[a-zA-Z0-9\s.,!?'\"-]{20,}$", message) or "global" in full_lower or "bilingual" in full_lower:
        score += 8
        match_points.append("英語メッセージまたはグローバル・外資系コンテキスト（英語力を活かせる可能性）")

    # 6. 技術リーダー層・同業エンジニアからの申請
    if category == "engineer_tech":
        if re.search(r"\b(cto|vpoe|tech lead|architect|lead)\b", full_lower):
            score += 15
            match_points.append("CTO / Tech Lead / アーキテクト等、ハイレベルな技術リーダーからの申請")
        else:
            score += 8
            match_points.append("同業エンジニアからのつながり申請（技術的ネットワーク拡大）")

    # 7. 共通コネクション
    if mutual_count > 0:
        score += 5
        match_points.append(f"共通のつながりが {mutual_count} 名存在")

    # --- ネガティブ・懸念点判定 ---
    # 1. SES / 客先常駐 / 受託
    if re.search(r"\b(ses|客先常駐|派遣|受託開発|アウトソーシング)\b", full_lower):
        score -= 30
        caution_points.append("SES / 客先常駐 / 受託開発の可能性あり（ユーザーの足切り基準に抵触）")

    # 2. 高頻度出社・完全出社
    if re.search(r"\b(出社必須|完全出社|毎日出社|on-site mandatory)\b", full_lower):
        score -= 25
        caution_points.append("出社必須の可能性あり（青梅線小作駅通勤負荷・リモート希望と不一致）")

    # 3. 営業・勧誘目的
    if category == "sales_business":
        if not re.search(r"(採用|エンジニア|recruit|hiring)", full_lower):
            score -= 20
            caution_points.append("営業・商材提案・セミナー勧誘の可能性が高い")

    # 4. メッセージなしのエージェント・人事
    if not message and category in ("recruiter_agent", "corporate_hr"):
        caution_points.append("添付メッセージなしの一斉つながり申請の可能性あり（具体案件は要確認）")

    # 5. 一般的な無言申請
    if not message and category == "other":
        score -= 10
        caution_points.append("メッセージおよび明確な共通項が少なく、申請意図が不明瞭")

    # スコア正規化 (0 - 100)
    score = max(0, min(100, score))

    # --- ランク判定 ---
    # S: 具体的優良スカウト（Cloud/AI/WFH等合致）または高スコア
    if (score >= 75 and message and ("wfh" in full_lower or "remote" in full_lower or tech_matches)) or score >= 85:
        rank = "S"
        rank_label = "S (高推奨)"
        action = "承認推奨（メッセージ返信・カジュアル面談を前向きに検討）"
    elif score >= 65:
        rank = "A"
        rank_label = "A (推奨)"
        action = "承認推奨（つながり保持・求人や技術情報収集に有用）"
    elif score >= 45:
        rank = "B"
        rank_label = "B (ニュートラル)"
        action = "承認可（ネットワーク拡大・状況に応じて情報交換）"
    else:
        rank = "C"
        rank_label = "C (低優先/注意)"
        action = "保留またはスキップ推奨（営業DM・不一致の可能性が高い）"

    # サマリコメントの生成
    summary_parts = []
    if category == "recruiter_agent":
        summary_parts.append("転職エージェント / ヘッドハンターからの申請。")
    elif category == "corporate_hr":
        summary_parts.append("企業人事・採用担当者からの申請。")
    elif category == "engineer_tech":
        summary_parts.append("エンジニア / 技術者からの申請。")
    elif category == "sales_business":
        summary_parts.append("営業・ビジネス職からの申請。")
    else:
        summary_parts.append("つながり申請。")

    if rank in ("S", "A"):
        if tech_matches or remote_matches:
            reasons = []
            if tech_matches:
                reasons.append("/".join(tech_matches))
            if remote_matches:
                reasons.append("リモート・WFH条件")
            summary_parts.append(f"ユーザーの希望条件（{'、'.join(reasons)}）と高く合致し、価値あるコンタクトです。")
        else:
            summary_parts.append("求人情報収集や専門的なキャリア機会の観点からつながる価値があります。")
    elif rank == "B":
        summary_parts.append("一般的なネットワーク拡大として承認して差し支えありません。")
    else:
        summary_parts.append("商材営業や条件不一致の懸念があるため、慎重な検討または保留を推奨します。")

    summary_comment = "".join(summary_parts)

    return EvaluationResult(
        category=category,
        category_label=category_label,
        rank=rank,
        rank_label=rank_label,
        score=score,
        action=action,
        match_points=match_points,
        caution_points=caution_points,
        summary_comment=summary_comment,
    )


def evaluate_invitations_batch(invitations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """複数の招待データに評価結果を付与して返す."""
    evaluated_items = []
    for inv in invitations:
        inv_copy = dict(inv)
        eval_res = evaluate_invitation(inv)
        inv_copy["evaluation"] = eval_res.to_dict()
        evaluated_items.append(inv_copy)
    return evaluated_items
