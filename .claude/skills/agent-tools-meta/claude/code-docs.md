# Claude Code 最新ドキュメント参照（code.claude.com）

Claude Code の機能・設定（hooks、skills、settings.json、スラッシュコマンド、サブエージェント、MCP、メモリ等）に関する質問に、学習データの記憶ではなく最新の公式ドキュメント（code.claude.com）を根拠に回答する。

- 棲み分け: `claude` コマンドのオプション・サブコマンドは [cli-docs.md](cli-docs.md)。
- パスはスキルのフォルダ（`SKILL.md` のあるフォルダ。以下 `<skill-dir>`）基準。

## 手順

1. **公式ドキュメントを取得する**

   ```bash
   uv run python <skill-dir>/scripts/download_claude_code_reference.py
   ```

   - `<skill-dir>/output/claude/llms.txt`（ページ一覧）と `llms-full.txt`（全文、約 6MB）を書き出す
   - 24 時間以内に取得済みならスキップする。`--force` で強制再取得

2. **関連箇所を探す**

   - まず `<skill-dir>/output/claude/llms.txt` を Grep/Read して、質問に関連しそうなページの URL・slug を特定する
   - 詳細な本文が必要なら `<skill-dir>/output/claude/llms-full.txt` を Grep して該当セクションのおおよその位置を掴む（全文を Read しない）

3. **該当セクションを抽出する**（本文が長い場合に推奨）

   ```bash
   uv run python <skill-dir>/scripts/extract_doc_section.py <slug または URL> [<slug または URL>...]
   ```

   - 例: `uv run python <skill-dir>/scripts/extract_doc_section.py hooks skills`
   - `<skill-dir>/output/claude/temp/<slug>.txt` に該当セクションだけが書き出されるので、それを Read して内容を確認する（`temp/` は都度上書きされる作業用置き場）

4. **回答する**

   - 抽出した本文に基づいて回答し、参照した URL（`Source:` 行）を明示する
   - `llms-full.txt` に該当ページが見つからない場合は、その旨を伝えた上で WebFetch 等で `code.claude.com` を直接参照してもよい
