# プロファイル（ログイン状態の置き場）

根拠は [.claude/docs/browser-handoff-notes.md](../../../docs/browser-handoff-notes.md)（`@playwright/cli` 0.1.19 / Chrome 152 / Windows 11 実測）。

## 規約

| 項目 | 規約 |
|---|---|
| 置き場 | `%LOCALAPPDATA%\claude-browser-profiles\<site>`（既定値。`.env` で変更可 → 下の「置き場の設定」） |
| `<site>` | 対象のホスト名由来の短い識別子。`github` / `kintone` / `salesforce` など。**一度決めたら変えない** |
| セッション名 | `-s=<site>`。プロファイル名と同じ文字列を使う |
| ブラウザ | `--browser` は省略（既定が実 Chrome チャネル）。明示するなら `--browser=chrome` で固定し、以後変えない |
| `--profile` | **毎回付ける。** 省略すると `<in-memory>` の別プロファイルになり、前回のログインが見えない |

セッション名・ブラウザ・プロファイルパスのどれか 1 つでも変えると**別プロファイル = 再ログイン**になる。
だから固定する。現在のパスは `playwright-cli list` の `user-data-dir` 行で常に確認できる。

## 一覧と説明（`scripts/profiles.mjs`）

手で `ls` せず、同梱スクリプトを使う。毎回パスを思い出す／発明することを避けるための土台。

```bash
P=".claude/skills/sharing-browser-with-user/scripts/profiles.mjs"
node $P list                 # 既存プロファイル + 説明の一覧（表）
node $P list --json          # 機械処理用
node $P show <site>          # 1 件の詳細 + メモ本文
node $P path <site>          # --profile に渡すパス
node $P register <site> --description "..." [--url ...] [--tags a,b] [--note "..."]
node $P used <site>          # last-login を今日に更新
node $P config               # 解決済みの ROOT / META
```

Node 以外の依存はない（PowerShell でも Git Bash でも同じコマンドで動く）。
プロファイル本体の中は**スクリプトも読まない** — ディレクトリ名を列挙するだけ。

### 説明ファイルの形式

1 プロファイル = 1 ファイル。`<META>/<site>.md`:

```markdown
---
name: github
description: 自分の GitHub アカウント（PR レビュー用）
url: https://github.com/
tags: personal,dev
created: 2026-09-15
last-login: 2026-09-15
---

備考は本文に自由に書く。`show` で表示される。
```

- フロントマターは `key: value` の 1 階層だけ（YAML パーサ依存を避けるため）。ネストや配列は使わない
- **`description` にアカウントを特定できる情報を書かない。** メールアドレス・社員番号・テナント名など。
  「会社の kintone」「自分の GitHub」程度の粒度でよい
- 認証が終わったら `register`、以後ログインし直すたびに `used` を叩く。
  `last-login` が古いプロファイルはサイト側セッションが切れている可能性が高い、という目安になる
- プロファイルを消してメタだけ残った場合、`list` に `(削除済)` として出る。不要なら `.md` を消す

### なぜプロファイルディレクトリの中に置かないか

Chrome の user-data-dir に無関係なファイルを置いても動きはする。それでも外に出しているのは、
このスキルの中核ルール「**エージェントはプロファイルディレクトリを読まない**」（[SKILL.md](../SKILL.md)
「絶対に守ること」3）と両立させるため。中に置くと「メタだけ読む」という例外ができ、
Cookie DB の隣を開く運用が常態化する。`_meta/` はプロファイルルート直下・プロファイル本体の外にある。

`_` 始まり・`.` 始まりのディレクトリは `list` の走査対象外なので、`_meta` がプロファイルとして
数えられることはない。

## 置き場の設定（`.env`）

既定値のままで動く。変えたいときだけ `.env.example` を `.env` にコピーする:

```bash
cp .claude/skills/sharing-browser-with-user/.env.example .claude/skills/sharing-browser-with-user/.env
```

| キー | 既定 | 用途 |
|---|---|---|
| `BROWSER_PROFILES_ROOT` | `%LOCALAPPDATA%\claude-browser-profiles` | プロファイル本体のルート |
| `BROWSER_PROFILES_META` | `<ROOT>\_meta` | 説明 Markdown の置き場 |

優先順位は **環境変数 > `.env` > `.env.example` > スクリプト内の既定値**。
`%LOCALAPPDATA%` / `$LOCALAPPDATA` / 先頭の `~` は展開される。

`.env` は upstream の `.gitignore` に入っているためコミットされない。**リポジトリごとに違う置き場を
使える**のはこの仕組み。逆に `.env.example` は追跡されるので、そこに実パスや秘匿値を書かない。

## なぜ `--persistent` の自動生成先に任せないか

`--persistent` だけを指定すると CLI が自動でプロファイルを作るが、その場所は

```
%LOCALAPPDATA%\ms-playwright\daemon\<daemon-hash>\ud-<session>-<browser>
```

で、`<daemon-hash>` は **CLI のインストール実体に紐づく**。`@playwright/cli` を更新するとハッシュが変わり、
旧プロファイルは移行されずに取り残される = **過去のログインが全部消えたように見える**（実測: 0.1.17 →
0.1.19 でルートが変わった）。

「スキル/プロセスをまたいで再ログイン不要」が要件なので、CLI 更新で壊れる置き場は使えない。
よって `--profile` で固定パスを明示する。

## 1 プロファイル = 1 インスタンス

同じ `--profile` を指す 2 つ目のセッションは起動できない:

```
Error: Browser is already in use for <dir>, use --isolated to run multiple instances of the same browser
```

- ユーザーが普段使っている Chrome プロファイルとの共用も同じ理由で不可。
  加えて公式ドキュメントが既定プロファイルの自動化を非サポートと明記している
  （`docs/src/api/class-browsertype.md` の `launchPersistentContext.userDataDir` warning）
- `--isolated` は `open --help` に出てこない内部フラグ。**使わない**（使うと永続化の意味がなくなる）
- 複数サイトを同時に扱うときは `<site>` ごとに別セッション・別プロファイルにする。並行して開ける

## 秘匿情報の扱い

プロファイルディレクトリには**実 Cookie・トークン・場合によっては保存パスワード**が入っている。

- **エージェントはこのディレクトリを Read / Grep / コピーしない。** 中身の確認が必要なときも
  `playwright-cli list` の出力だけを見る
- リポジトリツリー内に置かない（このクローンは公開リポジトリ由来）。だから `%LOCALAPPDATA%` 配下にしている
- `.gitignore` への追加は不要（そもそもリポジトリ外）

**プロファイルとは別に `.playwright-cli/` にも痕跡が残る。** CLI はページに触れるたび、カレント
ディレクトリ直下の `.playwright-cli/` に `page-*.yml`（snapshot）と `console-*.log` を書き出す。
ログイン後に操作すれば**そこに個人情報が入る**。upstream の `.gitignore` に含まれるためコミットは
されないが、作業後に不要なら消してよい（プロファイルと違い、消しても認証状態は失われない）。

## `state-save`（storageState）を既定にしない理由

`state-save` は認証トークンを**平文 JSON でファイルに書き出す**。永続プロファイル方式ならそもそも不要。

使ってよいのは、ユーザーが明示的に「CI に持っていきたい」「別マシンで使いたい」と要求した場合だけ。
そのときも:

- 書き出し先をユーザーに確認する（リポジトリ内には書かない）
- 中身を会話に出さない
- 認証フェーズ中には実行しない（[SKILL.md](../SKILL.md) の「絶対に守ること」1）

## 寿命と掃除

- プロファイル自体に期限はない。切れるのは**サイト側のセッション**。切れたら Phase 2 をもう一度回す
- 使えるプロファイルの棚卸しは `node scripts/profiles.mjs list`。`last-login` が古いものが候補
- 消すときは `playwright-cli -s=<site> delete-data`。**認証状態も消えるので再ログインが必要になる**。
  併せて `<META>/<site>.md` も消す（残すと `list` に `(削除済)` として出続ける）
- **Windows では手動削除がしばしば失敗する。** `close` 直後でも一部ファイル
  （`Default/WebStorage/QuotaManager` 等）が掴まれたままで `Permission denied` になる。
  `rm -rf` ではなく `delete-data` を使い、残骸が残っても致命的ではないものとして扱う
