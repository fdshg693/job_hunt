"""LinkedIn のメッセージスレッド 1 件を取得して JSON で出力する CLI.

LinkedIn 単一スレッド取得スクリプト。位置引数のスレッド URL を開き、取得結果を JSON で標準出力に出す（ファイル保存はしない）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.auth_engine import ensure_site_authenticated
from scripts.common.browser_auth import (
    resolve_profile_path,
    run_code_snippet,
    update_profile_last_used,
)
from scripts.common.cli import build_epilog

SCRIPT_MJS = Path(__file__).resolve().parent / "fetch_single_thread.mjs"

def fetch_thread(target_url: str, session: str = "job-hunt"):
    prof = resolve_profile_path(session)
    # 認証確認
    auth_ok = ensure_site_authenticated("linkedin", session=session, profile_dir=prof)
    if not auth_ok:
        print("LinkedIn auth failed or timed out", file=sys.stderr)
        return None

    # MJSコードを読み込んでターゲットURLを置換
    template_code = SCRIPT_MJS.read_text(encoding="utf-8")
    run_code = template_code.replace(
        "process.env.TARGET_URL || 'https://www.linkedin.com/messaging/thread/2-OTU4NTFlOWQtMWY5NS00YTFhLWFmMjMtMTRiYThiMjliMWM2XzEwMA==/'",
        repr(target_url),
    ).strip().rstrip(";")

    data = run_code_snippet(session, run_code, timeout=60)
    update_profile_last_used(session)
    return data

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="LinkedIn のメッセージスレッド 1 件を取得し、JSON で標準出力に出す",
        epilog=build_epilog(
            examples=[
                'uv run python scripts/linkedin/fetch_single_thread.py "https://www.linkedin.com/messaging/thread/<thread-id>/"',
                'uv run python scripts/linkedin/fetch_single_thread.py "<thread-url>" > thread.json  # JSON をファイルに保存',
            ],
            related=["scripts/linkedin/navigate_messages.py: 前に使う（会話一覧からスレッド URL を拾う）"],
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("url", help="スレッド URL（https://www.linkedin.com/messaging/thread/.../）")
    args = parser.parse_args()
    res = fetch_thread(args.url)
    if res:
        print(json.dumps(res, ensure_ascii=False, indent=2))
