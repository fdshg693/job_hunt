# ブラウザ作業をスクリプトにする（認証壁に当たっても止まらない形で）

[SKILL.md](../SKILL.md) の Phase 3 の先。**同じ手順を繰り返すとき**に、その場の CLI 操作を
再実行可能なスクリプトへ落とすための指針。

前提は 2 つ。**ログインは決定的に成功しない**（サイト側のセッションはいつか切れる）ので、
スクリプトは認証壁に当たったら失敗で終わらず、ユーザーに気づかせてタイムアウト付きで待つ。
そして**認証中でもエージェントがページ本文を読まない**という中核ルールは、スクリプト化しても一切緩まない。

以下は `@playwright/cli` 0.1.19 / Windows 11 / 実 Chrome での実測に基づく。CLI のコマンド・オプションの仕様は
[using-playwright-cli](../../using-playwright-cli/SKILL.md) の `output/` が正で、ここには転記しない。

## 1. スクリプトにする / しない

**既定はスクリプトにしない。** ログイン状態に依存するスクリプトは腐りやすく、腐ったときの
リカバリ（再ログインの依頼）が人間を必要とするため、書いた分だけ保守が増える。

| 状況 | どうするか |
|---|---|
| 1 回きりの調査・探索・「この画面を見てきて」 | **CLI の逐次操作のまま。**スクリプトにしない |
| 同じ手順を後日また実行する（定期取得、月次の集計） | スクリプト |
| 同じ操作を件数分まわす（20 件のチケットを順に開く） | スクリプト |
| 他のセッション／他の人が再現する必要がある | スクリプト |
| 迷う規模（3〜4 手で終わる、使うのは今日だけ） | **スクリプトにしない側に倒す** |
| スクリプトにはしたいが、手順が長い／初見のサイトでロケータが分からない | **一括で書き下ろさない。**[往復ワークフロー](../../using-playwright-cli/references/script-cli-roundtrip.md)で 5 手前後ずつ育てる |
| 途中に「人がやった方が早い区間」がある（認証・CAPTCHA・目視判断） | 同上。その区間を手操作区間にして、`recording-*` で成果だけ回収する |

スクリプトにすると決めたら、**認証壁の契約（3 節）を必ず組み込む。**
「今はログイン済みだから」で省くと、次に切れたときに黙って失敗する。

往復で育てる場合も同じで、**認証壁の契約（3 節）と禁止事項（4 節）は一切緩まない。**
往復側のリファレンスは手順だけを扱い、認証の扱いはこのファイルが正。

## 2. 何を素材にするか

`playwright-cli` は**全アクションが等価な Playwright TypeScript を出力する**。スクリプトは
これを拾って組み立てる。手で新しくロケータを考えない（仕様は
[test-generation.md](../../using-playwright-cli/output/playwright-cli/references/test-generation.md)）。

**ref（`e1` / `e5` など）は絶対に残さない。** これは snapshot を撮った時点のセッション限りの
識別子で、再実行では別の要素を指すか、存在しない。**生成コード側の role ベースのロケータ
（`page.getByRole('button', { name: 'Submit' })`）だけを残す**のが唯一の正解。
ここが最も事故る箇所なので、スクリプトを書き終えたら `e\d` の混入を目で確認する。

### 実行モデル — `run-code --filename=` を既定にする

```bash
playwright-cli -s=<site> run-code --filename=<スクリプトのパス>
```

- **`-s=<site>` は必須。** 省略すると `default` セッションを探して失敗し、開いている窓には落ちない
- 実行先は `open --profile=...` で開いた**既存のタブ**。ログイン状態・Cookie・localStorage を
  そのまま引き継ぐので、認証を再現する必要がない
- 独立した `@playwright/test` ファイルにするのは、**CI に載せる場合だけ**。この環境では
  `playwright` モジュールが無いため追加インストールが要り、さらに同じ `--profile` を
  別プロセスで掴むと「1 プロファイル = 1 インスタンス」に当たる（[profiles.md](profiles.md)）

### `run-code` のサンドボックスは狭い

書き始める前に知っておくべき制約（実測）:

- **返り値が唯一の出力。`console.log` は握り潰される。**長い待機の途中経過は見えないので、
  報告したい情報はすべて返り値に入れる
- `URL` / `process` / `require` / `fetch` / `setTimeout` が**無い**。
  URL の判定は文字列の正規表現か `page.evaluate(() => location.host)`、スリープは `page.waitForTimeout(ms)`
- `import` / `export` / `require` は構文として非対応。1 ファイル 1 つの関数に閉じる
- **OS 通知はスクリプトから撃てない**（`process` が無い）。通知は必ずエージェントのシェルから別プロセスで出す

## 3. 認証壁の契約

スクリプトの冒頭に「ログイン済みか」の判定を置き、壁だったら
**通知 → タイムアウト付き待機 → 再開 or 中断**の順で進む。

### 3-1. 検知 — URL だけを見る

```js
async page => {
  const url = page.url();
  const onAuthWall = /\/login|\/signin|\/sso\/|accounts\.google\.com|login\.microsoftonline\.com/i.test(url);
  const loc = await page.evaluate(() => ({ host: location.host, path: location.pathname }));
  return { onAuthWall, host: loc.host, path: loc.path };
}
```

認証ドメインのパターンはサイトごとに違うので、**このコード片は同梱しない。対象に合わせて毎回書く。**
返り値を `host` / `path` / boolean に限るのが条件（→ 4 節）。

### 3-2. 通知 — 気づかせてから待つ

待機に入る**直前に 1 回だけ**、次の 2 つを撃つ。ポーリングのたびに繰り返さない。

```bash
powershell.exe -NoProfile -File .claude/skills/sharing-browser-with-user/scripts/notify-user.ps1 \
  -Title "ログインをお願いします" -Body "<site> の窓で認証を完了してください"
```

- **`pwsh`（7 系）では動かない。`powershell.exe`（Windows PowerShell 5.1）を明示する**こと。
  WinRT の型が .NET Core には無い
- このスクリプトは**失敗しても exit 0** で返る（トーストが出せなければビープ、それも駄目なら黙る）。
  通知の失敗で自動化本体を止めない
- 集中モード中はトーストが通知センターに入るだけでポップアップしない。だから
  スクリプト側の `page.bringToFront()` と**併用する**。ただし `bringToFront()` は
  **ユーザーのフォーカスを奪う**ので、こちらも待機開始時の 1 回だけ

**そして会話でも依頼する。** 文面は [handoff-protocol.md](handoff-protocol.md)（Phase 2 と同じもの）を使う。
OS 通知は「気づきやすさ」の上乗せであって、本命は会話側の依頼。

`PushNotification` ツールは**在席中のユーザーには送信をスキップする**仕様なので、この用途には使えない。

### 3-3. 待機 — スクリプト内で待つ。既定 10 分

```js
async page => {
  const t0 = Date.now();
  await page.bringToFront();
  try {
    await page.waitForURL(u => !/\/login|\/signin/i.test(u.toString()), { timeout: 600000 });
    return { loggedIn: true, waitedMs: Date.now() - t0 };
  } catch (e) {
    const closed = /has been closed/.test(String(e.message));
    return { loggedIn: false, timedOut: !closed, windowClosed: closed, waitedMs: Date.now() - t0 };
  }
}
```

- **CLI 側のコマンドタイムアウトは無い**（10 分の待機がそのまま通ることを実測済み）。
  待ち時間は Playwright の `timeout` だけが支配する。MFA / SSO を含む手動ログインの既定は **10 分**
- `waitForURL` は**述語関数**を取れる。「認証ドメインから離れたら成功」という否定形で書けば、
  ログイン後の URL を事前に知らなくてよい
- ユーザーの「終わった」宣言を待たずに**スクリプトが自力で再開してよい**。これは
  「エージェントが認証画面を読む」ことにはならない（返り値は boolean と経過ミリ秒だけ）

### 3-4. 返り値で分岐する

| 返り値 | エージェントの動き |
|---|---|
| `{ loggedIn: true }` | 本来の作業スクリプトを続行する |
| `{ loggedIn: false, timedOut: true }` | **窓を閉じずに中断。**どこまで進んだかを会話で報告して終わる。通知の二重撃ちはしない |
| `{ loggedIn: false, windowClosed: true }` | ユーザーが窓を閉じた。セッションごと消えているので、Phase 1 から開き直す |

タイムアウト時に `close` しないのは、ユーザーが認証の途中かもしれないため
（[handoff-protocol.md](handoff-protocol.md)「ユーザーが不在・応答がない場合」と同じ扱い）。

### 3-5. 再開できる分割にする

タイムアウトから戻ったとき**最初からやり直さないで済む**ように、スクリプトを分ける:

- **「認証壁の検知 + 待機」を、本来の作業から独立した 1 ファイルにする。**作業スクリプトに埋め込むと、
  再開のたびに冒頭の副作用（フォームの再入力、重複投稿）が走る
- 作業側は**手順の区切りごとにファイルを分け、それぞれが現在地から始められる形**にする。
  「一覧を開く → 1 件処理する」なら、2 つ目は「すでに一覧にいる」前提で書き、途中から呼べるようにする
- 各ファイルは**どこまで終わったかを返り値に入れる**（`{ done: 12, total: 20 }` など）。
  `console.log` が消える以上、進捗を持ち出す手段は返り値しかない

## 4. やってはいけないこと

[SKILL.md](../SKILL.md) の「絶対に守ること」の延長。スクリプト化は、これらを破る誘因が
そろって強くなるので明示的に塞ぐ。

1. **返り値にページ本文を入れない。** `run-code` が認証中に許されるのは
   「返り値を URL / boolean に限る」という条件付きであって、コマンド自体が解禁されたわけではない。
   `page.evaluate(() => document.body.innerText)` を返せば当然アウト
2. **スクリプトが待っている間に `snapshot` / `find` を撃たない。** 待機中のセッションはロックされず、
   実際に通ってしまう（実測）。**これは仕組みでは守られない。** 待つのは会話の側
3. **資格情報をスクリプト・`.env`・環境変数・コマンド引数のいずれにも置かない。**
   ID / パスワード / MFA コードは会話にも持ち込まない。ユーザーが貼ってきても使わない
   （[handoff-protocol.md](handoff-protocol.md)）
4. **`storageState` をリポジトリ配下に書き出さない。** 保存先は**常に明示パスでリポジトリ外**。
   引数を省略するとカレント（＝リポジトリ内）に書かれる
5. **認証フェーズをスクリーンショット・トレース・動画にまたがせない。**
   `--trace` や録画を有効にしたまま認証を挟むと、入力中の資格情報が成果物に残る。
   記録を取るなら**ログイン完了を検知した後で開始する**
6. **検知回避に踏み込まない。** 自動化フラグの偽装は、弾かれたときも選択肢に入らない。
   [troubleshooting.md](troubleshooting.md) の方式 B（`attach`）へ

## 5. 委譲（`pwdo`）が認証壁に当たったとき

ブラウザ操作の一区間を安いモデルへ渡す [`pwdo`](../../../../ai/tools/pwdo/README.md) を使った場合も、
このファイルの契約は緩まない。**委譲先はユーザーと会話できないので、常に「中断」側に倒す。**
3 節の「通知 → 待機 → 再開」は**呼び出し側（あなた）へ戻ってから**適用する。

pwdo は認証に関わる操作を**ツール層で実行不能にしてあり**、認証画面に到達した時点で
`status: blocked` / `reason: auth-required` で終わる。返ってくるのは
「認証壁に当たった」という事実と**最終 URL のホスト名だけ**で、ページ本文・タイトル・
フォーム項目名は 1 バイトも返らない（ガードの中身は pwdo の README が正。ここには転記しない）。

受け取ったあとの手順:

1. **そのセッションに `snapshot` / `find` を撃たない。** 「**読まない**ではなく**打たない**」
   （[SKILL.md](../SKILL.md) の「絶対に守ること」1）は、委譲から戻った直後にも同じく効く。
   委譲先が止まったのに呼び出し側が撃つと、結局ログイン画面が会話に入る。
   `auth-required` のときの `next` に `pwq snapshot` が入っていないのはそのため。
2. **[SKILL.md](../SKILL.md) の Phase 2 へ戻る。** 文面は [handoff-protocol.md](handoff-protocol.md)。
   窓は開いたまま（生きたセッションが返る）なので、Phase 1 からやり直す必要はない。
3. **ユーザーの「終わった」宣言を受けてから、同じ区間をもう一度委譲する。**
   pwdo は承認を受けて続きを走らせる経路を持たない単発プロセスなので、再開ではなく再実行になる。
   途中まで進んでいた分は回収スクリプト（報告の `script.path`）に残っている。
4. **`reason: login-wall` はモデルの申告なので、そのまま信じない。**
   実測で認証と無関係な場面にも付いた例がある。ツール層が検知した `auth-required` とは信頼度が違い、
   `login-wall` のときは呼び出し側が自分で現在地を確かめてから判断する。

**委譲に使うセッションが認証済みプロファイルであること自体は問題ない。** 禁じられているのは
認証操作そのものであって、ログイン後の作業を委譲することではない。

## 関連

| 状況 | 見る場所 |
|---|---|
| ユーザーへの依頼文面・待ち方 | [handoff-protocol.md](handoff-protocol.md) |
| **毎回**ログインを求められる（＝プロファイルの故障） | [troubleshooting.md](troubleshooting.md)。本ファイルが扱うのは正常なセッション期限のほう |
| スクリプトの素材となる生成コードの仕様 | [using-playwright-cli](../../using-playwright-cli/SKILL.md) の `output/` |
| 一括で書き下ろさず、少しずつ実行しながら育てる | [script-cli-roundtrip.md](../../using-playwright-cli/references/script-cli-roundtrip.md) |
| 一区間を安いモデルへ委譲する（認証は委譲しない） | [pwdo の README](../../../../ai/tools/pwdo/README.md)。認証壁に当たったときの受け取り方は本ファイル 5 節 |
