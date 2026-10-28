# Claude CLI ヘルプ参照（`claude --help`）

Claude Code CLI（`claude` コマンド）のオプション・フラグ・サブコマンドに関する質問に、学習データの記憶ではなく `claude --help` の実際の出力を根拠に回答する。

- 前提: `claude` CLI がインストールされ PATH から呼べること。
- 棲み分け: Claude Code の機能・設定の概念（公式サイトのドキュメント由来）は [code-docs.md](code-docs.md)。ここは `claude` コマンドの CLI インターフェース（`--help` 出力由来）に特化する。
- パスはスキルのフォルダ（`SKILL.md` のあるフォルダ。以下 `<skill-dir>`）基準。

## 手順

1. **スナップショットを生成する**

   ```bash
   uv run python <skill-dir>/scripts/generate_claude_help_yaml.py
   ```

   - `claude --version` と `claude --help` を実行し、構造化した結果を `<skill-dir>/output/claude/help_result.yaml` に書き出す（バージョン、usage、description、commands、arguments、options）
   - 24 時間以内に取得済みなら再生成をスキップする。`--force` で強制再生成
   - `claude` コマンドが無い/失敗する環境ではスクリプトが失敗し、スナップショットも無い（コミットしていない）。その場合はその旨を伝え、[code-docs.md](code-docs.md) の公式ドキュメント（`cli-reference` ページ）で確認する

2. **`<skill-dir>/output/claude/help_result.yaml` を Read/Grep して回答する**

   - `usage` / `description` / `commands`（サブコマンド一覧）/ `arguments` / `options` を検索し、該当エントリの `description` を根拠として提示する
   - 回答には、どのオプション/サブコマンドを参照したかを明示する（例: `--dangerously-skip-permissions` オプションの説明に基づく、など）
   - `--dangerously-skip-permissions` のような危険操作・権限関連のオプションについて聞かれた場合は、`description` に書かれている警告文（"Bypass all permission checks. Recommended only for sandboxes with no internet access." 等）をそのまま伝える

3. **サブコマンド固有の詳細は `claude <サブコマンド> --help` の実行結果で確認する**

   `claude --help` のトップレベル出力には `commands` の説明しかない（`mcp` / `plugin` / `agents` / `doctor` / `install` / `auth` など多数のサブコマンドがある）。それぞれの詳しいオプションを聞かれたら、以下のいずれかで確認する。

   - `claude <サブコマンド> --help` を実行し、出力をそのまま読んで回答する
   - 構造化して残したい場合は `uv run python <skill-dir>/scripts/generate_claude_help_yaml.py --help-file <キャプチャしたファイル> --output <skill-dir>/output/claude/<サブコマンド>.yaml` でパースし直す（パーサーは `Commands:` / `Arguments:` / `Options:` セクション構造であれば、トップレベル以外にも使える）

## 補足

- Claude Code の `--help` は commander.js（Node.js）製で、Codex CLI の clap（Rust）製とはヘルプの書式が異なる（各エントリは「インデント2の名前行＋同行または深いインデントに揃えられた説明行」の形。長いフラグ名では説明が次行に折り返される。パーサーはこれらの説明行を空白1つで連結して1つの `description` にまとめている）
- `output/` は生成物でコミットしない（スキル直下の `.gitignore`）
