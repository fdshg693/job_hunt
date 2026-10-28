---
paths:
- vault/profile/tech/**/*.md
- templates/vault/profile/tech/**/*.md
---

<!-- 自動生成ファイル: .agents/rules/tech-notes.md から scripts/dev/sync_agents.py で生成。直接編集せず .agents/rules/tech-notes.md を編集して再同期すること -->

# 技術詳細ノート（vault/profile/tech/）規約

- 履歴書・自己PRに書くには細かすぎる技術の一次情報の置き場。要約は `resume.md` / `skills.md`、詳細はここに書き、同じ内容を両方に書かない
- `projects/{key}.md` は 1 プロジェクト 1 ファイル、`areas/{key}.md` は 1 技術領域 1 ファイル。キーはファイル名と一致させる（スキーマは `docs/vault/schema.md` の `TechProjectDoc` / `TechAreaDoc`）。新規作成は `templates/vault/profile/tech/` の雛形をコピーする
- `projects/` `areas/` の中に README などスキーマ外のファイルを置かない（検証エラーになる）
- 「現在地（今やっていること）」と「説明できないこと・未経験」を必ず書き、更新したら `updated_at` を更新する
- 外部提出物（応募書類・媒体プロフィール・英語版・PDF）に直接引用しない。外部に出す内容は `resume.md` / `skills.md` に要約してから使う。弱みや本音を含むファイルには `visibility: "internal"` を付ける
