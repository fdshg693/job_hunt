---
name: sweep-chores
description: ユーザーが「雑務を片付けて」「vault を整理して」「pipeline が古い」「たまっているタスクを処理して」「記録を最新にして」など、vault にたまった更新漏れの整理を依頼した際、または read-job-mail・schedule-interview 等の作業の最後に残りの雑務を片付ける際に適用。scripts/vault/find_chores.py と AI による自由文の読み取りで雑務（期限切れ・面談結果の未記入・pipeline.md 手書き部の停滞・放置企業・古い外部資料の要約・圧縮候補・英語版の未同期 等）を見つけ、優先度順に示して、自動修正（差分提示）／承認を取って修正／ユーザーへのヒアリングの区分で 1 件ずつ片付ける。
meta:
  tag: [vault-maintenance, pipeline-update, chores]
  requires_repo_tools: scripts/vault, scripts/profile/sync_en.py
  requires_env: none
  dependencies: python
  requires_install: none
  requires_hooks: none
  requires_skills: read-job-mail, schedule-interview, consult-company-job, using-job-hunt-scripts
  status: beta
  version: 1.1.0
---

<!-- 自動生成ファイル: .agents/skills/sweep-chores/SKILL.md から scripts/dev/sync_agents.py で生成。直接編集せず .agents/skills/sweep-chores/SKILL.md を編集して再同期すること -->

# vault 雑務の検出・順次処理スキル (`sweep-chores`)

vault の記録が実態から遅れてたまる雑務を見つけ、優先度順に片付けるスキルです。役割は「見つけて、片付けるか振り分ける」ところまでで、企業の調査は [`consult-company-job`](../consult-company-job/SKILL.md)、日程調整は [`schedule-interview`](../schedule-interview/SKILL.md)、メールの確認は [`read-job-mail`](../read-job-mail/SKILL.md) に任せます。

> [!CAUTION]
> 1. **スクリプトの結果だけで決めない**: `find_chores.py` は候補と根拠を出すだけ。status 変更・見送り・圧縮は、企業ログ本文とユーザーのプロファイルを読んだ上で案を作り、承認を取る（[`.agents/rules/goal.md`](../../rules/goal.md) の「機械的フィルタの過信禁止」）。
> 2. **`auto` でも黙って直さない**: 直した後に差分の要約を必ず見せる。
> 3. **pipeline.md のマーカー内は手で編集しない**: `<!-- pipeline:begin -->` 〜 `<!-- pipeline:end -->` は `build_pipeline.py` で再生成する。手で直すのはマーカー外だけ（[`.agents/rules/tracks.md`](../../rules/tracks.md)）。
> 4. **内部情報を書き写さない**: `visibility: internal`（`criteria.md`・`ratings.md`・`vault/profile/internal/`）は判断材料に使ってよいが、pipeline.md など internal でないファイルに書かない。
> 5. **コミットはユーザーに頼まれたときだけ**。

CLI の仕様（検出器・閾値・処理区分・優先度・出力形式）の正本は [`docs/vault/chores.md`](../../../docs/vault/chores.md)。

## 無人実行（定期実行）時

定期実行ルーチン（[`docs/automation/README.md`](../../../docs/automation/README.md)）から呼ばれ、ユーザーがその場にいないときは、次のように縮めて動く。

- Step 1・2 の検出は通常どおり行う。Step 3 の処理範囲の確認はしない。
- 自分で直すのは **`auto` 区分だけ**で、それも権限プロファイルで vault への書き込みが許されている場合に限る。許されていなければ `auto` も直さず、直す内容を結果に書く。直したらファイルごとの変更点を結果に列挙する（差分の提示の代わり）。
- `confirm` は案と根拠 1 行を、`ask` は質問を、それぞれ「ユーザーがやること」として返す。status の変更・見送り・圧縮・英語版同期・`data-ref` の解消は実行しない。
- Step 5 は `validate.py` と `find_chores.py --summary` だけを流す。`build_pipeline.py` は vault を直したときだけ流す。

---

## ワークフロー手順

### Step 1: 検出

```powershell
uv run python scripts/vault/find_chores.py --json
# track を絞るとき
uv run python scripts/vault/find_chores.py --track domestic --json
```

- 各雑務の `id`（`{検出器}:{対象}`）・`handling`（`auto` / `confirm` / `ask`）・`priority`・`reason`・`suggestion`・`path` を読む。
- 「その他の validate 警告」は `validate-warning` として含まれる。整合性エラー（スキーマ違反）は対象外なので、別途 `validate.py` がエラー 0 であることも確かめておく。

### Step 2: AI による補完検出

スクリプトは自由文を見ない。次を読み、企業ログのフロントマター（`status` / `action_type` / `next_action` / `next_due`）や面談ログと食い違っているものを雑務に足す。

| 読むもの | ずれの例 | 処理区分 |
| --- | --- | --- |
| 各 track の `pipeline.md` のマーカー外（活動フェーズ・次回アクションのチェックリスト・「気になる求人」等のリスト） | 済んだ予定が `[ ]` のまま／見送った企業が有力候補に残っている／もう無い予定が次回アクションに書かれている | `auto`（企業ログの記録どおりに直す） |
| 企業ログの `status_note`・`next_action`・本文「4. 最終回答」の次のアクション | 終わった日程調整が `next_action` に残っている／面談済みなのに status が手前のまま | 事実が vault 内で確かめられるなら `confirm`、ユーザーにしか分からないなら `ask` |
| 面談ログの「6. 次回アクション・選考結果」 | 面談ログでは次ステージが決まっているのに企業ログが更新されていない | `confirm` |

- Step 1 で `pipeline-stale` が出ていなくても、マーカー外は読む（`updated_at` を更新しただけで中身が古いことがある）。
- 補完分の ID は `ai:{対象}`（例: `ai:pipeline-checklist`、`ai:loglass-next-action`）として一覧に混ぜる。

### Step 3: 一覧の提示と処理範囲の確認

処理区分ごとにまとめ、各区分の中は優先度順（[`docs/vault/chores.md`](../../../docs/vault/chores.md) の「優先度」: 期限・予定 → 記録の欠落 → 鮮度 → 整理）に番号を振って示す。

```
## AIが直します（auto）
 1. pipeline-stale:domestic — 手書き部が 10/14 で停止。次回アクションを企業ログに合わせます
## 承認をください（confirm）
 2. idle-company:go — considering のまま 14 日。案: 見送り（理由: ...）/ 応募 / 保留
 3. en-sync:preferences.md — 日本語版の変更を英訳して反映します（差分は処理時に提示）
## 教えてください（ask）
 4. overdue-action:enginee — LinkedIn には返信しましたか？ 返信内容（日程調整に進む／見送り）は？
```

- `confirm` の各件には、企業ログ本文を読んだ上での案（と根拠 1 行）を付ける。
- `ask` の質問はここでまとめて出し、**一度に答えてもらう**。返信の有無などメールで分かることは、[`read-job-mail`](../read-job-mail/SKILL.md) で確かめるかどうかも選択肢として示す。
- 処理範囲をユーザーに選んでもらう（全部／番号指定／`auto` だけ）。

### Step 4: 順次処理

処理の順は「`auto` → `ask` の回答反映 → `confirm`（圧縮・英語版同期・`data-ref` 以外）→ 圧縮・`data-ref`・英語版同期」。

#### `auto`

- **pipeline.md のマーカー外**: 企業ログのフロントマターに合わせて、活動フェーズ・次回アクション・チェックリストを直す。フロントマターの `next_action` / `next_due` / `updated_at` も直近の予定に合わせる。マーカー内は Step 5 の `build_pipeline.py` に任せる。
- **面談ログの未リンク**（`interview-unlinked`）: 企業ログ（またはリクルーターログ）の「5. 選考・面談サマリ」に相対リンクを足す（例: `[カジュアル面談 (2026-10-21)](2026-10-21_casual.md)`）。面談内容の要約が無ければ、面談ログから 1〜3 行で要約を添える。
- **終了企業に残った `action_type`**（`validate-warning` の `auto`）: `action_type: none` にし、`next_action` / `next_due` を消す。
- 直したファイルの `updated_at` を当日にする。最後に、ファイルごとに「何をどう直したか」を箇条書きで示す。

#### `ask`（回答を受けて反映）

- **期限切れアクション・予定日が過ぎた scheduled**: 回答に従って企業ログの `status` / `action_type` / `next_action` / `next_due` / `status_note` / `updated_at` を更新し、本文に日付付き見出しで経緯を追記する。次の日程調整が要るなら [`schedule-interview`](../schedule-interview/SKILL.md) に渡す。
- **面談の結果・感想**（`interview-result` / `interview-memo` / `past-scheduled`）: [`.agents/rules/interview-log.md`](../../rules/interview-log.md) の三層同期で記録する（面談ログの「4. 面談メモ」「5. 所感」と `result` → `index.md` の「5. 選考・面談サマリ」とフロントマター → Step 5 で pipeline 再生成）。ユーザーの話が短ければ、面談ログの「2. 事前準備・確認したかった論点」に沿って足りない点を追加で聞く。
- 回答が「まだ分からない」なら、`next_due` を次に確かめる日に延ばし、`next_action` に何を待っているかを書く。

#### `confirm`

1 件ずつ案を示し、承認を得てから書く。

- **status の変更・見送り**（`idle-company` / `waiting-stale` / `recruiter-stale` 等）: `rejected`（企業が決めた）と `declined`（自分が決めた）の区別は [`.agents/rules/company-log.md`](../../rules/company-log.md) に従い、迷えばユーザーに確認する。見送りなら `decline_reason` を書く。リクルーターは [`.agents/rules/recruiter-log.md`](../../rules/recruiter-log.md) の `status` 基準に従う。
- **再調査が要る**（応募判断の材料が足りない等）: このスキルでは調べず、[`consult-company-job`](../consult-company-job/SKILL.md) に回すかをユーザーに聞く。
- **圧縮**（`compact`）: [`.agents/rules/company-log.md`](../../rules/company-log.md) の「見送り企業の圧縮」の手順（`compact_closed.py draft` → 要約をユーザーに確認 → `apply`）にそのまま乗せる。`apply` は未コミットの変更があるフォルダを拒否するので、**ほかの雑務の変更をユーザーにコミットしてもらってから**行う。コミットされていなければ、圧縮は「次回に回す」として残す。圧縮のたびに、見送りで初めて分かった条件・志向が `vault/profile/` や `criteria.md` に吸収済みかを確かめる。
- **外部資料の要約が古い**（`material-stale` / `material-raw-missing`）: `uv run python scripts/vault/add_material.py --refresh <material のパス>` で生データを取り直し、stdout の生データと要約を見比べて差分を示す。承認後に要約本文を直し、`fetched_at` を今日にする（変化が無ければ `fetched_at` だけ）。`--refresh` の対象外（Speaker Deck・note 以外）は元ページを見て直接直す。選考が進んでいて資料の見直しが不要なら、ユーザーの判断で次回に回す（手順と日付の意味は [`docs/vault/materials.md`](../../../docs/vault/materials.md)）。
- **生データの直接参照**（`data-ref`）: 本文が指す `data/` の内容のうち判断に使った点を、企業・リクルーターなら `add_material.py` で material にして `links` から辿る形に、それ以外（スクリーニング・`ratings.md`・employers 等）は本文に 1〜2 行で要約して、`data/` パスを外す案を示す。生データが既に読めないものは、残っている本文の記述で足りるかをユーザーに確かめて参照だけ外す。`ratings.md` は internal なので、要約もそのファイル内に留める。
- **英語版の未同期**（`en-sync`）: 日本語版の該当ファイルの差分（`git diff` や `updated_at` 以降の変更）を英訳して見せ、承認後に `vault/profile/en/` に反映し、`uv run python scripts/profile/sync_en.py update-meta <ファイル名>` でメタデータを更新する（[`.agents/rules/user-profile.md`](../../rules/user-profile.md) の英語版同期規約）。`visibility: internal` の内容は訳さない。

処理中にユーザーの新しい志向・条件が分かったら（見送りの理由は特に）、[`.agents/rules/user-profile.md`](../../rules/user-profile.md) の振り分けに従って `vault/profile/` や track の `strategy.md` / `criteria.md` への追記を提案する。

### Step 5: 後処理

```powershell
uv run python scripts/vault/validate.py
uv run python scripts/vault/build_pipeline.py --track <track>
uv run python scripts/vault/find_chores.py --summary
```

- `validate.py` をエラー 0 にする。
- 再実行した `find_chores.py` で、処理したはずの雑務が消えていること、残りが「残すと決めたもの」だけであることを確かめる。

### Step 6: ユーザーへの報告

1. **処理した雑務**: 区分ごとの件数と、更新したファイル（相対パス）・主な変更点（status・next_action 等）。
2. **残した雑務**: 件数と理由（「回答待ち」「コミット後に圧縮」「ユーザーが保留を選択」等）。
3. **他スキルに回すもの**: 日程調整（`schedule-interview`）・企業の再調査（`consult-company-job`）・メール確認（`read-job-mail`）。
4. **プロファイルへの追記提案**: 処理中に分かった志向・条件。
5. **構造的な改善案**: 同じ種類の雑務が繰り返し出ている場合（例: pipeline.md 手書きの次回アクションが毎回古くなる）、発生源を消す改善案を 1〜2 行。
