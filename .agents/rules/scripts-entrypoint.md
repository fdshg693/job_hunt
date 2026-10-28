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

### docstring と `--help`（使用例・関連スクリプト）

`--help` を見れば、ファイルや `docs/` を開かなくても使い方が分かる状態に保つ。`tests/test_script_help.py`（AST の静的検査）が欠落を検出する。

- **モジュール docstring の 1 行目**に「何をする CLI か」を 1 文で書く（例: `OpenWork の会社クチコミ・8 項目評価を取得して保存する CLI.`）。70 字以内で `CLI` を含め、後ろに空行を入れて詳細は 3 行目以降に書く。1 行目はスクリプト一覧 [`docs/scripts/catalog.md`](../../docs/scripts/catalog.md)（`scripts/dev/gen_script_catalog.py` の生成物）の生成元になる。非推奨の互換ラッパーは `非推奨: 代わりに scripts/x/y.py を使う.` とする。
- **`--help` に使用例 2〜3 個と関連スクリプト**を出す: `create_base_parser(examples=..., related=...)` / `create_search_parser(...)`、共通パイプラインは `JobCrawlerConfig` / `MessageCrawlerConfig` の `examples` / `related`、`argparse.ArgumentParser` を直接作るなら `epilog=build_epilog(...)` と `RawDescriptionHelpFormatter`。
  - `examples` は `uv run python scripts/...` から書くコマンド 1 行ずつ（補足は行末の `  # ...`）。代表的な使い方と重要なオプションに絞り、網羅的な説明は各引数の `help=` と `docs/{site}/README.md` に任せる。
  - `related` は前後に使うスクリプトだけ（`scripts/openwork/resolve_company.py: 先に企業 ID を解決する`）。場面ごとの使い分けの全体像は `--help` に書かない。

### 推奨エントリポイント実装パターン

```python
from scripts.common.cli import create_search_parser, entrypoint_guard

def main() -> None:
    parser = create_search_parser(
        examples=["uv run python scripts/{site}/search_jobs.py Python -n 5 --summary"],
        related=["scripts/{site}/fetch_job.py: ヒットした求人の詳細を取得する"],
    )  # description 省略時はモジュール docstring
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
- [ ] 認証判定・ハンドオフに `ensure_site_authenticated` を使用し、個別mjsを作成していないか
- [ ] スクリプト作成・変更に伴い、`docs/{site}/site_structure.md` および `docs/{site}/README.md` を最新化したか（新規サイトの場合は作成したか）
- [ ] docstring 1 行目に「何をする CLI か」を書き、`--help` に使用例と関連スクリプトを出したか（`tests/test_script_help.py`）
- [ ] 新規・改名・docstring 1 行目の変更なら `uv run python scripts/dev/gen_script_catalog.py` でスクリプト一覧 `docs/scripts/catalog.md` を再生成したか（`goal.md` には個別スクリプトを書かない）。新規サイトなら `docs/README.md` の媒体表にも追記したか
- [ ] `uv run ruff check` でリントを通過し、`uv run pytest` でテストが通過することを確認したか

## 8. ブラウザ認証・セッションハンドオフの共通化規約

転職サイトのブラウザ自動化における認証状態判定および未ログイン時の待機ハンドオフは、共通基盤に完全一本化されている。

### 1. 共通認証エンジンの利用義務
- **`ensure_site_authenticated` の使用**: 認証を要するスクリプトでは、必ず `scripts.common.auth_engine.ensure_site_authenticated(site_name, session=session, ...)` を使用して認証確認および手動ログイン待機ハンドオフを行うこと。
- **サイト個別mjsの作成禁止**: 各サイトディレクトリ（`scripts/{site}/`）配下に `auth_check.mjs` や `auth_guard.mjs` を個別に作成してはならない。サイト固有の判定条件（ログインURL正規表現、認証壁セレクタ、CAPTCHA/WAF判定等）は、すべて `scripts/common/auth_engine.py` の `SiteAuthConfig` および `scripts/common/js/universal_auth.mjs` に集約・管理する。

### 2. コマンド実行時の安全規約（`shell=False` の徹底）
- **`subprocess` に `shell=True` を使わない**: Windows 環境において cmd.exe が引数を再解釈し、URL の `&` や `%` などのメタ文字が切断・誤動作する原因となるため、外部プロセス起動には `shell=False` を徹底すること。`playwright-cli` は直接 `subprocess` で呼ばず、必ず `scripts.common.browser_auth.run_playwright_cmd` を経由すること。

## 9. スクレイパー共通実行パイプライン（crawlers）利用規約

メッセージ一覧取得や求人詳細取得スクリプトを新規作成・改修する際は、各サイトスクリプトでCLIパース、認証待機、キャッシュ確認、Playwright実行、データ検証、保存処理、出力フォーマットのボイラープレートを重複実装せず、`scripts.common.crawlers` の共通パイプラインを利用すること。

### 1. メッセージ一覧スクレイパー (`message_pipeline.py`)
- メッセージ・スカウト一覧取得スクリプト（`scripts/*/navigate_messages.py` 等）は、`MessageCrawlerConfig` を定義し、`run_message_pipeline(config)` を呼び出す構成とする。
- データの受け渡し・検証には `scripts.common.models.message.MessageItem` および `MessageBatch`（Pydantic v2 モデル）を使用する。

### 2. 求人詳細スクレイパー (`job_pipeline.py`)
- 求人詳細取得スクリプト（`scripts/*/fetch_job.py` 等）は、`JobCrawlerConfig` を定義し、`run_job_pipeline(config)` を呼び出す構成とする。
- データの受け渡し・検証には `scripts.common.models.job.JobPosting`（Pydantic v2 モデル）または `JobData` を使用する。
- 既存ファイルが存在し `--force` が指定されていない場合は、取得処理自体をスキップして既存ファイルパスを返すキャッシュガードが自動適用される。

## 10. コード品質検証・テスト実行規約

スクリプト改修・新規作成時および機能実装完了時は、以下の品質検証コマンドを実行してコードの整合性とテスト通過を確認すること。

```bash
# 静的解析・リンター確認（scripts/ 配下）
uv run ruff check scripts/

# 自動フォーマット確認（必要に応じて）
uv run ruff format --check scripts/

# 単体テスト実行（tests/ 配下のオフラインモックテスト）
uv run pytest
```

- **必須**: スクリプト改修後は `uv run ruff check` でリントエラーが出ないことを確認し、関連する単体テスト（`tests/`）が通過することを確認する。`fetch_job` 等の取得経路を変更したら `tests/test_fetch_job_paths.py` に経路を足す。未定義名は `tests/test_static_names.py` が検出する。
- **型チェック（任意・段階導入）**: `scripts/common/` や `scripts/vault/` を触った場合は `uv run mypy scripts/common/` による型チェックも推奨される。

## 11. 媒体プロファイル更新・SSOT同期CLI規約

転職サイトの登録プロファイル（基本情報、経歴企業・職歴、職務経歴・自己PR、希望条件、スキル等）を管理・更新するスクリプト（`scripts/{site}/manage_profile*.py`）は、以下の規約を遵守すること。

### 1. サブコマンド構造による統合
- 媒体内のプロファイルセクションごとにスクリプトを過剰に細分化・乱立させず、サブコマンド形式（例: `basic`, `company`, `resume`, `condition`, `skill`、および全セクション一括 `sync`）を採用して単一CLIに統合する。
- 各サブコマンド配下に `fetch`（取得・保存）、`update`（個別項目更新）、`sync`（SSOT同期）の共通アクションを定義する。

### 2. 安全ガード（自動バックアップ・差分プレビュー）の義務付け
- **更新前自動バックアップ**:
  - `update` や `sync` 等の更新系操作を実行する前に、必ず最新プロファイルを取得し、`scripts.common.profile_sync.save_profile_backup` を使用して `data/{site}/profile/backups/` 配下にタイムスタンプ付きの変更前JSONバックアップを自動保存すること。
- **`--dry-run` オプションの完備**:
  - 更新系操作には必ず `--dry-run` オプションを設け、ブラウザ側への変更送信や保存を実行せずに、変更前後の差分（Unified Diff）をプレビュー表示（`scripts.common.profile_sync.print_profile_diff`）できる設計とすること。
  - エージェントおよびユーザーは、初回実行時や一括同期前に `--dry-run` で差分を確認し、意図せぬ上書き事故を防止する。

### 3. SSOT（`vault/profile/`）との連携
- 媒体プロファイルへのデータ反映は、`vault/profile/`（`resume.md`, `skills.md` 等）および `vault/tracks/`（`strategy.md`）をSSOT（唯一の正本）として扱う。
- `scripts.common.profile_sync.load_vault_profile` 等の共通アダプター経由で構造化データを抽出し、媒体ごとのフォームやAPI仕様へ適切にマッピングして同期すること。

### 4. 公開同期パスにおける個人情報の直書き禁止
- 公開対象パス（`scripts/`, `docs/`, `tests/`, `templates/`, `webui/` 等）に個人情報（氏名・スラッグ・年収・スコア・自己紹介文の完成文等）を直書きしてはならない。
- 外部送信用完成文や個人固有値は `vault/profile/sites/` や `vault/profile/resume.md` から読み込み、テストコードでは `tests/fixtures/` のダミーデータを使用すること。
- 禁止語スキャン（`scripts/dev/check_public_leak.py`）が pre-commit フックおよびパブリック同期 CI で機械的に検査する。
