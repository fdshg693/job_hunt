"""LinkedIn の Other メッセージを機械的に事前仕分けし参考区分を出す CLI.

LinkedIn メッセージ評価・仕分け支援モジュール.

【重要・運用原則】
本スクリプトの出力（属性判定、スコア、推奨区分）は、送信者名やスニペットのキーワードに基づく
粗削りな「機械的事前フィルタ（参考情報）」に過ぎません。
本スクリプトのスコアや判定のみを根拠にして、最終的な仕分け（返信・保存・削除/アーカイブ）を
決定することは絶対に禁止です。

就活サポートにおける評価の原則:
1. 機械的フィルタはあくまで参考とし、最終的にはユーザーのプロファイル（vault/profile/preferences.md,
   criteria.md 等）と照らし合わせ、文脈・実態を総合的に判断すること。
2. 事前フィルタ（古い日付、明らかな営業アンケート等）を理由にそれ以上の詳細調査（スレッド本文開封や
   企業・エージェント調査）を行わない場合は、その旨と理由を必ず記録・明記すること。
3. 数十件程度の規模のメッセージを安易に完全機械化して思考停止しないこと。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from scripts.common.cli import build_epilog

MESSAGES_OTHER_PATH = WORKSPACE_ROOT / "data" / "linkedin" / "messages" / "messages_other.json"


@dataclass
class MessageEvaluation:
    """メッセージ評価結果."""

    index: int
    name: str
    date: str
    snippet: str
    category: str  # corporate_hr, recruiter_agent, engineer_tech, sales_business, other
    category_label: str
    action: str  # A (返信検討), B (保存のみ), C (削除/アーカイブ)
    action_label: str
    score: int
    is_old: bool  # 2025年以前か
    match_points: list[str] = field(default_factory=list)
    caution_points: list[str] = field(default_factory=list)
    summary_comment: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def categorize_sender_and_message(name: str, snippet: str) -> tuple[str, str]:
    """送信者名とスニペットから属性カテゴリを判定."""
    text = f"{name} {snippet}".lower()

    # 営業・ツール・アンケート勧誘
    if re.search(r"\b(consultants on ai tool adoption|consulting|survey|アンケート|協業|営業|freelance)\b", text):
        if "recruiting consultants on ai tool adoption" in text:
            return "sales_business", "営業 / アンケート / ツール導入勧誘"

    # 企業人事・ダイレクトスカウト
    if any(k in text for k in ["datadog", "secai marche", "geniee", "astemo", "cypremos", "片岡"]):
        return "corporate_hr", "企業直接採用 / 人事・役員"

    # 人材紹介エージェント・ヘッドハンター
    agent_keywords = [
        "ランスタッド", "randstad", "vcからの案件", "ヘッドハンター", "エージェント",
        "recruiter", "scout", "紹介", "求人", "キャリア機会", "ポジションのご紹介",
        "opportunity", "consultant position", "hiring", "follow up"
    ]
    if any(k in text for k in agent_keywords) or any(k in name.lower() for k in ["chavan", "irawan", "rana", "joseph", "shimizu"]):
        return "recruiter_agent", "転職エージェント / ヘッドハンター"

    # エンジニア・技術リーダー
    if any(k in text for k in ["cto", "vpoe", "tech lead", "architect"]):
        return "engineer_tech", "エンジニア / 技術リーダー"

    return "other", "その他 / 未分類"


def evaluate_message(msg: dict[str, Any]) -> MessageEvaluation:
    """メッセージ1件の評価と推奨アクションを決定."""
    index = msg.get("index", 0)
    name = msg.get("name", "Unknown")
    date = msg.get("date", "")
    snippet = msg.get("snippet", "")

    category, category_label = categorize_sender_and_message(name, snippet)

    is_old = "2025" in date or "2024" in date or "2023" in date

    score = 50
    match_points: list[str] = []
    caution_points: list[str] = []

    text_lower = f"{name} {snippet}".lower()

    # --- ポジティブ要因判定 ---
    # 1. 企業直接スカウト（高評価）
    if category == "corporate_hr":
        score += 25
        match_points.append("企業直接採用・人事からの連絡（機会価値が高い）")

    # 2. 技術領域（AI/LLM, Cloud, Go, Python, Backend）
    if re.search(r"\b(ai|agi|llm|生成ai|産業ai)\b", text_lower):
        score += 15
        match_points.append("AI / LLM / AGI 関連")
    if re.search(r"\b(backend|バックエンド|fullstack|フルスタック|software engineer)\b", text_lower):
        score += 10
        match_points.append("バックエンド / ソフトウェアエンジニア領域")
    if re.search(r"\b(go|python|fastapi|k8s|kubernetes)\b", text_lower):
        score += 10
        match_points.append("希望言語・技術スタック（Go/Python）")

    # 3. リモート・柔軟な働き方
    if re.search(r"\b(リモート|フルリモート|remote|fully-remote|フレックス)\b", text_lower):
        score += 15
        match_points.append("フルリモート / フレックス言及")

    # 4. 年収提示
    high_salary_match = re.search(r"(\d{2,4})万|(\d{1,2})m\s*jpy", text_lower)
    if high_salary_match:
        if "25m" in text_lower or "1500万" in text_lower or "1200万" in text_lower:
            score += 20
            match_points.append("高年収提示（1200万〜2500万円水準）")
        elif "1000万" in text_lower or "11m" in text_lower or "11.5m" in text_lower:
            score += 15
            match_points.append("希望年収帯提示（1000万〜1150万円水準）")
        elif "800万" in text_lower:
            score += 10
            match_points.append("希望年収帯（〜800万円水準）")

    # 5. グローバル / 英語環境
    if "bilingual" in text_lower or "global" in text_lower or "海外展開" in text_lower:
        score += 10
        match_points.append("グローバル / 英語環境（英語力を活かせる）")

    # 6. CTO / VPoE / リードポジション
    if re.search(r"\b(cto|vpoe|lead|リード)\b", text_lower):
        score += 15
        match_points.append("CTO / VPoE / リードポジションの打診")

    # --- ネガティブ要因判定 ---
    # 1. 営業・アンケート勧誘
    if "ai tool adoption" in text_lower or "consultants on" in text_lower:
        score -= 50
        caution_points.append("AIツール導入に関するアンケート・営業勧誘の疑い（求人ではない）")

    # 2. フリーランス・業務委託
    if "freelance" in text_lower or "業務委託" in text_lower:
        score -= 30
        caution_points.append("フリーランス / 業務委託（正社員志向と乖離）")

    # 3. 経験浅向け・低レイヤ
    if "実務経験1〜3年" in text_lower or "1〜3年" in text_lower:
        score -= 25
        caution_points.append("ジュニア層向け（実務経験1〜3年対象）の求人")

    # 4. フロントエンド専任
    if "frontend" in text_lower and not ("fullstack" in text_lower or "backend" in text_lower):
        score -= 30
        caution_points.append("フロントエンド専任職種（ユーザーの完全NG条件に抵触）")

    # 5. 古いメッセージ（2025年以前）
    if is_old:
        score -= 20
        caution_points.append("2025年以前の古いメッセージ（募集終了の可能性が極めて高い）")

    # 6. 単なるフォローアップや中身の薄いコピペ
    if re.search(r"^(quick follow-up|follow up|再送|hiring good talents like you)", snippet.lower()):
        score -= 10
        caution_points.append("案件詳細が記載されていない汎用フォローアップ")

    # スコア正規化
    score = max(0, min(100, score))

    # --- アクション決定 ---
    # 決定規則:
    # 古いメッセージ（is_old）は原則 A にしない
    # 営業・ツールアンケート・明らかなミスマッチ・汎用コピペ → C
    # 企業人事直、または直近の極めて有望な案件（スコア>=75） → A
    # それ以外で残す価値のあるエージェント・情報 → B
    if "ai tool adoption" in text_lower or "freelance" in text_lower or "実務経験1〜3年" in text_lower or "frontend" in text_lower:
        action = "C"
        action_label = "C (削除/アーカイブ)"
    elif is_old:
        if score >= 55 and category in ("corporate_hr", "recruiter_agent"):
            action = "B"
            action_label = "B (保存のみ)"
        else:
            action = "C"
            action_label = "C (削除/アーカイブ)"
    else:
        if category == "corporate_hr" or score >= 75:
            action = "A"
            action_label = "A (返信検討)"
        elif score >= 50:
            action = "B"
            action_label = "B (保存のみ)"
        else:
            action = "C"
            action_label = "C (削除/アーカイブ)"

    # サマリコメント
    if action == "A":
        summary_comment = "企業直採用または希望条件（技術・待遇・リモート）に強く合致する有望メッセージ。返信・面談を前向きに検討。"
    elif action == "B":
        summary_comment = "将来の参考・リクルーター人脈として有用。直近返信は行わず、情報としてローカル保持を推奨。"
    else:
        summary_comment = "営業DM、明らかな条件不一致、または募集終了した古いメッセージ。LinkedIn上の整理（削除/アーカイブ）を推奨。"

    return MessageEvaluation(
        index=index,
        name=name,
        date=date,
        snippet=snippet,
        category=category,
        category_label=category_label,
        action=action,
        action_label=action_label,
        score=score,
        is_old=is_old,
        match_points=match_points,
        caution_points=caution_points,
        summary_comment=summary_comment,
    )


BLOCKS = {
    1: {"range": (0, 8), "description": "直近最新（2026年7月30日〜8月27日）: 9件"},
    2: {"range": (9, 17), "description": "初夏・6月後半（2026年6月17日〜6月30日）: 9件"},
    3: {"range": (18, 26), "description": "2026年春〜初頭（2026年2月13日〜6月17日）: 9件"},
    4: {"range": (27, 35), "description": "2025年過去分（2025年4月30日〜12月21日）: 9件"},
}


def load_messages() -> list[dict[str, Any]]:
    if not MESSAGES_OTHER_PATH.exists():
        print(f"Error: {MESSAGES_OTHER_PATH} not found.", file=sys.stderr)
        sys.exit(1)
    with open(MESSAGES_OTHER_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("messages", [])


def print_block_table(block_id: int, evaluations: list[MessageEvaluation]) -> None:
    meta = BLOCKS.get(block_id, {})
    print(f"\n### ■ ブロック {block_id}: {meta.get('description', '')}")
    print("> 【注意】以下の出力は機械的事前フィルタ（参考情報）です。スコア単体で最終決定せず、総合的に判断してください。詳細調査をスキップする場合は理由を必ず明記してください。\n")
    print("| # | 送信者 | 日付 | 属性 | スコア(参考) | 仮推奨 | 件名 / スニペット | 機械判定ポイント (参考) |")
    print("|---|---|---|---|---|---|---|---|")
    for ev in evaluations:
        reasons = "; ".join(ev.match_points[:2] + ev.caution_points[:1])
        snippet_short = ev.snippet.replace("|", "/")
        print(f"| {ev.index} | {ev.name} | {ev.date} | {ev.category_label.split('/')[0].strip()} | {ev.score} | {ev.action} | {snippet_short} | {reasons} |")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LinkedIn Otherメッセージ事前フィルタ・仕分け参考情報出力（※本出力のみで最終判定を下すことは禁止）",
        epilog=build_epilog(
            examples=[
                "uv run python scripts/linkedin/evaluate_messages.py --block 1",
                "uv run python scripts/linkedin/evaluate_messages.py --all --json  # 全件を JSON で",
            ],
            related=[
                "scripts/linkedin/navigate_messages.py: 前に使う（--status Other で messages_other.json を作る）",
            ],
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--block", type=int, choices=[1, 2, 3, 4], help="特定のブロックのみ評価・表示")
    parser.add_argument("--all", action="store_true", help="全ブロックの評価サマリを表示")
    parser.add_argument("--json", action="store_true", help="JSON形式で出力")
    args = parser.parse_args()

    messages = load_messages()
    all_evaluations = [evaluate_message(m) for m in messages]

    if args.json:
        if args.block:
            start, end = BLOCKS[args.block]["range"]
            target = all_evaluations[start:end + 1]
        else:
            target = all_evaluations
        print(json.dumps([e.to_dict() for e in target], ensure_ascii=False, indent=2))
        return

    if args.block:
        start, end = BLOCKS[args.block]["range"]
        target = all_evaluations[start:end + 1]
        print_block_table(args.block, target)
    else:
        for b_id in [1, 2, 3, 4]:
            start, end = BLOCKS[b_id]["range"]
            target = all_evaluations[start:end + 1]
            print_block_table(b_id, target)

    # 全体サマリ
    counts = {"A": 0, "B": 0, "C": 0}
    for ev in all_evaluations:
        counts[ev.action] += 1
    print("\n#### 全体初期推計集計")
    print(f"- 区分A (返信検討): {counts['A']} 件")
    print(f"- 区分B (保存のみ): {counts['B']} 件")
    print(f"- 区分C (削除/アーカイブ): {counts['C']} 件")
    print(f"- 合計: {len(all_evaluations)} 件")


if __name__ == "__main__":
    main()
