"""LinkedIn プロフィール情報（Headline, About, Skills等）取得スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
LinkedInのプロフィールトップ、自己紹介（About）、スキル一覧画面（/details/skills/）
から情報を取得し、JSONおよびFrontmatter付きMarkdownとして保存します。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.auth_engine import ensure_site_authenticated
from scripts.common.browser_auth import (
    resolve_profile_path,
    run_code_snippet,
    run_playwright_cmd,
    update_profile_last_used,
)
from scripts.common.cli import to_relative_path

LINKEDIN_SCRIPTS_DIR = Path(__file__).resolve().parent
PROFILE_DATA_DIR = PROJECT_ROOT / "data" / "linkedin" / "profile"
FETCH_SCRIPT_PATH = LINKEDIN_SCRIPTS_DIR / "fetch_profile.mjs"

DEFAULT_PROFILE_SLUG = "seiwan-maikuma-25a744362"


def fetch_linkedin_profile(
    session: str,
    slug: str = DEFAULT_PROFILE_SLUG,
    timeout: float = 40.0,
) -> dict[str, Any]:
    """fetch_profile.mjs を実行してプロフィール辞書を取得する."""
    if not FETCH_SCRIPT_PATH.exists():
        raise RuntimeError(f"Playwrightスクリプトが見つかりません: {FETCH_SCRIPT_PATH}")

    template_code = FETCH_SCRIPT_PATH.read_text(encoding="utf-8")
    run_code = template_code.replace("'__LINKEDIN_PROFILE_SLUG__'", json.dumps(slug))

    result = run_code_snippet(session, run_code, timeout=timeout)
    if not result:
        raise RuntimeError("Playwright実行で応答が取得できませんでした")
    if not result.get("success"):
        err = result.get("error") or "不明なエラー"
        raise RuntimeError(f"LinkedIn プロフィール取得エラー: {err}")

    return result.get("profile", {})


def save_profile_data(
    profile_data: dict[str, Any],
    output_dir: Path = PROFILE_DATA_DIR,
) -> list[Path]:
    """プロフィールデータをJSONおよびFrontmatter付きMarkdownとして保存する."""
    output_dir.mkdir(parents=True, exist_ok=True)
    saved_files: list[Path] = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. JSON 保存
    json_path = output_dir / "profile.json"
    data_with_meta = {
        "fetched_at": now_str,
        "source": "linkedin",
        **profile_data,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data_with_meta, f, ensure_ascii=False, indent=2)
    saved_files.append(json_path)

    # 2. Markdown 保存
    md_path = output_dir / "profile.md"
    name = profile_data.get("name", "未設定")
    headline = profile_data.get("headline", "")
    location = profile_data.get("location", "")
    about = profile_data.get("about", "")
    skills = profile_data.get("skills", [])

    lines = [
        "---",
        f"title: LinkedIn プロフィール ({name})",
        f"updated_at: '{now_str}'",
        f"headline: {json.dumps(headline, ensure_ascii=False)}",
        f"location: {json.dumps(location, ensure_ascii=False)}",
        f"skills_count: {len(skills)}",
        "source: linkedin",
        "---",
        "",
        f"# LinkedIn プロフィール: {name}",
        "",
        f"- **肩書き (Headline)**: {headline or '未設定'}",
        f"- **所在地 (Location)**: {location or '未設定'}",
        f"- **最終同期日時**: {now_str}",
        "",
        "## 自己紹介 (About)",
        "",
        about or "（未設定）",
        "",
        f"## 保有スキル (Skills, 計 {len(skills)} 件)",
        "",
    ]

    for idx, sk in enumerate(skills, start=1):
        s_id = sk.get("id", "")
        s_name = sk.get("name", "")
        lines.append(f"{idx}. **{s_name}** (`ID: {s_id}`)")

    lines.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    saved_files.append(md_path)

    return saved_files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LinkedIn プロフィール情報（Headline, About, Skills）を取得して保存します。"
    )
    parser.add_argument("--slug", default=DEFAULT_PROFILE_SLUG, help="LinkedInプロフィールスラッグ")
    parser.add_argument("--session", default="job-hunt", help="Playwrightブラウザセッション名")
    parser.add_argument("--profile-path", default=None, help="カスタムブラウザプロファイルディレクトリ")
    parser.add_argument("--headed", action="store_true", help="ブラウザを表示して実行")
    parser.add_argument("--timeout", type=float, default=45.0, help="実行タイムアウト（秒）")
    parser.add_argument("--no-notify", action="store_true", help="手動ログイン時の通知を抑制")
    parser.add_argument("--summary", action="store_true", help="人間可読なサマリテキストを出力")
    parser.add_argument("--json", action="store_true", help="取得結果をJSON形式で標準出力")
    parser.add_argument("--keep-open", action="store_true", help="実行後にブラウザセッションを維持")

    args = parser.parse_args()

    profile_dir = resolve_profile_path(args.session, args.profile_path)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    target_check_url = f"https://www.linkedin.com/in/{args.slug}/"
    ensure_site_authenticated(
        site="linkedin",
        session=args.session,
        target_url=target_check_url,
        headed=args.headed,
        timeout=args.timeout,
        no_notify=args.no_notify,
        profile_dir=profile_dir,
        exit_on_fail=True,
    )

    try:
        profile_data = fetch_linkedin_profile(args.session, slug=args.slug, timeout=args.timeout)
        saved_files = save_profile_data(profile_data)
        update_profile_last_used(args.session)

        if args.json:
            print(json.dumps(profile_data, ensure_ascii=False, indent=2))
        elif args.summary:
            print("\n========================================================", file=sys.stderr)
            print(f" LinkedIn プロフィール取得結果: {profile_data.get('name')}", file=sys.stderr)
            print("========================================================\n", file=sys.stderr)
            print(f"名前:       {profile_data.get('name')}", file=sys.stderr)
            print(f"Headline:   {profile_data.get('headline')}", file=sys.stderr)
            print(f"所在地:     {profile_data.get('location')}", file=sys.stderr)
            skills = profile_data.get("skills", [])
            print(f"スキル数:   {len(skills)} 件", file=sys.stderr)
            if skills:
                skill_names = [s.get("name") for s in skills[:5]]
                print(f"スキル例:   {', '.join(skill_names)}...", file=sys.stderr)
            print("\n[保存ファイル]", file=sys.stderr)
            for f in saved_files:
                print(f"  - {to_relative_path(f)}", file=sys.stderr)
        else:
            for f in saved_files:
                print(to_relative_path(f))

    except Exception as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if not args.keep_open:
            run_playwright_cmd([f"-s={args.session}", "close"], timeout=10)


if __name__ == "__main__":
    main()
