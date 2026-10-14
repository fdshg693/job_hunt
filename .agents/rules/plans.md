---
trigger: glob
globs: .agents/plans/**/*.md
---

# プラン管理・参照ルール

## 遵守すべき要点

- **独立Implementation Planの二重作成禁止**: `.agents/plans/` 配下にプランがある場合、別個のImplementation Planを作成してはならない（単なる重複になるため）。
- **OKF準拠のfrontmatter**:
  - 概要ファイル / 単一完結プラン: `type: Plan`
  - 各ステップファイル: `type: Plan Step`
  - 進捗ステータス（`status`）は規定の6値（`planning-research`, `planning-breakdown`, `ready`, `implementing-started`, `implementing-in-progress`, `implementing-done`）を厳格に管理する。
- **進捗の記録**:
  - ステップ着手時は `implementing-in-progress`、完了時は `implementing-done` に更新する。
  - `00-overview.md` のステップ一覧に完了マーク（✅）を反映する。
- **全ステップ完了後のクリーンアップ**:
  - 全ステップが `implementing-done` になった際は、プランフォルダ一式を削除し、他ファイルに残る参照を除去する（README.mdのクリーンアップ手順を参照）。