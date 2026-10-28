"""ブラウザ自動化・認証ハンドオフ共通モジュール.

各求人・転職サイト共通のプロファイル管理、認証状態判定補助、
Windows OSトースト通知、Playwright CLI実行処理を提供します。
"""

from __future__ import annotations

import functools
import json
import os
import re
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


@functools.cache
def _resolve_playwright_cli() -> list[str]:
    """playwright-cli の実行コマンドプレフィックスを解決する.

    Windows では cmd.exe の引数再解釈（& や % などの切断）を防ぐため、
    node.exe と playwright-cli.js を shell=False で直接起動する。
    解決順:
    1. 環境変数 PLAYWRIGHT_CLI_JS (明示指定)
    2. sys.platform != "win32" の場合は shutil.which("playwright-cli")
    3. Windows: shutil.which("playwright-cli") のシム (.cmd / sh) から playwright-cli.js を抽出
    4. Windows: node と同階層または global node_modules からの探索
    """
    env_js = os.environ.get("PLAYWRIGHT_CLI_JS")
    if env_js:
        p = Path(env_js).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"PLAYWRIGHT_CLI_JS points to non-existent file: {env_js}")
        node = shutil.which("node") or "node"
        return [node, str(p)]

    if sys.platform != "win32":
        cli = shutil.which("playwright-cli")
        if cli:
            return [cli]
        raise FileNotFoundError("playwright-cli not found in PATH")

    cli_path = shutil.which("playwright-cli")
    if cli_path:
        shim_file = Path(cli_path)
        shim_dir = shim_file.parent
        try:
            content = shim_file.read_text(encoding="utf-8", errors="replace")
            matches = re.findall(r"([^\s\"\'\(\)]*playwright-cli\.js)", content)
            for raw in matches:
                clean = (
                    raw.replace("%~dp0\\", "")
                    .replace("%~dp0/", "")
                    .replace("%~dp0", "")
                    .replace("$basedir\\", "")
                    .replace("$basedir/", "")
                    .replace("$basedir", "")
                    .replace("$basedir_win\\", "")
                    .replace("$basedir_win/", "")
                    .replace("$basedir_win", "")
                )
                target = (shim_dir / clean).resolve()
                if target.is_file():
                    shim_node = shim_dir / "node.exe"
                    if shim_node.is_file():
                        node_bin = str(shim_node)
                    else:
                        node_bin = shutil.which("node") or "node"
                    return [node_bin, str(target)]
        except Exception:
            pass

    node_bin = shutil.which("node")
    if node_bin:
        node_dir = Path(node_bin).parent
        candidates = [
            node_dir / "node_modules" / "@playwright" / "cli" / "playwright-cli.js",
            node_dir / "node_modules" / "playwright-cli" / "playwright-cli.js",
        ]
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "npm" / "node_modules" / "@playwright" / "cli" / "playwright-cli.js")
        localappdata = os.environ.get("LOCALAPPDATA")
        if localappdata:
            candidates.append(Path(localappdata) / "pnpm" / "global" / "5" / "node_modules" / "@playwright" / "cli" / "playwright-cli.js")
        for cand in candidates:
            if cand.is_file():
                return [node_bin, str(cand.resolve())]

    raise FileNotFoundError(
        "playwright-cli executable or entrypoint (playwright-cli.js) not found. "
        "Ensure playwright-cli is installed or set PLAYWRIGHT_CLI_JS."
    )


def run_playwright_cmd(
    args: list[str],
    env_vars: dict[str, str] | None = None,
    timeout: float | None = None,
) -> tuple[int, str, str]:
    """playwright-cli コマンドを実行し、(returncode, stdout, stderr) を返す."""
    try:
        cli_prefix = _resolve_playwright_cli()
    except Exception as e:
        return -1, "", str(e)

    cmd = cli_prefix + args
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
            shell=False,
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
    """run-code --filename=<script> --raw を実行し、戻り値JSONをパースする.

    playwright-core 1.63 以降の run-code サンドボックスには `process` が無いため、
    スクリプトが `process.env` を参照する場合は env_vars を `process` シムとして
    関数スコープに注入したラッパーを一時生成して実行する。
    """
    source = script_path.read_text(encoding="utf-8")
    wrapped_path: Path | None = None
    if "process.env" in source:
        import uuid

        inner = source.rstrip().rstrip(";")
        wrapped = (
            "async page => {\n"
            f"  const process = {{ env: {json.dumps(env_vars or {}, ensure_ascii=False)} }};\n"
            f"  return await (\n{inner}\n  )(page);\n"
            "}\n"
        )
        wrapped_path = PROJECT_ROOT / f".tmp_{session}_{uuid.uuid4().hex[:8]}.mjs"
        wrapped_path.write_text(wrapped, encoding="utf-8")
    try:
        code, stdout, stderr = run_playwright_cmd(
            [f"-s={session}", "run-code", f"--filename={wrapped_path or script_path}", "--raw"],
            env_vars=env_vars,
            timeout=timeout,
        )
    finally:
        if wrapped_path and wrapped_path.exists():
            try:
                wrapped_path.unlink()
            except Exception:
                pass
    if code != 0:
        err_msg = stderr.strip() or stdout.strip()
        lines = [line.strip() for line in err_msg.splitlines() if line.strip() and line.strip() != "### Error"]
        first_err = [line for line in lines if "error" in line.lower()]
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
    try:
        _resolve_playwright_cli()
        return True
    except Exception:
        return False


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

