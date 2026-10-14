---
trigger: glob
globs: data/**/jobs/**/*.md, scripts/**/*.py
---

# 求人データフォーマット仕様

求人情報は `data/{source}/jobs/{id}.md` にフロントマター付きMarkdown形式で保存する。将来他の媒体（Wantedly, Green等）が追加されても共通のCLI/LLM検索ができるよう、以下のスキーマを遵守する。

## フロントマター仕様

### 共通必須項目
- `id`: 求人ID（文字列。URLから一意に定まるID、例: `FyTVLvHVuEiQm`）
- `source`: 求人媒体名（文字列、小文字。例: `findy`）
- `company`: 企業名（文字列）
- `title`: 求人タイトル（文字列）
- `url`: 求人URL（文字列）
- `fetched_at`: 取得日時（ISO 8601形式、例: `2026-09-14T13:30:00+09:00`）

### 共通任意項目（可能な限り抽出）
- `salary_min`: 最小年収（数値、円単位。例: `6000000`）
- `salary_max`: 最大年収（数値、円単位。例: `9000000`）
- `salary_text`: 給与表示文字列（文字列。例: `"600万円〜900万円"`）
- `skills`: 必要/歓迎技術スタック・キーワード（文字列配列）
- `job_roles`: 職種カテゴリ（文字列配列。例: `["フルスタックエンジニア"]`）
- `location`: 勤務地（文字列）
- `remote_type`: リモート方針（文字列。例: `"ハイブリッド"`, `"フルリモート"` 等）
- `tags`: 特徴・魅力タグ（文字列配列）
- `company_url`: 企業ホームページ等のURL（文字列）

## 本文仕様

フロントマターの後に、以下のセクション構成でMarkdown形式の本文を記述する（該当項目がない場合は省略可）。

```markdown
# {title}

## 概要・仕事内容
{description}

## 必須要件 (Must)
{must_skills}

## 歓迎要件 (Desired)
{desired_skills}

## 開発環境
{development_environment}

## 仕事の魅力・特徴
{rewarding}

## 求める人物像
{personality}

## 勤務地・就業条件・福利厚生
{location / employment_pattern / others}
```

## データ抽出・保存パイプライン (共通基盤の活用)

求人情報の抽出・正規化およびファイル保存は、二重実装やデータゆれを防ぐため `scripts/common/` の共通基盤を利用すること。

- **年収表記の円換算**: `scripts.common.normalizers.parse_salary_range` を使用して `(min, max)` の円単位整数を取得する。
- **CLI引数の年収パース**: `scripts.common.normalizers.parse_salary_arg` を使用する（"800" / "800万" を `8000000` に変換）。
- **リモート勤務タイプの判定**: `scripts.common.normalizers.detect_remote_type` を使用して「出社」「ハイブリッド」「フルリモート」に分類する。
- **スキルキーワードの抽出**: `scripts.common.normalizers.extract_skills_from_text` を使用して単一情報源（SSOT）から単語境界を考慮して抽出する。
- **Frontmatter付きMarkdownの保存**: `scripts.common.storage.JobData` モデルを構築し、`scripts.common.storage.save_job_markdown` で保存する。
- **検索一覧（Markdown/JSON）の保存**: `scripts.common.storage.save_search_result` を使用する。
- **新規求人サイトの追加**: `scripts/templates/site_scraper_template.py` および `docs/guides/new_site_scraper_guide.md` を参照すること。

## 検索・取得ツール

> [!NOTE]
> エントリポイントスクリプトは原則として標準出力（stdout）に作成・該当した `data/` 配下のファイルパスを出力します。ターミナル整形表示を行いたい場合は `--summary` オプションを指定してください（詳細は `.agents/rules/scripts-entrypoint.md` を参照）。

### 1. オンライン求人検索・取得 (Findy)

企業名やキーワードからFindy上の求人一覧・詳細URLを検索し、必要に応じてローカルMarkdownへの自動保存まで行える。
デフォルトでは検索結果ファイル（`data/findy/searches/...md`）や保存求人ファイルのパスが標準出力に出力される。

```bash
# 企業名・キーワードでオンライン検索（検索結果ファイルのパスを出力）
uv run python scripts/findy/search_online.py "企業名や技術スタック"

# コンソール上にサマリテーブルを表示
uv run python scripts/findy/search_online.py "Python" --summary -n 5

# 年収絞り込み（例: 800万円以上）
uv run python scripts/findy/search_online.py "Go" --min-salary 800

# ヒットした求人をローカルMarkdownとして自動保存（保存された各ファイルパスを出力）
uv run python scripts/findy/search_online.py "企業名" --download --download-limit 3

# JSON形式で出力
uv run python scripts/findy/search_online.py "機械学習" --json
```

### 2. オンライン求人検索・取得 (ビズリーチ)

キーワードや条件（年収、勤務地、リモート等）からビズリーチ上の求人一覧・詳細URLを検索し、必要に応じてローカルMarkdownへの自動保存まで行える。
デフォルトでは検索結果ファイル（`data/bizreach/searches/...md`）や保存求人ファイルのパスが標準出力に出力される。

```bash
# キーワードでオンライン検索（検索結果ファイルのパスを出力）
uv run python scripts/bizreach/search_jobs.py "Python" -n 5

# コンソール上にサマリテーブルを表示
uv run python scripts/bizreach/search_jobs.py "Python" -n 5 --summary

# 年収絞り込み（例: 800万円以上）& リモート案件
uv run python scripts/bizreach/search_jobs.py "Go" --min-salary 800 --remote --summary

# ヒットした求人をローカルMarkdownとして自動保存（保存された各ファイルパスを出力）
uv run python scripts/bizreach/search_jobs.py "TypeScript" -n 3 --download --download-limit 3

# 求人IDまたはURLから単体詳細を取得・保存
uv run python scripts/bizreach/fetch_job.py 7755397

# スカウト/メッセージURLまたはスレッドIDから添付求人を自動取得・保存
uv run python scripts/bizreach/fetch_message_jobs.py 444484943
```

### 3. オンライン求人検索・取得 (OpenWork)

キーワードや条件（年収、勤務地、リモート等）からOpenWork上の求人一覧・詳細URLを検索し、必要に応じてローカルMarkdownへの自動保存まで行える。
デフォルトでは検索結果ファイル（`data/openwork/searches/...md`）や保存求人ファイルのパスが標準出力に出力される。

```bash
# キーワードでオンライン検索（検索結果ファイルのパスを出力）
uv run python scripts/openwork/search_jobs.py "Python" -n 5

# コンソール上にサマリテーブルを表示
uv run python scripts/openwork/search_jobs.py "Python" -n 5 --summary

# 年収絞り込み（例: 800万円以上）& リモート案件
uv run python scripts/openwork/search_jobs.py "Go" --min-salary 800 --remote --summary

# ヒットした求人をローカルMarkdownとして自動保存（保存された各ファイルパスを出力）
uv run python scripts/openwork/search_jobs.py "TypeScript" -n 3 --download --download-limit 3

# 求人IDまたはURLから単体詳細を取得・保存
uv run python scripts/openwork/fetch_job.py <job_id_or_url>
```

### 4. ローカル求人Markdownの横断検索・フィルタリング

保存された求人Markdownは、`scripts/common/search_jobs.py` を用いてコマンドラインから高速に検索・フィルタリングできる。
デフォルトでは一致した求人Markdownのファイルパスが出力される。

```bash
# 基本検索（一致したファイルパス一覧を出力）
uv run python scripts/common/search_jobs.py [フリーワード...]

# サマリテーブルで一覧表示
uv run python scripts/common/search_jobs.py --summary

# オプション例
uv run python scripts/common/search_jobs.py -s Python -s React --min-salary 700 --summary
uv run python scripts/common/search_jobs.py -c "企業名" --detail --summary
uv run python scripts/common/search_jobs.py --remote "フルリモート" --json
```
