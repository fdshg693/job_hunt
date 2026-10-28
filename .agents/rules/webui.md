---
trigger: glob
globs: webui/**
---

# Web UI 規約

- Web UI（`webui/`）は人間用の閲覧専用。vault への書き込みは行わない（正本の編集は AI/CLI）。書き込みに当たる操作は索引の作り直し（`POST /reindex`）だけ
- 起動は `uv run python -m webui`（http://127.0.0.1:8765）。待ち受けは 127.0.0.1 固定で、`--host` オプションは作らない
- データは索引（`scripts/vault/build_index.py` の `ensure_index()` / `connect()` / `search()`）と `scripts/vault/loader.py` の `load_doc()` からだけ取得し、vault をパースする処理を独自に書かない。SQL は `webui/queries.py` にだけ書く
- DB 接続はリクエストごとに開いて閉じる（Windows で索引の `os.replace` と競合させない）
- 表示ラベル・並び順は `scripts/vault/schema/`（`label_of`、`COMPANY_STATUS_META` 等）、一覧の短い表記は `scripts/vault/display.py` から取得し、テンプレートに値のリストやラベルを直接書かない
- internal ファイル（`criteria.md`, `ratings.md`, `vault/profile/internal/`）は表示しない。本文の相対リンクは `webui/links.py` の `ui_url()` で UI 内 URL に変換し、変換できないファイルへのリンクは無効化する
- 本文の Markdown は `webui/markdown.py` で HTML を無効にしてレンダリングする。htmx などの JS は `webui/static/` に同梱し、CDN から読まない
- 画面・フィルタを変えたら `tests/test_webui.py` を更新する
