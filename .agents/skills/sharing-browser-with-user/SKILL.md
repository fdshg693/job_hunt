---
name: sharing-browser-with-user
description: Opens a real, visible (headed) browser that the agent drives while the USER performs the login themselves in that same window — for sites behind a sign-in, MFA, SSO, CAPTCHA or a consent screen. The session is kept in a persistent profile so the login survives across runs and across sessions. Use when a task needs a logged-in site, when the user says "I'll log in myself" / "use my account" / "don't touch my password", when a previously working automation starts hitting a login wall, or when asked to watch what the browser is doing. For browser work that needs no sign-in, use using-playwright-cli instead.
allowed-tools: Bash(playwright-cli:*) Bash(node:*) Bash(powershell.exe:*) Read
# 同梱ファイル:
#   - scripts/profiles.mjs: 既存プロファイルの一覧・説明の登録（毎回発明しないための同梱スクリプト）
#   - .env.example: プロファイル置き場のパス設定。`.env` にコピーすればリポジトリごとに変更可
#   - references/handoff-protocol.md: 認証をユーザーに渡すときの言い回し・待ち方・禁止事項
#   - references/profiles.md: プロファイルの置き場・命名・寿命・削除・複数サイトの扱い
#   - references/troubleshooting.md: 再ログイン要求／多重起動／Google ブロック／attach フォールバック
#   - references/scripted-automation.md: 繰り返す作業をスクリプト化するときの指針と、認証壁に当たったときの契約
#   - scripts/notify-user.ps1: 手動ログイン待ちに入るときの OS 通知（ベストエフォート。失敗しても exit 0）
#   - README.md: メンテナ向け。設計意図、using-playwright-cli との責務分担
# 暗黙の前提:
#   - `playwright-cli`（@playwright/cli）がグローバル導入済み。未導入時は using-playwright-cli の Installation 節
#   - Windows + 実 Chrome チャネルが既定（.claude/docs/browser-handoff-notes.md の実測環境）
#   - ユーザーが対話可能なセッションであること（認証の手動実行を依頼するため）
# 設計メモ:
#   - CLI のフラグ仕様はここに転記しない。正は using-playwright-cli/output/ 側 1 箇所。
#     このスキルは「手順 + 禁止事項」だけを持つ
#   - 実測で確定した事実の根拠は .claude/docs/browser-handoff-notes.md
# 依存スキル: using-playwright-cli（コマンド仕様の正）
---

# 実ブラウザをユーザーと共有する（認証はユーザーが行う）

エージェントが **headed（可視）の実ブラウザ**を立ち上げ、ログインだけをユーザーが同じウィンドウで手で行う。
認証後の操作はエージェントが続ける。ログイン状態は**永続プロファイル**に残り、次回以降は再ログイン不要。

**このスキルを使う線引き**: サインインが絡むとき、またはユーザーに画面を見せたいときだけ。
ログイン不要のブラウザ操作は [using-playwright-cli](../using-playwright-cli/SKILL.md) に流す。
コマンド一覧・オプションの仕様もそちら（`output/playwright-cli/`）が正で、このスキルでは補わない。

## 絶対に守ること

1. **認証フェーズ中はセッションに対してコマンドを一切発行しない。**
   `snapshot` / `screenshot` / `pdf` / `find` / `goto` / `state-save` / `cookie-*` / `localstorage-*` /
   `run-code` / `eval` はもちろん、ページに触れる系すべて。ユーザーが「終わった」と言うまで**待つだけ**。
   「読まない」ではなく「打たない」なのは、**実行した時点で出力がエージェントの会話に入る**ため
   （`snapshot` / `find` はページ本文をそのまま stdout に出し、抑止フラグは無い）。
   加えて `open` / `goto` / `reload` は `.playwright-cli\page-*.yml` にページ全体を書き出す。
   唯一許容されるのは daemon の情報しか見ない `playwright-cli list`。
2. **資格情報を受け取らない・聞かない。** ID / パスワード / MFA コード / リカバリコードを
   会話に書かせない。ユーザーが貼ってきた場合も使わず、ブラウザ側で入力するよう促す。
3. **プロファイルディレクトリを Read しない。** Cookie DB やログを開けば認証情報が読めてしまう。
   中身の確認が必要なときも `playwright-cli list` の出力だけを見る。
4. **認証完了はユーザーの宣言で判断する。** URL や要素のポーリングで「ログインできたか」を推測しない。
5. **検知回避に踏み込まない。** `--disable-blink-features=AutomationControlled` 等は使わない。
   弾かれたら [troubleshooting.md](references/troubleshooting.md) のフォールバック（`attach`）へ。

## 手順

### Phase 0 — 既存プロファイルを先に確認する（毎回やる）

**新しいプロファイルを作る前に、使い回せるものがないかを必ず見る。** 使い捨てを増やすと
再ログインの回数が増えるだけで、ログイン状態を永続化した意味がなくなる。

```bash
node .claude/skills/sharing-browser-with-user/scripts/profiles.mjs list
```

出力は `site` / `description` / `url` / `last-login` / `tags` の表。判断はこの表だけで行う
（プロファイルの中身は開かない）。

- **対象サイト用のプロファイルがある** → その `site` をそのまま Phase 1 で使う。多くの場合 Phase 2 は不要
- **説明が `(説明なし)` のものしかない** → 名前から用途が推測できるならユーザーに確認する。
  推測できないものを流用しない（別アカウントでログインしている可能性がある）
- **ない** → Phase 1 で新規に作り、**認証が終わったら必ず `register` する**（下記）

補助コマンド:

```bash
P=".claude/skills/sharing-browser-with-user/scripts/profiles.mjs"
node $P show <site>      # 1 件の詳細 + メモ本文
node $P path <site>      # --profile に渡すパスだけを出力
node $P config           # 解決済みの ROOT / META パス
node $P list --json      # 機械処理用
```

置き場を変えたいリポジトリでは `.env.example` を `.env` にコピーして
`BROWSER_PROFILES_ROOT` / `BROWSER_PROFILES_META` を設定する（優先順位は 環境変数 > `.env` > 既定値）。

### Phase 1 — 可視ブラウザを起動する

セッション名とプロファイルパスは**サイトごとに固定**する（規約は [profiles.md](references/profiles.md)）。
`<site>` は対象のホスト名由来の短い識別子（例: `github`, `kintone`, `salesforce`）。

```bash
# パスはスクリプトに出させる。--profile は毎回必ず付ける（付け忘れると in-memory になり前回のログインが見えない）
PROFILE="$(node .claude/skills/sharing-browser-with-user/scripts/profiles.mjs path <site>)"

# open はページの読み込みが落ち着くまで戻らず、数分かかるサイトもある。必ずバックグラウンドで起動する
playwright-cli -s=<site> open <url> --headed --profile="$PROFILE" &
```

`<url>` には**ログイン画面そのものを指定してよい**。`open` は自動 snapshot を保存するが、撮られるのは
遷移直後＝ユーザーが入力する前なので資格情報は写らない。写るのを避けたいのは**ここから先**であり、
だから「絶対に守ること」1 は認証中のコマンド発行そのものを禁じている。

PowerShell なら `$env:LOCALAPPDATA` を使い、`Start-Process` かバックグラウンドジョブで起動する。

起動したら次を確認してから先に進む:

```bash
playwright-cli list    # 対象セッションが status: open、user-data-dir が上記 PROFILE になっていること
```

`user-data-dir: <in-memory>` と出たら `--profile` の付け忘れ。閉じて付け直す。
`open` がまだ戻っていなくても `status: open` なら窓は使える状態にある。

### Phase 2 — 認証をユーザーに渡す

**まずログイン済みかを確かめる。** 起動 URL がログイン後の画面なら Phase 2 は丸ごと飛ばしてよい。
判定は `open` の出力（または `list` 実行後の `find <ログイン後にだけ出る語>`）の **Page URL** だけで行う。
認証ドメインに飛ばされていたら（例: `www.example.com/login/` → `auth.example.com/...`）そこで
読み取りをやめ、以下に移る。

ログイン画面と判定したあとに追加のコマンドを打たない。Phase 3 で使う判定と同じものを流用しようとして
`snapshot` を撃つのが一番ありがちな事故。

1. ユーザーに「ブラウザを開いた。この窓でログインしてほしい。終わったら教えて」と伝える
   （文面と伝えるべき項目は [handoff-protocol.md](references/handoff-protocol.md)）
2. **待つ。** この間、上の「絶対に守ること」1 に挙げたコマンドを一切実行しない。
   `playwright-cli list` でセッションが生きているかの確認だけは許容する
3. ユーザーの完了宣言を受けてから Phase 3 に進む
4. **完了宣言を受けたら、そのプロファイルを登録する**（次回 Phase 0 で判断できるようにするため）:

   ```bash
   P=".claude/skills/sharing-browser-with-user/scripts/profiles.mjs"
   node $P register <site> --description "<何用か・どのアカウント種別か>" --url "<入口 URL>" --tags "<任意>"
   node $P used <site>      # last-login を今日に更新。以後ログインし直すたびに実行する
   ```

   `--description` には**アカウントを特定できる情報（メールアドレス・社員番号など）を書かない**。
   「自分の GitHub アカウント」「会社の kintone」程度の粒度でよい。

### Phase 3 — 通常操作に戻る

以降は [using-playwright-cli](../using-playwright-cli/SKILL.md) の通常手順。
同じ `-s=<site>` を指定し続ける限り同じブラウザ・同じログイン状態で操作できる。

作業が終わったら:

```bash
playwright-cli -s=<site> close    # プロファイルは残るので次回は再ログイン不要
```

`delete-data` は**認証状態も消える**。トラブルシュート以外で使わない。

**同じ手順を後日また実行するなら**、その場の操作で終わらせずスクリプトに落とす。判断基準と、
認証が切れていたときの契約（通知 → タイムアウト付き待機 → 再開 or 中断）は
[scripted-automation.md](references/scripted-automation.md)。

## 次回以降の実行

Phase 0 の `list` で使えるプロファイルを確認し、同じ `-s=<site>` と同じ `--profile` で Phase 1 を
実行するだけ（`--profile` の値は `profiles.mjs path <site>` が出す）。サイト側のセッションが生きていれば
ログイン画面は出ず、Phase 2 は不要。出た場合は Phase 2 をもう一度回す（説明は
[handoff-protocol.md](references/handoff-protocol.md) の「再ログインを頼むとき」）。

## 個別トピック

| 状況 | 見る場所 |
|---|---|
| ユーザーへの依頼の文面・待ち方・完了宣言の扱い | [references/handoff-protocol.md](references/handoff-protocol.md) |
| 既存プロファイルの一覧・説明の登録（スクリプト） | [scripts/profiles.mjs](scripts/profiles.mjs) / [references/profiles.md](references/profiles.md) |
| プロファイルの置き場・命名・複数サイト・削除・秘匿情報 | [references/profiles.md](references/profiles.md) |
| 同じ作業を繰り返す＝スクリプト化する／スクリプトが認証壁に当たった | [references/scripted-automation.md](references/scripted-automation.md) |
| 毎回ログインを求められる／多重起動エラー／Google に弾かれた | [references/troubleshooting.md](references/troubleshooting.md) |
| CLI のコマンド・オプションそのもの | [using-playwright-cli](../using-playwright-cli/SKILL.md) の `output/` |
| 実測で確定した挙動の根拠 | [.claude/docs/browser-handoff-notes.md](../../docs/browser-handoff-notes.md) |
