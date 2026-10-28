"""data/ の保持期間を過ぎた生データを一覧・削除する CLI.

既定は dry-run（削除候補のパスを出すだけ）。``--apply`` で削除し、自動実行の最終実行時刻も更新する。
保持ポリシー表・保護対象・取得日の判定は scripts/common/data_retention.py が正。

    uv run python scripts/vault/prune_data.py -s                # 削除候補（vault から参照されて残すものも表示）
    uv run python scripts/vault/prune_data.py --days 30 -s      # 保持期間を変えて試す
    uv run python scripts/vault/prune_data.py --apply -s        # 削除する
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

# プロジェクトルートパス (scripts/vault/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import create_base_parser, entrypoint_guard
from scripts.common.data_retention import DEFAULT_RETENTION_DAYS, delete_units, find_expired, write_state


def main() -> None:
    parser = create_base_parser(
        description="data/ の保持期間を過ぎた生データを一覧・削除する（既定は dry-run）",
        examples=[
            "uv run python scripts/vault/prune_data.py -s  # 削除候補と、vault から参照されていて残すもの（dry-run）",
            "uv run python scripts/vault/prune_data.py --days 30 -s  # 保持日数を変えて試す",
            "uv run python scripts/vault/prune_data.py --apply -s  # 削除する",
        ],
        related=[
            "scripts/vault/add_material.py: 残したい内容は先に material の要約にする（--refresh で取り直し）",
        ],
    )
    parser.add_argument("--apply", action="store_true", help="実際に削除する（指定しなければ候補を出すだけ）")
    parser.add_argument("--days", type=int, default=DEFAULT_RETENTION_DAYS, help=f"保持日数（既定: {DEFAULT_RETENTION_DAYS}）")
    parser.add_argument(
        "--root", type=Path, default=PROJECT_ROOT, help="data/ と vault/ を含むディレクトリ（既定: リポジトリルート）"
    )
    parser.add_argument(
        "--today", type=dt.date.fromisoformat, default=dt.date.today(), help="基準日（YYYY-MM-DD、既定: 今日）"
    )
    args = parser.parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        root = args.root if args.root.is_absolute() else PROJECT_ROOT / args.root
        data_dir = root / "data"
        units = find_expired(args.today, args.days, data_dir=data_dir, vault_dir=root / "vault")
        removable = [u for u in units if not u.protected_by]
        kept = [u for u in units if u.protected_by]
        if args.apply:
            removable = delete_units(removable)
            if root == PROJECT_ROOT:
                write_state(dt.datetime.now(), len(removable), state_path=data_dir / ".prune_state.json")

        for unit in removable:
            ctx.add_result_paths(unit.paths)
        verb = "削除" if args.apply else "削除候補"
        ctx.info(f"{verb} {len(removable)} 件 / vault から参照されていて残す {len(kept)} 件（保持 {args.days} 日、基準日 {args.today}）")

        def print_summary() -> None:
            print(f"## {verb}（{len(removable)} 件、{args.today - dt.timedelta(days=args.days)} より前に取得）")
            for unit in removable:
                print(f"- {unit.fetched}（{unit.date_source}） {', '.join(unit.rel_paths(data_dir))}")
            if kept:
                print(f"\n## 保持期間切れだが vault から参照されているので残す（{len(kept)} 件。material 化して参照を外す）")
                for unit in kept:
                    print(f"- {unit.fetched} {', '.join(unit.rel_paths(data_dir))} ← {unit.protected_by}")

        json_data = {
            "today": args.today.isoformat(),
            "days": args.days,
            "applied": args.apply,
            "removable": [
                {"paths": u.rel_paths(data_dir), "fetched": u.fetched.isoformat() if u.fetched else None, "date_source": u.date_source}
                for u in removable
            ],
            "kept": [{"paths": u.rel_paths(data_dir), "referenced_by": u.protected_by} for u in kept],
        }
        sys.exit(ctx.flush_outputs(summary_fn=print_summary, json_data=json_data))


if __name__ == "__main__":
    main()
