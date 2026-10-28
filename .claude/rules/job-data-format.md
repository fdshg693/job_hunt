---
paths:
- data/**/jobs/**/*.md
- scripts/**/*.py
---

<!-- 自動生成ファイル: .agents/rules/job-data-format.md から scripts/dev/sync_agents.py で生成。直接編集せず .agents/rules/job-data-format.md を編集して再同期すること -->

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
- **データモデル**: Pydantic v2 の `scripts.common.models.job.JobPosting`（または既存互換の `scripts.common.storage.JobData`）を使用する。相互変換（`JobPosting.from_job_data()` / `to_job_data()`）に対応している。
- **Frontmatter付きMarkdownの保存**: `scripts.common.storage.save_job_markdown(job)` を使用する（`JobPosting` および `JobData` の双方を直接受け入れ可能）。
- **求人詳細取得パイプライン**: 各サイトの求人スクレイパーは `scripts.common.crawlers.job_pipeline.run_job_pipeline` を使用して実装する。
- **検索一覧（Markdown/JSON）の保存**: `scripts.common.storage.save_search_result` を使用する。
- **新規求人サイトの追加**: `scripts/templates/site_scraper_template.py` および `docs/guides/new_site_scraper_guide.md` を参照すること。

## 検索・取得ツール

- 媒体ごとの求人検索・詳細取得（`scripts/{site}/search_*.py` / `fetch_job.py`）と、保存済み求人の横断検索（`scripts/common/search_local_jobs.py`）がある。一覧は [スクリプト一覧](../../docs/scripts/catalog.md)、オプション・使用例は各スクリプトの `--help`、媒体固有の手順は `docs/{site}/README.md`。
- 標準出力は作成・該当したファイルパスのみで、整形表示は `--summary`（[scripts-entrypoint.md](scripts-entrypoint.md)）。
