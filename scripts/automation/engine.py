"""定期実行ルーチンの実行エンジン.

ルーチンのステップを上から順に実行し、出力を ``data/automation/runs/{date}/{routine}/`` に保存して
プレースホルダで後段に渡し、最後にブリーフを ``data/automation/briefs/`` に書く。

- ``when`` が満たされないステップ・``on_failure: stop`` の後のステップは理由付きでスキップする。
- script ステップは ``sys.executable`` でリポジトリの CLI を実行する（エンジン自身が ``uv run python`` で動く前提）。
  終了コード 2 は認証切れとして扱い、「ユーザーがやること: ログイン」に回す。
- agent ステップは前後で作業ツリーの未コミット変更を比べ、権限プロファイルの ``writes`` の範囲外の変更を
  「無断の変更」として警告する（agy は書き込みを防げないため。自動で元には戻さない）。
- ``writes: vault`` のステップは、開始時に vault に未コミット変更があれば読み取り専用に格下げする。コミットはしない。
- 同一ルーチンの多重起動はロックファイルで防ぎ、``once_per_day`` は状態ファイルの最終実行日で守る。
- スケジューラからの起動（``scheduled=True``）は ``schedule.weekdays`` 外の曜日なら何もしない
  （ログオン時トリガーは曜日で絞れないため）。
- ブリーフを書いたら ``brief.notify`` に従ってトースト通知する（失敗しても実行は失敗にしない）。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from scripts.automation import notify
from scripts.automation.agents import (
    AGY_SETTINGS_PATH,
    Adapter,
    AgentRequest,
    AgentResult,
    make_adapter,
    missing_agy_rules,
)
from scripts.automation.brief import BRIEF_INSTRUCTIONS, BRIEF_SCHEMA, BriefData, Notice, render_brief
from scripts.automation.config import (
    GLOBAL_PLACEHOLDERS,
    PLACEHOLDER_RE,
    STEP_REF_RE,
    AgentStep,
    AgyPermission,
    ClaudePermission,
    Routine,
    RoutinesConfig,
    ScriptStep,
    When,
    vault_root_of,
)
from scripts.common.paths import AUTOMATION_DATA_DIR, PROJECT_ROOT

StepStatus = Literal["succeeded", "failed", "skipped"]

# 1 つのプレースホルダに展開する出力の上限（プロンプトの肥大化を防ぐ。超えたら末尾を切って注記する）
MAX_PLACEHOLDER_CHARS = 100_000
# 読み取り専用に格下げしたときに claude に残すツール
READ_ONLY_TOOLS = ["Read", "Grep", "Glob"]
# この時間を過ぎたロックは前回の異常終了の残りとみなして回収する
STALE_LOCK_SECONDS = 3 * 60 * 60


@dataclass
class StepResult:
    id: str
    kind: str
    status: StepStatus
    output: str = ""
    reason: str = ""
    agent: str | None = None
    structured: Any = None
    auth_required: bool = False
    denied: list[str] = field(default_factory=list)
    timed_out: bool = False
    cost_usd: float | None = None
    duration_seconds: float = 0.0
    files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["output_chars"] = len(d.pop("output"))
        return d


@dataclass
class RunOutcome:
    status: Literal["completed", "already_ran", "locked", "not_today"]
    routine: str
    run_dir: Path | None = None
    brief_path: Path | None = None
    results: list[StepResult] = field(default_factory=list)
    message: str = ""


ScriptRunner = Callable[[list[str], Path, int], tuple[int | None, str, str]]
SnapshotFn = Callable[[Path], dict[str, str] | None]
# (routine, status, payload, user_tasks, brief_path) -> 通知できたか
Notifier = Callable[[str, str, dict[str, Any] | None, int, Path], bool]
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


# ---------------------------------------------------------------------------
# プレースホルダ・条件
# ---------------------------------------------------------------------------


def expand(text: str, values: dict[str, str], results: dict[str, StepResult]) -> str:
    """``{{name}}`` を展開する. 参照の正しさは config.check_references で検査済みの前提."""

    def repl(m: Any) -> str:
        name = m.group(1)
        if name in values:
            return values[name]
        ref = STEP_REF_RE.match(name)
        if ref and ref.group(1) in results:
            r = results[ref.group(1)]
            if ref.group(2) == "status":
                return r.status
            out = r.output
            if len(out) > MAX_PLACEHOLDER_CHARS:
                out = out[:MAX_PLACEHOLDER_CHARS] + f"\n…（{len(r.output) - MAX_PLACEHOLDER_CHARS} 文字を省略）"
            return out
        return m.group(0)

    return PLACEHOLDER_RE.sub(repl, text)


def when_satisfied(when: Literal["always"] | When, results: dict[str, StepResult]) -> tuple[bool, str]:
    """(実行するか, しないときの理由)."""
    if when == "always":
        return True, ""
    assert isinstance(when, When)
    cond, step_id = when.conditions()[0]
    r = results.get(step_id)
    if r is None:
        return False, f"{step_id} の結果が無い"
    checks = {
        "if_nonempty": (r.status == "succeeded" and bool(r.output.strip()), f"{step_id} の出力が空（{r.status}）"),
        "if_empty": (r.status == "succeeded" and not r.output.strip(), f"{step_id} の出力が空でない（{r.status}）"),
        "if_succeeded": (r.status == "succeeded", f"{step_id} が {r.status}"),
        "if_failed": (r.status == "failed", f"{step_id} が {r.status}"),
    }
    ok, why = checks[cond]
    return ok, "" if ok else f"when.{cond} を満たさない: {why}"


# ---------------------------------------------------------------------------
# 外部プロセス・git
# ---------------------------------------------------------------------------


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def run_script(cmd: list[str], cwd: Path, timeout: int) -> tuple[int | None, str, str]:
    """script ステップを実行する. タイムアウトしたら returncode は None."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            timeout=timeout,
            env=_child_env(),
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return None, "", ""
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _git(root: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def worktree_snapshot(root: Path) -> dict[str, str] | None:
    """未コミット変更のあるファイル → 内容のハッシュ（削除は ``<deleted>``）. git が使えなければ None.

    開始時点で既に変更があったファイルも、前後のハッシュの比較で新たな変更を検出できる。
    """
    out = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if out is None:
        return None
    snap: dict[str, str] = {}
    entries = out.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, path = entry[:2], entry[3:]
        if "R" in xy or "C" in xy:
            i += 1  # リネーム・コピーは元のパスが次の要素に続く
        p = root / path
        try:
            snap[path] = hashlib.sha1(p.read_bytes()).hexdigest() if p.is_file() else "<deleted>"
        except OSError:
            snap[path] = "<unreadable>"
    return snap


def changed_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))


def _in_scope(path: str, writes: str) -> bool:
    if writes == "vault":
        return path.startswith(("vault/", "data/"))
    if writes == "data":
        return path.startswith("data/")
    return False


# ---------------------------------------------------------------------------
# ロック・状態
# ---------------------------------------------------------------------------


class RoutineLock:
    """同一ルーチンの多重起動を防ぐロックファイル（O_EXCL で作る）."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.acquired = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                except OSError:
                    continue
                if age < STALE_LOCK_SECONDS:
                    return False
                self.path.unlink(missing_ok=True)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps({"pid": os.getpid(), "started_at": dt.datetime.now().isoformat(timespec="seconds")}))
            self.acquired = True
            return True
        return False

    def release(self) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False


def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# ---------------------------------------------------------------------------
# エンジン
# ---------------------------------------------------------------------------


class RoutineRunner:
    """1 つのルーチンを実行する. テストでは adapters / script_runner / snapshot を差し替える."""

    def __init__(
        self,
        cfg: RoutinesConfig,
        config_path: Path,
        *,
        root: Path = PROJECT_ROOT,
        data_dir: Path = AUTOMATION_DATA_DIR,
        now: dt.datetime | None = None,
        dry_run: bool = False,
        adapters: dict[str, Adapter] | None = None,
        script_runner: ScriptRunner = run_script,
        snapshot: SnapshotFn = worktree_snapshot,
        agy_settings_path: Path = AGY_SETTINGS_PATH,
        notifier: Notifier = notify.notify_brief,
        log: Callable[[str], None] = lambda m: print(m, file=sys.stderr),
    ) -> None:
        self.cfg = cfg
        self.vault_root = vault_root_of(config_path)
        self.root = root
        self.data_dir = data_dir
        self.now = now or dt.datetime.now()
        self.dry_run = dry_run
        self._adapters = adapters or {}
        self.script_runner = script_runner
        self.snapshot = snapshot
        self.agy_settings_path = agy_settings_path
        self.notifier = notifier
        self.log = log
        self.notices: list[Notice] = []

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def today(self) -> str:
        return self.now.date().isoformat()

    def adapter(self, name: str) -> Adapter:
        if name not in self._adapters:
            agent = self.cfg.agents.get(name)
            assert agent is not None  # check_references で検査済み
            self._adapters[name] = make_adapter(name, agent)
        return self._adapters[name]

    def run(self, routine_id: str, *, force: bool = False, scheduled: bool = False) -> RunOutcome:
        routine = self.cfg.routine(routine_id)
        days = routine.schedule.weekdays if routine.schedule is not None else None
        if scheduled and not force and days and WEEKDAYS[self.now.weekday()] not in days:
            return RunOutcome(
                "not_today",
                routine.id,
                message=f"{routine.id} は {WEEKDAYS[self.now.weekday()]} に実行しない（weekdays: {', '.join(days)}）",
            )
        state = load_state(self.state_path)
        prev = state.get(routine.id) or {}
        once = routine.schedule is not None and routine.schedule.once_per_day
        if once and not force and not self.dry_run and prev.get("last_run_date") == self.today:
            last = prev.get("last_brief")
            return RunOutcome(
                "already_ran",
                routine.id,
                brief_path=self.root / last if last else None,
                message=f"{routine.id} は今日（{self.today}）実行済み（--force で再実行）",
            )

        lock = RoutineLock(self.data_dir / "locks" / f"{routine.id}.lock")
        if not self.dry_run and not lock.acquire():
            return RunOutcome("locked", routine.id, message=f"{routine.id} は実行中（{lock.path}）")
        try:
            outcome = self._run(routine)
        finally:
            lock.release()

        if not self.dry_run:
            state = load_state(self.state_path)
            state[routine.id] = {
                "last_run_date": self.today,
                "last_run_at": self.now.isoformat(timespec="seconds"),
                "last_brief": _rel(outcome.brief_path, self.root) if outcome.brief_path else None,
                "last_run_dir": _rel(outcome.run_dir, self.root) if outcome.run_dir else None,
            }
            save_state(self.state_path, state)
        return outcome

    # -- 本体 ----------------------------------------------------------------

    def _run(self, routine: Routine) -> RunOutcome:
        # dry-run は別ディレクトリにして、本実行のディレクトリ名をずらさない
        run_dir = self.data_dir / "runs" / self.today / (f"{routine.id}_dry-run" if self.dry_run else routine.id)
        if run_dir.exists() and not self.dry_run:
            run_dir = run_dir.with_name(f"{routine.id}_{self.now:%H%M%S}")
        run_dir.mkdir(parents=True, exist_ok=True)
        values = {
            "today": self.today,
            "tomorrow": (self.now.date() + dt.timedelta(days=1)).isoformat(),
            "now": self.now.strftime("%Y-%m-%d %H:%M"),
            "routine": routine.id,
            "run_dir": _rel(run_dir, self.root),
        }
        assert set(values) == set(GLOBAL_PLACEHOLDERS)

        vault_dirty = self._vault_dirty()
        results: dict[str, StepResult] = {}
        stopped_by: str | None = None
        dry_lines: list[str] = []
        for step in routine.steps:
            if stopped_by is not None:
                res = StepResult(step.id, step.kind, "skipped", reason=f"{stopped_by} が失敗し on_failure: stop")
            else:
                ok, why = when_satisfied(step.when, results)
                if not ok:
                    res = StepResult(step.id, step.kind, "skipped", reason=why)
                elif isinstance(step, ScriptStep):
                    res = self._run_script_step(step, values, results, run_dir, dry_lines)
                else:
                    is_brief = routine.brief is not None and routine.brief.step == step.id
                    res = self._run_agent_step(step, values, results, run_dir, vault_dirty, is_brief, dry_lines)
            results[step.id] = res
            self.log(f"[{res.status}] {step.id}" + (f": {res.reason}" if res.reason else ""))
            if res.status == "failed" and step.on_failure == "stop" and stopped_by is None:
                stopped_by = step.id

        ordered = [results[s.id] for s in routine.steps]
        (run_dir / "run.json").write_text(
            json.dumps(
                {
                    "routine": routine.id,
                    "started_at": values["now"],
                    "dry_run": self.dry_run,
                    "steps": [r.to_dict() for r in ordered],
                    "notices": [asdict(n) for n in self.notices],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        if self.dry_run:
            dry_path = run_dir / "dry-run.md"
            dry_path.write_text("\n".join(dry_lines), encoding="utf-8")
            return RunOutcome("completed", routine.id, run_dir=run_dir, brief_path=dry_path, results=ordered)

        brief_path = None
        if routine.brief is not None:
            data = BriefData(
                routine=routine.id,
                date=self.today,
                generated_at=dt.datetime.now().isoformat(timespec="seconds"),
                results=ordered,
                notices=self.notices,
                brief_step=routine.brief.step,
                # 開始時に vault がきれいだったときだけ、変更はこの実行によるものと言える
                vault_diff_stat=(_git(self.root, "diff", "--stat", "--", "vault/") or "")
                if vault_dirty is False
                else "",
            )
            brief_path = self._brief_path(routine.id)
            brief_path.write_text(render_brief(data), encoding="utf-8")
            if data.payload is not None:
                brief_path.with_suffix(".json").write_text(
                    json.dumps(data.payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            if routine.brief.notify:
                self._notify(routine.id, data, brief_path)
        return RunOutcome("completed", routine.id, run_dir=run_dir, brief_path=brief_path, results=ordered)

    def _notify(self, routine_id: str, data: BriefData, brief_path: Path) -> None:
        user_tasks = sum(n.kind == "user_task" for n in self.notices)
        try:
            ok = self.notifier(routine_id, data.status, data.payload, user_tasks, brief_path)
        except Exception as e:  # noqa: BLE001 - 通知の失敗で実行全体を失敗にしない
            self.log(f"[warn] 通知に失敗: {e}")
            return
        if not ok:
            self.log("[warn] 通知を出せなかった（ブリーフは保存済み）")

    def _brief_path(self, routine_id: str) -> Path:
        d = self.data_dir / "briefs"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{self.today}_{routine_id}.md"
        if path.exists():
            path = d / f"{self.today}_{routine_id}_{self.now:%H%M%S}.md"
        return path

    def _vault_dirty(self) -> bool | None:
        out = _git(self.root, "status", "--porcelain", "--", "vault/")
        return None if out is None else bool(out.strip())

    def _notice(
        self, kind: Literal["warning", "user_task"], title: str, detail: str = "", step: str | None = None
    ) -> None:
        self.notices.append(Notice(kind, title, detail, step))

    # -- script --------------------------------------------------------------

    def _run_script_step(
        self, step: ScriptStep, values: dict[str, str], results: dict[str, StepResult], run_dir: Path, dry: list[str]
    ) -> StepResult:
        args = [expand(a, values, results) for a in step.run[1:]]
        cmd = [sys.executable, step.run[0], *args]
        timeout = 60 * (step.timeout_minutes or self.cfg.defaults.timeout_minutes)
        if self.dry_run:
            dry += [f"## {step.id}（script）", "", "```", " ".join(["uv run python", step.run[0], *args]), "```", ""]
            return StepResult(step.id, "script", "succeeded", output=f"<{step.id} の出力（dry-run）>", reason="dry-run")
        res = self._exec_script(step, cmd, timeout, run_dir)
        if res.status == "failed":
            # 後段のプロンプトで失敗の理由が分かるようにする（when の条件は status で判定するので影響しない）
            res.output = f"（取得に失敗: {res.reason}）"
        return res

    def _exec_script(self, step: ScriptStep, cmd: list[str], timeout: int, run_dir: Path) -> StepResult:
        started = time.monotonic()
        code, out, err = self.script_runner(cmd, self.root, timeout)
        res = StepResult(step.id, "script", "succeeded", duration_seconds=time.monotonic() - started)
        (run_dir / f"{step.id}.stdout.txt").write_text(out, encoding="utf-8")
        if err:
            (run_dir / f"{step.id}.stderr.txt").write_text(err, encoding="utf-8")
        if code is None:
            res.status, res.timed_out, res.reason = "failed", True, f"{timeout // 60} 分でタイムアウト"
            self._notice("user_task", f"{step.run[0]} を手動で実行して確かめる", res.reason, step.id)
            return res
        if code == 2:
            res.status, res.auth_required = "failed", True
            res.reason = "認証切れ（終了コード 2）"
            self._notice(
                "user_task",
                f"{step.run[0]} が使うサービスにログインする",
                f"`uv run python {step.run[0]} --help` で認証手順を確認して手動で一度実行する",
                step.id,
            )
            return res
        if code != 0:
            res.status = "failed"
            res.reason = f"終了コード {code}: " + (err.strip().splitlines() or [""])[-1][:200]
            self._notice("user_task", f"{step.id} の失敗を確認する", res.reason, step.id)
            return res
        if step.capture == "stdout":
            res.output = out
        else:
            parts = []
            for line in out.splitlines():
                p = self.root / line.strip()
                if line.strip() and p.is_file():
                    res.files.append(line.strip())
                    parts.append(f"### {line.strip()}\n\n{p.read_text(encoding='utf-8', errors='replace').rstrip()}\n")
            res.output = "\n".join(parts)
        return res

    # -- agent ---------------------------------------------------------------

    def _build_prompt(
        self, step: AgentStep, values: dict[str, str], results: dict[str, StepResult], is_brief: bool
    ) -> str:
        body = (
            step.prompt
            if step.prompt is not None
            else (self.vault_root / str(step.prompt_file)).read_text(encoding="utf-8")
        )
        parts = [expand(self.cfg.defaults.preamble, values, {}).strip(), expand(body, values, results).strip()]
        if is_brief:
            parts.append(BRIEF_INSTRUCTIONS.strip())
        return "\n\n".join(p for p in parts if p) + "\n"

    def _schema(self, step: AgentStep, is_brief: bool) -> dict[str, Any] | None:
        if is_brief:
            return BRIEF_SCHEMA
        if isinstance(step.output_schema, str):
            return json.loads((self.vault_root / step.output_schema).read_text(encoding="utf-8"))
        return step.output_schema

    def _run_agent_step(
        self,
        step: AgentStep,
        values: dict[str, str],
        results: dict[str, StepResult],
        run_dir: Path,
        vault_dirty: bool | None,
        is_brief: bool,
        dry: list[str],
    ) -> StepResult:
        agent_name = step.agent or self.cfg.defaults.agent
        agent_cfg = self.cfg.agents.get(agent_name)
        assert agent_cfg is not None
        perm = agent_cfg.permission_profiles[step.permission]
        note = ""
        if perm.writes == "vault" and vault_dirty is not False:
            why = "vault に未コミットの変更がある" if vault_dirty else "git で vault の状態を確かめられない"
            perm = _downgrade(perm)
            note = f"{why}ので読み取り専用に格下げした"
            self._notice("user_task", "vault の変更をコミットしてから再実行する（任意）", note, step.id)
        if isinstance(perm, AgyPermission):
            if missing := missing_agy_rules(perm, self.agy_settings_path):
                self._notice(
                    "user_task",
                    "agy の settings.json に許可ルールを追加する",
                    "~/.gemini/antigravity-cli/settings.json の permissions に不足: " + " / ".join(missing),
                    step.id,
                )

        req = AgentRequest(
            prompt=self._build_prompt(step, values, results, is_brief),
            permission=perm,
            cwd=self.root,
            timeout_seconds=60 * (step.timeout_minutes or self.cfg.defaults.timeout_minutes),
            model=step.model,
            effort=step.effort,
            json_schema=self._schema(step, is_brief),
        )
        adapter = self.adapter(agent_name)
        if self.dry_run:
            dry += [
                f"## {step.id}（agent: {agent_name}、権限: {step.permission}）",
                "",
                *([f"> {note}", ""] if note else []),
                "```",
                subprocess.list2cmdline(adapter.build_command(req)),
                "```",
                "",
                "<details><summary>プロンプト（stdin）</summary>",
                "",
                "````text",
                req.prompt.rstrip(),
                "````",
                "",
                "</details>",
                "",
            ]
            out = '{"summary": "(dry-run)", "tasks": []}' if is_brief else f"<{step.id} の応答（dry-run）>"
            return StepResult(step.id, "agent", "succeeded", output=out, reason="dry-run", agent=agent_name)

        (run_dir / f"{step.id}.prompt.md").write_text(req.prompt, encoding="utf-8")
        before = self.snapshot(self.root)
        started = time.monotonic()
        result = adapter.run(req)
        duration = time.monotonic() - started
        after = self.snapshot(self.root)
        (run_dir / f"{step.id}.stdout.txt").write_text(result.stdout, encoding="utf-8")
        if result.stderr:
            (run_dir / f"{step.id}.stderr.txt").write_text(result.stderr, encoding="utf-8")

        res = _to_step_result(step.id, agent_name, result, duration)
        if note:
            res.reason = f"{note}。{res.reason}".rstrip("。")
        if res.structured is not None:
            (run_dir / f"{step.id}.json").write_text(
                json.dumps(res.structured, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        self._agent_notices(step, agent_name, result)
        if before is not None and after is not None:
            unexpected = [p for p in changed_paths(before, after) if not _in_scope(p, perm.writes)]
            if unexpected:
                stat = _git(self.root, "diff", "--stat", "--", *unexpected) or ""
                self._notice(
                    "warning",
                    f"無断の変更: 書き込み範囲（writes: {perm.writes}）の外のファイルが変わった。元に戻していない",
                    "\n".join(
                        [*(f"- {p}" for p in unexpected), *([f"```\n{stat.rstrip()}\n```"] if stat.strip() else [])]
                    ),
                    step.id,
                )
        return res

    def _agent_notices(self, step: AgentStep, agent_name: str, result: AgentResult) -> None:
        if result.auth_required:
            how = (
                "ターミナルで `claude` を起動して /login する"
                if agent_name == "claude"
                else "ターミナルで `agy` を起動してログインする"
            )
            self._notice("user_task", f"{agent_name} にログインする", how, step.id)
        if result.denied:
            where = (
                f"agents.{agent_name}.permission_profiles.{step.permission}.allow"
                if agent_name == "claude"
                else "~/.gemini/antigravity-cli/settings.json の permissions.allow"
            )
            self._notice(
                "user_task",
                "拒否された操作を確かめる（必要なら許可ルールを追加して再実行）",
                f"拒否: {', '.join(result.denied)}。許可するなら {where} に追加する",
                step.id,
            )
        if result.timed_out:
            self._notice(
                "user_task",
                f"{step.id} のタイムアウトを確かめる",
                "timeout_minutes を延ばすかプロンプトを軽くする",
                step.id,
            )
        elif not result.ok and not result.auth_required:
            self._notice("user_task", f"{step.id} の失敗を確認する", result.error or "", step.id)


def _to_step_result(step_id: str, agent_name: str, result: AgentResult, duration: float) -> StepResult:
    output = (
        json.dumps(result.structured, ensure_ascii=False, indent=2) if result.structured is not None else result.text
    )
    reason = "" if result.ok else (result.error or "失敗")
    if result.denied:
        reason = (reason + f"。拒否 {len(result.denied)} 件").lstrip("。")
    return StepResult(
        step_id,
        "agent",
        "succeeded" if result.ok else "failed",
        output=output,
        reason=reason,
        agent=agent_name,
        structured=result.structured,
        auth_required=result.auth_required,
        denied=result.denied,
        timed_out=result.timed_out,
        cost_usd=result.cost_usd,
        duration_seconds=duration,
    )


def _downgrade(perm: ClaudePermission | AgyPermission) -> ClaudePermission | AgyPermission:
    """vault への書き込みを外した権限プロファイル（claude は読み取り系のツールだけにする）."""
    if isinstance(perm, ClaudePermission):
        tools = [t for t in (perm.tools or READ_ONLY_TOOLS) if t in READ_ONLY_TOOLS] or READ_ONLY_TOOLS
        return perm.model_copy(update={"writes": "none", "tools": tools, "allow": []})
    return perm.model_copy(update={"writes": "none"})
