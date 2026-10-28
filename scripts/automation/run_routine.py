"""定期実行エージェントルーチンの YAML を検証・実行する CLI.

ルーチン定義（既定: vault/automation/routines.yaml、雛形: templates/vault/automation/routines.yaml）を読み、
claude / agy の無人実行で「今日ユーザーがやること」のブリーフを作る。

サブコマンド:
- ``validate``: YAML のスキーマ・ステップ間の参照・prompt_file の実在を検査する（実行はしない）
- ``run <routine>``: ステップを順に実行し、ブリーフを data/automation/briefs/ に書く。
  ``--dry-run`` は CLI を呼ばず、組み立てたコマンドとプロンプトを data/automation/runs/ に書くだけ。
  ``once_per_day`` のルーチンは同じ日の 2 回目以降は何もしない（``--force`` で再実行）。
  ``--scheduled``（タスク スケジューラからの起動）は ``schedule.weekdays`` 外の曜日なら何もしない
- ``last [routine]``: 直近のブリーフのパス
- ``register``: YAML の ``schedule`` から Windows タスク スケジューラ（フォルダ job-hunt）にタスクを登録・上書きし、
  YAML から消えた・無効にしたルーチンのタスクは削除する。OS の設定を変えるので、先に ``--dry-run`` で差分を見る
- ``unregister [routine]``: タスクを解除する（省略時は全部。空になったタスクフォルダも消す）
- ``status``: 登録状態・前回の結果・次回実行時刻と YAML との差分

.agents/rules/scripts-entrypoint.md 規約に準拠し、標準出力にはファイルパスのみを出力する
（validate: 検査した YAML / run: ブリーフ（ブリーフが無いルーチンは実行ログ run.json、--dry-run は dry-run.md）/
last: ブリーフ / register・unregister・status: data/automation/scheduler/ の結果 Markdown）。実行済み・実行中で何もしなかったときは、直近のブリーフのパスを出して終了コード 0。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# プロジェクトルートパス (scripts/automation/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.automation.config import (  # noqa: E402
    AgentStep,
    ConfigError,
    RoutinesConfig,
    config_warnings,
    load_config,
)
from scripts.automation.engine import RoutineRunner, RunOutcome, load_state  # noqa: E402
from scripts.automation.scheduler import (  # noqa: E402
    TASK_PATH,
    Change,
    Scheduler,
    SchedulerError,
    build_specs,
    changes_markdown,
    plan_changes,
)
from scripts.common.cli import EntrypointContext, create_base_parser, entrypoint_guard, to_relative_path  # noqa: E402
from scripts.common.paths import AUTOMATION_CONFIG_PATH, AUTOMATION_DATA_DIR  # noqa: E402


def routines_dict(cfg: RoutinesConfig) -> list[dict]:
    """--json / --summary 用のルーチン一覧."""
    out = []
    for r in cfg.routines:
        out.append(
            {
                "id": r.id,
                "enabled": r.enabled,
                "schedule": r.schedule.model_dump() if r.schedule else None,
                "steps": [
                    {
                        "id": s.id,
                        "kind": s.kind,
                        "agent": (s.agent or cfg.defaults.agent) if isinstance(s, AgentStep) else None,
                        "when": s.when if isinstance(s.when, str) else dict(s.when.conditions()),
                    }
                    for s in r.steps
                ],
                "brief": r.brief.step if r.brief else None,
            }
        )
    return out


def latest_brief(routine_id: str | None) -> Path | None:
    """状態ファイルの最終ブリーフ（無ければ briefs/ の最新ファイル）."""
    state = load_state(AUTOMATION_DATA_DIR / "state.json")
    entries = [state.get(routine_id) or {}] if routine_id else list(state.values())
    found = [PROJECT_ROOT / e["last_brief"] for e in entries if isinstance(e, dict) and e.get("last_brief")]
    found = [p for p in found if p.is_file()]
    if not found:
        pattern = f"*_{routine_id}*.md" if routine_id else "*.md"
        found = list((AUTOMATION_DATA_DIR / "briefs").glob(pattern))
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def write_scheduler_report(name: str, changes: list[Change], title: str) -> Path:
    """register / unregister / status の結果を data/automation/scheduler/{name}.md（と .json）に書く."""
    out_dir = AUTOMATION_DATA_DIR / "scheduler"
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / f"{name}.md"
    md.write_text(changes_markdown(changes, title=title), encoding="utf-8")
    md.with_suffix(".json").write_text(
        json.dumps([c.to_dict() for c in changes], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return md


def print_changes(changes: list[Change]) -> None:
    for c in changes:
        line = f"- {TASK_PATH}{c.routine}: {c.kind}"
        if c.spec is not None:
            line += f" / {', '.join(c.spec.triggers_text())}"
        if c.current is not None and c.kind != "remove":
            line += f" / 前回: {c.current.last_run or '未実行'}（{c.current.last_result}） 次回: {c.current.next_run or '-'}"
        print(line)


def run_scheduler_command(ctx: EntrypointContext, args, cfg: RoutinesConfig, config_path: Path) -> None:
    """register / unregister / status. 失敗したら終了コード 1."""
    if sys.platform != "win32":
        ctx.error("タスク スケジューラの操作は Windows でだけ使える")
        sys.exit(1)
    sched = Scheduler()
    config_arg = None if config_path.resolve() == AUTOMATION_CONFIG_PATH.resolve() else to_relative_path(config_path)
    try:
        current = sched.list_tasks()
        if args.command == "unregister":
            names = [t.name for t in current if args.routine in (None, t.name)]
            if args.routine and not names:
                ctx.warn(f"{TASK_PATH}{args.routine} は登録されていない")
            changes = [Change("remove", t.name, None, t) for t in current if t.name in names]
            if not args.dry_run and names:
                sched.unregister(names)
            title = f"タスク解除{'（dry-run）' if args.dry_run else ''}"
        else:
            changes = plan_changes(build_specs(cfg, config_arg=config_arg), current)
            if args.command == "register" and not args.dry_run:
                todo = [c for c in changes if c.kind != "unchanged"]
                sched.apply(todo)
                # 登録後の状態（次回実行時刻など）で書き直す
                after = {t.name: t for t in sched.list_tasks()}
                for c in changes:
                    if c.kind != "remove":
                        c.current = after.get(c.routine)
            title = {
                "status": "タスク スケジューラの状態",
                "register": f"タスク登録{'（dry-run: まだ登録していない）' if args.dry_run else ''}",
            }[args.command]
    except SchedulerError as e:
        ctx.error(str(e))
        sys.exit(1)

    pending = [c for c in changes if c.kind != "unchanged"]
    if args.command == "status":
        ctx.info(
            f"登録 {len(current)} 件 / YAML との差分 {len(pending)} 件" + ("（register で反映）" if pending else "")
        )
    else:
        verb = "予定" if args.dry_run else "実施"
        ctx.info(f"{title}: 変更{verb} {len(pending)} 件")
    ctx.add_result_path(write_scheduler_report(args.command, changes, title))
    sys.exit(ctx.flush_outputs(lambda: print_changes(changes), {"changes": [c.to_dict() for c in changes]}))


def report_run(ctx: EntrypointContext, outcome: RunOutcome) -> None:
    if outcome.status != "completed":
        ctx.info(outcome.message)
        if outcome.brief_path is not None and outcome.brief_path.is_file():
            ctx.add_result_path(outcome.brief_path)
        return
    failed = [r.id for r in outcome.results if r.status == "failed"]
    skipped = [r.id for r in outcome.results if r.status == "skipped"]
    ctx.info(
        f"{outcome.routine}: {len(outcome.results)} ステップ"
        + (f" / 失敗: {', '.join(failed)}" if failed else "")
        + (f" / スキップ: {', '.join(skipped)}" if skipped else "")
    )
    if outcome.brief_path is not None:
        ctx.add_result_path(outcome.brief_path)
    elif outcome.run_dir is not None:
        ctx.add_result_path(outcome.run_dir / "run.json")


def main() -> None:
    parser = create_base_parser(
        examples=[
            "uv run python scripts/automation/run_routine.py validate --summary",
            "uv run python scripts/automation/run_routine.py run morning-brief --dry-run  # コマンドとプロンプトだけ",
            "uv run python scripts/automation/run_routine.py run morning-brief --force -s  # 今日 2 回目でも実行",
            "uv run python scripts/automation/run_routine.py register --dry-run -s  # 登録内容と差分だけ見る",
            "uv run python scripts/automation/run_routine.py status -s",
        ],
        related=[
            "scripts/vault/find_chores.py: ルーチンの script ステップで雑務を洗い出す",
        ],
    )
    parser.add_argument(
        "command",
        choices=["validate", "run", "last", "register", "unregister", "status"],
        help="validate: YAML を検査する / run: ルーチンを実行する / last: 直近のブリーフのパス / "
        "register・unregister・status: タスク スケジューラへの登録・解除・状態確認",
    )
    parser.add_argument("routine", nargs="?", help="ルーチン id（run では必須、last・unregister では任意）")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run: CLI を呼ばず、コマンドとプロンプトだけを書き出す / register・unregister: 差分だけ出して変更しない",
    )
    parser.add_argument(
        "--scheduled",
        action="store_true",
        help="run: タスク スケジューラからの起動（schedule.weekdays 外の曜日なら何もしない）",
    )
    # --force は共通パーサーにある（run: 今日実行済みでも実行する。once_per_day を無視）
    parser.add_argument(
        "--config",
        type=Path,
        default=AUTOMATION_CONFIG_PATH,
        help="ルーチン定義 YAML（既定: vault/automation/routines.yaml）",
    )
    args = parser.parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        if args.command == "last":
            path = latest_brief(args.routine)
            if path is None:
                ctx.error("ブリーフがまだ無い")
                sys.exit(1)
            ctx.add_result_path(path)
            sys.exit(ctx.flush_outputs())
        if args.command == "run" and not args.routine:
            parser.error("run にはルーチン id を指定する")
        if args.command in ("register", "status") and args.routine:
            parser.error(f"{args.command} はルーチン id を取らない（YAML の全ルーチンが対象）")

        config_path: Path = args.config if args.config.is_absolute() else PROJECT_ROOT / args.config
        try:
            cfg = load_config(config_path)
        except ConfigError as e:
            ctx.error(f"{to_relative_path(e.path)}: {len(e.errors)} 件のエラー")
            for msg in e.errors:
                ctx.log(f"  - {msg}")
            sys.exit(1)

        for w in config_warnings(cfg):
            ctx.warn(w)

        if args.command in ("register", "unregister", "status"):
            run_scheduler_command(ctx, args, cfg, config_path)

        if args.command == "run":
            try:
                cfg.routine(args.routine)
            except KeyError as e:
                ctx.error(str(e.args[0]))
                sys.exit(1)
            runner = RoutineRunner(cfg, config_path, dry_run=args.dry_run, log=ctx.log)
            outcome = runner.run(args.routine, force=args.force, scheduled=args.scheduled)
            report_run(ctx, outcome)

            def print_run_summary() -> None:
                print(outcome.message or f"{outcome.routine}: {outcome.status}")
                for r in outcome.results:
                    print(f"- {r.id} [{r.kind}] {r.status}" + (f": {r.reason}" if r.reason else ""))
                for p in ctx.result_paths:
                    print(p)

            run_json = {
                "status": outcome.status,
                "routine": outcome.routine,
                "paths": ctx.result_paths,
                "steps": [r.to_dict() for r in outcome.results],
                "notices": [n.__dict__ for n in runner.notices],
            }
            sys.exit(ctx.flush_outputs(print_run_summary, run_json))

        ctx.add_result_path(config_path)
        ctx.info(f"OK: ルーチン {len(cfg.routines)} 件")
        routines = routines_dict(cfg)

        def print_summary() -> None:
            print(f"{config_path.name}: ルーチン {len(routines)} 件")
            for r in routines:
                sched = r["schedule"]
                when = "手動のみ"
                if sched:
                    parts = [*sched["daily_at"], *(["ログオン時"] if sched["on_logon"] else [])]
                    when = ", ".join(parts) or "トリガー無し"
                    if sched["weekdays"]:
                        when += f"（{'/'.join(sched['weekdays'])}）"
                print(f"- {r['id']}{'' if r['enabled'] else '（無効）'}: {when} / ブリーフ: {r['brief'] or '-'}")
                for s in r["steps"]:
                    cond = "" if s["when"] == "always" else f"  when={s['when']}"
                    print(f"    {s['id']} [{s['kind']}{':' + s['agent'] if s['agent'] else ''}]{cond}")

        sys.exit(ctx.flush_outputs(print_summary, {"config": ctx.result_paths[0], "routines": routines}))


if __name__ == "__main__":
    main()
