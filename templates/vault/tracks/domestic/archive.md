---
type: "closed_archive"
track: "domestic"
updated_at: "2026-10-19"
companies: []
---

# 見送り台帳（domestic）

終了（見送り・不合格・ブラックリスト）した企業フォルダと、古いスクリーニング集約ログを 1 社数行に圧縮した台帳。
正はフロントマターの `companies`（本文に一覧表は書かない。一覧は Web UI の見送り台帳ページで見る）。
追記・圧縮は `uv run python scripts/vault/compact_closed.py` で行う。圧縮前の詳細は git 履歴に残っている。
