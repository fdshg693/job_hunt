# 定期実行エージェントルーチン（今日やることブリーフ）

PC にログオンしている間に Windows タスク スケジューラから AI エージェント（Claude Code の `claude -p`・Antigravity の `agy`）を無人で動かし、雑務・メール・予定を確かめて「今日ユーザーがやること」のブリーフを作る仕組み（`scripts/automation/`）。

- 何をどの順で実行するか・プロンプト・スケジュールは YAML で定義する。コードは触らない。
- 無人実行なので、外部への送信・媒体プロフィール更新・カレンダー登録・コミットなど外向き・取り消しにくい操作はしない。それらは「ユーザーがやること」としてブリーフに載る。
- CLI の使い方・サブコマンド・出力パスは `uv run python scripts/automation/run_routine.py --help` が正。YAML のキー・型・許容値の正は [`scripts/automation/config.py`](../../scripts/automation/config.py)（このページにキー表は書かない）。

## 1. ファイルの置き場所

| 何 | 場所 | 公開 |
| --- | --- | --- |
| ルーチン定義（自分用） | `vault/automation/routines.yaml`（`prompt_file` などの相対パスは `vault/` 基準） | しない |
| ルーチン定義の雛形 | [`templates/vault/automation/routines.yaml`](../../templates/vault/automation/routines.yaml)（全キーのコメント付き例） | する |
| ブリーフ | `data/automation/briefs/{YYYY-MM-DD}_{routine}.md`（＋同名 `.json`） | しない |
| 実行ログ | `data/automation/runs/{YYYY-MM-DD}/{routine}/`（各ステップの stdout・stderr・プロンプト、`run.json`） | しない |
| 実行状態・ロック | `data/automation/state.json`（ルーチンごとの最終実行日）、`data/automation/locks/` | しない |
| スケジューラ操作の結果 | `data/automation/scheduler/{register,unregister,status}.md`（毎回上書き） | しない |

`runs/` と `briefs/` は `data/` の保持期間（60 日）で消える（[`docs/vault/materials.md`](../vault/materials.md)）。ブリーフで判断したことは、必要なら vault の企業ログ等に記録しておく。

## 2. 初期設定

```powershell
# 1. 雛形をコピーして自分用に書き換える
Copy-Item templates/vault/automation/routines.yaml vault/automation/routines.yaml

# 2. YAML を検査する（スキーマ・ステップ間の参照・prompt_file の実在）
uv run python scripts/automation/run_routine.py validate --summary

# 3. CLI を呼ばずに、組み立てたコマンドとプロンプトを確かめる
uv run python scripts/automation/run_routine.py run morning-brief --dry-run
#    → data/automation/runs/{今日}/morning-brief_dry-run/dry-run.md を読む

# 4. 1 回本実行してブリーフを確かめる（claude / agy の費用がかかる）
uv run python scripts/automation/run_routine.py run morning-brief --force -s

# 5. タスク スケジューラへの登録内容を差分だけ確かめてから登録する
uv run python scripts/automation/run_routine.py register --dry-run -s
uv run python scripts/automation/run_routine.py register -s
uv run python scripts/automation/run_routine.py status -s
```

- 前提: `claude` と `agy` にログイン済みで PATH から呼べること、Gmail・カレンダーを使うステップがあるなら `scripts/google/auth.py` の認可が済んでいること（[`docs/google/README.md`](../google/README.md)）。
- タスクは管理者権限なしで登録できる（タスクフォルダ `\job-hunt\`、ログオン中のみ実行）。
- やめるときは `unregister`（ルーチン id を省略すると全部。空になった `\job-hunt\` フォルダも消す）。

## 3. YAML の書き方（考え方）

雛形のコメントが例を兼ねる。ここでは組み立て方の考え方だけを書く。

### 構造

- `defaults`: 既定の CLI（`claude` / `agy`）・タイムアウト・`preamble`（全 agent ステップの先頭に付く無人実行の約束）。
- `agents`: CLI ごとの既定モデルと**権限プロファイル**（`read_only`・`write_data` 等、名前は自由）。ステップは `permission:` でプロファイル名を選ぶ。
- `routines`: ルーチンごとに `schedule`・`steps`・`brief`。

### ステップは 2 種類

| `kind` | 使いどころ |
| --- | --- |
| `script` | 機械で取れる情報（`find_chores.py --json`、Gmail・カレンダーの取得等）。安く確実。`capture: file` なら stdout に出たパスのファイル内容が出力になる（スクリプト出力規約に合わせた形） |
| `agent` | 判断・要約・仕分け。プロンプトに前段の出力を埋め込む |

材料はなるべく `script` で取り、`agent` には判断だけをさせる。機械的な判定をそのまま結論にしない原則（[goal.md](../../.agents/rules/goal.md) の「機械化の誤用防止」）と、費用の両方のため。

### 段階の踏み方

- ステップは上から順に実行する（並列・DAG は無い）。
- `{{steps.<id>.output}}` / `{{steps.<id>.status}}` で**前段**のステップの出力・結果をプロンプトや引数に埋め込む。ほかに `{{today}}` `{{tomorrow}}` `{{now}}` `{{routine}}` `{{run_dir}}`。
- `when: {if_nonempty: <id>}` などで条件付きにできる（`if_nonempty` / `if_empty` / `if_succeeded` / `if_failed` のどれか 1 つ）。
- `on_failure: continue`（既定）なら失敗しても後続を続ける。取得系のステップは continue にしておくと、認証切れの日もブリーフ自体は出る。
- 長いプロンプトは `prompt_file`（`vault/` 相対）に出せる。

### ブリーフ

- `brief.step` に指定した agent ステップに、実行エンジンがタスク配列の JSON Schema を付けて構造化出力させ、Markdown に整形する。そのステップに `output_schema` は書かない。
- `brief.notify: true` ならトースト通知を出す（閉じるまで画面に残る。「開く」でブリーフの `.md` が開く）。

### スケジュール

- `daily_at`（`"08:30"` のように引用符で囲む）と `on_logon`（ログオン 2 分後）を併用してよい。`once_per_day: true` なら同じ日の 2 回目以降は何もしない。朝 PC をつけた時刻が日によって違っても、最初の機会に 1 回だけ走る。
- `weekdays` は実行エンジン側で守る（ログオン時トリガーは曜日で絞れないため、タスクは `run --scheduled` で起動し、対象外の曜日は何もしない）。
- 時刻を逃したら可能になり次第実行する。スリープ解除はしない。バッテリー駆動中も実行する。
- **YAML を変えたら `register` し直す**。タスクの説明に YAML から作った指紋（`[spec:…]`）が入っていて、`status` が差分（`update`）を出す。タスク スケジューラ側を手で直しても、次の `register` で YAML の内容に戻る。

### 権限の考え方

- 既定は「読み取り＋`data/` への書き込み」まで。`--dangerously-skip-permissions` は使わない。
- **claude**: プロファイルの `tools`（`--tools`）で使えるツールを絞り、`allow` / `deny`（`--allowedTools` / `--disallowedTools`）にコマンド単位の許可を書く（例: `Bash(uv run python scripts/gmail/search_messages.py *)`）。許可されていない操作は拒否され、ターンは続く。
- **agy**: 実行ごとに許可ルールを渡せない。`allow` / `deny` は `~/.gemini/antigravity-cli/settings.json` の `permissions` に**入っているべきルールの宣言**で、足りなければブリーフで知らせる（settings.json は書き換えない）。ワークスペース内のファイル書き込みは既定で許可されるので、`writes: none` のステップは実行前後の差分で無断の変更を検出して警告する。
- `writes: vault` のステップは、開始時に `vault/` に未コミット変更が無いときだけそのまま実行する。あれば読み取り専用に格下げし、理由をブリーフに書く。コミットはしない。

## 4. 出力の読み方

- `run` の stdout はブリーフのパス。実行済み（`once_per_day`）・実行中（ロック）で何もしなかったときも、直近のブリーフのパスを出して終了コード 0。`last [routine]` でも直近のブリーフのパスが分かる。
- ブリーフのフロントマター: `status`（`ok` / `partial` / `failed`）・`tasks`（件数）・`user_tasks_from_runner`（実行エンジンが足した「ユーザーがやること」の件数）・`warnings`・`cost_usd`。
- 本文: 要約 → 「やること」（優先度順。理由・期限・関連ファイル・出典）→ 「確かめられなかったこと」→ 「実行結果」（ステップごとの結果と、実行エンジンが検出したログイン切れ・権限拒否・格下げ等）。
- 詳しく見たいときは `data/automation/runs/{date}/{routine}/` の `run.json` と各ステップの `.stdout.txt` / `.stderr.txt` / `.prompt.md`。

## 5. トラブルシュート

| 症状 | 原因と対処 |
| --- | --- |
| ブリーフに「○○にログインする」 | script ステップの終了コード 2（媒体・Google の認証切れ）や、`claude` / `agy` の未ログイン。ログインしてから `run <routine> --force` で取り直す。Google は外部ターミナルで `uv run python scripts/google/auth.py` |
| ブリーフに「許可されていない操作が拒否された」 | 権限プロファイルの `allow` が足りない。claude は YAML の `allow` に、agy は `~/.gemini/antigravity-cli/settings.json` の `permissions.allow` に足す。足す前に、その操作を無人でさせてよいかを考える |
| 「agy の settings.json に許可ルールを追加する」 | プロファイルで宣言した `allow` / `deny` が settings.json に無い。Windows の PowerShell では前方一致に `command(regex:...)` を使う |
| 「読み取り専用に格下げした」 | `writes: vault` のステップの開始時に vault に未コミット変更があった。コミットしてから再実行するか、そのままでよい |
| 応答が空・タイムアウト | 両 CLI とも権限拒否やタイムアウトでも終了コード 0 になる。実行エンジンは出力の中身で判定して「失敗」にする。`.stderr.txt` を見る。長い処理はステップの `timeout_minutes` を延ばす |
| タスクが動かない | `status -s` で登録状態・前回の結果・次回実行時刻を見る。`LastTaskResult` が 267011 なら未実行、0 なら成功。ログオンしていない間は実行されない（仕様） |
| `claude` / `agy` / `uv` が見つからない | タスクはユーザー環境変数の PATH で動く。mise の shims・agy・`~/.local/bin` がユーザー PATH にあるか確かめ、`register` し直す（uv の絶対パスは登録時に解決される） |
| 実行時にコンソール窓が出る | 起動は `conhost.exe --headless` で窓を出さない想定。`claude` / `agy` の子プロセスで窓が出る場合は未対策（見つけたら報告。子プロセスを窓なしで起動する対応を入れる） |
| 費用が想定より高い | ブリーフのフロントマター `cost_usd` を見る。材料が長いと sonnet で 1 回 $0.2〜0.3 程度。軽いステップは `model: haiku` に上書きし、`max_budget_usd` で上限を決める |

## 6. 両 CLI の無人実行の挙動（実装の前提）

実機で確かめた挙動（claude 2.1 系・agy 1.2 系、2026-10）。CLI を上げて挙動が変わったら、ここと `scripts/automation/agents.py` を直す。

| 項目 | claude（`claude -p`） | agy |
| --- | --- | --- |
| プロンプトの渡し方 | stdin（`-p` に引数なし） | stdin（`-p` を付けない） |
| 成否の判定 | 権限拒否でも exit 0。`--output-format json` の `is_error`・`permission_denials`・`structured_output` の有無を見る | 権限拒否・`--print-timeout` 切れでも exit 0・`status: SUCCESS`。`response` が空か、`denied_actions`（ドキュメントに無い項目）、stderr の `auto-denied` / `print timeout` を見る |
| 許可が要る操作 | 拒否されてターンは続く。読み取り専用のコマンドは許可ルールなしで通る | 待たずに自動拒否され、多くは回答せずに終わる |
| 許可ルールの渡し方 | 実行ごとに `--tools` / `--allowedTools` / `--disallowedTools` | 渡せない。`~/.gemini/antigravity-cli/settings.json` の `permissions` だけ。ワークスペース内の読み書きは既定で許可 |
| 未ログイン | 結果の本文にエラーが出る | `authentication required` で終了（ハングしない） |
| 使わないもの | `--bare`（OAuth を使わず API キー必須になる）、`--dangerously-skip-permissions` | `--dangerously-skip-permissions`。`--sandbox` / `--mode auto` は Windows では agy 1.4.4 以降で、ネットワークを使うスクリプトが通らない見込み |
