# トラブルシュート

以下は `@playwright/cli` 0.1.19 での実測に基づく。

## 毎回ログインを求められる

原因はほぼ「別プロファイルを掴んでいる」。順に確認する。

```bash
playwright-cli list     # user-data-dir を見る
```

| `user-data-dir` の値 | 原因 | 対処 |
|---|---|---|
| `<in-memory>` | `--profile` の付け忘れ | `close` して `--profile="$PROFILE"` 付きで開き直す |
| `...\ms-playwright\daemon\<hash>\ud-...` | `--persistent` だけを使っている | `--profile` で固定パスに切り替える。**この時点で過去のログインは引き継げない**ので再ログインになる |
| 想定と違う `claude-browser-profiles\<name>` | `<site>` 名がぶれている | [profiles.md](profiles.md) の規約どおりに名前を固定する |
| 想定どおり | サイト側のセッション期限切れ | 正常。Phase 2 をもう一度回す |

`--browser` を前回と変えた場合も別プロファイル扱いになる。

**「たまにログインを求められる」はここではない。**サイト側のセッション期限は正常な挙動で、
故障ではない。スクリプト化した作業がそれに当たったときの扱いは
[scripted-automation.md](scripted-automation.md) の「認証壁の契約」。

## `Browser is already in use for <dir>` で起動できない

同じプロファイルを指すセッションがすでに動いている。

```bash
playwright-cli list            # 既存セッションを確認
playwright-cli -s=<site> close # 不要なら閉じる。あるいはそのセッションをそのまま使う
```

**そのセッションが目的のものなら閉じずに再利用する**（すでにログイン済みかもしれない）。
`--isolated` は使わない（永続化されなくなる）。

daemon ごと固まっているときの最終手段:

```bash
playwright-cli close-all    # 全セッションを閉じる
playwright-cli kill-all     # daemon ごと落とす
```

なお通常の `close` で daemon プロセスも終了する（`close` 直後の `kill-all` は
`No daemon processes found.` を返す）。`kill-all` が要るのは `close` が効かないときだけ。

## `open` が返ってこない

**ブラウザが閉じるまで待っているわけではない**（0.1.19 実測）。`open` はブラウザを daemon に預けたあと、
指定 URL の読み込みが落ち着くまで待ってから結果を出力する。窓はその間もう開いており操作可能。

常時接続（long-polling / WebSocket）を張るページでは待ちが数分に伸びる。実測: bizreach の
`/login/` は即時に返ったが、ログイン後の `/mypage/` は 120 秒で返らなかった（窓と認証状態は正常）。

よってバックグラウンド起動（bash なら末尾 `&`、PowerShell なら `Start-Process` / ジョブ）が必要。
`open` の完了を待たずに `playwright-cli list` で `status: open` を確認し、ページの状態は
`find <text>` で見る（`snapshot` より出力が小さい）。`open` 自身の出力は取りこぼしても問題ない。

## Google に `This browser or app may not be secure` で弾かれた

Google は webdriver 以外の複数シグナルで自動化起動のブラウザを判定する。
`navigator.webdriver` は false でも弾かれることがある（実測環境でも報告例あり）。

**検知回避のフラグは使わない。** 方式 B（ユーザーが自分で起動した Chrome に接続する）に切り替える。

### 方式 B — `attach --cdp` フォールバック

ユーザーに次を依頼する:

1. Chrome を開き、`chrome://inspect/#remote-debugging` で **Allow remote debugging** を有効にする
2. 有効化後、Chrome を再起動する
3. そのまま `<site>` にログインしてもらう（ここでもエージェントは画面を読まない）
4. 「終わった」宣言を受けてから接続する:

```bash
playwright-cli -s=<site> attach --cdp=chrome
```

B の制約:

- ログイン状態はユーザーの Chrome 側に残る。このスキルの永続プロファイルは使わない（`--profile` は無関係）
- Chrome 136 以降、既定ユーザーデータディレクトリでは `--remote-debugging-port` が無視される
  （https://developer.chrome.com/blog/remote-debugging-port ）。上記の `chrome://inspect` 経由での
  有効化が必要なのはこのため
- 作業後は `playwright-cli -s=<site> detach`。ユーザーの Chrome を `close` で閉じない

B でも弾かれる場合は、そのサイトの自動化を諦めてユーザーに手順を提示する方向に切り替える。

## `delete-data` を使うとき

```bash
playwright-cli -s=<site> delete-data
```

**認証状態が消え、次回は再ログインが必要になる。** 実行前に必ずユーザーに伝えて同意を取る。

- 対象が開いていても成功する（ブラウザは閉じる）: `Deleted user data for browser '<name>'.`
- 対象が無ければ `No user data found for browser '<name>'.`（exit 0）

手動での `rm -rf` は Windows でファイルが掴まれたまま `Permission denied` になりやすいので使わない。

## `cookie-set` が `Invalid cookie fields` になる

`--domain` / `--path` を渡すと `Protocol error (Storage.setCookies): Invalid cookie fields` になることがある。
そもそも**認証状態の投入に `cookie-set` を使わない**（このスキルの方針は「人が本物のブラウザでログインする」）。

## 想定と違うフラグが `--help` に無い

このスキルは 0.1.19 実測を前提にしている。`using-playwright-cli` の `output/`（upstream main の
スナップショット）と実際の CLI にはズレがある（例: `open --idle-timeout` はスナップショットにあるが
0.1.19 の `--help` に無い）。**判断は `playwright-cli <cmd> --help` の実出力を優先し、
差があれば差として報告する。**
