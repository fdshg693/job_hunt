"""Gmail ラベル規則（就活メールの範囲と分類）の正本.

このリポジトリが読むのは `JOB` ラベルとその下位ラベル（`JOB/...`）が付いたメールだけ。
ラベルの付与はユーザーが Gmail で行う（スコープは gmail.readonly なので、こちらからは付けられない）。
規則を変えるときはこのファイルだけを直し、docs/gmail/README.md と .agents/rules/gmail.md の説明を合わせる。
"""

from __future__ import annotations

from typing import Any

from scripts.gmail.client import execute

# このリポジトリで扱うメールの範囲を決める親ラベル
ROOT_LABEL = "JOB"

# 分類ラベル: CLI の --label に渡すキー → (Gmail のラベル名, 意味)
CATEGORIES: dict[str, tuple[str, str]] = {
    "recruiter": ("JOB/RECRUITER", "リクルーター・エージェント・ヘッドハンターとのやり取り"),
    "schedule": ("JOB/SCHEDULE", "面談・面接などの日程調整"),
}


class LabelSetupError(Exception):
    """規則で決めたラベルが Gmail に無い（ユーザーが Gmail でラベルを作る必要がある）."""


def _is_under(name: str, parent: str) -> bool:
    """name が parent そのもの、または parent の下位ラベルか（Gmail のラベル名は大文字小文字を区別しない）."""
    name, parent = name.casefold(), parent.casefold()
    return name == parent or name.startswith(parent + "/")


def is_job_label(name: str) -> bool:
    return _is_under(name, ROOT_LABEL)


def fetch_label_names(service: Any) -> dict[str, str]:
    """ラベル ID → ラベル名の対応を取る（システムラベルは ID と名前が同じ）."""
    resp = execute(service.users().labels().list(userId="me"))
    return {label["id"]: label["name"] for label in resp.get("labels", [])}


def label_names_of(label_ids: list[str], label_names: dict[str, str]) -> list[str]:
    """ラベル ID の並びを名前にする（対応が無い ID はそのまま）."""
    return sorted({label_names.get(i, i) for i in label_ids})


def has_job_label(label_ids: list[str], label_names: dict[str, str]) -> bool:
    return any(is_job_label(label_names.get(i, i)) for i in label_ids)


def _search_term(name: str) -> str:
    """ラベル名を Gmail 検索の label: 語にする（`/` と空白はハイフンに置き換える）."""
    return "label:" + name.replace("/", "-").replace(" ", "-").lower()


def scope_query(label_names: dict[str, str], category: str | None = None) -> str:
    """検索範囲を JOB 配下（category 指定時はその分類ラベル配下）に限る Gmail 検索語を作る.

    Gmail の label: は下位ラベルを含まないので、配下のラベルを列挙して OR にする。
    """
    parent = CATEGORIES[category][0] if category else ROOT_LABEL
    names = sorted(n for n in set(label_names.values()) if _is_under(n, parent))
    if not any(n.casefold() == parent.casefold() for n in names):
        raise LabelSetupError(
            f"Gmail にラベル「{parent}」がありません。Gmail でラベルを作り、就活メールに付けてください"
            "（規則: scripts/gmail/labels.py、手順: docs/gmail/README.md）。"
        )
    terms = [_search_term(n) for n in names]
    return terms[0] if len(terms) == 1 else "{" + " ".join(terms) + "}"
