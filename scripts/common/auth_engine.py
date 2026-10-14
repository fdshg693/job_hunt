"""汎用ブラウザ認証・ハンドオフ実行エンジン (auth_engine.py).

全求人サイト（Findy, ビズリーチ, OpenWork等）の認証判定、
Windows OSトースト通知、手動ログイン・CAPTCHA解除待機を一元管理します。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.common.browser_auth import (
    PROJECT_ROOT,
    resolve_profile_path,
    run_code_script,
    run_playwright_cmd,
    send_os_notification,
    update_profile_last_used,
)

UNIVERSAL_AUTH_SCRIPT = PROJECT_ROOT / "scripts" / "common" / "js" / "universal_auth.mjs"


@dataclass
class SiteAuthConfig:
    """サイト固有の認証設定モデル."""

    site_name: str
    login_url: str
    target_url: str | None = None
    auth_wall_regex: str = ""
    logged_in_selectors: list[str] = field(default_factory=list)
    is_captcha_site: bool = False
    auth_check_script: Path | None = None
    auth_guard_script: Path | None = None


# --- 既定サイト定義 ---

FINDY_AUTH_CONFIG = SiteAuthConfig(
    site_name="Findy",
    login_url="https://findy-code.io/users/sign_in",
    target_url="https://findy-code.io/home",
    auth_wall_regex=r"/users/sign_in|/login|/signin|/users/auth|accounts\.google\.com|github\.com/login",
    logged_in_selectors=['header a[href*="/likes"]', 'header a[href*="/home"]', 'nav a[href*="/likes"]'],
    auth_check_script=PROJECT_ROOT / "scripts" / "findy" / "auth_check.mjs",
    auth_guard_script=PROJECT_ROOT / "scripts" / "findy" / "auth_guard.mjs",
)

BIZREACH_AUTH_CONFIG = SiteAuthConfig(
    site_name="ビズリーチ",
    login_url="https://www.bizreach.jp/login/",
    target_url="https://www.bizreach.jp/job-search/",
    auth_wall_regex=r"auth\.id\.bizreach\.jp|/login|/signin|/members/register|/auth/login-callback",
    logged_in_selectors=['nav a[href*="/mypage"]', 'a[href*="/messages"]', 'button:has-text("様")'],
    auth_check_script=PROJECT_ROOT / "scripts" / "bizreach" / "auth_check.mjs",
    auth_guard_script=PROJECT_ROOT / "scripts" / "bizreach" / "auth_guard.mjs",
)

OPENWORK_AUTH_CONFIG = SiteAuthConfig(
    site_name="OpenWork",
    login_url="https://www.openwork.jp/login.php",
    target_url="https://www.openwork.jp/mypage/resume",
    auth_wall_regex=r"login\.php",
    logged_in_selectors=['a[href*="/mypage/"]', 'a[href*="/job_apply_list"]', 'a[href*="/user_logout.php"]'],
    is_captcha_site=True,
    auth_check_script=PROJECT_ROOT / "scripts" / "openwork" / "auth_check.mjs",
    auth_guard_script=PROJECT_ROOT / "scripts" / "openwork" / "auth_guard.mjs",
)


LINKEDIN_AUTH_CONFIG = SiteAuthConfig(
    site_name="LinkedIn",
    login_url="https://www.linkedin.com/login",
    target_url="https://www.linkedin.com/jobs/",
    auth_wall_regex=r"linkedin\.com/(?:authwall|login|checkpoint|uas/login)|accounts\.google\.com",
    logged_in_selectors=[
        'header a[href*="/jobs"]',
        'nav a[href*="/jobs"]',
        'nav button:has-text("プロフィール")',
        'button[aria-label*="Me"]',
        'a[href*="/messaging"]',
    ],
    is_captcha_site=True,
    auth_check_script=PROJECT_ROOT / "scripts" / "linkedin" / "auth_check.mjs",
    auth_guard_script=PROJECT_ROOT / "scripts" / "linkedin" / "auth_guard.mjs",
)

FORKWELL_AUTH_CONFIG = SiteAuthConfig(
    site_name="Forkwell",
    login_url="https://auth.forkwell.com/u/login",
    target_url="https://jobs.forkwell.com/dashboard",
    auth_wall_regex=r"auth\.forkwell\.com|/users/sign_in|/login|/signin",
    logged_in_selectors=[
        'a[href*="/users/sign_out"]',
        'a[href*="/dashboard"]',
        'button:has-text("スカウト")',
        'a[href*="/messages"]',
        '.dashboard-card',
    ],
    auth_check_script=PROJECT_ROOT / "scripts" / "forkwell" / "auth_check.mjs",
    auth_guard_script=PROJECT_ROOT / "scripts" / "forkwell" / "auth_guard.mjs",
)

LEVTECH_DIRECT_AUTH_CONFIG = SiteAuthConfig(
    site_name="レバテックダイレクト",
    login_url="https://levtech-direct.jp/signin",
    target_url="https://levtech-direct.jp/mypage/message",
    auth_wall_regex=r"auth\.levtech\.jp|/signin|/login",
    logged_in_selectors=[
        'a[href*="/mypage"]',
        'a[href*="/mypage/message"]',
        'a[href*="/mypage/profile"]',
    ],
    auth_check_script=PROJECT_ROOT / "scripts" / "levtech_direct" / "auth_check.mjs",
    auth_guard_script=PROJECT_ROOT / "scripts" / "levtech_direct" / "auth_guard.mjs",
)

GREEN_AUTH_CONFIG = SiteAuthConfig(
    site_name="Green",
    login_url="https://www.green-japan.com/login",
    target_url="https://www.green-japan.com/profiles/edit",
    auth_wall_regex=r"green-japan\.com/login|accounts\.google\.com",
    logged_in_selectors=[
        'a[href*="/profiles/edit"]',
        'a[href*="/messages"]',
        'a[href*="/client_users/interests"]',
        'a[href*="/favorites/received"]',
        'a[href*="/search"]',
        'button:has-text("ログアウト")',
    ],
    auth_check_script=PROJECT_ROOT / "scripts" / "green" / "auth_check.mjs",
    auth_guard_script=PROJECT_ROOT / "scripts" / "green" / "auth_guard.mjs",
)

YOUTRUST_AUTH_CONFIG = SiteAuthConfig(
    site_name="YOUTRUST",
    login_url="https://youtrust.jp/sign_in",
    target_url="https://youtrust.jp/settings/profile",
    auth_wall_regex=r"youtrust\.jp/sign_in|accounts\.google\.com",
    logged_in_selectors=[
        'header a[href*="/friend_connections"]',
        'header a[href*="/chat_rooms"]',
        'header a[href*="/users/"]',
        'a[href*="/settings/profile"]',
        'button:has-text("保存")',
    ],
    auth_check_script=PROJECT_ROOT / "scripts" / "youtrust" / "auth_check.mjs",
    auth_guard_script=PROJECT_ROOT / "scripts" / "youtrust" / "auth_guard.mjs",
)

WELLFOUND_AUTH_CONFIG = SiteAuthConfig(
    site_name="Wellfound",
    login_url="https://wellfound.com/login",
    target_url="https://wellfound.com/profile/edit",
    auth_wall_regex=r"wellfound\.com/(?:login|join)|accounts\.google\.com",
    logged_in_selectors=[
        'img[alt*="Avatar for"]',
        'button:has-text("Open to offers")',
        'a[href*="/profile/edit"]',
        'a[href*="/jobs"]',
    ],
    auth_check_script=PROJECT_ROOT / "scripts" / "wellfound" / "auth_check.mjs",
    auth_guard_script=PROJECT_ROOT / "scripts" / "wellfound" / "auth_guard.mjs",
)

SITE_AUTH_CONFIGS: dict[str, SiteAuthConfig] = {
    "findy": FINDY_AUTH_CONFIG,
    "bizreach": BIZREACH_AUTH_CONFIG,
    "openwork": OPENWORK_AUTH_CONFIG,
    "linkedin": LINKEDIN_AUTH_CONFIG,
    "forkwell": FORKWELL_AUTH_CONFIG,
    "levtech_direct": LEVTECH_DIRECT_AUTH_CONFIG,
    "levtech-direct": LEVTECH_DIRECT_AUTH_CONFIG,
    "green": GREEN_AUTH_CONFIG,
    "youtrust": YOUTRUST_AUTH_CONFIG,
    "wellfound": WELLFOUND_AUTH_CONFIG,
}


def get_site_auth_config(site: str | SiteAuthConfig) -> SiteAuthConfig:
    """サイト名文字列または設定インスタンスから SiteAuthConfig を解決する."""
    if isinstance(site, SiteAuthConfig):
        return site
    key = site.lower().strip()
    if key in SITE_AUTH_CONFIGS:
        return SITE_AUTH_CONFIGS[key]
    raise ValueError(f"未知のサイト認証設定です: {site} (対応: {list(SITE_AUTH_CONFIGS.keys())})")


def ensure_site_authenticated(
    site: str | SiteAuthConfig,
    session: str = "job-hunt",
    target_url: str | None = None,
    headed: bool = False,
    timeout: int = 120,
    no_notify: bool = False,
    profile_dir: Path | None = None,
    exit_on_fail: bool = True,
    navigate_if_needed: bool = True,
) -> bool:
    """サイトの認証状態を確認し、未認証時は安全にトースト通知・手動待機ハンドオフを実行する.

    引数:
        site: サイト名（'findy', 'bizreach', 'openwork'）または SiteAuthConfig
        session: ブラウザプロファイルセッション名（デフォルト: 'job-hunt'）
        target_url: 初回起動/チェック時にナビゲートする対象URL（省略時はサイト設定の既定値）
        headed: デバッグ用headed起動フラグ
        timeout: 手動待機タイムアウト秒数（デフォルト: 120秒）
        no_notify: OSトースト通知を抑制するか
        profile_dir: プロファイルディレクトリの明示的指定（省略時は自動解決）
        exit_on_fail: 認証失敗またはタイムアウト時に sys.exit(2) するか（False時は戻り値False）
        navigate_if_needed: 初期URLへのブラウザ起動/ナビゲーションを行うか

    戻り値:
        bool: 認証完了時は True、失敗/中断時は False
    """
    config = get_site_auth_config(site)
    p_dir = profile_dir or resolve_profile_path(session)

    # 1. 必要に応じてブラウザセッション起動・対象URLへナビゲート
    dest_url = target_url or config.target_url or config.login_url
    if navigate_if_needed and dest_url:
        open_args = [f"-s={session}", "open", dest_url, f"--profile={p_dir}"]
        if headed:
            open_args.append("--headed")
        code, out, err = run_playwright_cmd(open_args, timeout=30)
        if code != 0:
            print(f"エラー: ブラウザセッションの起動に失敗しました: {err or out}", file=sys.stderr)
            if exit_on_fail:
                sys.exit(1)
            return False

    # 2. 認証状態のチェック
    env_vars = {
        "AUTH_ACTION": "check",
        "AUTH_WALL_REGEX": config.auth_wall_regex,
        "LOGGED_IN_SELECTORS": json.dumps(config.logged_in_selectors),
        "CHECK_CAPTCHA": "1" if config.is_captcha_site else "0",
        "TARGET_URL": dest_url or "",
    }

    check_result: dict[str, Any] | None = None
    if config.auth_check_script and config.auth_check_script.exists():
        check_result = run_code_script(session, config.auth_check_script, env_vars=env_vars, timeout=15)
    elif UNIVERSAL_AUTH_SCRIPT.exists():
        check_result = run_code_script(session, UNIVERSAL_AUTH_SCRIPT, env_vars=env_vars, timeout=15)


    on_auth_wall = check_result.get("onAuthWall", True) if check_result else True
    auth_type = check_result.get("authType") if check_result else None

    # すでに認証完了している場合
    if not on_auth_wall:
        update_profile_last_used(session)
        return True

    # 3. 未認証・認証壁・CAPTCHA検知時の手動ハンドオフ
    is_captcha = (auth_type == "captcha") or (config.is_captcha_site and auth_type != "login")
    if is_captcha:
        print(
            f"\n[{config.site_name} 認証確認] 画像認証（CAPTCHA）が検出されました。手動解除が必要です。",
            file=sys.stderr,
        )
        if not no_notify:
            send_os_notification(
                f"{config.site_name} 画像認証をお願いします",
                f"プロファイル '{session}' のブラウザで画像認証を解除してください。",
            )
        prompt_title = "【手動画像認証 解除手順】"
        prompt_body = "表示されたブラウザで画像認証を解除してください:"
        cmd_url = target_url or config.target_url or config.login_url
    else:
        print(
            f"\n[{config.site_name} 認証確認] ログイン状態が確認できませんでした。手動ログインが必要です。",
            file=sys.stderr,
        )
        if not no_notify:
            send_os_notification(
                f"{config.site_name} ログインをお願いします",
                f"プロファイル '{session}' のブラウザでログインを完了してください。",
            )
        prompt_title = "【手動ログイン手順】"
        prompt_body = "ブラウザでログインを完了させてください:"
        cmd_url = config.login_url

    print("----------------------------------------------------------------------", file=sys.stderr)
    print(prompt_title, file=sys.stderr)
    print("Windowsのサンドボックス制約により、エージェント環境からは可視ブラウザを操作できません。", file=sys.stderr)
    print("普段お使いの外部ターミナル（PowerShell / Windows Terminal）で以下のコマンドを実行し、", file=sys.stderr)
    print(prompt_body, file=sys.stderr)
    print(f'  playwright-cli -s={session} open "{cmd_url}" --headed --profile="{p_dir}"', file=sys.stderr)
    print("----------------------------------------------------------------------", file=sys.stderr)

    wait_target = "画像認証の解除完了" if is_captcha else "ログイン完了"
    print(f"{wait_target}を待機しています（最大 {timeout} 秒）...", file=sys.stderr)

    # 4. タイムアウト付き待機スクリプトの実行
    guard_env = {
        "AUTH_ACTION": "guard",
        "AUTH_WALL_REGEX": config.auth_wall_regex,
        "LOGGED_IN_SELECTORS": json.dumps(config.logged_in_selectors),
        "CHECK_CAPTCHA": "1" if config.is_captcha_site else "0",
        "TIMEOUT_MS": str(timeout * 1000),
    }

    guard_result: dict[str, Any] | None = None
    if config.auth_guard_script and config.auth_guard_script.exists():
        guard_result = run_code_script(session, config.auth_guard_script, timeout=timeout + 15)
    elif UNIVERSAL_AUTH_SCRIPT.exists():
        guard_result = run_code_script(session, UNIVERSAL_AUTH_SCRIPT, env_vars=guard_env, timeout=timeout + 15)

    success = False
    if guard_result:
        if is_captcha:
            success = bool(guard_result.get("cleared") or guard_result.get("loggedIn"))
        else:
            success = bool(guard_result.get("loggedIn"))

    if not success:
        reason = (
            "ウィンドウが閉じられました"
            if guard_result and guard_result.get("windowClosed")
            else "タイムアウトしました"
        )
        err_action = "手動画像認証" if is_captcha else "手動ログイン"
        print(f"\nエラー: {err_action}が完了しませんでした（{reason}）。処理を中断します。", file=sys.stderr)
        if exit_on_fail:
            sys.exit(2)
        return False

    success_action = "画像認証が解除されました" if is_captcha else "ログインが完了しました"
    print(f"\n[{config.site_name} 認証確認] {success_action}。処理を続行します。", file=sys.stderr)
    update_profile_last_used(session)
    return True
