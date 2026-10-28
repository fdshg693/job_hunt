"""vault の値を一覧表示用の短い文字列にする関数群（pipeline.md と Web UI で共有）.

モデルではなく素の値を受け取る。pipeline はモデルから、Web UI は索引の行から呼ぶため。
"""

from __future__ import annotations

from scripts.vault.schema import REMOTE_TYPE_SHORT_LABELS, RemoteType


def format_salary(lo: int | None, hi: int | None) -> str:
    """年収（万円）を「600〜900万円」「600万円〜」「〜900万円」の形にする."""
    if lo is None and hi is None:
        return ""
    if hi is None:
        return f"{lo}万円〜"
    if lo is None:
        return f"〜{hi}万円"
    return f"{lo}万円" if lo == hi else f"{lo}〜{hi}万円"


def format_remote(remote_type: RemoteType | str | None, office_days_per_week: float | None) -> str:
    """勤務形態を「ハイブリッド（週2出社）」「リモート中心（月1出社）」の形にする."""
    if remote_type is None:
        return ""
    label = REMOTE_TYPE_SHORT_LABELS[RemoteType(remote_type)]
    days = office_days_per_week
    if not days:
        return label
    # 週1未満は月あたりの回数で書く（office_days_per_week は月N回を N/4 で記録している）
    return f"{label}（週{days:g}出社）" if days >= 1 else f"{label}（月{days * 4:g}出社）"


def format_fit(lo: int | None, hi: int | None) -> str:
    if lo is None:
        return ""
    return str(lo) if lo == hi else f"{lo}〜{hi}"


def format_interest(interest: int | None) -> str:
    return "" if interest is None else "★" * interest
