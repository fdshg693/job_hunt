"""YOUTRUST のチャット一覧・スレッド本文を取得して保存する CLI.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
YOUTRUSTのログイン状態確認・未ログイン時の通知待機ハンドオフ・チャットルーム画面（/chat_rooms）からの
メッセージ一覧抽出・個別スレッド本文取得・構造化フロントマター付きMarkdownおよびJSON形式での永続化を実行します。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/youtrust/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.browser_auth import (
    resolve_profile_path,
    run_code_script,
    run_playwright_cmd,
    update_profile_last_used,
)
from scripts.common.crawlers.message_pipeline import (
    MessageCrawlerConfig,
    MessagePipelineContext,
    run_message_pipeline,
)
from scripts.common.models.message import MessageBatch, MessageItem

YOUTRUST_SCRIPTS_DIR = Path(__file__).resolve().parent
NAVIGATE_SCRIPT_PATH = YOUTRUST_SCRIPTS_DIR / "navigate_messages.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "youtrust" / "messages"
BASE_URL = "https://youtrust.jp/chat_rooms"

BOX_TYPE_LABEL_MAP = {
    "all": "すべてのチャット",
    "scout": "スカウト・採用関連",
    "unread": "未読メッセージ",
    "sales": "営業・提案チャット",
}


def format_timestamp(ts: int | float | None) -> str:
    """UNIX秒タイムスタンプを表示用文字列に変換する."""
    if not ts:
        return "-"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def execute_navigate_messages(
    session: str,
    box_type: str = "all",
    limit: int = 0,
    fetch_threads: bool = False,
    room_id: str = "",
    mark_as_read: bool = False,
    timeout: int = 60,
) -> dict[str, Any]:
    """navigate_messages.mjs にパラメータを注入して実行する."""
    if not NAVIGATE_SCRIPT_PATH.exists():
        raise RuntimeError(f"メッセージスクリプトが見つかりません: {NAVIGATE_SCRIPT_PATH}")

    profile_path = resolve_profile_path(session)
    run_playwright_cmd([f"-s={session}", "open", BASE_URL, f"--profile={profile_path}"])

    template_code = NAVIGATE_SCRIPT_PATH.read_text(encoding="utf-8")
    run_code = (
        template_code.replace("'__BOX_TYPE__'", json.dumps(box_type))
        .replace("'__LIMIT__'", json.dumps(str(limit)))
        .replace("__FETCH_THREADS__", "true" if fetch_threads else "false")
        .replace("'__ROOM_ID__'", json.dumps(room_id or ""))
        .replace("__MARK_AS_READ__", "true" if mark_as_read else "false")
    ).strip().rstrip(";")

    tmp_script_path = YOUTRUST_SCRIPTS_DIR / f".tmp_navigate_{box_type}_{room_id or 'all'}.mjs"
    tmp_script_path.write_text(run_code, encoding="utf-8")

    try:
        result = run_code_script(session, tmp_script_path, timeout=timeout)
        if not result:
            raise RuntimeError("Playwrightスクリプトの実行に失敗しました")
        if not result.get("success"):
            err = result.get("error") or "不明なエラー"
            raise RuntimeError(f"メッセージ取得エラー: {err}")
        update_profile_last_used(session)
        return result
    finally:
        if tmp_script_path.exists():
            try:
                tmp_script_path.unlink()
            except Exception:
                pass


def generate_room_markdown(room: dict[str, Any], now: datetime) -> str:
    """単一チャットルーム（スレッド詳細）用のMarkdownを整形する."""
    room_id = room.get("id") or ""
    other = room.get("otherUser") or {}
    name = other.get("name") or room.get("displayName") or "名前不明"
    company = other.get("companyName") or "-"
    room_url = f"https://youtrust.jp/chat_rooms/{room_id}"
    thread = room.get("thread") or []
    fetched_at_str = now.isoformat(timespec="seconds")

    lines = [
        "---",
        "source: youtrust",
        "type: chat_room",
        f"room_id: '{room_id}'",
        f"display_name: '{name}'",
        f"company: '{company}'",
        f"chat_room_type: '{room.get('chatRoomType') or ''}'",
        f"unread_count: {room.get('unreadCount', 0)}",
        f"fetched_at: '{fetched_at_str}'",
        f"url: '{room_url}'",
        f"message_count: {len(thread)}",
        "---",
        "",
        f"# YOUTRUST チャットルーム: {name}（{company}）",
        "",
        f"- 取得日時: {now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- ルームID: `{room_id}`",
        f"- ルームURL: [{room_url}]({room_url})",
        f"- 未読件数: {room.get('unreadCount', 0)} 件",
        "",
        "## 送信者プロフィール",
        "",
        f"- **氏名**: {other.get('name') or '-'}",
        f"- **企業**: {other.get('companyName') or '-'}",
        f"- **職種**: {', '.join(other.get('jobCategories') or []) or '-'}",
        f"- **スキル**: {', '.join(other.get('skills') or []) or '-'}",
    ]

    if other.get("introduction"):
        lines.append("")
        lines.append("### 自己紹介文")
        lines.append("")
        for line in other["introduction"].splitlines():
            lines.append(f"> {line}")

    lines.append("")
    lines.append("## メッセージ履歴")
    lines.append("")

    if not thread:
        if room.get("lastCommentContent"):
            lines.append("### 最新メッセージ（抜粋）")
            lines.append("")
            lines.append("```text")
            lines.append(room["lastCommentContent"].strip())
            lines.append("```")
        else:
            lines.append("> メッセージ履歴がありません。")
    else:
        for idx, msg in enumerate(thread, start=1):
            sender_name = msg.get("sender", {}).get("name") or "不明"
            msg_dt = format_timestamp(msg.get("createdAt"))
            read_dt = f" (既読: {format_timestamp(msg.get('readAt'))})" if msg.get("readAt") else ""
            lines.append(f"### {idx}. {sender_name} ({msg_dt}{read_dt})")
            lines.append("")
            lines.append("```text")
            lines.append((msg.get("rawComment") or msg.get("comment") or "").strip())
            lines.append("```")
            lines.append("")

    return "\n".join(lines)


def generate_markdown(data: dict[str, Any], box_type: str, now: datetime) -> str:
    """メッセージ一覧を構造化フロントマター付きMarkdownに整形する（後方互換用）."""
    box_label = BOX_TYPE_LABEL_MAP.get(box_type, box_type)
    rooms = data.get("rooms", [])
    total_count = data.get("totalCount", len(rooms))
    fetched_at_str = now.isoformat(timespec="seconds")

    lines = [
        "---",
        "source: youtrust",
        "type: messages",
        f"box_type: '{box_type}'",
        f"box_label: '{box_label}'",
        f"fetched_at: '{fetched_at_str}'",
        f"url: '{data.get('url', BASE_URL)}'",
        f"total_count: {total_count}",
        "---",
        "",
        f"# YOUTRUST チャットルーム・メッセージ一覧 [{box_label}] ({now.strftime('%Y-%m-%d %H時')})",
        "",
        f"- 取得日時: {now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 絞り込み: {box_label} (`{box_type}`)",
        f"- 対象URL: {data.get('url', BASE_URL)}",
        f"- 取得件数: {total_count} 件",
        "",
    ]

    if not rooms:
        lines.append("> 該当するチャットルーム・メッセージはありません。\n")
        return "\n".join(lines)

    lines += [
        "## チャットルーム一覧",
        "",
        "| # | 未読 | 種別 | 相手 | 所属企業 / 役職 | 最終送信日時 | 最新メッセージ抜粋 |",
        "|---|---|---|---|---|---|---|",
    ]

    for idx, room in enumerate(rooms, start=1):
        other = room.get("otherUser") or {}
        name = (other.get("name") or room.get("displayName") or "名前不明").replace("|", "\\|")
        company = (other.get("companyName") or "-").replace("|", "\\|")
        jobs = (" / ".join(other.get("jobCategories") or []) or "-").replace("|", "\\|")
        affil = f"{company} ({jobs})" if jobs != "-" else company
        unread = f"● ({room.get('unreadCount')})" if room.get("unreadCount", 0) > 0 else "-"
        rtype = room.get("chatRoomType") or "-"
        last_dt = format_timestamp(room.get("lastCommentedAt"))
        snippet = (room.get("lastCommentContent") or "-")[:80].replace("\n", " ").replace("|", "\\|")

        lines.append(f"| {idx} | {unread} | {rtype} | [{name}](#room-{room.get('id')}) | {affil} | {last_dt} | {snippet} |")
    lines.append("")

    lines += ["## ルーム詳細", ""]

    for idx, room in enumerate(rooms, start=1):
        other = room.get("otherUser") or {}
        name = other.get("name") or room.get("displayName") or "名前不明"
        company = other.get("companyName") or "-"
        room_id = room.get("id") or ""
        room_url = f"https://youtrust.jp/chat_rooms/{room_id}"

        lines.append(f'<a id="room-{room_id}"></a>')
        lines.append(f"### {idx}. {name}（{company}）")
        lines.append("")
        lines.append(f"- **ルームURL**: [{room_url}]({room_url})")
        lines.append(f"- **チャット種別**: {room.get('chatRoomType') or '-'}")
        lines.append(f"- **未読件数**: {room.get('unreadCount', 0)} 件")
        lines.append(f"- **ブックマーク**: {'はい' if room.get('isBookmarked') else 'いいえ'}")
        lines.append(f"- **アーカイブ**: {'はい' if room.get('isArchived') else 'いいえ'}")
        lines.append(f"- **最終メッセージ日時**: {format_timestamp(room.get('lastCommentedAt'))}")

        lines.append("")
        lines.append("#### 相手プロフィール")
        lines.append("")
        lines.append(f"- **氏名**: {other.get('name') or '-'}")
        lines.append(f"- **企業**: {other.get('companyName') or '-'}")
        if other.get("jobCategories"):
            lines.append(f"- **職種**: {', '.join(other['jobCategories'])}")
        account_types = []
        if other.get("isRecruiter"):
            account_types.append("採用担当者")
        if other.get("isHeadhunter"):
            account_types.append("ヘッドハンター")
        if other.get("isSales"):
            account_types.append("営業担当")
        if account_types:
            lines.append(f"- **アカウント属性**: {', '.join(account_types)}")
        if other.get("skills"):
            lines.append(f"- **スキル**: {', '.join(other['skills'])}")
        if other.get("introduction"):
            lines.append("")
            lines.append("> **自己紹介文**:")
            for intro_line in other["introduction"].splitlines():
                lines.append(f"> {intro_line}")

        thread = room.get("thread") or []
        if thread:
            lines.append("")
            lines.append("#### スレッドメッセージ履歴")
            lines.append("")
            for msg in thread:
                sender_name = msg.get("sender", {}).get("name") or "不明"
                msg_dt = format_timestamp(msg.get("createdAt"))
                read_dt = f" (既読: {format_timestamp(msg.get('readAt'))})" if msg.get("readAt") else ""
                lines.append(f"**{sender_name}** ({msg_dt}{read_dt})")
                lines.append("")
                lines.append("```text")
                lines.append((msg.get("rawComment") or msg.get("comment") or "").strip())
                lines.append("```")
                lines.append("")
        elif room.get("lastCommentContent"):
            lines.append("")
            lines.append("#### 最新メッセージ抜粋")
            lines.append("")
            lines.append("```text")
            lines.append(room["lastCommentContent"].strip())
            lines.append("```")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def print_formatted_summary(data: dict[str, Any] | MessageBatch, box_type: str = "all") -> None:
    """メッセージ一覧のサマリをコンソールに整形出力する（後方互換用）."""
    box_label = BOX_TYPE_LABEL_MAP.get(box_type, box_type)
    if isinstance(data, MessageBatch):
        rooms = data.extra_metadata.get("rooms", [])
        total_count = data.total_count if data.total_count is not None else len(rooms)
        url = data.url or BASE_URL
    else:
        rooms = data.get("rooms", [])
        total_count = data.get("totalCount", len(rooms))
        url = data.get("url", BASE_URL)

    print("\n========================================================")
    print(f" YOUTRUST チャットルーム・メッセージ一覧 [{box_label}]")
    print(f" URL:  {url}")
    print(f" 件数: 全 {total_count} 件")
    print("========================================================\n")

    if not rooms:
        print("現在、該当するチャットルーム・メッセージはありません。")
        return

    for idx, room in enumerate(rooms, start=1):
        other = room.get("otherUser") or {}
        name = other.get("name") or room.get("displayName") or "名前不明"
        company = other.get("companyName") or "-"
        categories = " / ".join(other.get("jobCategories") or [])
        unread_badge = f"[未読: {room.get('unreadCount')}件]" if room.get("unreadCount", 0) > 0 else ""
        type_badge = f"[{room.get('chatRoomType') or '通常'}]"
        badges = " ".join(b for b in [unread_badge, type_badge] if b)

        last_comment_dt = format_timestamp(room.get("lastCommentedAt"))

        print(f"[{idx}] {badges} {name} （{company} / {categories or '-'}）")
        print(f"    ルームID: {room.get('id')}")
        print(f"    最終日時: {last_comment_dt}")
        snippet = room.get("lastCommentContent") or ""
        if snippet:
            print(f"    最新抜粋: {snippet[:120].strip()}...")
        thread = room.get("thread") or []
        if thread:
            print(f"    スレッド: {len(thread)} 件のメッセージを取得済み")
        print("-" * 56)


def _custom_fetch(ctx: MessagePipelineContext) -> dict[str, Any]:
    box_type = getattr(ctx.args, "box_type", "all")
    if ctx.args.tab and ctx.args.tab != "all":
        box_type = ctx.args.tab
    ctx.tab = box_type
    ctx.tab_label = BOX_TYPE_LABEL_MAP.get(box_type, box_type)

    room_id = getattr(ctx.args, "room_id", "")
    fetch_threads = getattr(ctx.args, "fetch_threads", False)
    mark_as_read = getattr(ctx.args, "mark_as_read", False)
    limit = ctx.args.limit or 0

    return execute_navigate_messages(
        session=ctx.session,
        box_type=box_type,
        limit=limit,
        fetch_threads=fetch_threads,
        room_id=room_id,
        mark_as_read=mark_as_read,
        timeout=ctx.args.timeout,
    )


def _parse_batch(data: dict[str, Any]) -> MessageBatch:
    rooms = data.get("rooms", [])
    messages: list[MessageItem] = []
    for r in rooms:
        other = r.get("otherUser") or {}
        name = other.get("name") or r.get("displayName") or "名前不明"
        company = other.get("companyName") or ""
        item = MessageItem(
            id=r.get("id"),
            sender=name,
            company=company,
            subject=r.get("displayName") or f"{name}（{company}）",
            snippet=r.get("lastCommentContent") or "",
            url=f"https://youtrust.jp/chat_rooms/{r.get('id')}" if r.get("id") else "",
            is_unread=(r.get("unreadCount", 0) > 0),
            scout_type=r.get("chatRoomType") or "通常",
            date=format_timestamp(r.get("lastCommentedAt")),
            extra_metadata=dict(r),
        )
        messages.append(item)

    extra_meta = {
        "rooms": rooms,
        **{k: v for k, v in data.items() if k not in ("rooms", "messages", "totalCount", "url")},
    }
    return MessageBatch(
        source="youtrust",
        type="messages",
        url=data.get("url", BASE_URL),
        total_count=data.get("totalCount", len(rooms)),
        messages=messages,
        extra_metadata=extra_meta,
    )


def _custom_save(batch: MessageBatch, ctx: MessagePipelineContext) -> list[Path]:
    now = ctx.now
    output_dir = ctx.config.default_output_dir if ctx.args.output_dir is None else ctx.args.output_dir
    target_room_id = getattr(ctx.args, "room_id", "")
    raw_rooms = batch.extra_metadata.get("rooms", [])

    output_dir.mkdir(parents=True, exist_ok=True)
    history_dir = output_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    rooms_dir = output_dir / "rooms"
    rooms_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []
    time_str = now.strftime("%Y%m%d_%H%M%S")

    # Case A: 特定ルーム単体の取得の場合
    if target_room_id and raw_rooms:
        room = raw_rooms[0]
        room_md_path = rooms_dir / f"{target_room_id}.md"
        room_json_path = rooms_dir / f"{target_room_id}.json"

        room_md_content = generate_room_markdown(room, now)
        room_md_path.write_text(room_md_content, encoding="utf-8")
        room_json_path.write_text(json.dumps(room, ensure_ascii=False, indent=2), encoding="utf-8")
        saved_paths.extend([room_md_path, room_json_path])
        return saved_paths

    # Case B: 一覧（複数ルーム）の保存
    slug = ctx.tab.lower()
    latest_md = output_dir / f"messages_{slug}.md"
    latest_json = output_dir / f"messages_{slug}.json"
    latest_all_md = output_dir / "messages_latest.md"
    latest_all_json = output_dir / "messages_latest.json"

    history_md = history_dir / f"messages_{slug}_{time_str}.md"
    history_json = history_dir / f"messages_{slug}_{time_str}.json"

    raw_dict = {
        "url": batch.url,
        "totalCount": batch.total_count,
        "rooms": raw_rooms,
        **{k: v for k, v in batch.extra_metadata.items() if k != "rooms"},
    }
    md_content = generate_markdown(raw_dict, ctx.tab, now)
    latest_md.write_text(md_content, encoding="utf-8")
    history_md.write_text(md_content, encoding="utf-8")

    json_payload = {
        "source": "youtrust",
        "type": "messages",
        "box_type": ctx.tab,
        "fetched_at": now.isoformat(timespec="seconds"),
        "url": batch.url or BASE_URL,
        **raw_dict,
    }
    json_str = json.dumps(json_payload, ensure_ascii=False, indent=2)
    latest_json.write_text(json_str, encoding="utf-8")
    history_json.write_text(json_str, encoding="utf-8")

    saved_paths.extend([latest_md, latest_json, history_md])

    if slug == "all":
        latest_all_md.write_text(md_content, encoding="utf-8")
        latest_all_json.write_text(json_str, encoding="utf-8")
        saved_paths.extend([latest_all_md, latest_all_json])

    for room in raw_rooms:
        r_id = room.get("id")
        if r_id and (room.get("thread") or len(raw_rooms) == 1):
            r_md = rooms_dir / f"{r_id}.md"
            r_json = rooms_dir / f"{r_id}.json"
            r_md.write_text(generate_room_markdown(room, now), encoding="utf-8")
            r_json.write_text(json.dumps(room, ensure_ascii=False, indent=2), encoding="utf-8")
            saved_paths.extend([r_md, r_json])

    return saved_paths


def _custom_summary(batch: MessageBatch, ctx: MessagePipelineContext) -> None:
    print_formatted_summary(batch, box_type=ctx.tab)


def _setup_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--box-type",
        choices=["all", "scout", "unread", "sales"],
        default="all",
        help="チャットルームの絞り込み種別 (デフォルト: all)",
    )
    parser.add_argument(
        "--room-id",
        type=str,
        default="",
        help="特定のチャットルームIDのみをピンポイント取得する場合に指定",
    )
    parser.add_argument(
        "--fetch-threads",
        action="store_true",
        help="各チャットルームの全メッセージ履歴（スレッド本文）まで取得する",
    )
    parser.add_argument(
        "--mark-as-read",
        action="store_true",
        help="取得と同時に既読フラグを更新する（デフォルトは既読にしない安全設計）",
    )


CONFIG = MessageCrawlerConfig(
    site_id="youtrust",
    site_name="YOUTRUST",
    auth_site="youtrust",
    default_output_dir=DEFAULT_OUTPUT_DIR,
    tab_url_map={"all": BASE_URL},
    tab_label_map=BOX_TYPE_LABEL_MAP,
    default_tab="all",
    tab_choices=["all", "scout", "unread", "sales"],
    custom_fetch_fn=_custom_fetch,
    parse_batch_fn=_parse_batch,
    custom_summary_fn=_custom_summary,
    custom_save_fn=_custom_save,
    setup_args_fn=_setup_args,
    examples=[
        "uv run python scripts/youtrust/navigate_messages.py --summary",
        "uv run python scripts/youtrust/navigate_messages.py --box-type scout --summary  # スカウトのみ",
        "uv run python scripts/youtrust/navigate_messages.py --room-id <room-id> --summary  # 1 スレッドの本文を取得",
    ],
)


def save_messages_result(
    data: dict[str, Any],
    box_type: str = "all",
    target_room_id: str = "",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    now: datetime | None = None,
) -> list[Path]:
    """取得したチャットルーム・メッセージデータをファイル保存する（後方互換用）."""
    if now is None:
        now = datetime.now()
    batch = _parse_batch(data)
    batch.tab = box_type
    batch.tab_label = BOX_TYPE_LABEL_MAP.get(box_type, box_type)

    from types import SimpleNamespace

    dummy_args = SimpleNamespace(output_dir=output_dir, room_id=target_room_id)
    ctx = MessagePipelineContext(
        config=CONFIG,
        args=dummy_args,  # type: ignore
        entrypoint_ctx=None,  # type: ignore
        tab=box_type,
        tab_label=BOX_TYPE_LABEL_MAP.get(box_type, box_type),
        target_url=BASE_URL,
        session="job-hunt",
        profile_dir=output_dir,
        now=now,
    )
    return _custom_save(batch, ctx)


def main() -> None:
    """CLIエントリポイント."""
    sys.exit(run_message_pipeline(CONFIG))


if __name__ == "__main__":
    main()
