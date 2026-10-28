# スクリプト ⇄ CLI の往復でスクリプトを育てる

長いブラウザ手順を一度に書き下ろさず、**「少し書く → 実行 → 続きを手で探索 → 記録から回収して追記」**を
繰り返して育てるための手順。認証の有無とは無関係（認証壁の扱いは
[scripted-automation.md](../../sharing-browser-with-user/references/scripted-automation.md) が正）。

以下は `@playwright/cli` 0.1.19 / Windows 11 / Chrome / TodoMVC デモでの実測に基づく。
コマンド・オプションの仕様は `output/playwright-cli/` が正で、ここには転記しない。

## 1. 往復する / しない

**固定費は 1 チャンクあたり 5 コマンド**（snapshot / recording-start / recording-stop / 回収 / 検証実行）。
探索が 2〜3 手しかないチャンクでは、この固定費が支配する。

| 状況 | どうするか |
|---|---|
| ロケータが事前に分かっていて、手順が 5 手未満 | **往復しない。** `run-code` に直接書く |
| 初見のサイト / 手順が長い（10 手以上） | **往復する。** 5 手前後でチャンクに切る |
| 人がやった方が早い区間がある（認証・CAPTCHA・目視判断） | **往復する。** その区間を手操作区間にして記録で回収（→ 5 節） |
| 読み取り・集計・アサーションが多い | **往復する。ただし回収だけでは足りない。** チャンクごとに「効いたことの確認」を足す手間を見込む（→ 4 節） |

往復が一括スクリプト化より得になる理由はコマンド数ではない（**往復の方が多い**）。
**手戻りの原因が、チャンク 1 つ分の範囲に閉じる**という 1 点に尽きる。

## 2. 1 チャンクの手順

```bash
playwright-cli -s=<site> run-code --filename=./chunk-N.js   # 1. 少し進める（成功時は ### Page に現在地が出る）
playwright-cli -s=<site> snapshot                            # 2. ★必須。理由は下記
playwright-cli -s=<site> recording-start                     # 3. ★探索の一手目より前に撃つ
playwright-cli --raw -s=<site> <action> <ref>                #    探索 N 手（--raw を付けてよい）
playwright-cli --json -s=<site> recording-stop > rec.json    # 4. チャンクに落とす直前に必ず撃つ
```

回収は機械的に済ませる。手で写さない:

````bash
jq -r '.result' rec.json | sed -n '/```js/,/```/p' | sed '1d;$d' > recorded.txt
{ echo "async page => {"; sed 's/^/  /' recorded.txt; echo "  return { /* 観測値 */ };"; echo "}"; } > chunk-next.js
playwright-cli -s=<site> run-code --filename=./chunk-next.js   # 5. 検証実行
````

**回収したコードは無変換で `run-code` に載る。** 記録には `import` も `test()` も `expect` も
ref も現れないので、`async page => { ... }` で包んで返り値を足すだけでよい。

### なぜ `run-code` の直後に full `snapshot` が要るのか

**ref が誤爆するからではない**（ref は位置ではなく DOM 要素の同一性に紐づき、失効時は必ず
`Error: Ref <r> not found ...` で落ちる）。理由は **スクリプトが新しく作った要素の ref が、
snapshot を撮るまで一切存在しないから**。理由を取り違えると「ref が生きているなら省いてよい」と読まれて壊れる。

なお `run-code` はナビゲーションを含んでも `.playwright-cli/page-*.yml` を書かない。
スクリプト実行後に状態をファイルで残したいなら `snapshot --filename=...` を明示的に撃つ。

### なぜ回収は記録（`recording-*`）一本なのか

記録は**操作の出所を問わない** — CLI コマンド・`run-code` 内の locator 操作・座標クリック・
**ユーザーが headed の窓で手でやった操作**、すべてを拾い、意味的ロケータへ正規化して出す。
記録されるのは「状態を変えた操作」だけで、`snapshot` / `find` / `eval` は入らない。

- `### Ran Playwright code` 節（生成コード）は **`--json` に入らない**ので機械抽出できない。
  recording を張り忘れた区間の救済としてのみ使う（stdout から目で写す）
- **`eval` / `generate-locator` が出したロケータをスクリプトへ写さない。** 意味的アンカーを持たない
  コンテナ要素の ref からは、ページのデータを埋め込んだ `getByText('Mark all as completetask-')` のような
  壊れやすいロケータが出る。記録経由ならこの問題は起きない（操作した要素しか記録されないため）

### `--raw` / `--json` の使い分け

| コマンド | `--raw` | `--json` |
|---|---|---|
| アクション（`click` / `fill` …） | **出力が空になる**（成功と失敗が区別できない） | **`{}` だけ**（同上） |
| `eval` | 値だけ出る。付けてよい | — |
| `recording-stop` | 記録されたコードは残る。付けてよい | **`.result` に回収物が入る。これを使う** |

探索アクションに `--raw` を付けても**記録は消えない**（`--raw` は stdout の話で、回収可能性の話ではない）。
出力が短くなる分むしろ安い。ただし**回収作業中に失敗を握り潰すと後続が空振りする**ので、
`>/dev/null` で捨てない。

## 3. チャンクの分け方

- **初期化は必ず別ファイル**にする（`chunk0-init.js`）。`goto` + `localStorage.clear()` + `reload()` を
  作業チャンクに入れると、続きだけ実行するたびに状態が消える
- 各チャンクは**現在地から始められる形**にし、返り値に観測値を入れる（`console.log` は握り潰される）
- 再実行は 2 モードとも通ること: **続きだけ実行**（チャンク単独を 2 回）と**最初から通し実行**（init → 全チャンク）

```js
// chunk0-init.js — 通し実行専用。現在地に関わらず既知の状態へ戻す
async page => {
  await page.goto('https://example.test/');
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  return { chunk: 0, ok: true, url: page.url() };
}
```

## 4. 回収した行に「足すもの」3 つ

**記録は操作しか持っていない。** リハーサルで起きた手戻りは 100% が
「記録に含まれない部分」で起きた（回収した行が原因の手戻りは 0）。重心はここに置く。

### 4-1. 効いたことの確認（毎回）

記録には**待機が入らない**。クリックを連続で撃って直後に `count()` / `innerText()` を読むと、
**前のレンダリングの値を拾う**（これらに auto-wait は無い）。

**`page.waitForURL()` では直らない**ことがある（ハッシュは再レンダリングより先に変わる）。
待つべきは**操作が効いた結果の DOM**:

```js
const tour = async name => {
  await page.getByRole('link', { name }).click();
  await page.locator('.filters .selected', { hasText: name }).waitFor();   // ← 手で足す一手
  return page.getByTestId('todo-title').count();
};
```

間に別の待ちが挟まると**たまたま直る**ので、動いたからといって確認を省いたと気づけない。
一括スクリプト化でこれをやると、再現性の無い失敗になる。

`expect` はサンドボックスに無く、CLI にアサーション系コマンドも無い。
**アサーションは「書き換える」ものではなく「足す」もの**:

| やりたいこと | `run-code` での書き方 |
|---|---|
| `expect(locator).toBeVisible()` | `await locator.waitFor({ state: 'visible', timeout: 3000 })` |
| `expect(locator).toHaveCount(n)` | `const n = await locator.count();` → 返り値に入れる／`if` で `throw` |
| `expect(page).toHaveURL(re)` | `await page.waitForURL(re, { timeout: 3000 })` |
| 明示的な失敗 | `throw new Error('expected 2 todos, got ' + n)` |

集計・読み取りのロケータは**自分で書く部分なので事故りやすい**（`getByRole('listitem').count()` が
フッタのリンクまで数えて 6 を返した実例）。書いたら 1 回実行して値を目で確かめる。

### 4-2. 入口ガード（`return` で書く。`throw` ではない）

チャンクの冒頭に「想定の現在地・前提状態にいるか」を置く。**`throw` にすると
「前提不一致」と「本当の失敗」の区別が消える**:

| 状況 | 出力 | exit |
|---|---|---|
| 前提不一致（ガードに引っかかった） | `{ ok: false, reason: 'entry-guard:url', url }` | **0** |
| 本当の失敗（アサーション・タイムアウト） | `### Error` のみ（**`### Page` は出ない**） | **1** |

```js
if (!page.url().startsWith('https://example.test/'))
  return { chunk: 2, ok: false, reason: 'entry-guard:url', url: page.url() };
```

→ **exit code だけで一次切り分けができる**状態を保つ。

### 4-3. 冪等ガード（操作の型ごとに 3 パターン）

| 操作の型 | 例 | 冪等化 |
|---|---|---|
| 追加系 | 項目の投入 | **既にあるならスキップ。** `if (await <記録のロケータ>.count() === 0)` で記録の行を包む |
| トグル系 | `check()` / `uncheck()` | **何もしなくてよい**（既にその状態なら no-op） |
| 破壊系 | 「完了を消す」等 | **「やることが残っているか」で先に `return`**（下記） |

破壊系をガード無しで置くと、**30 秒待ってから本当の失敗と同じ顔（`### Error` + exit 1）で落ちる**。
4-2 で作った切り分けが壊れるうえ、通し実行のたびに 30 秒の固定費が積む。

```js
const before = await page.locator('.todo-list li.completed').count();
if (before === 0)
  return { chunk: 4, ok: true, skipped: true, reason: 'nothing-completed', cleared: 0 };
```

**`ok: false` ではなく `ok: true, skipped: true`** にする。「やることが無い」は失敗ではない。

3 パターンとも**記録から回収したロケータをそのまま使い回せる**。ガード用に別途書き起こさない。

## 5. 手操作区間を挟む

**エージェントが 1 つもコマンドを撃たない区間**をつくり、ユーザーに窓で操作してもらっても、
その操作は記録に残り、意味的ロケータでそのまま回収できる。認証に限らず「人がやった方が早い区間」全般に使える。

- `recording-start` を撃ってから依頼し、終わったら `recording-stop`。**「エージェントが操作しない」を守ったまま成果だけ回収できる**
- **人の記録にはノイズが混じる。** 入力欄へフォーカスするための `.click()` など、
  エージェントの `fill` では出ない行が入る。**回収前に不要な `click` を落とす**
- 認証壁を挟む場合の依頼・待機・禁止事項は
  [scripted-automation.md](../../sharing-browser-with-user/references/scripted-automation.md) の 3 節と 4 節が正。
  **往復にしても認証壁の契約は一切緩まない**

## 6. チャンクが落ちたとき

失敗時の出力は `### Error` だけで、**`### Page` 節が出ない**（現在地が分からない）。
ブラウザは `status: open` のままで、**前半の副作用は残る**。次に撃つのはこれ:

```bash
playwright-cli --raw -s=<site> eval "() => location.href"
```

ページ本文を会話に入れずに現在地だけ取れる唯一の安い手段。エラー文にページ本文は載らない
（call log にセレクタ文字列が出るだけ）ので、この出力をそのまま読んでよい。

記録は**成功した操作だけ**を持つので、「どこまで進んだか」は `recording-stop` からも取れる。

## 7. やってはいけないこと

1. **`run-code` の後に snapshot を撮らずに ref を使い回さない**（2 節）。SPA のハッシュ遷移では ref が生き残るが、
   document を作り直す遷移では全部失効し ref の名前空間まで変わる。**どちらが起きたかはエージェント側から判別できない**
2. **スコープ付き `snapshot <ref>` を往復の途中で使わない。** ref テーブルが**その部分木だけに置き換わり**、
   外側の ref が全部 `not found` になる。使うなら直後に full `snapshot` を撮り直す。
   エラーメッセージ（`Try capturing new snapshot.`）から原因が分からない事故りやすい挙動
3. **1 チャンク = 1 記録区間を崩さない。** 記録は排他で、**止めずに覗く手段が無い**
   （`recording-start` の二重撃ちは `Error: Recording is already in progress.`）。
   止め忘れは次の区間との混線として現れる
4. **回収アクションを `--raw` / `--json` で撃って失敗を握り潰さない**（2 節の表）
5. **`eval` / `generate-locator` のロケータをスクリプトに写さない**（2 節）
6. **ref をスクリプトに残さない。** 記録経由なら混入しないが、書き終えたら
   `grep -nE "\b(f[0-9]+)?e[0-9]+\b" chunk*.js` で確認する
7. **スクリプト内で catch したタイムアウトは exit 0。** 認証壁待ちのタイムアウトで exit 0 になる実測を
   一般則として引用しない。**catch しない例外は exit 1**

## 8. まだ確かめていないこと

手順を適用する前に、対象がここに当たらないか見る（当たるなら 1 回実測してこの節に結果を足す）:

- **複数タブ**をまたぐ往復（実測はすべて 1 タブ）
- **`--persistent` / `--profile` 付き**の往復（実測は in-memory プロファイル）
- **非 SPA**（document を作り直す）サイトでの往復。ref 失効の切り分けはハッシュ遷移でしか見ていない
- **10 手を超える長いチャンク**。実測の最大は 3 手（1 節の「5 手以上」は固定費からの逆算であって実測ではない）
- `select` / `upload` / `drag` / `dialog-*` の記録形。実測したのは `fill` / `press` / `check` / `click` / `goto` のみ
- 手操作区間が**数分に及んだ**場合に記録が保つか（実測は十数秒）

## 関連

| 状況 | 見る場所 |
|---|---|
| コマンド・オプションの仕様 | `output/playwright-cli/playwright-cli-skill.md`（[SKILL.md](../SKILL.md) の索引から） |
| `run-code` のサンドボックス制約・返り値が唯一の出力 | [scripted-automation.md](../../sharing-browser-with-user/references/scripted-automation.md) 2 節 |
| 認証壁の検知・通知・待機・禁止事項 | [scripted-automation.md](../../sharing-browser-with-user/references/scripted-automation.md) 3〜4 節 |
