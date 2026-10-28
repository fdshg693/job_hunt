"""非推奨: 代わりに scripts/levtech_direct/manage_profile.py resume を使う.

レバテックダイレクト 職務経歴・自己PR管理スクリプト（非推奨互換ラッパー）.

【注意】本スクリプトは scripts/levtech_direct/manage_profile.py に統合されました。
今後は以下のコマンドをご利用ください:
    uv run python scripts/levtech_direct/manage_profile.py resume [fetch|update|sync] [OPTIONS]
"""

from __future__ import annotations

import sys
from pathlib import Path

# プロジェクトルートパス
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.levtech_direct.manage_profile import run_section_cli


def main() -> int:
    print(
        "[DEPRECATION WARNING] manage_profile_resume.py は非推奨です。"
        "今後は 'manage_profile.py resume' をご利用ください。",
        file=sys.stderr,
    )
    return run_section_cli("resume")


if __name__ == "__main__":
    sys.exit(main())
