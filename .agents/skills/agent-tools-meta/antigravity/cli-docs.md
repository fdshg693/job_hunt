# agy CLI ヘルプ参照（`agy --help`）

Antigravity CLI（`agy` コマンド）のオプション・フラグ・サブコマンドに関する質問に、学習データの記憶ではなく
`agy --help` の実際の出力を根拠に回答する。`claude` CLI 版（[../claude/cli-docs.md](../claude/cli-docs.md)）と同じ発想だが、
`agy` 固有の挙動（下記「補足」）に合わせてサブコマンドのヘルプまでスナップショットに含めている。

- 前提: `agy` CLI がインストールされ PATH から呼べること。
- 棲み分け: Antigravity の機能・設定の概念（公式サイトのドキュメント由来）は [docs.md](docs.md)。
- パスはスキルのフォルダ（`SKILL.md` のあるフォルダ。以下 `<skill-dir>`）基準。

## 手順

1. **スナップショットを生成する**

   初回実行時や振る舞いが怪しいときは `--help` で使い方を確認してから実行すること。

   ```bash
   uv run python <skill-dir>/scripts/generate_agy_help_yaml.py --help
   uv run python <skill-dir>/scripts/generate_agy_help_yaml.py
   ```

   - `<skill-dir>/output/antigravity/help_result.yaml` に書き出す
   - 24時間以内に取得済みなら再生成をスキップする。`--force` で強制再生成。
   - `agy` が無い環境ではスクリプトが失敗し、スナップショットも無い（コミットしていない）。
     その場合はその旨を伝え、[docs.md](docs.md) の公式ドキュメント（`docs/cli/...` 配下）で確認する。

2. **`<skill-dir>/output/antigravity/help_result.yaml` を Read/Grep して回答する**

   以下のキーを検索し、該当エントリの `description` を根拠として提示する。

   - `usage` / `command` — トップレベルの使い方とコマンド名
   - `options` — トップレベルフラグ（`--print` / `-p`、`--model`、`--mode`、
     `--sandbox`、`--dangerously-skip-permissions` 等）。`default` フィールドに
     既定値が入る場合がある（例: `--print-timeout` の `5m0s`）
   - `subcommands` — サブコマンド一覧と1行説明（`agent`/`agents`/`changelog`/
     `help`/`install`/`models`/`plugin`/`plugins`/`update`）
   - `subcommand_help.<サブコマンド>` — 各サブコマンドの `usage` /
     `description` / `flags` / `commands`。`plugin` は `commands`（サブサブコマンド）
   - `plugins` と `agents` はそれぞれ `plugin` / `agent` のエイリアス
     （`alias_for` を持つ上で内容をインライン展開済み）

   - 回答には、どのフラグ/サブコマンドを参照したかを明示する（例:
     「`--dangerously-skip-permissions` オプションの説明に基づく」など）
   - `--dangerously-skip-permissions` のような権限関連のオプションについては、
     `description` の警告文をそのまま伝える

3. **スナップショットに無い・古い詳細は `agy help <サブコマンド>` で確認する**

   該当エントリが無い・怪しい場合は、直接確認する（**必ず `help` 付きで**。下記「補足」のハング注意）。

   ```bash
   agy help            # トップレベル（フラグ＋サブコマンド一覧）
   agy help <サブコマンド>   # 例: agy help install
   ```

   - 出力は **stderr** に書かれ **終了コード 1** で返る（Go の flag パッケージの
     仕様）。これはエラーではなくヘルプ表示の正常動作なので、stderr まで取り込むこと。
     生成スクリプトは stdout+stderr を結合して取り込んでいる。

## 補足

- 生成スクリプトは `agy --version` と `agy --help`、および各 `agy help <サブコマンド>` を実行し、
  構造化した結果（バージョン、usage、options、subcommands、subcommand_help）を書き出す
- `agy` は Go 製で、Claude Code の commander.js（Node.js）や Codex CLI の
  clap（Rust）とはヘルプの書式が異なる。トップレベルは `Usage of agy.exe:` 見出しの
  あとに2スペースインデントのフラグ行が並び、空行を挟んで `Available subcommands:` の
  あとにサブコマンド行が並ぶ。サブコマンドは `Usage:` 行 + 説明行 + `Flags:` または
  `Commands:` セクションからなる
- **ハング注意**: `agy agent` / `agy agents` / `agy models` のようにサブコマンドを
  **裸で**実行すると、対話/認証フローが始まりハングする。サブコマンドのヘルプは
  **必ず `agy help <サブコマンド>` 形式**で取得すること（こちらは常に終了する）。
  `agy plugin`（裸）と `agy plugins`（裸）はサブコマンド一覧＋エラーで終了するので安全
- `agy help help` は未対応（エラーになる）。トップレベルを使いたい場合は `agy help`
  （引数なし）を実行すること
- バイナリはサブプロセス経由で起動すると自己の拡張子を `agy.EXE` と大文字化して
  出力するクセがあるが、実ターミナルでは `agy.exe`（小文字）。生成スクリプトは
  usage 行を `agy.exe` に正規化してスナップショットに保存している
- `output/` は生成物でコミットしない（スキル直下の `.gitignore`）
