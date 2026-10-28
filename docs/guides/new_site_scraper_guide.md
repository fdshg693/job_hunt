# 新規求人サイトスクレイパー追加ガイド

本ガイドは、Wantedly、Green、dodaなどの新しい転職・求人サイトを本リポジトリに追加する際の手順、アーキテクチャ、および実装チェックリストをまとめたドキュメントです。

現在、本リポジトリでは **Findy**、**ビズリーチ**、**OpenWork**、**Forkwell**、**LinkedIn** の5媒体に対応しており、各サイト固有の実装例は `scripts/{site}/` および `docs/{site}/` で参照可能です。

リファクタリング済みの共通基盤（`scripts/common/`）を活用することで、認証ハンドオフ・CLI引数制御・データ正規化・Markdown永続化などの定型処理を再実装することなく、**サイト固有のHTML/APIパース処理（全体の20〜30%）のみ**の実装で安全に新規サイトを追加できます。

---

## 1. 全体アーキテクチャと責務分担

```
┌─────────────────────────────────────────────────────────────┐
│ サイト固有スクリプト (scripts/{site}/)                      │
│ - URLクエリパラメータの構築                                │
│ - DOMセレクタ・APIレスポンスからのデータ抽出 (bs4 / regex)  │
└──────────────┬───────────────────────────────┬──────────────┘
               │                               │
               ▼                               ▼
┌──────────────────────────────┐┌──────────────────────────────┐
│ 共通基盤: scripts/common/    ││ 共通基盤: scripts/common/    │
│ [auth_engine]                ││ [normalizers]                │
│ - ログイン状態確認・認証壁検知││ - 年収パース (円単位整数化) │
│ - OS通知 & 手動待機ハンドオフ││ - リモート判定・スキル抽出   │
│ [browser_auth]               ││ [storage]                    │
│ - run_code_snippet (実行)    ││ - JobData モデル             │
│ - 永続プロファイルセッション ││ - job-data-format 準拠保存   │
│ [cli]                        │└──────────────────────────────┘
│ - 標準引数パーサー生成       │
│ - stdout (パスのみ) / stderr │
└──────────────────────────────┘
```

---

## 2. 実装手順（5ステップ）

### Step 1: サイトの事前調査
`sharing-browser-with-user` スキルや普段のブラウザを用いて、対象サイトの仕様を調査します:
1. **検索URL構造**: キーワード、ページ番号、年収、勤務地等のGETパラメータ
2. **認証要件**: 非ログインで閲覧可能か、要ログインか、CAPTCHA（Cloudflare/reCAPTCHA）があるか
3. **HTML構造/セレクタ**: 求人カード要素、タイトル、企業名、給与表記、詳細リンクURL
4. **求人ID規則**: URLに含まれる一意のID（例: `/projects/12345` -> `12345`）

### Step 2: テンプレートのコピー
新規サイト用のディレクトリを作成し、雛形スクリプトをコピーします:

```powershell
# 例: Wantedly を追加する場合
mkdir scripts/wantedly
mkdir data/wantedly/jobs
mkdir data/wantedly/searches

# 雛形スクリプトをコピー
cp scripts/templates/site_scraper_template.py scripts/wantedly/search_jobs.py
```

### Step 3: 定数と認証設定の更新
スクリプト冒頭の定数と `SiteAuthConfig` を設定します:

```python
SITE_NAME = "Wantedly"
SITE_SOURCE = "wantedly"
SITE_BASE_URL = "https://www.wantedly.com"
SEARCH_BASE_URL = "https://www.wantedly.com/projects"

# 認証設定（ログインが必要なサイトの場合）
SITE_AUTH_CONFIG = SiteAuthConfig(
    site_name=SITE_NAME,
    login_url="https://www.wantedly.com/user/sign_in",
    target_url=SEARCH_BASE_URL,
    auth_wall_regex=r"/user/sign_in|/login",
    logged_in_selectors=['header a[href*="/user/profile"]', 'img[alt*="アバター"]'],
    is_captcha_site=False,
)
```

> [!TIP]
> ログイン不要で一般公開されている検索画面の場合は、`ensure_site_authenticated(...)` の呼び出しをスキップして問題ありません。

### Step 4: URL生成・パースロジックの実装
以下の3つの関数に対象サイト固有のロジックを実装します:

1. **`build_search_url(keyword, page, min_salary_man, remote)`**:
   サイトのクエリストリングを生成します。
2. **`parse_job_cards(html_content)`**:
   HTMLからカード要素をループし、`dict` のリストを生成します。
   - 年収抽出: `parse_salary_range(raw_salary_text)`
   - リモート判定: `detect_remote_type(location_text, card_text)`
   - スキル抽出: `extract_skills_from_text(card_text)`
   - URL正規化: `normalize_url(href, base_url=SITE_BASE_URL)`
3. **`fetch_and_save_job_detail(job_id, job_url, ...)`**:
   詳細ページを取得し、`JobData` モデルを作成して `save_job_markdown(job)` を実行します。

### Step 5: 動作検証
CLI規約に準拠しているかを以下のコマンドで確認します:

```powershell
# 1. ヘルプ確認
uv run python scripts/{site}/search_jobs.py --help

# 2. パスのみ出力（AI・パイプライン向け）の確認
uv run python scripts/{site}/search_jobs.py "Python" -n 3

# 3. 人間向けサマリ表示の確認
uv run python scripts/{site}/search_jobs.py "Python" -n 3 --summary

# 4. JSON出力の確認
uv run python scripts/{site}/search_jobs.py "Python" -n 3 --json

# 5. 求人詳細ダウンロード保存の確認
uv run python scripts/{site}/search_jobs.py "Python" -n 2 --download
```

### Step 6: サイト構造ドキュメントの作成 (`docs/{site}/`)
スクリプト実装で判明した仕様を必ず文書化し、今後の保守や機能追加時に参照できるようにします（`.agents/rules/scripts-entrypoint.md` 準拠）:
1. **`docs/{site}/site_structure.md`**: URL一覧、主要セレクタ（求人カード、タイトル、給与等）、認証仕様、APIエンドポイントの整理
2. **`docs/{site}/README.md`**: サイト概要、実装済みスクリプト一覧、使用例、取得データ保存パス

---

## 3. 共通モジュール・API リファレンス

### `scripts.common.cli`
| 関数 / クラス | 説明 |
| --- | --- |
| `create_base_parser(desc, default_limit)` | `--summary`, `--json`, `-n/--limit`, `--force` を備えた基底パーサー |
| `create_search_parser(desc, ...)` | 求人検索用の共通引数（`query`, `--min-salary`, `--remote`, `--download` 等）を備えたパーサー |
| `entrypoint_guard(summary, json_mode)` | 例外捕捉、Ctrl+C ハンドリング、結果パス追跡を行うコンテキストマネージャ |
| `to_relative_path(path)` | プロジェクトルートからの相対パス（スラッシュ区切り）に変換 |

### `scripts.common.normalizers`
| 関数 | 説明 |
| --- | --- |
| `parse_salary_range(text)` | "800万〜1200万円" 等から `(8000000, 12000000)` の円単位タプルを取得 |
| `parse_salary_arg(val)` | CLI引数の "800" や "800万" を円単位数値 `8000000` にパース |
| `detect_remote_type(loc, body)` | 本文や勤務地から `"出社"`, `"フルリモート"`, `"ハイブリッド"` を自動判定 |
| `extract_skills_from_text(text)` | SSOT辞書（`KNOWN_SKILL_KEYWORDS`）に基づき、単語境界を考慮して技術スタックを抽出 |
| `format_salary_display(min, max)` | コンソールサマリ表示用に "800万〜1200万円" 形式の文字列を生成 |
| `normalize_url(url, base_url)` | 相対URL解決および不要なトラッキングクエリ（`utm_*`等）を除去 |

### `scripts.common.storage`
| 関数 / クラス | 説明 |
| --- | --- |
| `JobData` | `job-data-format.md` に完全準拠した求人データモデル（dataclass） |
| `save_job_markdown(job, output_dir, force)` | フロントマター付き求人Markdownを保存。戻り値: `(Path, is_new)` |
| `save_search_result(source, keyword, jobs, ...)` | 検索一覧のMarkdownおよびJSONを自動保存。戻り値: `(md_path, json_path)` |

### `scripts.common.browser_auth`
| 関数 / 変数 | 説明 |
| --- | --- |
| `run_playwright_cmd(args, ...)` | `playwright-cli` を `shell=False` で実行し、cmd.exe による `&` 切断を防ぐ共通ラッパー |
| `run_code_snippet(session, code)` | 一時 mjs スクリプトを生成・実行して結果 JSON をパース |
| `check_playwright_cli()` | `playwright-cli` の実行環境（シムおよび `playwright-cli.js` エントリ）が利用可能か検証 |

> [!IMPORTANT]
> `playwright-cli` は `run_playwright_cmd` 経由で起動する（cmd.exe を介さない）。直接 `subprocess` で `playwright-cli` を呼ばないこと。エントリの場所が特殊な環境は環境変数 `PLAYWRIGHT_CLI_JS` で指定する。

### `scripts.common.auth_engine`
| 関数 / クラス | 説明 |
| --- | --- |
| `SiteAuthConfig` | サイトごとのログインURL、判定セレクタ、CAPTCHAフラグ等の宣言的設定モデル |
| `ensure_site_authenticated(site, session, ...)` | 認証状態をチェックし、未認証・CAPTCHA時はOS通知＆手動ハンドオフを実施 |

---

## 4. 実装チェックリスト

スクリプト完成時、以下の規約・要件を満たしているか確認してください:

- [ ] **エントリポイント出力規約 (`scripts-entrypoint.md`)**:
  - [ ] デフォルト実行時、標準出力（stdout）には生成・該当したファイルパスのみを出力しているか（1行1パス）。
  - [ ] コンソール向けのテキストサマリ表示は `--summary`（または `-s`）指定時のみ行われるか。
  - [ ] 取得進捗、デバッグ情報、エラーメッセージはすべて標準エラー出力（stderr）に出力しているか。
  - [ ] 正常終了時は `0`、エラー時は `1`、認証中断時は `2` の終了コードを返しているか。
- [ ] **求人データフォーマット (`job-data-format.md`)**:
  - [ ] 求人Markdownは `data/{source}/jobs/{id}.md` に保存されているか。
  - [ ] フロントマターの必須項目（`id`, `source`, `company`, `title`, `url`, `fetched_at`）が含まれているか。
  - [ ] 年収（`salary_min`, `salary_max`）は円単位の整数になっているか（`parse_salary_range` を使用）。
  - [ ] リモート区分は「出社 / フルリモート / ハイブリッド」に分類されているか（`detect_remote_type` を使用）。
- [ ] **CLI引数命名の整合性**:
  - [ ] 件数上限は `-n` / `--limit`、ダウンロード上限は `--download-limit` になっているか（`create_search_parser` を使用していれば自動準拠）。
  - [ ] 上書きオプションは `--force` になっているか。
  - [ ] モジュール docstring の 1 行目が「〜を…する CLI.」の 1 文（70 字以内）で、パーサーに `examples=[...]`（使用例 2〜3 個）と `related=[...]`（前後に使うスクリプト）を渡して `--help` 末尾に出しているか（テンプレートの `create_search_parser` 呼び出しを参照。`tests/test_script_help.py` で検査）。
- [ ] **サイト構造ドキュメントの作成・最新化 (`docs/{site}/`)**:
  - [ ] 実装前に `docs/{site}/site_structure.md` 等を確認し、サイト構造・セレクタ設計を理解したか。
  - [ ] 新規サイト追加時、`docs/{site}/site_structure.md` と `docs/{site}/README.md` を作成したか。
  - [ ] 既存スクリプト修正・仕様変更時、判明したセレクタやエンドポイントを `docs/{site}/` に即座に反映したか。

