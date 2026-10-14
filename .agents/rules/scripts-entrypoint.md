---
trigger: glob
globs: scripts/**/*.py, scripts/**/*.mjs, scripts/**/*.sh, docs/**/*.md
---

# スクリプト開発・エントリポイント出力運用規約

`scripts/` フォルダ配下に配置される、AIエージェントまたはユーザーが直接CLIから実行するエントリポイントスクリプト（`fetch_job.py`, `search_online.py`, `navigate_likes.py`, `navigate_messages.py`, `search_jobs.py` 等）は、以下の出力規約を厳格に遵守すること。

## 1. 標準出力（stdout）はファイルパス専用とする

- **「名前の結果（求人名・企業名・スカウト送信者名・本文サマリ等のテキスト一覧）」をデフォルトで標準出力に出力してはならない**。
- スクリプトが作成・更新した `data/` 配下のファイルパス（または検索で該当した既存ファイルパス）のみを、標準出力（stdout）に **1行につき1パス** で出力する。
- パス形式はワークスペースルートからの相対パス（例: `data/findy/jobs/FyTVLvHVuEiQm.md`）とする。
- これにより、呼び出し側のAIエージェントやパイプライン処理は不要なトークン消費や文字列パースを伴わず、直接対象ファイルを `view_file` や後続ツールへ渡すことができる。

```bash
# 好ましい出力例（stdout）:
data/findy/jobs/b86n25tSyJTvH.md

# 複数件作成された場合の例（stdout）:
data/findy/likes/2026-09-18-02.md
data/findy/likes/2026-09-18-02.json
```

## 2. 人間向けサマリ表示は `--summary` オプション限定とする

- 人間がターミナルで実行して求人一覧やメッセージサマリを確認したい場合は、必ず `--summary`（または `--verbose`）オプションを明示指定した時のみ出力する。
- デフォルト実行時はサマリを抑制し、ファイルパスのみを出力する。

## 3. ログ・進捗・認証メッセージ・エラーはすべて `stderr` に出力する

- 取得中ステータス（`[取得中]`、`[スキップ]` 等）、ブラウザ認証ハンドオフ案内、警告、エラー、完了件数表示などはすべて `sys.stderr`（標準エラー出力）へ出力する。
- 標準出力（stdout）をファイルパス以外の文字列で汚さないこと。

## 4. データの永続化と結果ファイルの生成

- 外部サービスから取得したデータやオンライン検索結果は、必ず `data/` 配下にフロントマター付きMarkdownまたはJSONとして永続化してから、その生成ファイルパスを返す。
- 検索スクリプト等で単体求人ではなく一覧を取得する場合も、検索結果ファイル（`data/{source}/searches/YYYY-MM-DD-HHmmss_{keyword}.md` 等）を保存してそのパスを返す。

## 5. 終了コード

- 正常完了時は `0`、エラー時は `1`、認証ハンドオフ中断やタイムアウト時は `2` など、明確な終了コードを返すこと。

## 6. 共通CLI基盤の利用と標準フラグ仕様

新規スクリプト作成時は、車輪の再発明やフラグ命名のばらつきを排除し、`scripts.common.cli` の `create_base_parser` / `create_search_parser` および `EntrypointContext` / `entrypoint_guard` を利用すること。

全サイト横断で以下の標準フラグ体系を遵守する:
- `--limit` / `-n`: 取得・表示件数上限
- `--summary` / `-s`: 人間向けターミナルサマリ表示（デフォルトは非表示でstdoutはパスのみ）
- `--json`: JSON構造化出力
- `--min-salary` / `--max-salary`: 年収フィルタ（数値または `800` 等の万円単位、`normalizers.parse_salary_arg` を使用）
- `--remote`: リモート条件フィルタ
- `--download`: 検索結果求人のローカルMarkdown自動保存
- `--download-limit`: ダウンロード保存件数上限
- `--force`: 既存ファイルの強制上書き取得
- `--session`: Playwright共通プロファイルセッション名（デフォルト: `job-hunt`）

### 推奨エントリポイント実装パターン

```python
from scripts.common.cli import create_search_parser, entrypoint_guard

def main() -> None:
    parser = create_search_parser(description="求人検索CLI")
    args = parser.parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        # 処理と保存...
        ctx.add_result_path(saved_path)
        ctx.flush_outputs(summary_fn=print_summary)

if __name__ == "__main__":
    main()
```

## 7. サイト構造ドキュメント（`docs/{site}/`）の事前参照と最新化の徹底

スクリプトと対象サイト仕様・ドキュメントの乖離を防ぎ、メンテナンス性とスクレイピング精度を担保するため、以下の運用を必須とする。

### 1. 実装前の事前参照（サイト構造の理解）
- **推測・勘による実装の禁止**: 新規スクリプト作成や既存スクリプト修正（セレクタ変更、新エンドポイント追加、不具合対応等）を行う前に、必ず対象サイトの `docs/{site}/site_structure.md`、`docs/{site}/README.md`、および `docs/guides/new_site_scraper_guide.md` を熟読すること。
- **理解すべき主要要素**:
  - 対象ページのURL体系・クエリパラメータ規則
  - DOMセレクタ・構造（求人カード、タイトル、企業名、年収、詳細リンク等）
  - 認証フロー（ログインURL、認証壁正規表現、ログイン判定セレクタ）
  - バックエンドAPI仕様や内部データ構造（JSONレスポンス、GraphQL等）
- 既存の調査知見を踏まえて設計・実装することで、手戻りやセレクタの重複調査を防ぐ。

### 2. 実装完了時のドキュメント最新化（コードとドキュメントの同期）
- **仕様変更・新規発見の即時反映**:
  - サイト仕様変更に伴うDOMセレクタの更新
  - 新規APIエンドポイント、クエリパラメータ、ヘッダーの追加・変更
  - 認証仕様やリダイレクトの変更
  - 新機能（いいね、スカウト、応募状況、職歴更新等）のスクリプト追加
  上記が発生した場合は、必ず対応する `docs/{site}/site_structure.md` および `docs/{site}/README.md` を同時に更新・最新化すること。
- **新規サイト追加時のドキュメント作成必須化**:
  - 新規サイトのスクリプトを作成した場合は、必ず `docs/{site}/site_structure.md` と `docs/{site}/README.md` を新規作成し、URL一覧、セレクタ定義、認証仕様、スクリプト一覧を網羅すること。
- **作業完了の定義**:
  - 「スクリプトのコード実装・動作確認」と「`docs/{site}/` の最新化」は**不可分のワンセット**である。ドキュメントの更新が完了するまで、スクリプトの作成・改修作業を完了としてはならない。

### 3. 実装チェックリスト
- [ ] 実装前に `docs/{site}/site_structure.md` 等を確認し、サイト構造やセレクタ設計を理解したか
- [ ] デフォルト実行時の標準出力（stdout）は生成・該当ファイルパスのみか
- [ ] 人間向けサマリは `--summary` 指定時のみ表示されるか
- [ ] ログ・進捗・エラーはすべて `stderr` に出力されているか
- [ ] スクリプト作成・変更に伴い、`docs/{site}/site_structure.md` および `docs/{site}/README.md` を最新化したか（新規サイトの場合は作成したか）


