"""ブラウザ自動化・認証ハンドオフ共通モジュール.

各求人・転職サイト共通のプロファイル管理、認証状態判定補助、
Windows OSトースト通知、Playwright CLI実行処理を提供します。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/common/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 共通スキルスクリプト
PROFILES_SCRIPT = PROJECT_ROOT / ".agents" / "skills" / "sharing-browser-with-user" / "scripts" / "profiles.mjs"
NOTIFY_SCRIPT = PROJECT_ROOT / ".agents" / "skills" / "sharing-browser-with-user" / "scripts" / "notify-user.ps1"


def resolve_profile_path(session_name: str, explicit_path: str | None = None) -> Path:
    """セッション名に対応するプロファイルディレクトリの絶対パスを解決する."""
    if explicit_path:
        p = Path(explicit_path).expanduser().resolve()
        return p

    # profiles.mjs から解決を試みる
    if PROFILES_SCRIPT.exists():
        try:
            res = subprocess.run(
                ["node", str(PROFILES_SCRIPT), "path", session_name],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
            resolved = res.stdout.strip()
            if resolved:
                return Path(resolved).resolve()
        except Exception:
            pass

    # フォールバック: Windows の LOCALAPPDATA / claude-browser-profiles
    local_app_data = os.environ.get(
        "LOCALAPPDATA",
        str(Path.home() / "AppData" / "Local") if sys.platform == "win32" else str(Path.home() / ".local" / "share"),
    )
    return (Path(local_app_data) / "claude-browser-profiles" / session_name).resolve()


def update_profile_last_used(session_name: str) -> None:
    """profiles.mjs を呼び出して最終利用日を更新する."""
    if not PROFILES_SCRIPT.exists():
        return
    try:
        subprocess.run(
            ["node", str(PROFILES_SCRIPT), "used", session_name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except Exception:
        pass


def send_os_notification(title: str, body: str) -> None:
    """Windows PowerShell 5.1 を使ってトースト通知を送信する（ベストエフォート）."""
    if not NOTIFY_SCRIPT.exists() or sys.platform != "win32":
        return
    try:
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-File",
                str(NOTIFY_SCRIPT),
                "-Title",
                title,
                "-Body",
                body,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except Exception:
        pass


def run_playwright_cmd(
    args: list[str],
    env_vars: dict[str, str] | None = None,
    timeout: float | None = None,
) -> tuple[int, str, str]:
    """playwright-cli コマンドを実行し、(returncode, stdout, stderr) を返す."""
    cmd = ["playwright-cli"] + args
    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=True,
            env=env,
            timeout=timeout,
        )
        return res.returncode, res.stdout, res.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)


def run_code_script(
    session: str,
    script_path: Path,
    env_vars: dict[str, str] | None = None,
    timeout: float | None = None,
) -> dict[str, Any] | None:
    """run-code --filename=<script> --raw を実行し、戻り値JSONをパースする."""
    code, stdout, stderr = run_playwright_cmd(
        [f"-s={session}", "run-code", f"--filename={script_path}", "--raw"],
        env_vars=env_vars,
        timeout=timeout,
    )
    if code != 0:
        err_msg = stderr.strip() or stdout.strip()
        lines = [l.strip() for l in err_msg.splitlines() if l.strip() and l.strip() != "### Error"]
        first_err = [l for l in lines if "error" in l.lower()]
        display_err = first_err[0] if first_err else (lines[0] if lines else "Unknown error")
        print(f"[警告] Playwrightスクリプト実行エラー: {display_err}", file=sys.stderr)
        return None

    out = stdout.strip()
    if not out:
        return None

    # JSON部分の抽出 (末尾行または全体)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        pass

    lines = out.splitlines()
    for line in reversed(lines):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    return None


def check_playwright_cli() -> bool:
    """playwright-cli が利用可能か確認する."""
    return shutil.which("playwright-cli") is not None


def random_sleep(min_sec: float = 1.0, max_sec: float = 2.5) -> None:
    """指定範囲でランダムスリープを行う（スクレイピング負荷軽減）."""
    import random
    import time

    sleep_time = random.uniform(min_sec, max_sec)
    time.sleep(sleep_time)


def run_code_snippet(
    session: str,
    code_str: str,
    timeout: float | None = None,
    env_vars: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """一時mjsファイルを安全に生成して実行し、結果JSONを取得して確実に削除する.

    並行実行時のファイル名衝突を防ぐためUUID付き一時ファイルを使用します。
    """
    import uuid

    tmp_path = PROJECT_ROOT / f".tmp_{session}_{uuid.uuid4().hex[:8]}.mjs"
    try:
        tmp_path.write_text(code_str, encoding="utf-8")
        return run_code_script(session, tmp_path, env_vars=env_vars, timeout=timeout)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

