"""メッセージ共通データモデル (scripts.common.models.message).

各転職サイトのメッセージ・スカウト一覧取得（navigate_messages.py）および
スレッド詳細取得で扱う構造化データモデル（Pydantic v2）を提供します。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MessageItem(BaseModel):
    """個別メッセージ・スカウトの構造化モデル."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    # 主要共通フィールド
    id: str | int | None = None
    sender: str = ""
    company: str = ""
    subject: str = ""
    body: str = ""
    snippet: str = ""
    url: str = ""
    date: str | None = None
    is_unread: bool = False
    scout_type: str = "通常"
    deadline: str | None = None
    job_url: str | None = None
    job_title: str | None = None
    raw_text: str = ""

    # サイト固有拡張メタデータ (badges, attachedJobs, threadId, isReplied, etc.)
    extra_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_input(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        d = dict(data)
        extra = dict(d.get("extra_metadata") or {})

        # キャメルケースや別名キーの正規化マッピング
        alias_map = {
            "isUnread": "is_unread",
            "scoutType": "scout_type",
            "jobUrl": "job_url",
            "jobTitle": "job_title",
            "rawText": "raw_text",
            "sentAt": "date",
            "threadUrl": "url",
            "companyName": "company",
            "senderName": "sender",
            "name": "sender",
            "latestMessage": "body",
        }

        # 定義済みフィールド名（正規名）
        defined_fields = {
            "id",
            "sender",
            "company",
            "subject",
            "body",
            "snippet",
            "url",
            "date",
            "is_unread",
            "scout_type",
            "deadline",
            "job_url",
            "job_title",
            "raw_text",
            "extra_metadata",
        }

        # エイリアスの解決
        for old_key, new_key in alias_map.items():
            if old_key in d and new_key not in d:
                d[new_key] = d[old_key]

        # 定義外キーを extra_metadata に退避
        for k, v in list(d.items()):
            if k not in defined_fields:
                extra[k] = v

        d["extra_metadata"] = extra
        return d

    def to_dict(self) -> dict[str, Any]:
        """従来の辞書出力（JSON保存・Markdown生成互換用）に変換する."""
        base: dict[str, Any] = {
            "id": self.id,
            "sender": self.sender,
            "company": self.company,
            "subject": self.subject,
            "snippet": self.snippet,
            "url": self.url,
            "date": self.date,
            "isUnread": self.is_unread,
            "is_unread": self.is_unread,
            "scoutType": self.scout_type,
            "scout_type": self.scout_type,
            "deadline": self.deadline,
            "jobUrl": self.job_url,
            "job_url": self.job_url,
            "jobTitle": self.job_title,
            "job_title": self.job_title,
        }
        if self.body:
            base["body"] = self.body
            base["latestMessage"] = self.body
        if self.raw_text:
            base["rawText"] = self.raw_text
            base["raw_text"] = self.raw_text

        # サイト固有の extra_metadata を展開
        for k, v in self.extra_metadata.items():
            if k not in base:
                base[k] = v

        return base


class MessageBatch(BaseModel):
    """メッセージ一覧バッチ全体のメタデータおよびアイテムコレクション."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    source: str
    type: str = "messages"
    tab: str = "all"
    tab_label: str = ""
    fetched_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    url: str = ""
    total_count: int = 0
    fetched_count: int | None = None
    success: bool = True
    title: str = ""
    messages: list[MessageItem] = Field(default_factory=list)
    extra_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_batch(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        d = dict(data)
        extra = dict(d.get("extra_metadata") or {})

        # キャメルケースキー対応
        if "totalCount" in d and "total_count" not in d:
            d["total_count"] = d["totalCount"]
        if "fetchedCount" in d and "fetched_count" not in d:
            d["fetched_count"] = d["fetchedCount"]

        defined_fields = {
            "source",
            "type",
            "tab",
            "tab_label",
            "fetched_at",
            "url",
            "total_count",
            "fetched_count",
            "success",
            "title",
            "messages",
            "extra_metadata",
        }

        for k, v in list(d.items()):
            if k not in defined_fields:
                extra[k] = v

        d["extra_metadata"] = extra
        return d

    def to_dict(self) -> dict[str, Any]:
        """JSON保存用の標準辞書表現."""
        d: dict[str, Any] = {
            "source": self.source.lower(),
            "type": self.type,
            "tab": self.tab,
            "tab_label": self.tab_label,
            "fetched_at": self.fetched_at,
            "success": self.success,
            "url": self.url,
            "totalCount": self.total_count,
            "total_count": self.total_count,
            "fetchedCount": self.fetched_count if self.fetched_count is not None else len(self.messages),
            "fetched_count": self.fetched_count if self.fetched_count is not None else len(self.messages),
            "messages": [m.to_dict() for m in self.messages],
        }
        if self.title:
            d["title"] = self.title

        for k, v in self.extra_metadata.items():
            if k not in d:
                d[k] = v

        return d
