"""非推奨: 代わりに scripts/common/search_local_jobs.py を使う.

このファイルは後方互換性のための非推奨エイリアスです。
今後は `scripts/common/search_local_jobs.py` を使用してください。
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

# プロジェクトルートパス設定 (sys.path に追加して絶対インポートを可能にする)
_CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _CURRENT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 非推奨警告
warnings.warn(
    "scripts.common.search_jobs は非推奨です。scripts.common.search_local_jobs を使用してください。",
    DeprecationWarning,
    stacklevel=2,
)

from scripts.common.search_local_jobs import (  # noqa: E402
    DEFAULT_DATA_DIR,
    JobItem,
    filter_jobs,
    format_salary_display,
    load_all_jobs,
    main,
    parse_salary_arg,
    print_terminal_view,
    sort_jobs,
)

__all__ = [
    "DEFAULT_DATA_DIR",
    "JobItem",
    "filter_jobs",
    "format_salary_display",
    "load_all_jobs",
    "main",
    "parse_salary_arg",
    "print_terminal_view",
    "sort_jobs",
]

if __name__ == "__main__":
    print(
        "警告: scripts/common/search_jobs.py は非推奨です。"
        "今後は scripts/common/search_local_jobs.py を使用してください。\n",
        file=sys.stderr,
    )
    main()
