# Google API 共通認証ガイド（Gmail・Calendar）

Gmail 連携（[`docs/gmail/README.md`](../gmail/README.md)）と Google カレンダー連携が共有する、GCP 側の準備・認証情報の置き場所・認可・失効対応をまとめる。

- 1 つの GCP プロジェクト・1 つの OAuth クライアント・1 つの `token.json` で Gmail と Calendar の両方を扱う。
- 認証はユーザー OAuth（Installed App フロー）。個人 Gmail ではサービスアカウントのドメイン全体の委任が使えないため。
- スコープはサービス別に [`scripts/google/client.py`](../../scripts/google/client.py) でだけ定義し、`token.json` はその**和集合と完全一致**するものだけを受け付ける（[§6](#6-スコープ)）。

---

## 目次

1. [セットアップ（GCP の準備）](#1-セットアップgcp-の準備)
2. [認証情報の置き場所](#2-認証情報の置き場所)
3. [トラブルシューティング（セットアップ）](#3-トラブルシューティングセットアップ)
4. [初回認可（`auth.py`）](#4-初回認可authpy)
5. [トークン失効時の対処](#5-トークン失効時の対処)
6. [スコープ](#6-スコープ)
7. [スクリプト一覧](#7-スクリプト一覧)
8. [旧 Gmail 専用構成からの移行](#8-旧-gmail-専用構成からの移行)

---

## 1. セットアップ（GCP の準備）

GCP リソースはすべて手動で用意する（同意画面・OAuth クライアントは Terraform 等で作れないため）。請求先アカウント（billing）は不要。

| リソース | 作り方 |
| --- | --- |
| GCP プロジェクト（組織・請求先アカウントなし） | gcloud |
| `gmail.googleapis.com` / `calendar-json.googleapis.com` の有効化 | gcloud |
| OAuth 同意画面（External・Testing、自分をテストユーザーに登録） | Console |
| OAuth クライアント（デスクトップアプリ）の `client_secret.json` | Console |

クラウドを変更するコマンドと Console 操作はユーザーが自分の外部ターミナル・普段のブラウザで行う。エージェントは `describe` / `list` などの読み取りコマンドで結果を確かめるだけにする。

### 1.1 gcloud のログイン

```powershell
gcloud auth list                 # アクティブなアカウントを確認
gcloud auth login                # 違うアカウント、またはトークン期限切れ（invalid_grant）のとき
```

- `gcloud auth application-default login`（ADC）は不要。このリポジトリの Google 連携は ADC を使わない。
- gcloud の既定プロジェクト（`gcloud config set project`）は変えず、以降のコマンドには `--project=` を付ける。

### 1.2 プロジェクトの作成

```powershell
gcloud projects create <project-id> --name="job-hunt-google"
gcloud projects describe <project-id>     # lifecycleState: ACTIVE を確認
```

- プロジェクト ID は全世界で一意かつ変更不可。Console で作る場合は自動生成の ID でよい。
- プロジェクト ID はリポジトリに書かない（スクリプトは `client_secret.json` しか使わないので不要）。
- Gmail 連携だけの頃に作った `job-hunt-gmail` プロジェクトはそのまま使ってよい（ID・表示名は変えなくてよい）。

### 1.3 API の有効化

```powershell
gcloud services enable gmail.googleapis.com calendar-json.googleapis.com --project=<project-id>
gcloud services list --enabled --project=<project-id>    # gmail.googleapis.com と calendar-json.googleapis.com があることを確認
```

### 1.4 OAuth 同意画面（Google Auth platform）

Console の「Google Auth platform」（旧「OAuth 同意画面」）で設定する。URL の `project=` にプロジェクト ID を入れる。

1. **初期設定** — `https://console.cloud.google.com/auth/overview?project=<project-id>` で「開始（Get started）」
   - アプリ名: `job-hunt-google`（既存の `job-hunt-gmail` のままでも動く。ブランディング画面で変えてよい）
   - サポートメール・連絡先メール: 自分の Gmail アドレス
   - 対象（Audience）: **外部（External）**（個人 Gmail には組織が無いので内部は選べない）
2. **対象** — `https://console.cloud.google.com/auth/audience?project=<project-id>`
   - 公開ステータスは **テスト中（Testing）** のまま。「アプリを公開」は押さない
   - テストユーザーに自分の Gmail アドレスを追加
   - 「ブランディングページで構成を完了する必要があります」の表示は公開時のみ必要なので無視してよい
3. **データアクセス（任意）** — `https://console.cloud.google.com/auth/scopes?project=<project-id>`
   - [§6](#6-スコープ) の 4 スコープを追加して保存（同意画面に表示させるため。認可時にスクリプトが要求するので必須ではない）
   - `calendar.events.owned` / `calendar.events.freebusy` は一覧に出ないことがある。その場合は「スコープを手動で追加」に URL を貼る
   - 「制限付きスコープ」「機密性の高いスコープ」と表示されるが、Testing のまま自分だけで使うので審査は不要

> [!WARNING]
> Testing 状態では refresh token が **7 日で失効**する（パスワード変更・6 か月未使用・アクセス取り消しでも失効）。失効すると `invalid_grant`（google-auth では `RefreshError`）になり、再認可が必要。

### 1.5 OAuth クライアント（デスクトップアプリ）

既存のクライアント（Gmail 連携で作ったもの）があれば、その `client_secret.json` を新しい置き場所へ移すだけでよい（[§8](#8-旧-gmail-専用構成からの移行)）。作り直す場合:

1. `https://console.cloud.google.com/auth/clients?project=<project-id>` →「クライアントを作成」
2. アプリケーションの種類: **デスクトップ アプリ**（ウェブ アプリケーションではない）
3. 作成後のダイアログ（または一覧のダウンロードアイコン）から JSON をダウンロード
4. `client_secret.json` にリネームして、[2. 認証情報の置き場所](#2-認証情報の置き場所) に置く
5. 作り直した場合は、使わなくなった旧クライアントを一覧から削除する（不要な秘密を GCP 側に残さない）

```powershell
New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\job-hunt\google"
Move-Item "$env:USERPROFILE\Downloads\client_secret_*.json" "$env:LOCALAPPDATA\job-hunt\google\client_secret.json"
Test-Path "$env:LOCALAPPDATA\job-hunt\google\client_secret.json"
```

---

## 2. 認証情報の置き場所

| ファイル | 既定パス | 内容 |
| --- | --- | --- |
| `client_secret.json` | `%LOCALAPPDATA%\job-hunt\google\client_secret.json` | OAuth クライアント情報（1.5 でダウンロード） |
| `token.json` | `%LOCALAPPDATA%\job-hunt\google\token.json` | アクセストークン・refresh token（`auth.py` が作成。refresh のたびに上書き）。独自キー `job_hunt_authorized_at` に初回認可の日時を持つ |

- ディレクトリは環境変数 `JOB_HUNT_GOOGLE_DIR` で上書きできる（テストや別マシン用）。解決ロジックは `scripts/google/client.py` の `credentials_dir()`。
- 旧 `%LOCALAPPDATA%\job-hunt\gmail\` と旧環境変数 `JOB_HUNT_GMAIL_DIR` は読まない（フォールバックは作らない）。
- リポジトリ（`scripts/` `docs/` は公開同期対象）の外に置く。ブラウザプロファイル（`%LOCALAPPDATA%\claude-browser-profiles\`）と同じ考え方。誤ってリポジトリ内に置いたときの保険として、`.gitignore` に `client_secret*.json` / `token*.json` を入れてある。
- 中身をチャット・ログ・コミットに出さない。エージェントは存在確認（`Test-Path`）と `auth.py --check` だけを行う。

---

## 3. トラブルシューティング（セットアップ）

| 症状 | 対処 |
| --- | --- |
| `gcloud` が `invalid_grant: Token has been expired or revoked` | `gcloud auth login` をやり直す |
| `gcloud projects create` が利用規約への同意を求めるエラー | 初めて GCP を使うアカウントで起こる。Console を一度開いて規約に同意してから再実行 |
| プロジェクト作成数の上限エラー | 不要なプロジェクトを削除する |
| 有効化直後に API 呼び出しが失敗する | 反映に数分かかることがある。少し待って再試行 |
| 同意画面で「内部」を選べない | 個人 Gmail には組織が無いため。「外部」を選ぶ |

---

## 4. 初回認可（`auth.py`）

ブラウザでの同意が要るので、**ユーザーが自分の外部ターミナルで**実行する（エージェントが起動したブラウザはユーザーに見えないことがあるため。`playwright-action.md` と同じ方針）。

```powershell
uv run python scripts/google/auth.py
```

1. 既定のブラウザが開く（開かないときはターミナルに出た URL を開く）。ローカルの空きポート（`port=0`）でリダイレクトを受けるので、ポート指定は不要。
2. 1.4 でテストユーザーに登録した Gmail アカウントを選ぶ。
3. 「Google はこのアプリを確認していません」と出たら「続行」（Testing 状態の自作アプリなので想定どおり）。
4. アクセス権限がスコープごとのチェックボックスで並ぶ（分割同意）。**すべてにチェックを入れて**「続行」。1 つでも外すと、外したものを表示して失敗する（終了コード 2）。
5. 「認可が完了しました」のタブが出たら閉じる。stdout に `token.json` のパスが出て、stderr に失効の目安（認可から 7 日後）が出る。

エージェントは次のコマンドでトークンが使えるかだけを確かめる（ブラウザは開かない）。

```powershell
uv run python scripts/google/auth.py --check
```

- トークンを読み込み、期限切れなら refresh し、Gmail の `users.getProfile` と Calendar の `calendarList.list(maxResults=1)` を 1 回ずつ呼んで確かめる。メールアドレス・カレンダー名等の結果は出力しない。
- 成功時は stderr に「失効の目安（残り約 N 日）」を出す。残り 1 日未満なら警告になるので、面談前など大事なタイミングの前に再認可しておく。
- stdout には何も出さない（ファイルを作らないため）。判定は終了コードで行う。

| 終了コード | 意味 |
| --- | --- |
| 0 | 正常（`--check` はトークン有効） |
| 1 | その他のエラー（API 未有効化、ネットワーク等） |
| 2 | ユーザーの再認可が必要（未認可・失効・スコープ不一致・`client_secret.json` が無い）。stderr に再認可コマンドを出す |

Gmail・Calendar の各スクリプトも同じ終了コード 2 の約束に従う。

---

## 5. トークン失効時の対処

Testing 状態では refresh token が失効するのが日常的に起きる。失効すると各スクリプトは「トークン失効（invalid_grant）」と出して終了コード 2 で止まる。

| 失効の条件 | 備考 |
| --- | --- |
| 認可から 7 日経過 | 同意画面が Testing の間は必ず起きる。`--check` で残り日数を確認できる |
| Google アカウントのパスワード変更 | Gmail スコープを含むトークンは失効する |
| 6 か月未使用 | |
| アクセスの取り消し | [Google アカウントのサードパーティ接続](https://myaccount.google.com/connections) からこのアプリを削除した場合 |

対処はどれも同じで、[4. 初回認可](#4-初回認可authpy) のコマンドをもう一度実行するだけ（`token.json` は上書きされる。事前に消す必要はない）。

| 症状 | 対処 |
| --- | --- |
| 「トークン失効（invalid_grant）」 | `uv run python scripts/google/auth.py` で再認可 |
| 「トークンのスコープが想定と異なります（不足: ...）」 | 同意画面でチェックを外したか、スコープ追加前の古い token.json。すべてにチェックを入れて再認可 |
| 「トークンのスコープが想定と異なります（想定外: ...）」 | 別用途で作った token.json が置かれている。再認可で上書きする |
| 「トークンの更新に失敗しました: RefreshError」（invalid_grant 以外） | `client_secret.json` を作り直した（クライアントを削除・再作成した）場合に起きる。再認可する |
| 「Access blocked: ... has not completed the Google verification process」 | 認可したアカウントがテストユーザーに登録されていない。1.4 の「対象」で追加する |
| `--check` が「Gmail API / Calendar API の呼び出しに失敗しました（HTTP 403）」（終了コード 1） | その API が有効になっていない。1.3 を確認 |

---

## 6. スコープ

定義は `scripts/google/client.py` の `GMAIL_SCOPES` / `CALENDAR_SCOPES` だけに置き、`SCOPES` はその和集合。追加・変更はコードを書く前にユーザーに相談する。

| サービス | スコープ | 同意画面の表示（目安） | 用途 |
| --- | --- | --- | --- |
| Gmail | `https://www.googleapis.com/auth/gmail.readonly` | Gmail のメールの閲覧 | 就活メールの検索・本文取得（送信・ラベル変更・既読化はできない） |
| Calendar | `https://www.googleapis.com/auth/calendar.events.owned` | 自分のカレンダーの予定の閲覧・編集 | 自分所有のカレンダーの予定の一覧・作成・更新・削除 |
| Calendar | `https://www.googleapis.com/auth/calendar.events.freebusy` | カレンダーの空き状況の閲覧 | 面談候補日を出すための空き時間（freeBusy） |
| Calendar | `https://www.googleapis.com/auth/calendar.calendarlist.readonly` | カレンダー一覧の閲覧 | 対象カレンダーの選択 |

- `token.json` のスコープが和集合と**完全一致**しないものは読み込みを拒否して終了コード 2 にする。不足（分割同意で一部を外した、統合前の Gmail だけのトークン）も過剰（`gmail.modify` や全権 `calendar` の混入）も拒否する。部分一致を許すと、外したサービスだけ 403 になり原因が分かりにくいため。
- 全権 `calendar` は使わない（削除・共有設定の変更まで可能で過剰）。細粒度スコープが実 API で通らない場合の代替案は `calendar.events` + `calendar.freebusy` + `calendar.calendarlist.readonly`。
- incremental authorization（`include_granted_scopes`）は使わない。毎回全スコープを一括で要求する。

---

## 7. スクリプト一覧

| スクリプト | 役割 |
| --- | --- |
| `scripts/google/client.py` | 共通層。スコープ定義、認証情報パスの解決、`token.json` の読込・refresh・保存、service の生成（`build_service(api, version)`）、再試行付き実行（`execute()`）。使えないときは `GoogleAuthError` を投げ、呼び出し側は終了コード 2 にする |
| `scripts/google/auth.py` | 初回認可（ユーザーが実行）と `--check`（エージェントが実行） |

`execute()` は 429・`rateLimitExceeded` / `userRateLimitExceeded`（403）・5xx を指数バックオフ（2, 4, 8, 16 秒＋揺らぎ、最大 5 回）で再試行する。401 は `GoogleAuthError`（終了コード 2）にする。400・その他の 403・404・409・412 は再試行しない。

サービス別のスクリプトは各ドキュメントを参照: Gmail → [`docs/gmail/README.md`](../gmail/README.md)、Calendar → [`docs/gcal/README.md`](../gcal/README.md)。

---

## 8. 旧 Gmail 専用構成からの移行

Gmail 連携だけだった頃の `%LOCALAPPDATA%\job-hunt\gmail\` は読まれなくなった。ユーザーが自分の外部ターミナルで次を行う。

1. GCP で Calendar API を有効化し（1.3）、同意画面のデータアクセスに Calendar の 3 スコープを追加する（1.4。任意）。
2. `client_secret.json` を新しい置き場所へ移す（作り直す場合は 1.5）。

   ```powershell
   New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\job-hunt\google"
   Move-Item "$env:LOCALAPPDATA\job-hunt\gmail\client_secret.json" "$env:LOCALAPPDATA\job-hunt\google\client_secret.json"
   ```

3. 再認可する（`uv run python scripts/google/auth.py`。分割同意ではすべてにチェック）。
4. 旧ディレクトリ（古い `token.json` が残っている）を消す。

   ```powershell
   Remove-Item -Recurse "$env:LOCALAPPDATA\job-hunt\gmail"
   ```

5. 環境変数 `JOB_HUNT_GMAIL_DIR` を設定していた場合は、`JOB_HUNT_GOOGLE_DIR` に置き換える。
