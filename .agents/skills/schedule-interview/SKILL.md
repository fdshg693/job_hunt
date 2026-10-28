---
name: schedule-interview
description: 企業・リクルーターから面談・面接の日程調整を求められた際（read-job-mail で日程調整メールを見つけた、ユーザーが「候補日を出して」「この日で確定した」「リスケになった」「辞退したので予定を消して」と言った等）に適用。Google カレンダーの空き時間から面談候補日を算出して返信下書きをチャットで示し、確定後はユーザー確認を取ってカレンダーに予定を登録し、企業ログの action_type・next_due・面談ログ雛形・pipeline.md を更新する。リスケ・辞退時の予定の更新・削除も扱う。返信の送信はしない。
meta:
  tag: [gcal, interview-scheduling, pipeline-update]
  requires_repo_tools: scripts/gcal, scripts/google/auth.py, scripts/vault
  requires_env: none
  dependencies: python
  requires_install: none
  requires_hooks: none
  requires_skills: read-job-mail, using-job-hunt-scripts
  status: beta
  version: 1.0.0
---

# 面談日程調整スキル (`schedule-interview`)

日程調整の依頼を受けてから面談が確定・変更・取り消しになるまでを扱うスキルです。「空き時間から候補日を出す → 返信下書きを示す → 確定したらカレンダー登録と vault 更新 → リスケ・辞退時の更新・削除」を 1 本の流れにまとめます。メールを読んで振り分けるところは [`read-job-mail`](../read-job-mail/SKILL.md)、企業の調査・評価は [`consult-company-job`](../consult-company-job/SKILL.md) が担当します。

> [!CAUTION]
> 1. **返信は送らない**: 返信は下書きをチャットで示すだけ。送信はユーザーが行う（Gmail は読み取り専用、[`.agents/rules/gmail.md`](../../rules/gmail.md)）。
> 2. **予定の作成・変更・削除はユーザーの確認を取ってから**: 日時・タイトル・場所を示して了承を得てから実行する。誤った日時の登録は面談のすっぽかしに直結する（[`.agents/rules/gcal.md`](../../rules/gcal.md)）。
> 3. **確定日時の正は vault**: 企業ログの `next_due` が正、カレンダーはその写し。どちらかを変えたら両方を合わせる。
> 4. **内部情報をカレンダーに書かない**: タイトルは `【面談】{会社名} {ステージ}` 程度。fit_score・本音メモ・`visibility: internal` の情報はタイトル・説明に書かない。

CLI の仕様の正本は [`docs/gcal/README.md`](../../../docs/gcal/README.md)（候補日算出 §4・§5、予定の作成・更新・削除 §6）。

---

## ワークフロー手順

### Step 1: トークンの確認

```powershell
uv run python scripts/google/auth.py --check
```

終了コードの扱いは [`read-job-mail`](../read-job-mail/SKILL.md) の Step 1 と同じ（2 ならユーザーに外部ターミナルで `uv run python scripts/google/auth.py` を実行してもらう。エージェントは認可を実行しない）。

### Step 2: 依頼内容と既定値の把握

1. **相手の指定を読む**（メールなら `data/gmail/threads/{thread_id}.md`）: 候補期間、所要時間、候補の数、形式（オンライン/対面）、相手のタイムゾーン、返信期限。
2. **企業ログを確認する**: `scripts/common/check_company.py --track <track> -s <会社名>` で企業ログの有無と track を確かめる。企業ログが無ければ先に [`consult-company-job`](../consult-company-job/SKILL.md) で作る（日程調整だけで会社をログ化しないまま進めない）。
3. **ユーザーの既定値を読む**: track の `strategy.md` にある面談可能な時間帯・曜日・祝日の扱い・候補日出しで見るカレンダー・仮押さえの方針。
   - 書かれていない項目は、この時点でユーザーに質問し、回答を `strategy.md` に追記する（`updated_at` も更新）。コードやスキル本文には書かない。
4. **カレンダー未登録の予定を拾う**: 同じ track（必要なら他 track も）の `pipeline.md` や企業ログで `action_type: scheduled` の面談のうち、カレンダーに無いものは Step 3 で `--busy` に足す。カレンダーにあるかは `list_events.py --since <日付> --until <日付> --summary` で確かめる（企業からの招待で入った予定は目印が無いので `--job-only` では出ない）。

### Step 3: 候補日の算出

```powershell
# 例: domestic。時間帯・曜日・祝日の扱いは strategy.md の値を渡す。面談最優先のため --buffer 0 を指定
uv run python scripts/gcal/find_slots.py --since <YYYY-MM-DD> --until <YYYY-MM-DD> --duration <分> `
  --hours <strategy.md の時間帯> --weekdays <strategy.md の曜日> --buffer 0 --summary

# 例: overseas。判定はユーザーの TZ、表示は相手の TZ・英語
uv run python scripts/gcal/find_slots.py --since <YYYY-MM-DD> --until <YYYY-MM-DD> --duration <分> `
  --hours <...> --weekdays <...> --buffer 0 --display-tz <相手の IANA TZ> --lang en --summary
```

- 期間・所要時間は相手の指定に合わせる。指定が無ければ「今日から 2 週間」「60 分」程度から始める。
- 曜日・祝日は `strategy.md` の既定に従う（本人が土日祝も可でも、企業側の営業日に合わせて平日だけを既定にしている場合がある）。ユーザーの明示の指示で広げるときは `--weekdays mon-sun --holidays none`。overseas でも祝日は**ユーザー側の国**で判定する（相手国の祝日は相手が避ける）。
- 面談最優先のため、既存予定の前後にバッファを取らず（`--buffer 0`）、既存予定の間（例: 12:00まで予定、次が14:00〜なら 12:00〜14:00、14:00〜15:00と17:00〜17:30の間なら 15:00〜17:00）を目いっぱいに使う。
- `--busy "YYYY-MM-DD HH:MM-HH:MM"` で Step 2-4 の予定を足す。
- 終了コード 1（freeBusy のエラー）なら候補を出さず、原因を伝える（一部カレンダーを抜かして空きと誤認しないため）。

### Step 4: 返信用の候補を選び、下書きを示す

1. **目いっぱい提示・ユーザー側での間引き（順序の絶対遵守）**:
   - `--summary` の出力結果（目いっぱいの空き枠）をそのまま、または各日の目いっぱいの時間帯レンジ（例: `10/30(金) 10:00〜14:00、15:00〜17:00、18:00〜21:00`）として下書きに**すべて提示**する。
   - **AIが勝手に「3〜5枠に絞る」「日中と夜を分散して一部を削る」などと候補日時を間引いたり省略したりすることは厳禁**。
   - 不都合・不要な枠があれば**ユーザーが自分で間引く**。**絶対にこの順序を逆にしない**（AIが事前間引きした結果、ユーザーが本来選べたはずの候補枠が存在しないものと誤認されるのを防ぐ）。
2. 相手の TZ がユーザーと違うときは、相手の現地時刻を主にし、ユーザー側の時刻を併記する（`--display-tz` を変えて 2 回流すか、ユーザー側の表記を添える）。ずれた日付・曜日に注意する。
3. 返信下書きをチャットに示す。候補・所要時間・形式・必要なら確認事項（オンライン URL の送付依頼等）を入れる。内部情報（志望度・他社状況・本音の条件）は書かない。
4. **仮押さえ**: `strategy.md` の方針に従う。方針が無ければ「候補を出している間に他の予定が入ると矛盾する」ことを伝えて作るか聞き、方針を `strategy.md` に追記する。作る場合は候補ごとに
   ```powershell
   uv run python scripts/gcal/manage_events.py create --title "【仮】{会社名} {ステージ}" --start "<YYYY-MM-DD HH:MM>" --duration <分> --company-key <company-key> --force --dry-run
   ```
   で内容を見せてから作る（同日に複数枠を押さえるときは重複ガードを `--force` で外す）。作った予定 ID は Step 5 で不要分を消すために控えておく。
5. 企業ログを更新する: `action_type: waiting`、`next_action`（例: 「候補日を返信済み。確定連絡待ち」）、`next_due`（相手の回答期限、無ければ数日後）、`updated_at`。返信がまだユーザー側なら `action_required` のまま `next_action` に「候補日を返信」と書く。

### Step 5: 確定したら予定登録と vault 更新

ユーザーから確定日時を聞いた（または確定メールを読んだ）ら:

1. **カレンダーに既にあるか確かめる**: 企業から招待が届いている場合（Google Calendar の招待メール、主催者が相手）はその予定が正。重複して作らない。`list_events.py --since <日付> --until <日付> --summary` で確認する。
2. **予定を作る**（招待が無い場合）。内容を示して了承を取ってから:
   ```powershell
   uv run python scripts/gcal/manage_events.py create --title "【面談】{会社名} {ステージ}" `
     --start "<YYYY-MM-DD HH:MM>" --duration <分> --location "<相手から届いた会議 URL・住所>" --company-key <company-key> --dry-run
   uv run python scripts/gcal/manage_events.py create ...（同じ引数で --dry-run を外す） --summary
   ```
   - `--company-key` は必ず付ける（予定から企業ログを逆引きする目印）。
   - 会議 URL が未着なら `--location` を空にし、届いたら `update --location` で足す。
   - 仮押さえを作っていたら、確定した枠を `update --title` で本タイトルに変えるか、確定分を新規作成して仮押さえを消す。**不要になった仮押さえは一覧を示して了承を取ってから `delete`** する（自動では消さない）。
3. **企業ログ（`index.md`）を更新**: `status`（面談の段階に合わせる。値は [`docs/vault/schema.md`](../../../docs/vault/schema.md) の `CompanyStatus`）、`action_type: scheduled`、`next_due: "YYYY-MM-DD HH:MM"`（ユーザーの TZ）、`next_action`（例: 「カジュアル面談（Google Meet）」）、`status_note`、`updated_at`。本文には日付付き見出しで経緯の要約を追記する。予定 ID はフロントマターに書かない。
4. **面談ログの雛形を作る**: 同じ企業フォルダに `{YYYY-MM-DD}_{stage}.md` を stage に合う [`templates/interview/`](../../../templates/interview/) の雛形（カジュアル面談は `casual.md`、本選考は `interview.md`、エージェント面談は `recruiter.md`）から作り、「1. 面談基本情報」（日時・形式・相手）を埋める。事前論点の整理は面談前に [`.agents/rules/interview-log.md`](../../rules/interview-log.md) の手順で行う（ここでは雛形まででよい）。予定 ID を本文にメモしてよい。
5. **検証と再生成**:
   ```powershell
   uv run python scripts/vault/validate.py
   uv run python scripts/vault/build_pipeline.py --track <track>
   ```

リクルーター・エージェントとの面談なら、企業ログではなく `vault/recruiters/{recruiter-key}/` の `index.md` と面談ログを更新する（[`.agents/rules/recruiter-log.md`](../../rules/recruiter-log.md)）。予定の `--company-key` は付けない。

### Step 6: リスケ・辞退・キャンセル

1. 予定 ID を探す: `list_events.py --job-only --since <日付> --until <日付> --summary`（または面談ログ本文のメモ）。
2. **リスケ**: 新しい日時が決まっていなければ Step 3〜4 で候補を出し直す。決まったら内容を示して了承を取り、
   ```powershell
   uv run python scripts/gcal/manage_events.py update --id <event-id> --start "<YYYY-MM-DD HH:MM>" --dry-run
   ```
   → `--dry-run` を外して実行。企業ログの `next_due` と面談ログのファイル名（日付が変わる場合は `git mv`）・本文の日時を合わせる。
3. **辞退・キャンセル**: 了承を取ってから `manage_events.py delete --id <event-id>`。企業ログの `status`（辞退なら `declined` と `decline_reason`）・`action_type: none`・`next_action` を更新する。
4. **招待予定・ゲスト付き予定**は `manage_events.py` では変えられない（ガードで拒否、`--force` でも不可）。相手への連絡で変更してもらう旨をユーザーに伝え、vault だけを更新する。
5. 412（他所で変更済み）で止まったら `manage_events.py get --id <event-id> --summary` で今の内容を見せ、やり直すかをユーザーに確認する。
6. Step 5-5 の検証と再生成を流す。

### Step 7: ユーザーへの報告

1. **出した候補**: 算出条件（期間・時間帯・曜日・所要時間・TZ・足した busy）と、選んだ候補・返信下書き。
2. **カレンダーの変更**: 作成・更新・削除した予定（日時・タイトル。ID は必要なときだけ）。
3. **vault の変更**: 更新した企業ログ・面談ログ（相対パス）と `status` / `action_type` / `next_due`。
4. **ユーザーにお願いすること**: 返信の送信、招待予定の変更依頼など。
5. **追記した既定値**: `strategy.md` に足した面談可能時間帯・仮押さえ方針など。
6. **残りの雑務**: `uv run python scripts/vault/find_chores.py --summary` を流し、雑務（済んだ面談の結果未記入・pipeline.md の停滞等）があれば件数を添えて [`sweep-chores`](../sweep-chores/SKILL.md) で片付けるかを提案する。
