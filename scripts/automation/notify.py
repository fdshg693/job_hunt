"""ブリーフ完成時のトースト通知.

Windows PowerShell 5.1（``powershell.exe``）から WinRT の ``ToastNotificationManager`` を使う
（PowerShell 7 では WinRT 型が読めない）。通常のトーストはすぐ通知センターに引っ込んで気づかれないので、
``scenario="reminder"`` で閉じるまで画面に残し、「開く」ボタンでブリーフの ``file:///`` をプロトコル起動する。

通知はおまけなので、失敗しても例外を投げずに False を返す（実行全体は失敗にしない）。
"""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, quoteattr

# Windows PowerShell の AppUserModelID（トーストの送り主として表示される）
POWERSHELL_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
MAX_LINE_CHARS = 120

STATUS_LABELS = {"ok": "", "partial": "（一部失敗）", "failed": "（失敗）"}


def toast_text(routine: str, status: str, payload: dict[str, Any] | None, user_tasks: int) -> tuple[str, str]:
    """(タイトル, 本文). 件数と最上位のタスクを出す."""
    tasks = list((payload or {}).get("tasks") or [])
    top = next((t for t in tasks if t.get("priority") == "high"), tasks[0] if tasks else None)
    title = f"今日やること {len(tasks)} 件{STATUS_LABELS.get(status, '')}（{routine}）"
    lines = []
    if top is not None:
        lines.append(f"最優先: {top.get('title', '')}")
    elif payload is None:
        lines.append("ブリーフを作れなかった。実行結果を確認する")
    else:
        lines.append("やることは無い")
    if user_tasks:
        lines.append(f"ほかに実行時の対応 {user_tasks} 件（ログイン・許可ルール等）")
    return title, "\n".join(line[:MAX_LINE_CHARS] for line in lines)


def toast_xml(title: str, body: str, open_uri: str) -> str:
    texts = "".join(f"<text>{escape(t)}</text>" for t in [title, *body.splitlines()][:3])
    return (
        f'<toast scenario="reminder" activationType="protocol" launch={quoteattr(open_uri)}>'
        f'<visual><binding template="ToastGeneric">{texts}</binding></visual>'
        "<actions>"
        f'<action content="開く" activationType="protocol" arguments={quoteattr(open_uri)}/>'
        '<action content="閉じる" activationType="system" arguments="dismiss"/>'
        "</actions></toast>"
    )


def _script(xml: str) -> str:
    # XML は base64 で埋め込み、PowerShell の引用規則を気にしなくてよいようにする
    b64 = base64.b64encode(xml.encode("utf-8")).decode("ascii")
    return f"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64}'))
$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml($xml)
$toast = [Windows.UI.Notifications.ToastNotification]::new($doc)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{POWERSHELL_APP_ID}').Show($toast)
"""


def send_toast(title: str, body: str, open_path: Path) -> bool:
    """トーストを出す. 成功したら True（Windows 以外・失敗は False）."""
    if sys.platform != "win32":
        return False
    encoded = base64.b64encode(_script(toast_xml(title, body, open_path.resolve().as_uri())).encode("utf-16-le"))
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded.decode("ascii")],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def notify_brief(routine: str, status: str, payload: dict[str, Any] | None, user_tasks: int, brief_path: Path) -> bool:
    title, body = toast_text(routine, status, payload, user_tasks)
    return send_toast(title, body, brief_path)
