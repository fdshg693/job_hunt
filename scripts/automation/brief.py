"""ブリーフ（今日ユーザーがやること）の出力スキーマと Markdown 整形.

ブリーフのステップ（``routines[].brief.step``）には ``BRIEF_SCHEMA`` を構造化出力として付け、
返ったタスク配列を ``render_brief`` で Markdown にする。エージェントが返したタスクに加えて、
実行エンジンが見つけた「ユーザーがやること」（ログイン・許可ルールの追加・失敗したステップの再実行）と
警告（読み取り専用のはずのステップによる無断の変更）も載せる。機械の判定だけで落とさず、
スキップしたステップも理由付きで残す（goal.md「調査スキップ時の理由明記義務」）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from scripts.automation.engine import StepResult

PRIORITY_LABELS = {"high": "高", "medium": "中", "low": "低"}

BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "tasks"],
    "properties": {
        "summary": {"type": "string", "description": "今日の全体像を 1〜3 文で"},
        "tasks": {
            "type": "array",
            "description": "今日ユーザーがやるべき作業。優先度の高い順",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "reason", "priority"],
                "properties": {
                    "title": {"type": "string", "description": "やること（動詞で終える 1 行）"},
                    "reason": {"type": "string", "description": "なぜ今日やるのか・判断材料"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "due": {"type": "string", "description": "期限（YYYY-MM-DD または YYYY-MM-DD HH:MM）。無ければ空"},
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "関連するファイル（リポジトリルート相対）",
                    },
                    "source": {"type": "string", "description": "根拠にした材料（雑務・メール・予定 等）"},
                },
            },
        },
        "unverified": {
            "type": "array",
            "items": {"type": "string"},
            "description": "確かめられなかったこと",
        },
    },
}

BRIEF_INSTRUCTIONS = """
## 出力
出力スキーマに従って返してください。
- tasks: 今日ユーザーがやるべき作業を優先度の高い順に。期限が今日・明日のもの、相手を待たせているもの、
  取り消しにくい判断が要るものを high にする。やることが無ければ空配列。
- unverified: 材料が足りず確かめられなかったこと。
""".rstrip()


@dataclass
class Notice:
    """実行エンジンが見つけた、ブリーフに載せる事項."""

    kind: Literal["warning", "user_task"]
    title: str
    detail: str = ""
    step: str | None = None


@dataclass
class BriefData:
    routine: str
    date: str
    generated_at: str
    results: list[StepResult]
    notices: list[Notice] = field(default_factory=list)
    brief_step: str | None = None
    vault_diff_stat: str = ""
    dry_run: bool = False

    @property
    def brief_result(self) -> StepResult | None:
        return next((r for r in self.results if r.id == self.brief_step), None)

    @property
    def payload(self) -> dict[str, Any] | None:
        r = self.brief_result
        return r.structured if r is not None and isinstance(r.structured, dict) else None

    @property
    def status(self) -> str:
        if self.payload is None:
            return "failed"
        if any(r.status == "failed" for r in self.results) or any(n.kind == "warning" for n in self.notices):
            return "partial"
        return "ok"


def _md_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _task_lines(i: int, task: dict[str, Any]) -> list[str]:
    prio = PRIORITY_LABELS.get(str(task.get("priority")), str(task.get("priority", "")))
    head = f"### {i}. [{prio}] {task.get('title', '(無題)')}"
    if due := task.get("due"):
        head += f"（期限: {due}）"
    lines = [head, "", str(task.get("reason", "")).strip()]
    meta = []
    # ブリーフは data/automation/briefs/ に置くので、リポジトリルートへは 3 階層上がる
    if files := [f for f in task.get("files") or [] if f]:
        meta.append("- 関連: " + ", ".join(f"[{f}](../../../{f})" for f in files))
    if src := task.get("source"):
        meta.append(f"- 出典: {src}")
    if meta:
        lines += ["", *meta]
    lines.append("")
    return lines


def render_brief(data: BriefData) -> str:
    """ブリーフを Markdown（フロントマター付き）にする. ファイルは data/automation/briefs/ に置く前提."""
    payload = data.payload
    tasks = list(payload.get("tasks") or []) if payload else []
    costs = [r.cost_usd for r in data.results if r.cost_usd is not None]
    front = {
        "routine": data.routine,
        "date": data.date,
        "generated_at": data.generated_at,
        "status": data.status,
        "tasks": len(tasks),
        "user_tasks_from_runner": sum(n.kind == "user_task" for n in data.notices),
        "warnings": sum(n.kind == "warning" for n in data.notices),
    }
    if costs:
        front["cost_usd"] = round(sum(costs), 4)
    if data.dry_run:
        front["dry_run"] = True
    out = ["---", *(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in front.items()), "---", ""]
    out += [f"# 今日やること（{data.date}・{data.routine}）", ""]

    warnings = [n for n in data.notices if n.kind == "warning"]
    if warnings:
        out += ["> [!WARNING]"]
        for n in warnings:
            out.append(f"> **{n.title}**" + (f"（{n.step}）" if n.step else ""))
            out += [f"> {line}" for line in n.detail.splitlines() if line.strip()]
        out.append("")

    if payload is None:
        r = data.brief_result
        why = (r.reason or r.status) if r is not None else "ブリーフのステップが設定されていない"
        out += [f"ブリーフを作れなかった: {why}", ""]
        if r is not None and r.output.strip():
            out += [
                "<details><summary>ブリーフのステップの生の応答</summary>",
                "",
                r.output.strip(),
                "",
                "</details>",
                "",
            ]
    else:
        if summary := str(payload.get("summary") or "").strip():
            out += [summary, ""]
        out += ["## やること", ""]
        if tasks:
            for i, t in enumerate(tasks, 1):
                out += _task_lines(i, t)
        else:
            out += ["今日やることは見つからなかった。", ""]

    user_tasks = [n for n in data.notices if n.kind == "user_task"]
    if user_tasks:
        out += ["## 自動実行のためにやること", ""]
        for n in user_tasks:
            line = f"- **{n.title}**" + (f"（{n.step}）" if n.step else "")
            out.append(line + (f": {n.detail}" if n.detail else ""))
        out.append("")

    if payload and (unverified := [u for u in payload.get("unverified") or [] if u]):
        out += ["## 確かめられなかったこと", "", *(f"- {u}" for u in unverified), ""]

    if data.vault_diff_stat.strip():
        out += [
            "## vault の変更（未コミット。確認してコミットするのはユーザー）",
            "",
            "```",
            data.vault_diff_stat.rstrip(),
            "```",
            "",
        ]

    out += ["## 実行結果", "", "| ステップ | 種類 | 結果 | 時間 | 備考 |", "| --- | --- | --- | --- | --- |"]
    for r in data.results:
        note = r.reason or ""
        if r.cost_usd is not None:
            note = (note + f" ${r.cost_usd:.3f}").strip()
        out.append(
            f"| {r.id} | {r.kind}{':' + r.agent if r.agent else ''} | {r.status} | {r.duration_seconds:.0f}s | {_md_cell(note)} |"
        )
    out.append("")
    return "\n".join(out)
