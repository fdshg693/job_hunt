# Google カレンダー連携ガイド

Google カレンダーの空き時間から面談候補日（リクルーター・企業への返信にそのまま貼れる表記）を出し、予定を参照・作成・更新・削除するための運用手順をまとめる（GCP の準備・認証は Gmail 連携と共通で [`docs/google/README.md`](../google/README.md)）。

- スコープは `calendar.events.owned` / `calendar.events.freebusy` / `calendar.calendarlist.readonly`（[docs/google §6](../google/README.md#6-スコープ)）。全権 `calendar` は使わない。
- 認証は Gmail 連携と同じ OAuth クライアント・`token.json` を共有する。終了コードも共通: 0 正常 / 1 エラー / 2 再認可が必要。
- 読み取り（カレンダー一覧・予定一覧・空き時間）は §2〜5、予定の作成・更新・削除（安全ガード付き）は §6。運用ルールは [`.agents/rules/gcal.md`](../../.agents/rules/gcal.md)。
- パッケージ名が `gcal` なのは標準ライブラリ `calendar` との衝突を避けるため。

---

## 目次

1. [スクリプト一覧](#1-スクリプト一覧)
2. [カレンダー一覧（`list_calendars.py`）](#2-カレンダー一覧list_calendarspy)
3. [予定一覧（`list_events.py`）](#3-予定一覧list_eventspy)
4. [面談候補日（`find_slots.py`）](#4-面談候補日find_slotspy)
5. [候補日算出の仕様](#5-候補日算出の仕様)
6. [予定の作成・更新・削除（`manage_events.py`）](#6-予定の作成更新削除manage_eventspy)
7. [保存形式（`data/gcal/`）](#7-保存形式datagcal)
8. [API の挙動メモ](#8-api-の挙動メモ)

---

## 1. スクリプト一覧

| スクリプト | 役割 |
| --- | --- |
| `scripts/gcal/client.py` | Calendar API service の生成（`build_service()`）と再試行付き実行（`execute()`。本体は共通層 `scripts/google/client.py`）。期間の解決（`resolve_range()`）、`data/gcal/` への保存（`save_result()`）、このツールが作った予定の目印（`MANAGED_PROPERTY_KEY`）と企業ログとの対応キー（`COMPANY_PROPERTY_KEY`） |
| `scripts/gcal/slots.py` | 空き枠算出の純粋関数（API を呼ばない）。busy の合成、稼働時間帯・曜日・祝日・バッファ・刻みでの空き枠、返信用の表記 |
| `scripts/gcal/list_calendars.py` | 参照できるカレンダーの一覧（ID・表示名・primary・権限）を保存 |
| `scripts/gcal/list_events.py` | 期間内の予定一覧を保存。`--job-only` でこのツールが作った予定だけ |
| `scripts/gcal/find_slots.py` | freeBusy から面談候補（空き枠）を出して保存。`--summary` で返信用テキスト |
| `scripts/gcal/manage_events.py` | 予定の `create` / `get` / `update` / `delete`（目印付き作成・ガード・変更前バックアップ・`--dry-run`） |

読み取り系（`list_*` / `find_slots` / `manage_events.py get`）はエージェントが実行してよい。`manage_events.py` の `create` / `update` / `delete` は内容（日時・タイトル）をユーザーに提示して確認を取ってから実行する。stdout は保存したファイルのパスだけ、進捗・エラーは stderr。

---

## 2. カレンダー一覧（`list_calendars.py`）

```powershell
uv run python scripts/gcal/list_calendars.py --summary
```

- primary → owner のカレンダー → その他の順に並べる。
- `access_role` が `owner` のカレンダーだけが予定の作成・更新・削除・`list_events.py` の対象になる（`calendar.events.owned`）。`reader` 等のカレンダーは `find_slots.py` の busy にだけ使える。
- **どのカレンダーを busy に含めるかはユーザーに確認する**（primary だけだと共有カレンダーの予定を見落とす）。決めた ID は vault 等の非公開側に置き、docs・コードに実 ID を書かない。

---

## 3. 予定一覧（`list_events.py`）

```powershell
# 今日から 14 日分（primary）
uv run python scripts/gcal/list_events.py --summary

# 期間とカレンダーを指定
uv run python scripts/gcal/list_events.py --since 2026-11-01 --until 2026-11-30 --calendar <calendar-id>

# このツールが作った予定だけ
uv run python scripts/gcal/list_events.py --job-only --summary
```

| オプション | 意味 |
| --- | --- |
| `--since` / `--until` | `YYYY-MM-DD`。`--until` は当日を含む。省略時は今日から 14 日分 |
| `--calendar` | カレンダー ID（既定 `primary`）。自分所有のカレンダーだけ読める |
| `--job-only` | `extendedProperties.private` の `job_hunt_managed=1` が付いた予定だけ |
| `--tz` | 日付の区切りと表示のタイムゾーン（既定 `Asia/Tokyo`） |
| `-n` / `--limit` | 件数の上限（既定 100） |

- 繰り返し予定は展開する（`singleEvents=true`、開始順）。
- 予定のタイトルを含むので、保存先は `data/gcal/events/`（gitignore 済）だけ。vault には予定 ID と要約だけを書く。

---

## 4. 面談候補日（`find_slots.py`）

```powershell
# 今日から 14 日分、平日 10〜19 時、60 分以上の空き（primary）
uv run python scripts/gcal/find_slots.py --summary

# 期間・時間帯・所要時間を指定し、共有カレンダーも busy に含める
uv run python scripts/gcal/find_slots.py --since 2026-10-26 --until 2026-11-06 --hours 13-18 --duration 45 `
  --calendar primary --calendar <shared-calendar-id> --summary

# カレンダー未登録の面談（vault の scheduled 等）を busy に足す
uv run python scripts/gcal/find_slots.py --busy "2026-10-28 15:00-16:00" --summary

# overseas: 相手の現地時刻・英語表記で出す（時間帯・祝日の判定は --tz 側）
uv run python scripts/gcal/find_slots.py --display-tz America/Los_Angeles --lang en --summary
```

| オプション | 既定 | 意味 |
| --- | --- | --- |
| `--since` / `--until` | 今日〜14 日分 | `YYYY-MM-DD`。`--until` は当日を含む。今日を含むときは現在時刻より後だけ |
| `--duration` | 60 | 必要な所要時間（分）。これ未満の空きは出さない |
| `--hours` | `10-19` | 候補にする時間帯（`9:30-18:00` 形式も可。日跨ぎ・24:00 は不可） |
| `--weekdays` | `mon-fri` | 候補にする曜日（`mon,wed,fri`、`fri-mon` のような範囲も可） |
| `--buffer` | 15 | 既存予定の前後に空ける時間（分） |
| `--align` | 30 | 枠の開始・終了を揃える刻み（分） |
| `--holidays` | `JP` | 除外する祝日の国コード（ISO 3166-1）。`none` で除外しない |
| `--calendar` | `primary` | busy に含めるカレンダー ID（複数回指定可、最大 50） |
| `--busy` | なし | カレンダー未登録の予定を busy に足す（`'YYYY-MM-DD HH:MM-HH:MM'`、`--tz` の現地時刻。複数回指定可） |
| `--tz` | `Asia/Tokyo` | 時間帯・曜日・祝日を判定するタイムゾーン |
| `--display-tz` | `--tz` と同じ | 表示のタイムゾーン。`--tz` と違うときは TZ 略号を付ける |
| `--lang` | `ja` | `ja`: `10/28(水) 13:00〜15:00` / `en`: `Wed, Oct 28 13:00-15:00 (JST)` |
| `-n` / `--limit` | 30 | 候補数の上限（先頭から） |

- 既定値は汎用の値。ユーザー固有の希望（面談可能な時間帯・曜日・バッファ）は vault（track の `strategy.md` 等）を正とし、AI が引数で渡す。コードに個人の希望を書かない。
- 出力は**連続した空きをそのまま**並べたもの。相手に出す候補は AI が相手・状況に合わせて間引く（均等に散らす等の自動選択はしない）。
- 対象カレンダーのどれかで freeBusy がエラー（`notFound` 等）を返したら、候補を出さずに終了コード 1 にする（一部のカレンダーを黙って抜かすと、埋まっている時間を空きと誤認するため）。

---

## 5. 候補日算出の仕様

`scripts/gcal/slots.py`（テストは `tests/test_gcal_slots.py`）。

1. busy 区間（freeBusy ＋ `--busy`）を前後に `--buffer` 分ずつ広げて合成する（重なる・接する区間は 1 つにまとめる）。
2. 期間内の日を `--tz` で区切り、`--weekdays` に含まれず祝日でもない日だけ、`--hours` の稼働時間帯を作る。期間の端（現在時刻など）で切り詰める。
3. 稼働時間帯から busy を引いた残りを、開始は `--align` 刻みに切り上げ・終了は切り下げ、`--duration` 未満を捨てる。
4. 表示は `--display-tz` に変換する。表示タイムゾーンで日付を跨ぐ枠は終了側にも日付を付ける（例: `10/27(火) 18:00〜10/28(水) 03:00 (PDT)`）。DST の切替を跨ぐ枠は `(PDT/PST)` のように両方の略号を付ける。

- 祝日は Python の `holidays` パッケージで判定する（Google の祝日カレンダーは「予定なし」表示のため freeBusy に出ず、使わない）。
- Windows では `zoneinfo` に IANA データが無いため `tzdata` パッケージに依存する。

---

## 6. 予定の作成・更新・削除（`manage_events.py`）

```powershell
# 作成（面談確定時）。まず --dry-run で内容を確認
uv run python scripts/gcal/manage_events.py create --title "【面談】株式会社〇〇 カジュアル面談" `
  --start "2026-10-28 15:00" --duration 45 --location "<相手から届いた会議 URL>" --company-key <company-key> --dry-run
uv run python scripts/gcal/manage_events.py create ...（同じ引数で --dry-run を外す） --summary

# 取得（ID は create の出力、または list_events.py --job-only で確認）
uv run python scripts/gcal/manage_events.py get --id <event-id> --summary

# リスケ（開始だけ変えると元の所要時間を保つ）
uv run python scripts/gcal/manage_events.py update --id <event-id> --start "2026-10-30 11:00" --summary

# 削除（辞退・キャンセル時）
uv run python scripts/gcal/manage_events.py delete --id <event-id> --summary
```

| サブコマンド | 主なオプション |
| --- | --- |
| `create` | `--title`（必須）、`--start`（必須、`'YYYY-MM-DD HH:MM'`）、`--end` か `--duration`（既定 60 分）、`--location`、`--description`、`--company-key` |
| `get` | `--id` |
| `update` | `--id` ＋ 変えたい項目だけ（`--title` / `--start` / `--end` / `--duration` / `--location` / `--description` / `--company-key`）。`--start` だけなら元の所要時間を保つ |
| `delete` | `--id` |
| 共通 | `--calendar`（既定 `primary`）、`--tz`（日時の解釈と表示。既定 `Asia/Tokyo`）、`-s` / `--json`。書き込み系は `--dry-run` / `--force` |

### 安全ガード

| ガード | 挙動 | `--force` で外せるか |
| --- | --- | --- |
| 目印 | `create` は `extendedProperties.private` に `job_hunt_managed=1`（`--company-key` があれば `job_hunt_company_key`）を付ける。`update` / `delete` は目印のある予定だけ | 外せる（私用予定を変えるとき。ユーザーの明示確認を取ってから） |
| 招待予定 | 自分が organizer でない予定（企業から届いた招待）は変更・削除しない。ここで変えても相手側に反映されず、削除は辞退扱いになり得るため。リスケ・辞退は相手に連絡する | 外せない |
| ゲスト付き予定 | 自分以外の attendees がいる予定は変更・削除しない（相手のカレンダーに及ぶ） | 外せない |
| 通知 | 全操作で `sendUpdates=none` 固定。attendees を指定するオプションは無い | — |
| 重複作成 | `create` 前に同じ日（`--tz` の現地日付）の目印付き予定を探し、同じ `company_key`（無ければ同じタイトル）があれば作らない | 外せる（同日に 2 回面談がある等） |
| 競合 | `update` / `delete` は直前に `get` した etag を `If-Match` で送る。他所で変更されていれば 412 で止まる（終了コード 1）。`get` し直して確認する | — |
| バックアップ | `update` / `delete` の直前の予定 JSON を `data/gcal/backups/` に保存（誤操作時はここから手で戻す） | — |
| 終日予定 | 終日予定の日時変更は非対応（タイトル等の変更はできる）。`create` も時刻指定の予定だけ | — |

- 書き込めるのは `access_role` が `owner` のカレンダーだけ（`calendar.events.owned`）。それ以外は 403 で終了コード 1。
- Meet 等の会議 URL は自動生成しない。相手から届いた URL を `--location` か `--description` に書く。
- タイトルは `【面談】{会社名} {ステージ}` 程度にとどめる。カレンダーは他デバイス・共有先に表示されうるので、fit_score・本音メモ・`visibility: internal` の情報はタイトル・説明に書かない。

### vault との関係

- 確定日時の正は vault（企業ログの `next_due`）。カレンダーはその写し。リスケしたら両方を直す。
- 予定 ID は vault のスキーマに持たせない（フロントマターのフィールドは追加しない）。企業ログとの対応は予定側の `job_hunt_company_key` で逆引きする。面談ログの本文に予定 ID をメモするのは構わない。

---

## 7. 保存形式（`data/gcal/`）

```
data/gcal/
├── calendars/YYYY-MM-DD-HHmmss.{md,json}   # list_calendars.py
├── events/YYYY-MM-DD-HHmmss.{md,json}      # list_events.py
├── slots/YYYY-MM-DD-HHmmss.{md,json}       # find_slots.py
├── event/YYYY-MM-DD-HHmmss.{md,json}       # manage_events.py get
├── changes/YYYY-MM-DD-HHmmss.{md,json}     # manage_events.py create / update / delete（操作後の予定。delete は削除前の内容）
└── backups/YYYY-MM-DD-HHmmss_{action}_{event-id}.json  # update / delete 直前の予定（API の生 JSON）
```

- `.md` はフロントマター（`source: gcal`、`type`、条件、件数、`fetched_at`）＋表。`.json` は同じフロントマターの値＋一覧（`calendars` / `events` / `slots`）。
- `slots` の各要素: `start` / `end`（`--tz` のオフセット付き ISO 8601）、`minutes`、`text`（返信用表記）。
- `events` の各要素: `id`、`summary`、`start` / `end`（終日は `YYYY-MM-DD`、`end` は翌日＝排他）、`all_day`、`status`、`transparency`、`event_type`、`managed`、`private_properties`、`html_link`。
- `event` / `changes` のフロントマター: `action`、`calendar`、`event_id`（update は `changed` に変えた項目）。`.json` の `event` は `events` の各要素＋ `location` / `description` / `organizer_self` / `guest_count` / `etag`。
- `find_slots.py` は予定の本文を取らないので、`slots/` には busy の中身（タイトル等）は残らない。

---

## 8. API の挙動メモ

調査日: 2026-10-22。

- **freeBusy**: 応答はカレンダーごとの `busy[]`（開始を含み終了を含まない）。HTTP 200 でもカレンダー単位の `errors[]`（`notFound` 等）が入るので必ず見る。`timeZone` を渡さないと UTC（`Z`）で返る。
- **「予定なし」表示の予定**（`transparency: transparent`。祝日カレンダーの予定も）は busy に入らない。終日予定は「予定あり」なら busy に入る（API の仕様。実データでは未確認）。
- **reader 権限のカレンダー**（共有された他人のカレンダー）も `calendar.events.freebusy` で busy を取れることを実 API で確認済み。予定の本文は `events.list` で読めない。
- **辞退した予定**が busy に入るかは公式記述がなく未検証。気になる場合は `list_events.py` と突き合わせる。
- **events.list**: `timeMin` は予定の終了時刻の下限、`timeMax` は開始時刻の上限。`privateExtendedProperty` は複数条件の意味がドキュメント間で食い違うので 1 条件だけで使う。
- **events.insert / patch / delete**: `sendUpdates` は insert 以外で既定の記載が無いので常に `none` を明示する。patch は配列フィールドを丸ごと置き換える（このツールは配列を触らない）。`extendedProperties` のキーは 44 文字超で黙って破棄されるので短く保つ。
- **条件付き更新**: patch / delete に `If-Match: <etag>` を付けると、変更済みなら 412 `conditionNotMet`。削除済みの予定への delete は 410。
- **削除済みの予定の get**: 404 ではなく `status: cancelled` で返る（実 API で確認）。`manage_events.py` はこれをガードで拒否する。
- **作成・更新・削除の実 API 確認**（2026-10-22）: primary にテスト予定を create → 重複ガード → update（開始変更で所要時間維持）→ `list_events.py --job-only` に出る → delete、目印なしの予定の delete がガードで拒否されることを確認。

参照: [freebusy.query](https://developers.google.com/workspace/calendar/api/v3/reference/freebusy/query) / [events.list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list) / [calendarList.list](https://developers.google.com/workspace/calendar/api/v3/reference/calendarList/list) / [events.insert](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert) / [events.patch](https://developers.google.com/workspace/calendar/api/v3/reference/events/patch) / [events.delete](https://developers.google.com/workspace/calendar/api/v3/reference/events/delete) / [etag と条件付き更新](https://developers.google.com/workspace/calendar/api/guides/version-resources)
