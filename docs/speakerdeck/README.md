# Speaker Deck スライド文字起こし・取得ツール

Speaker Deck で公開されている会社紹介資料・登壇スライドから、スライドごとのテキスト・画像URL・メタデータを抽出し、Markdown（`transcript.md`）および構造化JSON（`deck.json`）としてローカルに保存するツールです。

## 概要

- **取得方式**: HTTP GET + BeautifulSoup（Playwright不要、ログイン不要、高速動作）
- **対象**: `https://speakerdeck.com/{username}/{deck_slug}` または埋め込みプレイヤーURL
- **保存先**: `data/speakerdeck/{username}/{deck_slug}/`（または `--output-dir`, `--company-key` で指定した場所）

## 実装スクリプト

| スクリプト | 説明 |
| --- | --- |
| `scripts/speakerdeck/fetch_deck.py` | 単体スライドデッキのテキスト・画像URL・PDFリンク取得CLI |
| `scripts/speakerdeck/search_decks.py` | Speaker Deck キーワード検索・一覧取得・保存および文字起こし連携CLI |

## 使用例

### 1. スライド検索 (`scripts/speakerdeck/search_decks.py`)

```powershell
# 基本検索（Markdown・JSONを生成し、stdoutには生成ファイルパスのみ出力）
uv run python scripts/speakerdeck/search_decks.py "ログラス"

# 人間向けサマリ表示（上位スライド、発表者、枚数、閲覧数、スター数を表示）
uv run python scripts/speakerdeck/search_decks.py "ログラス" --summary

# 言語フィルタ（デフォルト: ja、全言語指定は --lang all）
uv run python scripts/speakerdeck/search_decks.py "Kubernetes" --lang ja --summary

# 取得件数制限（デフォルト: 20）
uv run python scripts/speakerdeck/search_decks.py "会社説明資料" -n 5 --summary

# スライド文字起こし（fetch_deck.py）を一括連携取得
uv run python scripts/speakerdeck/search_decks.py "ログラス" -n 3 --fetch-decks --summary
```

### 2. 単体デッキ文字起こし・取得 (`scripts/speakerdeck/fetch_deck.py`)

```powershell
# 基本実行（Markdown・JSONを生成し、stdoutには生成ファイルパスのみ出力）
uv run python scripts/speakerdeck/fetch_deck.py "https://speakerdeck.com/loglass2019/whats-loglass"

# 人間向けサマリ表示（タイトル、スライド数、文字起こしサマリ等をコンソールに表示）
uv run python scripts/speakerdeck/fetch_deck.py "https://speakerdeck.com/loglass2019/whats-loglass" --summary

# PDF原本もダウンロード保存
uv run python scripts/speakerdeck/fetch_deck.py "https://speakerdeck.com/loglass2019/whats-loglass" --download-pdf

# 全スライドの画像（JPEG）もローカルにダウンロード保存
uv run python scripts/speakerdeck/fetch_deck.py "https://speakerdeck.com/loglass2019/whats-loglass" --download-images

# 特定の会社フォルダ（vault/tracks/domestic/companies/loglass/ 等）に紐付けて出力
uv run python scripts/speakerdeck/fetch_deck.py "https://speakerdeck.com/loglass2019/whats-loglass" --company-key loglass --summary

# 企業フォルダの materials/ に要約を作り、index.md の links に登録（add_material.py と同じ処理）
uv run python scripts/speakerdeck/fetch_deck.py "https://speakerdeck.com/loglass2019/whats-loglass" --company-key loglass --save-to-vault
```

`--save-to-vault` で作る material は `MaterialDoc` のフロントマター（`source_url`・`fetched_at`・`raw_data`＝このデッキの保存ディレクトリ・`raw_fetched_at`＝`deck.json` の取得日）付きで、本文には元URL・取得日・保存先を書かない。既存の material は `--force` が無ければ上書きしない。生データの取り直しは `scripts/vault/add_material.py --refresh`（[docs/vault/materials.md](../vault/materials.md)）。

## 出力ファイル構成

### 検索結果 (`data/speakerdeck/searches/`)

- `{YYYYMMDD_HHMMSS}_{query}.json`: 検索クエリ、言語、件数、各スライドのメタデータJSON
- `{YYYYMMDD_HHMMSS}_{query}.md`: フロントマター付きの検索結果一覧Markdownテーブル

### 単体スライド文字起こし (`data/speakerdeck/{username}/{deck_slug}/`)

`data/speakerdeck/{username}/{deck_slug}/`（`--company-key` 指定時は `data/speakerdeck/{company_key}/{deck_slug}/`、`-o` 指定時はそのディレクトリ）配下に以下のファイルが生成されます:

- `transcript.md`: スライドごとの見出し、画像埋め込み、抽出テキスト、発表者ノートを含むMarkdown
- `deck.json`: スライド番号、画像URL、テキスト、ノート、PDFダウンロードURL、取得日時 `fetched_at` 等の構造化メタデータJSON。vault の material から使われている場合は `materials`（material のリポジトリルート相対パスのリスト）を持ち、`--force` で取り直しても引き継ぐ
- `{filename}.pdf`: `--download-pdf` 指定時にダウンロードされた原本PDF（ダウンロード許可時のみ）
- `images/slide_{n}.jpg`: `--download-images` 指定時にダウンロードされた各スライド画像

## 関連ドキュメント

- [site_structure.md](site_structure.md): Speaker Deck の URL 構造・ページ構造・抽出仕様
