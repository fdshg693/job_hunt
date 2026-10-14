"""求人データ正規化・抽出共通モジュール (SSOT).

年収、リモート判定、スキル抽出、URL正規化等のビジネスロジックを
単一の情報源として集約・提供します。
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from urllib.parse import urljoin, urlparse, urlunparse

# 主要な技術スタック・キーワードの単一情報源 (SSOT)
KNOWN_SKILL_KEYWORDS: list[str] = [
    # 言語
    "Python",
    "Go",
    "Golang",
    "Rust",
    "Java",
    "Kotlin",
    "TypeScript",
    "JavaScript",
    "Ruby",
    "PHP",
    "C++",
    "C#",
    "Swift",
    "Scala",
    "R",
    # フロントエンド / フレームワーク
    "React",
    "Vue",
    "Next.js",
    "Nuxt.js",
    "Node.js",
    "Ruby on Rails",
    "Laravel",
    "FastAPI",
    "Django",
    "Flask",
    "Spring",
    "Spring Boot",
    "Flutter",
    "React Native",
    # クラウド / インフラ / DB
    "AWS",
    "GCP",
    "Azure",
    "Docker",
    "Kubernetes",
    "Terraform",
    "Ansible",
    "Linux",
    "PostgreSQL",
    "MySQL",
    "Redis",
    "MongoDB",
    "Elasticsearch",
    "GraphQL",
    "SQL",
    "CI/CD",
    "GitHub Actions",
    # AI / データ分析
    "LLM",
    "生成AI",
    "機械学習",
    "深層学習",
    "PyTorch",
    "TensorFlow",
    "scikit-learn",
    "OpenAI",
    "LangChain",
]


def extract_skills_from_text(
    text: str,
    custom_keywords: list[str] | None = None,
) -> list[str]:
    """本文中から主要な技術キーワード・スキルを単語境界を考慮して抽出する."""
    if not text:
        return []

    keywords = custom_keywords or KNOWN_SKILL_KEYWORDS
    found: list[str] = []
    text_lower = text.lower()

    for kw in keywords:
        kw_lower = kw.lower()
        # 英数字・アンダースコアで始まる単語境界
        pattern = r"(?<![a-zA-Z0-9_])" + re.escape(kw_lower) + r"(?![a-zA-Z0-9_])"
        if re.search(pattern, text_lower):
            # 'Golang' は 'Go' に統一するか、またはそのまま残す（ここではGoがある場合はGolangも表記上Goに統一または両立）
            normalized_name = "Go" if kw == "Golang" else kw
            if normalized_name not in found:
                found.append(normalized_name)

    return found


def parse_salary_range(salary_text: str | None) -> tuple[int | None, int | None]:
    """給与文字列から最小年収・最大年収（円単位の整数）を抽出する.

    対応パターン例:
    - 800万円〜1500万円, 800万 ～ 2200万円
    - 800万円以上, 800万以上
    - 〜800万円, 〜800万
    - 800万円
    """
    if not salary_text:
        return None, None

    text = salary_text.replace(",", "").strip()

    # 範囲: 800万円〜1500万円 / 800万 ～ 2200万円
    m_range = re.search(
        r"(\d+(?:\.\d+)?)\s*万(?:円)?\s*[〜~～-]\s*(\d+(?:\.\d+)?)\s*万(?:円)?",
        text,
    )
    if m_range:
        return int(float(m_range.group(1)) * 10000), int(float(m_range.group(2)) * 10000)

    # 範囲 (円単位表記): 8000000円〜15000000円
    m_yen_range = re.search(
        r"(\d{7,})\s*円?\s*[〜~～-]\s*(\d{7,})\s*円?",
        text,
    )
    if m_yen_range:
        return int(m_yen_range.group(1)), int(m_yen_range.group(2))

    # 最低のみ: 800万円以上 / 800万以上 / 800万円〜
    m_min = re.search(r"(\d+(?:\.\d+)?)\s*万(?:円)?\s*(?:以上|[〜~～-]\s*$)", text)
    if m_min:
        return int(float(m_min.group(1)) * 10000), None

    # 最高のみ: 〜800万円 / 〜800万
    m_max = re.search(r"[〜~～-]\s*(\d+(?:\.\d+)?)\s*万(?:円)?", text)
    if m_max:
        return None, int(float(m_max.group(1)) * 10000)

    # 単一値: 800万円 / 800万
    m_single = re.search(r"(\d+(?:\.\d+)?)\s*万(?:円)?", text)
    if m_single:
        val = int(float(m_single.group(1)) * 10000)
        return val, val

    return None, None


def parse_salary_arg(val: str | None) -> int | None:
    """CLI引数の年収指定を円単位の整数に変換する.

    例: '700' -> 7000000 (10000未満は万円指定とみなす)
        '700万' -> 7000000
        '7000000' -> 7000000
    """
    if val is None:
        return None
    val_clean = str(val).replace(",", "").replace("万", "").replace("円", "").strip()
    if not val_clean:
        return None
    try:
        num = int(float(val_clean))
        if num < 10000:
            return num * 10000
        return num
    except ValueError:
        raise argparse.ArgumentTypeError(f"不正な年収形式です: '{val}' (例: 700 または 7000000)")


def detect_remote_type(location_text: str | None, text_blob: str) -> str:
    """勤務地・本文からリモート勤務タイプ（出社 / フルリモート / ハイブリッド）を判定する."""
    combined = f"{location_text or ''} {text_blob}".lower()

    # 1. 出社確定キーワード
    if any(kw in combined for kw in ["リモートワーク不可", "リモート不可", "在宅勤務不可", "出社のみ", "原則出社"]):
        return "出社"

    # 2. フルリモート確定キーワード
    if any(kw in combined for kw in ["フルリモート", "完全在宅", "リモートメイン", "在宅勤務可（フルリモート）"]):
        return "フルリモート"

    # 3. ハイブリッド・リモート可キーワード
    if any(kw in combined for kw in ["リモート", "ハイブリッド", "ハイブリット", "在宅", "テレワーク"]):
        return "ハイブリッド"

    return "出社"


def format_salary_text(
    salary_min: int | None,
    salary_max: int | None,
    salary_remark: str | None = None,
) -> str | None:
    """年収数値から '600万円〜900万円' 等の標準テキストを生成する."""
    if salary_min and salary_max:
        min_man = salary_min // 10000
        max_man = salary_max // 10000
        return f"{min_man}万円〜{max_man}万円"
    if salary_min:
        return f"{salary_min // 10000}万円〜"
    if salary_max:
        return f"〜{salary_max // 10000}万円"
    if salary_remark and salary_remark.strip():
        return salary_remark.strip()
    return None


def format_salary_display(
    salary_min: int | None = None,
    salary_max: int | None = None,
    salary_text: str | None = None,
) -> str:
    """コンソール表示・サマリ表示用に年収を読みやすくフォーマットする."""
    if salary_text and salary_text.strip():
        return salary_text.strip()
    if salary_min is not None and salary_max is not None:
        min_man = salary_min // 10000
        max_man = salary_max // 10000
        return f"{min_man}万〜{max_man}万円"
    if salary_min is not None:
        return f"{salary_min // 10000}万円〜"
    if salary_max is not None:
        return f"〜{salary_max // 10000}万円"
    return "非公開/未設定"


def normalize_url(url: str, base_url: str | None = None) -> str:
    """URLの相対パス解決およびクエリパラメータの正規化（不要トラッキング除去）を行う."""
    if not url:
        return ""

    # 相対URLの解決
    if base_url and not url.startswith(("http://", "https://")):
        url = urljoin(base_url, url)

    parsed = urlparse(url)
    # クエリの不要パラメータ（utm_*, fbclid等）を除去
    if parsed.query:
        kept_queries = [
            q for q in parsed.query.split("&")
            if not any(q.startswith(prefix) for prefix in ("utm_", "fbclid", "gclid", "ref="))
        ]
        new_query = "&".join(kept_queries)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))

    return url


def normalize_company_name(name: str) -> str:
    """会社名から法人格記号（前株・後株、合同会社等）や不要な記号・空白を除去し、比較・検索用に正規化する.

    例:
        '株式会社SmartHR' -> 'SmartHR'
        '（株）メルカリ' -> 'メルカリ'
        'セキュアナビ 株式会社' -> 'セキュアナビ'
        'ＧＯ株式会社' -> 'GO'
    """
    if not name:
        return ""
    # 1. NFKC正規化（全角英数・記号の半角化、全角スペースの半角化）
    normalized = unicodedata.normalize("NFKC", name).strip()

    # 2. 法人格・略称パターンの除去
    patterns = [
        r"\(株\)",
        r"（株）",
        r"\(有\)",
        r"（有）",
        r"\(同\)",
        r"（同）",
        r"株式会社",
        r"有限会社",
        r"合同会社",
        r"合資会社",
        r"合名会社",
        r"一般社団法人",
        r"公益社団法人",
        r"一般財団法人",
        r"公益財団法人",
        r"特定非営利活動法人",
        r"NPO法人",
    ]
    for pat in patterns:
        normalized = re.sub(pat, "", normalized, flags=re.IGNORECASE)

    # 3. 前後の空白・記号除去
    normalized = re.sub(r"[\s\u3000]+", " ", normalized).strip()
    return normalized
