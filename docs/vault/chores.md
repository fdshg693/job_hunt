# vault 雑務検出 CLI（`scripts/vault/find_chores.py`）

vault の記録が実態から遅れてたまる雑務（期限切れ・面談結果の未記入・pipeline 手書き部の停滞・放置・外部資料の要約の古さ・圧縮候補・英語版の未同期 等）を洗い出す。**検出だけを行い、vault は書き換えない**。判断・処理は `sweep-chores` スキルで行う。

- 雑務があっても終了コードは 0（雑務は失敗ではない。pre-commit・CI には組み込まない）。
- 整合性違反（スキーマ・配置の誤り）は `validate.py` の担当。ここでは運用上の更新漏れを扱う。
- 自由文の食い違い（pipeline.md 手書きチェックリストと企業ログの status のずれ 等）は検出しない。スキル側で AI が読んで判断する。

## 使い方

```powershell
uv run python scripts/vault/find_chores.py                  # 雑務のあるファイルのパス（重複なし）
uv run python scripts/vault/find_chores.py --summary        # 優先度順の一覧（根拠・推奨アクション付き）
uv run python scripts/vault/find_chores.py --json           # 雑務オブジェクトの配列
uv run python scripts/vault/find_chores.py --track domestic --today 2026-10-30 --summary
```

| オプション | 既定 | 意味 |
| --- | --- | --- |
| `--track` | `all` | 対象 track。track に属さない雑務（リクルーター※・英語版・profile の警告）は常に含む。※リクルーターは `tracks:` にその track を含むものだけ |
| `--root` | リポジトリルート | `vault/` を含むディレクトリ |
| `--today` | 今日 | 日付比較の基準日 |
| `--waiting-days` | 7 | 連絡待ちの長期化とみなす日数 |
| `--idle-days` | 14 | 検討中の放置とみなす日数 |
| `--recruiter-days` | 30 | リクルーターの放置とみなす日数 |
| `--compact-days` | 14 | 圧縮候補とみなす終了後の日数（`compact_closed.py list --older-than-days` と同じ） |
| `--material-days` | 60 | 外部資料（material）の要約が古いとみなす日数（`fetched_at` から） |
| `-n` / `--limit` | なし | 優先度順の先頭 N 件だけ出す |

閾値は暫定値。試運転で多すぎ・少なすぎたら既定値を見直す。

## 処理区分（`handling`）

| 値 | 表示 | 意味 |
| --- | --- | --- |
| `auto` | AIが修正 | 判断が要らない。AI が直して差分を見せる |
| `confirm` | 要承認 | 判断が要る。AI が案を示し、ユーザーの承認を取ってから直す |
| `ask` | 要回答 | ユーザーしか知らない事実（面談の結果・感想、返信したか）が要る。質問にまとめる |

## 優先度（`priority`）

放置すると実害が出る順。同じ優先度の中は `since`（期限・面談日・最終更新日）の古い順。

| 値 | 表示 | 含む検出器 |
| --- | --- | --- |
| 1 | 期限・予定 | `overdue-action`, `past-scheduled`, `waiting-stale` |
| 2 | 記録の欠落 | `interview-result`, `interview-memo`, `interview-unlinked` |
| 3 | 鮮度 | `pipeline-stale`, `idle-company`, `recruiter-stale`, `material-stale`, `material-raw-missing`, `validate-warning` |
| 4 | 整理 | `compact`, `data-ref`, `en-sync` |

## 検出器

| 検出器 | 対象 | 条件 | 処理区分 | ID の対象部 |
| --- | --- | --- | --- | --- |
| `overdue-action` | 企業ログ | 進行中 status で `action_type: action_required` の `next_due` が基準日より前（判定は `loader.overdue_date`） | `ask` | 企業キー |
| `past-scheduled` | 企業ログ | 同上で `action_type: scheduled`（＝面談が済んでいるはず） | `ask` | 企業キー |
| `waiting-stale` | 企業ログ | 進行中 status で `action_type: waiting`、`updated_at` から `--waiting-days` 日以上 | `confirm` | 企業キー |
| `idle-company` | 企業ログ | 進行中 status で `action_type: none`、`updated_at` から `--idle-days` 日以上 | `confirm` | 企業キー |
| `interview-result` | 面談ログ | `date` が基準日より前で `result: pending` | `ask` | `{企業 or リクルーターキー}/{ファイル名}` |
| `interview-memo` | 面談ログ | `date` が基準日より前で「面談メモ」節がテンプレートのまま（後述） | `ask` | 同上 |
| `interview-unlinked` | 企業ログ・リクルーターログ | 同じフォルダの面談ログのファイル名が `index.md` の本文に出てこない。`path` はリンクを足す側の `index.md` | `auto` | 同上 |
| `pipeline-stale` | pipeline.md | フロントマター `next_due` が基準日より前、または `updated_at` が同じ track の企業ログの最新 `updated_at` より古い（企業ログが無い track は `next_due` だけ見る） | `auto` | track |
| `recruiter-stale` | リクルーターログ | `status: active` で `updated_at` から `--recruiter-days` 日以上 | `confirm` | リクルーターキー |
| `material-stale` | 外部資料（`materials/*.md`） | 所属する企業が進行中 status、またはリクルーターが `status: active`（`--track` 指定時はその track を扱うもの）で、`fetched_at` から `--material-days` 日以上。`raw_data` が全部残っている（または無い）もの | `confirm` | `{企業 or リクルーターキー}/{slug}` |
| `material-raw-missing` | 同上 | `material-stale` と同じ条件で、`raw_data` のどれかが存在しない（保持期間で削除済み）。`material-stale` の代わりに出す。要約が新しければ生データが消えていても出さない（正常） | `confirm` | 同上 |
| `compact` | 企業フォルダ・スクリーニング | `compact_closed.list_candidates` と同じ判定 | `confirm` | 企業キー / `screening/{ファイル名}` |
| `data-ref` | vault の全 Markdown（ローダーが読まない `ratings.md` 等も含む） | 本文が保持ポリシーの対象（期間を過ぎたら消える生データ）の `data/` パスを直接参照している。判定は `data_retention.vault_data_refs_by_file` / `is_retained_ref`（material の `raw_data` は数えない。`data/exports/`・`latest*`・ディレクトリだけの言及は対象外）。`path` は参照している vault ファイル | `confirm` | ファイルパス |
| `en-sync` | `vault/profile/en/` | `sync_en.check_sync_status` が STALE / MISSING / UNTRACKED（`vault/profile/en/` が無い vault では検出しない） | `confirm` | ファイル名 |
| `validate-warning` | 全 vault | 上で拾っていない `load_vault` の警告をファイル単位にまとめたもの。すべて「終了しているのに action_type が残っている」なら `auto`、それ以外は `confirm` | `auto` / `confirm` | ファイルパス |

- 「進行中 status」はスキーマの `COMPANY_STATUS_META` の分類（`StatusCategory.ACTIVE`）から引く。
- 外部資料・生データ・保持期間の関係は [materials.md](materials.md)。vault から参照されている生データはプルーニングで保護されるが、`data-ref` は「参照を外して material に寄せる」整理を促す。
- 期限切れの警告は `validate.py --today` でも出るが、ここでは `overdue-action` / `past-scheduled` として出し、`validate-warning` には含めない（二重に出さない）。

### 雑務 ID

`{検出器}:{対象}`（例: `overdue-action:enginee`, `interview-result:loglass/2026-10-23_casual`, `pipeline-stale:domestic`）。連番ではないので、再実行しても同じ雑務は同じ ID を指す。同じ企業キーが複数 track にあるときだけ `enginee@overseas` のように track を付ける。

### 面談メモ未記入の判定

本文の `## ` 見出しのうち「面談メモ」を含む節（番号は問わない）を見て、記入された行が 1 行も無ければ未記入とする。次の行は記入済みの根拠にしない。

- 空行・見出し・`---`・`※` 注記・`>` 引用
- 全体が括弧書きの行（`（面談後に記入）`, `（例: ...）`）
- 値が空、または `（例` で始まる `ラベル: 値` の行（`- **A**: `, `- 事業の現状:`）
- 太字だけの行（テンプレートの質問 `**Q1. ...？**`）
- 事前に書かれるメタ情報（`面談日時` / `日時` / `実施日時` / `面談相手` / `形式`）

分量では判定しない（短いメモでも記入済みのことがある。誤検出より取りこぼしを許す）。「面談メモ」節の無い形式のログは判定しない。

## 出力

- **既定**: 雑務のあるファイルのパス（ルート相対、重複なし、優先度順）
- **`--summary`**: 優先度ごとに番号付きで `[処理区分] ID  対象`・根拠・推奨アクション・パス
- **`--json`**:

```json
{
  "today": "2026-10-22",
  "root": "C:\\C\\job_hunt",
  "chores": [
    {
      "id": "overdue-action:enginee",
      "detector": "overdue-action",
      "handling": "ask",
      "priority": 1,
      "path": "vault/tracks/domestic/companies/enginee/index.md",
      "target": "株式会社Enginee",
      "reason": "期限 2026-10-21 を過ぎている（next_action: ...）",
      "suggestion": "対応済みか・どうするかを聞き、next_action / next_due を更新する",
      "since": "2026-10-21",
      "track": "domestic"
    }
  ]
}
```

`since` は並び順に使った日付（無ければ null）、`track` は track に属さない雑務では null。
