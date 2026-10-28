"""タスク スケジューラ登録・トースト通知 (scripts/automation/scheduler.py, notify.py) の単体テスト.

PowerShell は呼ばず、YAML → タスク定義・差分・生成する PowerShell スクリプト・登録済み一覧の解釈・通知文面を確かめる。
"""

from __future__ import annotations

import json
from pathlib import Path
from xml.dom.minidom import parseString

import pytest

from scripts.automation.config import RoutinesConfig
from scripts.automation.notify import toast_text, toast_xml
from scripts.automation.scheduler import (
    TASK_PATH,
    RegisteredTask,
    Scheduler,
    SchedulerError,
    build_specs,
    plan_changes,
    register_script,
    unregister_script,
)

UV = r"C:\Users\u\AppData\Local\mise\shims\uv.exe"
CONHOST = r"C:\Windows\System32\conhost.exe"


def make_cfg(*routines: dict) -> RoutinesConfig:
    return RoutinesConfig.model_validate(
        {
            "version": 1,
            "defaults": {"timeout_minutes": 15},
            "agents": {"claude": {"permission_profiles": {"read_only": {"tools": ["Read"]}}}},
            "routines": list(routines),
        }
    )


def routine(id_: str = "morning-brief", schedule: dict | None = None, **kw: object) -> dict:
    return {
        "id": id_,
        "schedule": schedule if schedule is not None else {"daily_at": ["08:30"], "on_logon": True},
        "steps": [
            {"id": "a", "kind": "script", "run": ["scripts/vault/find_chores.py"]},
            {"id": "b", "kind": "script", "run": ["scripts/vault/find_chores.py"], "timeout_minutes": 5},
        ],
        **kw,
    }


def specs(cfg: RoutinesConfig, **kw: object):
    return build_specs(cfg, root=Path(r"C:\repo"), uv=UV, conhost=CONHOST, **kw)


def test_build_specs_only_enabled_with_triggers() -> None:
    cfg = make_cfg(
        routine("a1"),
        routine("off", enabled=False),
        routine("manual", schedule={}),
        {k: v for k, v in routine("noschedule").items() if k != "schedule"},
    )
    out = specs(cfg)
    assert [s.routine for s in out] == ["a1"]
    s = out[0]
    assert s.execute == CONHOST
    assert s.arguments == [
        "--headless",
        UV,
        "run",
        "python",
        "scripts/automation/run_routine.py",
        "run",
        "a1",
        "--scheduled",
    ]
    assert s.working_dir == r"C:\repo"
    assert s.time_limit_minutes == 15 + 5 + 10
    assert s.full_name == f"{TASK_PATH}a1"
    assert f"[spec:{s.fingerprint}]" in s.task_description


def test_config_arg_and_fingerprint_changes() -> None:
    base = specs(make_cfg(routine()))[0]
    other = specs(make_cfg(routine()), config_arg="templates/vault/automation/routines.yaml")[0]
    assert other.arguments[-2:] == ["--config", "templates/vault/automation/routines.yaml"]
    assert other.fingerprint != base.fingerprint
    assert specs(make_cfg(routine()))[0].fingerprint == base.fingerprint  # 同じ YAML なら同じ指紋


def test_register_script_daily_and_logon() -> None:
    s = specs(make_cfg(routine()))[0]
    ps = register_script(s)
    assert "New-ScheduledTaskTrigger -Daily -At '08:30'" in ps
    assert "-AtLogOn -User $user" in ps and "$logon.Delay = 'PT2M'" in ps
    assert "-LogonType Interactive -RunLevel Limited" in ps
    assert "-StartWhenAvailable -MultipleInstances IgnoreNew" in ps
    assert "(New-TimeSpan -Minutes 30)" in ps
    assert "-AllowStartIfOnBatteries" in ps and "WakeToRun" not in ps
    assert f"-TaskPath '{TASK_PATH}'" in ps
    assert f"-Execute '{CONHOST}'" in ps
    assert "run morning-brief --scheduled" in ps


def test_register_script_weekly_and_quoting() -> None:
    cfg = make_cfg(
        routine(schedule={"daily_at": ["07:00", "18:00"], "weekdays": ["mon", "fri"]}, description="Bob's 朝")
    )
    ps = register_script(specs(cfg)[0])
    assert ps.count("-Weekly -DaysOfWeek Monday,Friday") == 2
    assert "-At '18:00'" in ps
    assert "AtLogOn" not in ps
    assert "Bob''s 朝" in ps  # 単一引用符は 2 つに


def test_plan_changes() -> None:
    a, b = specs(make_cfg(routine("a1"), routine("b1")))
    current = [
        RegisteredTask(name="a1", description=a.task_description),
        RegisteredTask(name="b1", description="job-hunt routine b1 [spec:000000000000]"),
        RegisteredTask(name="old", description="手で作った"),
    ]
    kinds = {c.routine: c.kind for c in plan_changes([a, b], current)}
    assert kinds == {"a1": "unchanged", "b1": "update", "old": "remove"}
    assert [c.kind for c in plan_changes([a], [])] == ["create"]


def test_unregister_script_deletes_empty_folder() -> None:
    ps = unregister_script(["a1", "o'k"])
    assert f"Unregister-ScheduledTask -TaskName 'a1' -TaskPath '{TASK_PATH}' -Confirm:$false" in ps
    assert "'o''k'" in ps
    assert "DeleteFolder('job-hunt', 0)" in ps


def test_list_tasks_parses_single_object_and_errors() -> None:
    one = {
        "name": "a1",
        "state": "Ready",
        "description": "x [spec:abcdefabcdef]",
        "action": "conhost.exe --headless ...",
        "triggers": "DailyTrigger 2026-10-28T08:30:00",
        "last_run": None,
        "last_result": 267011,
        "next_run": "2026-10-29 08:30:00",
        "extra": 1,
    }
    sched = Scheduler(runner=lambda script: (0, json.dumps(one), ""))
    [t] = sched.list_tasks()
    assert t.fingerprint == "abcdefabcdef" and t.triggers == ["DailyTrigger 2026-10-28T08:30:00"]
    assert Scheduler(runner=lambda script: (0, "[]", "")).list_tasks() == []

    with pytest.raises(SchedulerError, match="アクセスが拒否"):
        Scheduler(runner=lambda script: (1, "", "Register-ScheduledTask : アクセスが拒否されました")).list_tasks()


def test_apply_skips_unchanged() -> None:
    a, b = specs(make_cfg(routine("a1"), routine("b1")))
    calls: list[str] = []
    sched = Scheduler(runner=lambda script: (calls.append(script), (0, "", ""))[1])
    changes = plan_changes([a, b], [RegisteredTask(name="a1", description=a.task_description), RegisteredTask("gone")])
    sched.apply(changes)
    assert len(calls) == 2
    assert "-TaskName 'b1'" in calls[0] and "Unregister-ScheduledTask -TaskName 'gone'" in calls[1]


def test_toast_text() -> None:
    payload = {
        "summary": "s",
        "tasks": [
            {"title": "低い", "reason": "", "priority": "low"},
            {"title": "面談の返信", "reason": "", "priority": "high"},
        ],
    }
    title, body = toast_text("morning-brief", "partial", payload, 2)
    assert title == "今日やること 2 件（一部失敗）（morning-brief）"
    assert body.splitlines() == ["最優先: 面談の返信", "ほかに実行時の対応 2 件（ログイン・許可ルール等）"]
    assert toast_text("r", "failed", None, 0)[1] == "ブリーフを作れなかった。実行結果を確認する"
    assert toast_text("r", "ok", {"summary": "", "tasks": []}, 0)[1] == "やることは無い"


def test_toast_xml_escapes_and_is_reminder() -> None:
    uri = Path(r"C:\repo\data\automation\briefs\2026-10-28_r&1.md").as_uri()
    xml = toast_xml("<件> & 'x'", "1 行目\n2 行目", uri)
    doc = parseString(xml)
    toast = doc.documentElement
    assert toast.getAttribute("scenario") == "reminder"
    assert [t.firstChild.data for t in doc.getElementsByTagName("text")] == ["<件> & 'x'", "1 行目", "2 行目"]
    open_action = doc.getElementsByTagName("action")[0]
    assert open_action.getAttribute("activationType") == "protocol"
    assert open_action.getAttribute("arguments") == uri
