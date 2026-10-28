"""ルーチン YAML から Windows タスク スケジューラのタスクを生成・登録・解除・状態確認する.

YAML（``routines[].schedule``）が正で、タスク スケジューラ側は ``register`` のたびに YAML から作り直す。
タスクは ``\\job-hunt\\<routine-id>`` に置き、``conhost.exe --headless`` で
``uv run python scripts/automation/run_routine.py run <id> --scheduled`` を非表示で起動するだけにする
（ロジックはタスク側に持たない）。

- プリンシパル: ログオン中のユーザー・``Interactive``・``Limited``（管理者権限なしで登録できる）
- トリガー: ``daily_at`` ごとに日次（``weekdays`` があれば週次）＋ ``on_logon`` ならログオン時（少し遅らせる）
- 設定: 逃した時刻は可能になり次第実行・多重起動は無視・実行時間上限・スリープ解除しない・バッテリーでも実行

登録内容の指紋（``spec:<hash>``）をタスクの説明に入れ、``status`` / ``register`` は指紋の比較で YAML との差分を出す。
PowerShell の呼び出しは ``PowerShellRunner`` として差し替えられる（テストはモック）。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from scripts.automation.config import Routine, RoutinesConfig
from scripts.common.paths import PROJECT_ROOT

TASK_FOLDER = "job-hunt"
TASK_PATH = f"\\{TASK_FOLDER}\\"
RUNNER_SCRIPT = "scripts/automation/run_routine.py"
# ログオン直後はネットワーク・資格情報の準備が済んでいないことがあるので少し待つ
LOGON_DELAY = "PT2M"
# 実行時間上限 = ステップのタイムアウトの合計 + この余裕（分）
TIME_LIMIT_MARGIN_MINUTES = 10
POWERSHELL = "powershell.exe"

WEEKDAY_NAMES = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}
SPEC_RE = re.compile(r"\[spec:([0-9a-f]{12})\]")

PowerShellRunner = Callable[[str], tuple[int, str, str]]
ChangeKind = Literal["create", "update", "unchanged", "remove"]


class SchedulerError(Exception):
    """PowerShell の呼び出しに失敗した."""


@dataclass
class TaskSpec:
    """1 ルーチン分のタスク定義（YAML から生成する）."""

    routine: str
    description: str
    execute: str
    arguments: list[str]
    working_dir: str
    daily_at: list[str]
    weekdays: list[str] | None
    on_logon: bool
    time_limit_minutes: int
    fingerprint: str = field(default="", compare=False)

    @property
    def name(self) -> str:
        return self.routine

    @property
    def full_name(self) -> str:
        return f"{TASK_PATH}{self.routine}"

    @property
    def command_line(self) -> str:
        return subprocess.list2cmdline([self.execute, *self.arguments])

    @property
    def task_description(self) -> str:
        return f"{self.description} [spec:{self.fingerprint}]"

    def triggers_text(self) -> list[str]:
        days = f"（{'/'.join(self.weekdays)}）" if self.weekdays else "（毎日）"
        out = [f"{t}{days}" for t in self.daily_at]
        if self.on_logon:
            out.append(f"ログオン時（{LOGON_DELAY} 遅延）")
        return out


@dataclass
class RegisteredTask:
    """タスク スケジューラに登録済みのタスク（``Get-ScheduledTask`` の結果）."""

    name: str
    state: str = ""
    description: str = ""
    action: str = ""
    triggers: list[str] = field(default_factory=list)
    last_run: str | None = None
    last_result: int | None = None
    next_run: str | None = None

    @property
    def fingerprint(self) -> str | None:
        m = SPEC_RE.search(self.description or "")
        return m.group(1) if m else None


@dataclass
class Change:
    kind: ChangeKind
    routine: str
    spec: TaskSpec | None = None
    current: RegisteredTask | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "routine": self.routine,
            "spec": asdict(self.spec) if self.spec else None,
            "current": asdict(self.current) if self.current else None,
        }


# ---------------------------------------------------------------------------
# YAML → タスク定義
# ---------------------------------------------------------------------------


def resolve_uv() -> str:
    """uv の絶対パス. タスク スケジューラの PATH にはシェルの mise 設定が乗らないことがあるので登録時に固定する."""
    path = shutil.which("uv")
    if path is None:
        raise SchedulerError("uv が PATH に見つからない（mise で uv をインストールしているか確認する）")
    return str(Path(path).resolve()) if not Path(path).is_absolute() else path


def conhost_path() -> str:
    return str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "conhost.exe")


def time_limit_minutes(cfg: RoutinesConfig, routine: Routine) -> int:
    total = sum(s.timeout_minutes or cfg.defaults.timeout_minutes for s in routine.steps)
    return total + TIME_LIMIT_MARGIN_MINUTES


def _fingerprint(spec: TaskSpec) -> str:
    d = asdict(spec)
    d.pop("fingerprint")
    return hashlib.sha1(json.dumps(d, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def build_specs(
    cfg: RoutinesConfig,
    *,
    root: Path = PROJECT_ROOT,
    uv: str | None = None,
    conhost: str | None = None,
    config_arg: str | None = None,
) -> list[TaskSpec]:
    """登録すべきタスク（有効で、daily_at か on_logon のあるルーチン）.

    ``config_arg`` は既定以外の YAML を使うときに ``--config`` として渡すパス。
    """
    uv = uv or resolve_uv()
    specs: list[TaskSpec] = []
    for r in cfg.routines:
        sched = r.schedule
        if not r.enabled or sched is None or not (sched.daily_at or sched.on_logon):
            continue
        args = ["--headless", uv, "run", "python", RUNNER_SCRIPT, "run", r.id, "--scheduled"]
        if config_arg:
            args += ["--config", config_arg]
        spec = TaskSpec(
            routine=r.id,
            description=f"job-hunt routine {r.id}" + (f": {r.description}" if r.description else ""),
            execute=conhost or conhost_path(),
            arguments=args,
            working_dir=str(root),
            daily_at=[t.strip() for t in sched.daily_at],
            weekdays=list(sched.weekdays) if sched.weekdays else None,
            on_logon=sched.on_logon,
            time_limit_minutes=time_limit_minutes(cfg, r),
        )
        spec.fingerprint = _fingerprint(spec)
        specs.append(spec)
    return specs


def plan_changes(specs: list[TaskSpec], current: list[RegisteredTask]) -> list[Change]:
    """YAML（specs）と登録済み（current）の差分. YAML に無いタスクは remove."""
    by_name = {t.name: t for t in current}
    changes: list[Change] = []
    for s in specs:
        cur = by_name.pop(s.name, None)
        if cur is None:
            changes.append(Change("create", s.routine, s))
        elif cur.fingerprint != s.fingerprint:
            changes.append(Change("update", s.routine, s, cur))
        else:
            changes.append(Change("unchanged", s.routine, s, cur))
    changes += [Change("remove", name, None, cur) for name, cur in sorted(by_name.items())]
    return changes


# ---------------------------------------------------------------------------
# PowerShell スクリプトの生成
# ---------------------------------------------------------------------------


def ps_quote(text: str) -> str:
    """PowerShell の単一引用符文字列."""
    return "'" + text.replace("'", "''") + "'"


_PS_HEADER = "$ErrorActionPreference = 'Stop'\n[Console]::OutputEncoding = [Text.Encoding]::UTF8\n"
_PS_USER = '$user = "$env:USERDOMAIN\\$env:USERNAME"\n'


def register_script(spec: TaskSpec) -> str:
    lines = [
        _PS_HEADER + _PS_USER.rstrip(),
        f"$action = New-ScheduledTaskAction -Execute {ps_quote(spec.execute)} -Argument {ps_quote(subprocess.list2cmdline(spec.arguments))} -WorkingDirectory {ps_quote(spec.working_dir)}",
        "$triggers = @()",
    ]
    for t in spec.daily_at:
        if spec.weekdays:
            days = ",".join(WEEKDAY_NAMES[d] for d in spec.weekdays)
            lines.append(f"$triggers += New-ScheduledTaskTrigger -Weekly -DaysOfWeek {days} -At {ps_quote(t)}")
        else:
            lines.append(f"$triggers += New-ScheduledTaskTrigger -Daily -At {ps_quote(t)}")
    if spec.on_logon:
        lines += [
            "$logon = New-ScheduledTaskTrigger -AtLogOn -User $user",
            f"$logon.Delay = {ps_quote(LOGON_DELAY)}",
            "$triggers += $logon",
        ]
    lines += [
        "$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited",
        "$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew "
        f"-ExecutionTimeLimit (New-TimeSpan -Minutes {spec.time_limit_minutes}) "
        "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries",
        f"Register-ScheduledTask -TaskName {ps_quote(spec.name)} -TaskPath {ps_quote(TASK_PATH)} -Action $action -Trigger $triggers "
        f"-Principal $principal -Settings $settings -Description {ps_quote(spec.task_description)} -Force | Out-Null",
    ]
    return "\n".join(lines) + "\n"


# 最後のタスクを消すと空の \job-hunt\ フォルダが残るので Schedule.Service COM で消す
_PS_DELETE_EMPTY_FOLDER = f"""
try {{
  $svc = New-Object -ComObject Schedule.Service
  $svc.Connect()
  $folder = $svc.GetFolder('\\{TASK_FOLDER}')
  if ($folder.GetTasks(1).Count -eq 0 -and $folder.GetFolders(0).Count -eq 0) {{
    $svc.GetFolder('\\').DeleteFolder('{TASK_FOLDER}', 0)
  }}
}} catch {{ }}
"""


def unregister_script(names: list[str]) -> str:
    lines = [_PS_HEADER.rstrip()]
    for n in names:
        lines.append(
            f"Unregister-ScheduledTask -TaskName {ps_quote(n)} -TaskPath {ps_quote(TASK_PATH)} -Confirm:$false"
        )
    return "\n".join(lines) + "\n" + _PS_DELETE_EMPTY_FOLDER


_PS_LIST = (
    _PS_HEADER
    + f"""
function Fmt($d) {{ if ($d -and $d.Year -gt 2000) {{ $d.ToString('yyyy-MM-dd HH:mm:ss') }} else {{ $null }} }}
$tasks = @(Get-ScheduledTask -TaskPath {ps_quote(TASK_PATH)} -ErrorAction SilentlyContinue)
$out = @(foreach ($t in $tasks) {{
  $i = $t | Get-ScheduledTaskInfo
  [pscustomobject]@{{
    name = $t.TaskName
    state = [string]$t.State
    description = [string]$t.Description
    action = (@($t.Actions | ForEach-Object {{ "$($_.Execute) $($_.Arguments)" }}) -join '; ')
    triggers = @($t.Triggers | ForEach-Object {{ "$($_.CimClass.CimClassName -replace '^MSFT_Task','') $($_.StartBoundary)".Trim() }})
    last_run = Fmt $i.LastRunTime
    last_result = $i.LastTaskResult
    next_run = Fmt $i.NextRunTime
  }}
}})
ConvertTo-Json -InputObject $out -Depth 4 -Compress
"""
)


def run_powershell(script: str) -> tuple[int, str, str]:
    """Windows PowerShell 5.1 で実行する. 引用の解釈を避けるため -EncodedCommand（UTF-16LE）で渡す."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        proc = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise SchedulerError(f"{POWERSHELL} を実行できない: {e}") from e
    return proc.returncode, proc.stdout or "", proc.stderr or ""


# ---------------------------------------------------------------------------
# 操作
# ---------------------------------------------------------------------------


class Scheduler:
    def __init__(self, runner: PowerShellRunner = run_powershell) -> None:
        self.runner = runner

    def _run(self, script: str, what: str) -> str:
        code, out, err = self.runner(script)
        if code != 0:
            msg = (err.strip().splitlines() or [out.strip()])[-1] if (err.strip() or out.strip()) else ""
            raise SchedulerError(f"{what}に失敗（終了コード {code}）: {msg}")
        return out

    def list_tasks(self) -> list[RegisteredTask]:
        out = self._run(_PS_LIST, "タスク一覧の取得").strip()
        if not out:
            return []
        data = json.loads(out)
        if isinstance(data, dict):  # PowerShell 5.1 は要素 1 つの配列を展開することがある
            data = [data]
        known = set(RegisteredTask.__dataclass_fields__)
        tasks = []
        for d in data:
            d = {k: v for k, v in d.items() if k in known}
            if isinstance(d.get("triggers"), str):
                d["triggers"] = [d["triggers"]]
            tasks.append(RegisteredTask(**d))
        return tasks

    def apply(self, changes: list[Change]) -> None:
        """create / update は登録（上書き）、remove は解除する. unchanged は触らない."""
        for c in changes:
            if c.kind in ("create", "update"):
                assert c.spec is not None
                self._run(register_script(c.spec), f"{c.routine} の登録")
        removed = [c.routine for c in changes if c.kind == "remove"]
        if removed:
            self._run(unregister_script(removed), "タスクの解除")

    def unregister(self, names: list[str]) -> None:
        self._run(unregister_script(names), "タスクの解除")


def changes_markdown(changes: list[Change], *, title: str) -> str:
    """register / unregister / status の結果を人が読む Markdown にする."""
    labels = {"create": "新規登録", "update": "上書き（YAML と差分あり）", "unchanged": "変更なし", "remove": "削除"}
    out = [f"# {title}", ""]
    if not changes:
        out += ["対象のタスクは無い。", ""]
    for c in changes:
        out += [f"## {TASK_PATH}{c.routine}: {labels[c.kind]}", ""]
        if c.spec is not None:
            out += [
                f"- トリガー: {', '.join(c.spec.triggers_text())}",
                f"- 実行時間上限: {c.spec.time_limit_minutes} 分",
                f"- 作業ディレクトリ: `{c.spec.working_dir}`",
                f"- 指紋: `{c.spec.fingerprint}`",
                "",
                "```",
                c.spec.command_line,
                "```",
                "",
            ]
        if c.current is not None:
            out += [
                f"- 登録済みの状態: {c.current.state or '-'}"
                f" / 前回: {c.current.last_run or '未実行'}（結果 {c.current.last_result}）"
                f" / 次回: {c.current.next_run or '-'}",
                f"- 登録済みのトリガー: {', '.join(c.current.triggers) or '-'}",
                "",
            ]
    return "\n".join(out)
