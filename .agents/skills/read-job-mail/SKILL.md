---
name: read-job-mail
description: ユーザーが「メールを確認して」「最近のスカウト・面談日程・選考結果のメールを見て」など、Gmail に届いた就活関連メールの確認・整理を依頼した際、または企業・リクルーターとのやり取りをメールで確かめる必要がある際に適用。Gmail API（読み取り専用）でメールを検索・取得し、就活関連かを AI が判断して、スカウト→consult-company-job、日程・選考結果→企業ログの status・next_action 更新、媒体通知→各媒体スクリプトへ振り分け、ユーザーに報告する。送信・既読化・ラベル変更は行わない。
meta:
  tag: [gmail, mail-triage, job-consultation, pipeline-update]
  requires_repo_tools: scripts/gmail, scripts/common/check_company.py, scripts/vault
  requires_env: none
  dependencies: python
  requires_install: none
  requires_hooks: none
  requires_skills: consult-company-job, schedule-interview, using-job-hunt-scripts
  status: beta
  version: 1.1.0
---

# 就活メール確認・振り分けスキル (`read-job-mail`)

Gmail に届いた就活関連メールを読み取り専用で検索・取得し、内容に応じて既存フロー（企業相談・企業ログ更新・媒体スクリプト）へ振り分けるスキルです。役割は「メールを読んで振り分ける」ところまでで、企業調査そのものは [`consult-company-job`](../consult-company-job/SKILL.md) に任せます。

> [!CAUTION]
> 1. **読み取り専用**: スコープは `gmail.readonly` のみ。送信・既読化・ラベル変更・削除はしない（[`.agents/rules/gmail.md`](../../rules/gmail.md)）。返信が必要なら下書きをチャットで示し、送信はユーザーが行う。
> 2. **本文を vault に写さない**: vault には要約と `data/gmail/threads/{thread_id}.md` への参照だけを書く。
> 3. **機械的に判断しない**: クエリのヒットや件名だけで就活関連か・対応要否を決めない。送信者・企業・文脈をユーザーのプロファイルと照らして判断し、スキップしたものは理由を書く（[`.agents/rules/goal.md`](../../rules/goal.md) の「スカウト・メッセージ・求人評価の基本原則」）。

CLI の仕様・保存形式・クエリ例の正本は [`docs/gmail/README.md`](../../../docs/gmail/README.md)。

## 無人実行（定期実行）時

定期実行ルーチン（[`docs/automation/README.md`](../../../docs/automation/README.md)）から呼ばれ、ユーザーがその場にいないときは、次のように縮めて動く。

- Step 1 で終了コード 2 なら認可を待たずに打ち切り、「Google の再認可（外部ターミナルで `uv run python scripts/google/auth.py`）」をユーザーがやることとして返す。
- Step 2・3 の検索と本文取得は通常どおり行ってよい（`data/` への保存だけで、外向きの操作ではない）。
- Step 4 の振り分けは**実行しない**。企業ログの更新・`consult-company-job` への引き継ぎ・カレンダー登録・返信下書きの確定はせず、メールごとに「何をすべきか（返信・日程回答・status 更新等）・期限・根拠（スレッドのパスと要点）」を「ユーザーがやること」として返す。`rejected` / `declined` の区別など判断が要るものは判断材料だけを添える。
- 権限プロファイルで vault への書き込みが許されている場合も、ログの更新は「事実だけで決まり、ユーザーの判断が要らないもの」（例: 返信待ちが解消した記録）に留め、変更したファイルを結果に列挙する。

> [!NOTE]
> スクリプトが読むのは Gmail の `JOB` ラベル配下のメールだけ（`JOB/RECRUITER`: リクルーターとのやり取り、`JOB/SCHEDULE`: 日程調整）。規則の正本は `scripts/gmail/labels.py`、説明は `docs/gmail/README.md` §10。

---

## ワークフロー手順

### Step 1: トークンの確認

```powershell
uv run python scripts/google/auth.py --check
```

- 終了コード 0: 続行。stderr の「失効の目安（残り約 N 日）」が 1 日未満なら、作業後に再認可を勧める。
- 終了コード 2: 再認可が必要。**ユーザーに外部ターミナルで** `uv run python scripts/google/auth.py` を実行してもらい、「終わった」の合図を待つ（エージェントは認可を実行しない）。
- 終了コード 1: API 未有効化・ネットワーク等。`docs/google/README.md` の §3・§5 を見て原因を伝える。

### Step 2: 目的に合わせて検索（一覧だけ取る）

依頼の目的から分類ラベル（`--label`）・クエリ・期間を決める。迷ったら `docs/gmail/README.md` §9 の例から始め、期間は直近 7〜14 日を既定にする。

```powershell
# 例: 直近 14 日の日程調整（JOB/SCHEDULE）
uv run python scripts/gmail/search_messages.py --label schedule --since 14d -n 20 --summary

# 例: リクルーターとのやり取り（JOB/RECRUITER）
uv run python scripts/gmail/search_messages.py --label recruiter --since 30d --summary

# 例: JOB 配下全体から特定の会社・担当者
uv run python scripts/gmail/search_messages.py -q "from:example.co.jp" --since 30d --summary
```

- まず `--download` を付けずに一覧（件名・From・ラベル・snippet）だけを見る。クォータと不要な本文保存を避けるため。
- 依頼が広い（「最近のメール全部」等）ときは、`--since 14d` で JOB 配下全体を見るか、分類ラベルごとに分けて流す。分類ラベルの無いメール（選考結果・媒体通知等）は `JOB` だけが付いていることがあるので、分類ラベルだけで済ませない。
- ヒットが少ない・From が想定と違うときは `--summary` の From を見てクエリを直す。
- 届いているはずのメールが出てこないときは、Gmail で JOB ラベルが付いているかをユーザーに確かめてもらう（範囲外は検索できない）。終了コード 1 で「ラベル「JOB」がありません」と出たら、Gmail でラベルを作ってもらう。

### Step 3: 就活関連かの判断と本文取得

一覧を見て、スレッドごとに次の 3 つに分ける。

| 区分 | 扱い |
| --- | --- |
| 就活関連で中身を読む必要がある | `fetch_thread.py --thread-id <id> ...` で本文を取得して読む |
| 就活関連だが snippet で足りる（媒体の定型通知等） | 本文は取らず、snippet と件名で振り分ける |
| 就活と無関係・営業メール・古すぎる | 読まない。理由を Step 5 の報告に書く |

```powershell
uv run python scripts/gmail/fetch_thread.py --thread-id <thread_id> <thread_id>
```

- 保存先は stdout に出る `data/gmail/threads/{thread_id}.md`。それを読む。
- 社名が出てきたら、振り分け前に track を判定して重複・除外判定を流す。
  ```powershell
  uv run python scripts/common/check_company.py --track <domestic|overseas> -s <company-name>
  ```

### Step 4: 種類ごとの振り分け

| メールの種類 | 振り分け先 |
| --- | --- |
| スカウト・求人紹介（新規企業・新規リクルーター） | [`consult-company-job`](../consult-company-job/SKILL.md) のフローへ。メール要約を「1. 相談・リクエスト内容」の材料にする。リクルーターからなら [`.agents/rules/recruiter-log.md`](../../rules/recruiter-log.md) に従いリクルーターログも作成・更新 |
| 日程調整の依頼（こちらの返信待ち） | 企業ログの `action_type: action_required`、`next_action`（何を返すか）、`next_due`（返信期限）。候補日の算出・返信下書きは [`schedule-interview`](../schedule-interview/SKILL.md) へ |
| 日程確定・カレンダー招待 | [`schedule-interview`](../schedule-interview/SKILL.md) の Step 5 へ（カレンダー登録の要否確認、`action_type: scheduled`、`next_due` に日時 `YYYY-MM-DD HH:MM`、面談ログ雛形） |
| リスケ・キャンセルの連絡 | [`schedule-interview`](../schedule-interview/SKILL.md) の Step 6 へ |
| 選考結果（通過） | `status` を次ステージへ進め、`next_action` を更新 |
| 選考結果（不合格・辞退確定） | `status: rejected` / `declined` と `decline_reason`。区別に迷ったらユーザーに確認（[`.agents/rules/company-log.md`](../../rules/company-log.md)） |
| 相手の返信待ちが解消した・まだ来ない | `waiting` → 次の状態へ更新、または `next_due` 超過をユーザーに伝える |
| 媒体の通知（新着スカウト・メッセージあり等） | 本文はメールでなく媒体側にあるので、その媒体のスクリプトで取得するよう提案する（[`using-job-hunt-scripts`](../using-job-hunt-scripts/SKILL.md) の「メッセージ・スカウトを集める」） |

- 既存ログ（`[EXISTING]`）は日付付き見出しで追記し、本文には要約と `data/gmail/threads/{thread_id}.md` への参照を書く（本文の引用はしない）。
- `[EXCLUDED]` の企業からのメールは、過去の見送り理由を添えてユーザーに伝えるだけにする（再検討の指示がなければログを動かさない）。
- vault を更新したら `uv run python scripts/vault/validate.py` をエラー 0 にし、`uv run python scripts/vault/build_pipeline.py --track {track}` を流す。

### Step 5: ユーザーへの報告

次の形でまとめる。

1. **確認範囲**: 流したクエリ・期間・ヒット数、本文まで読んだスレッド数。
2. **要対応**: 返信・日程回答が必要なもの（期限順）。返信が要るものは下書きを添える（送信はユーザー）。日程回答は `schedule-interview` で候補日を出してから下書きにする。
3. **反映した内容**: 更新した企業ログ・リクルーターログ（相対パス）と変更点（status・next_action）。
4. **相談に回すもの**: 新規スカウト等で `consult-company-job` に進めるべき候補と、進めるかの確認。
5. **スキップしたもの**: 件数と理由（「営業メールのため」「30 日以上前で対応済みのため」等）。
6. **トークン**: 失効が近ければ再認可の案内。

最後に、メールで分かった新しい志向・条件（例: 日程調整で分かった面談可能な時間帯）があれば、`vault/profile/` や track の `strategy.md` への追記をユーザーに提案する（振り分けは [`.agents/rules/user-profile.md`](../../rules/user-profile.md)）。

さらに `uv run python scripts/vault/find_chores.py --summary` を流し、残りの雑務（期限切れ・面談結果の未記入・pipeline.md の停滞等）があれば件数を添えて [`sweep-chores`](../sweep-chores/SKILL.md) で片付けるかを提案する。
