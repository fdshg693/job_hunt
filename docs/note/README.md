# note.com 記事・検索結果取得ツール

note.com で公開されている記事URL（単一記事）およびキーワード検索（または検索URL）から、タイトル・本文Markdown・著者情報・メタデータ（スキ数・公開日時・タグ等）を抽出し、Markdown（Frontmatter付き）および構造化JSONとしてローカルに保存するツールです。

## 概要

- **取得方式**: HTTP GET + 公開JSON API（`https://note.com/api/v3/notes/{key}`, `https://note.com/api/v3/searches`）（Playwright不要、ログイン不要、数ミリ秒〜数十ミリ秒で高速動作）
- **対象**:
  - 単体記事: `https://note.com/{urlname}/n/{note_key}`、独自ドメイン記事、または `note_key`（例: `n24f8414083da`）
  - 記事検索: キーワード文字列（例: `"ログラス 転職"`）、または検索URL（例: `https://note.com/search?q=test&context=note&mode=search`）
- **保存先**:
  - 単体記事: `data/note/articles/{urlname}/{note_key}.md`（および `.json`）
  - 検索結果: `data/note/searches/{YYYYMMDD_HHMMSS}_{query}.md`（および `.json`）
  - 企業紐付け時（`--company-key`）: `data/note/companies/{company_key}/`

## 実装スクリプト

| スクリプト | 説明 |
| --- | --- |
| `scripts/note/fetch_article.py` | 単体note記事のメタデータおよび本文Markdown/JSON取得CLI |
| `scripts/note/search_notes.py` | note.com 記事キーワード検索・一覧取得・保存および記事詳細一括取得連携CLI |

## 使用例

### 1. 単体記事取得 (`scripts/note/fetch_article.py`)

```powershell
# 基本実行（Markdown・JSONを生成し、stdoutには生成ファイルパスのみ出力）
uv run python scripts/note/fetch_article.py "https://note.com/narumiruna19/n/n24f8414083da"

# note keyを直接指定して取得
uv run python scripts/note/fetch_article.py n24f8414083da

# 人間向けサマリ表示（タイトル、著者、公開日、スキ数、タグ、本文冒頭等をコンソールに表示）
uv run python scripts/note/fetch_article.py "https://note.com/narumiruna19/n/n24f8414083da" --summary

# JSONメタデータ出力をスキップし、Markdownのみ保存
uv run python scripts/note/fetch_article.py "https://note.com/narumiruna19/n/n24f8414083da" --no-json

# 特定の企業フォルダ（data/note/companies/{company_key}/）に紐付けて出力
uv run python scripts/note/fetch_article.py "https://note.com/narumiruna19/n/n24f8414083da" -c loglass --summary

# ファイル保存を行わずに解析結果・動作のみ確認（dry-run）
uv run python scripts/note/fetch_article.py "https://note.com/narumiruna19/n/n24f8414083da" --dry-run --summary
```

### 2. 記事検索 (`scripts/note/search_notes.py`)

```powershell
# 基本検索（Markdown・JSONを生成し、stdoutには生成ファイルパスのみ出力）
uv run python scripts/note/search_notes.py "ログラス 転職"

# 検索URLをそのまま渡して検索実行
uv run python scripts/note/search_notes.py "https://note.com/search?q=test&context=note&mode=search"

# 人間向けサマリ表示（ヒット記事一覧、スキ数、著者、URL等をコンソールに表示）
uv run python scripts/note/search_notes.py "転職体験談" --summary

# 取得件数制限（デフォルト: 10）
uv run python scripts/note/search_notes.py "エンジニア採用" -n 5 --summary

# 検索ヒットした各記事の本文・詳細（Markdown/JSON）を一括取得・保存
uv run python scripts/note/search_notes.py "ログラス" -n 3 --fetch-articles --summary

# 企業フォルダ（data/note/companies/{company_key}/searches/）に紐付けて出力
uv run python scripts/note/search_notes.py "ログラス" -c loglass --fetch-articles --summary
```

## 出力ファイル構成

### 単体記事 (`data/note/articles/{urlname}/` または `data/note/companies/{company_key}/`)

- `{note_key}.md`: YAML Frontmatter（タイトル、著者、公開日、スキ数、タグ、元URL等）および整形済み本文Markdown
- `{note_key}.json`: APIレスポンスに基づく構造化メタデータJSON（`--no-json` 指定時は非生成）

### 検索結果 (`data/note/searches/` または `data/note/companies/{company_key}/searches/`)

- `{YYYYMMDD_HHMMSS}_{query}.json`: 検索クエリ、取得件数、各記事のメタデータ配列
- `{YYYYMMDD_HHMMSS}_{query}.md`: フロントマター付きの検索結果一覧Markdownテーブル

## 関連ドキュメント

- [site_structure.md](site_structure.md): note.com のURL構造、APIエンドポイント仕様、HTMLからMarkdownへのパースルール等の詳細技術仕様
