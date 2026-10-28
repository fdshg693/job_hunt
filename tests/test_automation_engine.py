"""定期実行ルーチンの実行エンジン・CLI アダプタ・ブリーフ整形 (scripts/automation/) の単体テスト.

CLI（claude / agy）とスクリプトの実行は差し替え、条件分岐・失敗時の継続/停止・プレースホルダ・
認証切れの変換・1 日 1 回ガード・ロック・無断の変更の検出を確かめる。
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.automation.agents import (
    AgentRequest,
    AgentResult,
    AgyAdapter,
    ClaudeAdapter,
    missing_agy_rules,
)
from scripts.automation.config import AgyAgent, AgyPermission, ClaudeAgent, ClaudePermission, RoutinesConfig
from scripts.automation.engine import RoutineRunner, changed_paths

NOW = dt.datetime(2026, 10, 28, 8, 30)
TASKS = {
    "summary": "今日は 1 件",
    "tasks": [{"title": "面談の日程を返信する", "reason": "期限が今日", "priority": "high"}],
}


class FakeAdapter:
    name = "claude"

    def __init__(self, result: AgentResult | None = None) -> None:
        self.result = result or AgentResult(ok=True, structured=TASKS, cost_usd=0.01)
        self.requests: list[AgentRequest] = []

    def build_command(self, req: AgentRequest) -> list[str]:
        return ["fake-claude"]

    def run(self, req: AgentRequest) -> AgentResult:
        self.requests.append(req)
        return self.result


def make_cfg(steps: list[dict], *, once: bool = True, profiles: dict | None = None) -> RoutinesConfig:
    return RoutinesConfig.model_validate(
        {
            "version": 1,
            "defaults": {"preamble": "無人実行 {{today}}"},
            "agents": {"claude": {"permission_profiles": profiles or {"read_only": {"tools": ["Read"]}}}},
            "routines": [
                {
                    "id": "r1",
                    "schedule": {"daily_at": ["08:30"], "once_per_day": once},
                    "steps": steps,
                    "brief": {"step": "brief"},
                }
            ],
        }
    )


BRIEF_STEP = {"id": "brief", "kind": "agent", "prompt": "材料: {{steps.a.output}} / {{steps.a.status}}"}


def make_runner(
    tmp_path: Path,
    cfg: RoutinesConfig,
    scripts: dict[str, tuple[int | None, str, str]] | None = None,
    adapter: FakeAdapter | None = None,
    snapshots: list[dict[str, str] | None] | None = None,
    notified: list[tuple] | None = None,
) -> tuple[RoutineRunner, FakeAdapter, list[list[str]]]:
    adapter = adapter or FakeAdapter()
    calls: list[list[str]] = []
    scripts = scripts or {}

    def script_runner(cmd: list[str], cwd: Path, timeout: int) -> tuple[int | None, str, str]:
        calls.append(cmd)
        return scripts.get(cmd[1], (0, "", ""))

    snaps = list(snapshots) if snapshots is not None else None

    def snapshot(root: Path) -> dict[str, str] | None:
        return snaps.pop(0) if snaps else None

    runner = RoutineRunner(
        cfg,
        tmp_path / "vault" / "automation" / "routines.yaml",
        root=tmp_path,
        data_dir=tmp_path / "data" / "automation",
        now=NOW,
        adapters={"claude": adapter},
        script_runner=script_runner,
        snapshot=snapshot,
        agy_settings_path=tmp_path / "agy-settings.json",
        notifier=lambda *a: (notified.append(a) if notified is not None else None) or True,
        log=lambda m: None,
    )
    return runner, adapter, calls


def script(id_: str = "a", path: str = "scripts/vault/find_chores.py", **kw: Any) -> dict:
    return {"id": id_, "kind": "script", "run": [path, "--since", "{{today}}"], **kw}


def test_outputs_flow_into_prompt_and_brief(tmp_path: Path) -> None:
    runner, adapter, calls = make_runner(
        tmp_path, make_cfg([script(), BRIEF_STEP]), scripts={"scripts/vault/find_chores.py": (0, "雑務3件", "")}
    )
    outcome = runner.run("r1")

    assert calls[0][1:] == ["scripts/vault/find_chores.py", "--since", "2026-10-28"]
    prompt = adapter.requests[0].prompt
    assert prompt.startswith("無人実行 2026-10-28")
    assert "材料: 雑務3件 / succeeded" in prompt
    assert adapter.requests[0].json_schema is not None  # ブリーフのスキーマはエンジンが付ける

    assert outcome.brief_path is not None
    assert outcome.brief_path.name == "2026-10-28_r1.md"
    text = outcome.brief_path.read_text(encoding="utf-8")
    assert "面談の日程を返信する" in text and "[高]" in text
    assert 'status: "ok"' in text
    assert json.loads(outcome.brief_path.with_suffix(".json").read_text(encoding="utf-8")) == TASKS
    state = json.loads((tmp_path / "data/automation/state.json").read_text(encoding="utf-8"))
    assert state["r1"]["last_brief"] == "data/automation/briefs/2026-10-28_r1.md"


def test_capture_file_reads_listed_files(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data/mail.md").write_text("件名: 面談", encoding="utf-8")
    runner, adapter, _ = make_runner(
        tmp_path,
        make_cfg([script(capture="file"), BRIEF_STEP]),
        scripts={"scripts/vault/find_chores.py": (0, "data/mail.md\nnot/a/file\n", "")},
    )
    outcome = runner.run("r1")
    assert outcome.results[0].files == ["data/mail.md"]
    assert "### data/mail.md" in adapter.requests[0].prompt
    assert "件名: 面談" in adapter.requests[0].prompt


def test_when_skips_with_reason(tmp_path: Path) -> None:
    steps = [script(), {**BRIEF_STEP, "id": "triage", "when": {"if_nonempty": "a"}}, {**BRIEF_STEP}]
    runner, adapter, _ = make_runner(tmp_path, make_cfg(steps))
    outcome = runner.run("r1")
    triage = outcome.results[1]
    assert triage.status == "skipped"
    assert "if_nonempty" in triage.reason
    assert len(adapter.requests) == 1  # brief だけ
    assert "| triage | agent | skipped |" in outcome.brief_path.read_text(encoding="utf-8")


def test_on_failure_stop_skips_rest(tmp_path: Path) -> None:
    steps = [script(on_failure="stop"), BRIEF_STEP]
    runner, adapter, _ = make_runner(
        tmp_path, make_cfg(steps), scripts={"scripts/vault/find_chores.py": (1, "", "Traceback\nValueError: x")}
    )
    outcome = runner.run("r1")
    assert [r.status for r in outcome.results] == ["failed", "skipped"]
    assert "ValueError: x" in outcome.results[0].reason
    assert adapter.requests == []
    text = outcome.brief_path.read_text(encoding="utf-8")
    assert 'status: "failed"' in text and "ブリーフを作れなかった" in text


def test_auth_exit_code_becomes_login_task(tmp_path: Path) -> None:
    steps = [script(path="scripts/gmail/search_messages.py"), BRIEF_STEP]
    runner, adapter, _ = make_runner(
        tmp_path, make_cfg(steps), scripts={"scripts/gmail/search_messages.py": (2, "", "auth")}
    )
    outcome = runner.run("r1")
    assert outcome.results[0].auth_required
    assert "（取得に失敗: 認証切れ（終了コード 2））/ failed" in adapter.requests[0].prompt.replace(" / ", "/ ")
    text = outcome.brief_path.read_text(encoding="utf-8")
    assert "## 自動実行のためにやること" in text
    assert "scripts/gmail/search_messages.py が使うサービスにログインする" in text


def test_agent_denials_and_auth_become_user_tasks(tmp_path: Path) -> None:
    result = AgentResult(ok=False, auth_required=True, denied=["Bash(git push)"], error="Not logged in")
    runner, _, _ = make_runner(tmp_path, make_cfg([script(), BRIEF_STEP]), adapter=FakeAdapter(result))
    text = runner.run("r1").brief_path.read_text(encoding="utf-8")
    assert "claude にログインする" in text
    assert "Bash(git push)" in text


def test_once_per_day_and_force(tmp_path: Path) -> None:
    runner, adapter, _ = make_runner(tmp_path, make_cfg([script(), BRIEF_STEP]))
    first = runner.run("r1")
    again = runner.run("r1")
    assert again.status == "already_ran"
    assert again.brief_path == tmp_path / "data/automation/briefs/2026-10-28_r1.md"
    forced = runner.run("r1", force=True)
    assert forced.status == "completed"
    assert forced.brief_path != first.brief_path  # 同日 2 回目は時刻付きの別ファイル
    assert len(adapter.requests) == 2


def test_once_per_day_false_runs_again(tmp_path: Path) -> None:
    runner, _, _ = make_runner(tmp_path, make_cfg([script(), BRIEF_STEP], once=False))
    runner.run("r1")
    assert runner.run("r1").status == "completed"


def test_fresh_lock_blocks_run(tmp_path: Path) -> None:
    runner, adapter, _ = make_runner(tmp_path, make_cfg([script(), BRIEF_STEP]))
    lock = tmp_path / "data/automation/locks/r1.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("{}", encoding="utf-8")
    assert runner.run("r1").status == "locked"
    assert adapter.requests == []
    assert lock.exists()  # 他の実行のロックは消さない


def test_unexpected_changes_are_warned(tmp_path: Path) -> None:
    before = {"vault/a.md": "h1"}
    after = {"vault/a.md": "h2", "scripts/x.py": "h3"}
    runner, _, _ = make_runner(tmp_path, make_cfg([script(), BRIEF_STEP]), snapshots=[before, after])
    outcome = runner.run("r1")
    text = outcome.brief_path.read_text(encoding="utf-8")
    assert "> [!WARNING]" in text
    assert "vault/a.md" in text and "scripts/x.py" in text
    assert 'status: "partial"' in text


def test_changed_paths() -> None:
    assert changed_paths({"a": "1", "b": "2"}, {"a": "1", "b": "3", "c": "4"}) == ["b", "c"]
    assert changed_paths({"a": "1"}, {}) == ["a"]


def test_write_vault_is_downgraded_when_state_unknown(tmp_path: Path) -> None:
    # tmp_path は git リポジトリではないので vault の状態を確かめられず、読み取り専用に格下げされる
    profiles = {
        "read_only": {"tools": ["Read"]},
        "write_vault": {"writes": "vault", "tools": ["Read", "Edit", "Bash"], "allow": ["Edit(vault/**)"]},
    }
    steps = [script(), {**BRIEF_STEP, "permission": "write_vault"}]
    runner, adapter, _ = make_runner(tmp_path, make_cfg(steps, profiles=profiles))
    outcome = runner.run("r1")
    perm = adapter.requests[0].permission
    assert isinstance(perm, ClaudePermission)
    assert (perm.writes, perm.tools, perm.allow) == ("none", ["Read"], [])
    assert "格下げ" in outcome.results[1].reason


def test_dry_run_does_not_execute(tmp_path: Path) -> None:
    runner, adapter, calls = make_runner(tmp_path, make_cfg([script(), BRIEF_STEP]))
    outcome = runner.run("r1")  # 1 回実行して state を作る
    runner.dry_run = True
    adapter.requests.clear()
    calls.clear()
    dry = runner.run("r1")  # dry-run は once_per_day に掛からない
    assert dry.brief_path is not None and dry.brief_path.name == "dry-run.md"
    assert calls == [] and adapter.requests == []
    text = dry.brief_path.read_text(encoding="utf-8")
    assert "uv run python scripts/vault/find_chores.py --since 2026-10-28" in text
    assert "fake-claude" in text
    state = json.loads((tmp_path / "data/automation/state.json").read_text(encoding="utf-8"))
    assert state["r1"]["last_brief"].endswith(outcome.brief_path.name)


# ---------------------------------------------------------------------------
# アダプタ
# ---------------------------------------------------------------------------


def _req(perm: ClaudePermission | AgyPermission, schema: dict | None = None) -> AgentRequest:
    return AgentRequest(prompt="p", permission=perm, cwd=Path("."), timeout_seconds=120, json_schema=schema)


def test_claude_command() -> None:
    agent = ClaudeAgent(model="sonnet", max_budget_usd=0.5, permission_profiles={"x": ClaudePermission()})
    perm = ClaudePermission(
        tools=["Read", "Bash"], allow=["Bash(uv run python scripts/a.py *)"], deny=["Bash(git push *)"]
    )
    cmd = ClaudeAdapter(agent).build_command(_req(perm, {"type": "object"}))
    assert "--dangerously-skip-permissions" not in cmd
    for flag in ("-p", "--no-session-persistence", "--permission-prompts"):
        assert flag in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert cmd[cmd.index("--tools") + 1] == "Read,Bash"
    assert cmd[cmd.index("--allowedTools") + 1] == "Bash(uv run python scripts/a.py *)"
    assert cmd[cmd.index("--disallowedTools") + 1] == "Bash(git push *)"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == {"type": "object"}


@pytest.mark.parametrize(
    ("envelope", "ok", "error_part"),
    [
        ({"is_error": False, "result": "ok", "structured_output": {"tasks": []}}, True, None),
        ({"is_error": False, "result": "拒否された", "permission_denials": []}, False, "structured_output"),
        ({"is_error": True, "result": "Not logged in · Please run /login"}, False, "Not logged in"),
    ],
)
def test_claude_parse(envelope: dict, ok: bool, error_part: str | None) -> None:
    agent = ClaudeAgent(permission_profiles={"x": ClaudePermission()})
    res = ClaudeAdapter(agent).parse(0, json.dumps(envelope), "", _req(ClaudePermission(), {"type": "object"}))
    assert res.ok is ok
    if error_part:
        assert error_part in (res.error or "")
    if envelope.get("is_error"):
        assert res.auth_required


def test_claude_parse_denials_and_timeout() -> None:
    agent = ClaudeAgent(permission_profiles={"x": ClaudePermission()})
    env = {
        "is_error": False,
        "result": "done",
        "total_cost_usd": 0.012,
        "permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "uv run python -c 1"}}],
    }
    res = ClaudeAdapter(agent).parse(0, json.dumps(env), "", _req(ClaudePermission()))
    assert res.ok and res.denied == ["Bash(uv run python -c 1)"] and res.cost_usd == 0.012
    timed = ClaudeAdapter(agent).parse(None, "", "", _req(ClaudePermission()))
    assert timed.timed_out and not timed.ok


def test_agy_command_always_has_print_timeout() -> None:
    agent = AgyAgent(model="gemini-3.8-flash-medium", permission_profiles={"x": AgyPermission()})
    cmd = AgyAdapter(agent).build_command(_req(AgyPermission()))
    assert cmd[cmd.index("--print-timeout") + 1] == "120s"
    assert "-p" not in cmd  # stdin で渡す
    assert cmd[cmd.index("--model") + 1] == "gemini-3.8-flash-medium"


def test_agy_parse() -> None:
    adapter = AgyAdapter(AgyAgent(permission_profiles={"x": AgyPermission()}))
    req = _req(AgyPermission())
    ok = adapter.parse(0, json.dumps({"status": "SUCCESS", "response": "hi"}), "", req)
    assert ok.ok and ok.text == "hi"

    denied_env = {
        "status": "SUCCESS",
        "response": "",
        "denied_actions": [{"action": "command", "display_name": "RunCommand"}],
    }
    stderr = 'jetski: no output produced — a tool required the "command" permission that headless mode cannot prompt for, so it was auto-denied'
    denied = adapter.parse(0, json.dumps(denied_env), stderr, req)
    assert not denied.ok and "command(RunCommand)" in denied.denied

    timeout = adapter.parse(0, json.dumps({"status": "SUCCESS", "response": ""}), "[agy] print timeout after 2s", req)
    assert timeout.timed_out and not timeout.ok

    auth = adapter.parse(1, "", "authentication required", req)
    assert auth.auth_required and not auth.ok

    structured = adapter.parse(
        0, json.dumps({"status": "SUCCESS", "response": '{"tasks": []}'}), "", _req(AgyPermission(), {})
    )
    assert structured.ok and structured.structured == {"tasks": []}


def test_missing_agy_rules(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    perm = AgyPermission(allow=["command(regex:uv run .*)"], deny=["command(git push)"])
    assert missing_agy_rules(perm, settings) == ["allow: command(regex:uv run .*)", "deny: command(git push)"]
    settings.write_text(json.dumps({"permissions": {"allow": ["command(regex:uv run .*)"]}}), encoding="utf-8")
    assert missing_agy_rules(perm, settings) == ["deny: command(git push)"]
    assert missing_agy_rules(AgyPermission(), settings) == []


def test_brief_triggers_notification(tmp_path: Path) -> None:
    notified: list[tuple] = []
    runner, _, _ = make_runner(tmp_path, make_cfg([script(), BRIEF_STEP]), notified=notified)
    outcome = runner.run("r1")
    assert len(notified) == 1
    routine, status, payload, user_tasks, path = notified[0]
    assert (routine, status, payload, user_tasks) == ("r1", "ok", TASKS, 0)
    assert path == outcome.brief_path


def test_notification_failure_does_not_fail_run(tmp_path: Path) -> None:
    runner, _, _ = make_runner(tmp_path, make_cfg([script(), BRIEF_STEP]))

    def boom(*a: Any) -> bool:
        raise RuntimeError("toast")

    runner.notifier = boom
    outcome = runner.run("r1")
    assert outcome.status == "completed" and outcome.brief_path is not None


def test_notify_false_and_dry_run_do_not_notify(tmp_path: Path) -> None:
    notified: list[tuple] = []
    cfg = make_cfg([script(), BRIEF_STEP])
    assert cfg.routines[0].brief is not None
    cfg.routines[0].brief.notify = False
    make_runner(tmp_path, cfg, notified=notified)[0].run("r1")
    runner, _, _ = make_runner(tmp_path / "dry", make_cfg([script(), BRIEF_STEP]), notified=notified)
    runner.dry_run = True
    runner.run("r1")
    assert notified == []


def test_scheduled_run_skips_other_weekdays(tmp_path: Path) -> None:
    cfg = make_cfg([script(), BRIEF_STEP])
    assert cfg.routines[0].schedule is not None
    cfg.routines[0].schedule.weekdays = ["mon", "tue"]  # NOW は水曜
    runner, adapter, calls = make_runner(tmp_path, cfg)
    outcome = runner.run("r1", scheduled=True)
    assert outcome.status == "not_today" and calls == [] and adapter.requests == []
    assert runner.run("r1").status == "completed"  # 手動実行は曜日に関係なく動く
