# Speaker Deck サイト構造・仕様書

## 1. サイト概要

Speaker Deck はスライド資料の共有プラットフォーム。
多くのIT企業が採用ピッチ資料（会社説明資料）やテックカンファレンスの登壇資料を公開している。

- ベースURL: `https://speakerdeck.com`
- 認証要件: 不要（公開スライドは認証・ログインなしで全情報取得可能）
- レンダリング方式: サーバーサイドレンダリング（SSR）
  - 通常ページおよび埋め込みプレイヤー（`https://speakerdeck.com/player/{presentation_id}`）のHTML内に、全スライドのテキスト・画像URL・メタデータが含まれる。
  - Playwright等のブラウザ自動化は不要で、HTTP GETリクエストとBeautifulSoupによるパースで高速・軽量に取得可能。

---

## 2. URL体系

| 種類 | URL形式 | 用途・説明 |
| --- | --- | --- |
| 通常デッキページ | `https://speakerdeck.com/{username}/{deck_slug}` | スライド閲覧、デッキタイトル、投稿者、説明、PDFダウンロードリンク |
| 検索ページ | `https://speakerdeck.com/search?q={query}&lang={lang}&page={n}` | キーワード検索、言語絞り込み、スライド一覧表示、ページネーション |
| oEmbed API | `https://speakerdeck.com/oembed.json?url={encoded_url}` | 埋め込みプレイヤーHTML（iframe）情報を含むJSON |
| 埋め込みプレイヤー | `https://speakerdeck.com/player/{presentation_id}` | 全スライドの画像URL、プレビュー画像URL、抽出済みテキスト、ノートを含むSSRページ |
| スライド画像 | `https://files.speakerdeck.com/presentations/{id}/slide_{n}.jpg?...` | 各スライドの高解像度画像 |
| スライドプレビュー | `https://files.speakerdeck.com/presentations/{id}/preview_slide_{n}.jpg?...` | 各スライドのプレビュー画像 |
| PDFダウンロード | `https://files.speakerdeck.com/presentations/{id}/{filename}.pdf` | 原本PDF（投稿者がダウンロードを許可している場合のみ） |

---

## 3. DOM構造と主要セレクタ

### 3.1 通常デッキページ (`https://speakerdeck.com/{username}/{deck_slug}`)

| 要素 / 項目 | セレクタ / 属性 | 備考 |
| --- | --- | --- |
| プレゼンテーションID | `div.speakerdeck-embed[data-id]` | プレイヤー読み込み用のUUID |
| スライドタイトル | `h1` または `meta[property="og:title"]` | タイトル |
| 発表者 / 投稿者 | `a.speakerdeck-author` または URLパス `{username}` | ユーザー名・組織名 |
| 説明文 | `div.description` または `meta[property="og:description"]` | 概要文 |
| 公開日時 | `time[datetime]` または `span.published-at` | 公開日 |
| PDFダウンロードリンク | `a[title="Download PDF"]` または `a[href$=".pdf"]` | 存在しない場合あり（ダウンロード禁止設定） |

### 3.2 埋め込みプレイヤー (`https://speakerdeck.com/player/{presentation_id}`)

| 要素 / 項目 | セレクタ / 属性 | 備考 |
| --- | --- | --- |
| スライド要素一覧 | `div.js-sd-slide[data-url]` | プレゼンター枠（`sd-player-presenter-*`）を除外した実スライド要素 |
| スライド番号 | `h2.sd-player-slides--heading` または要素インデックス | 例: `Slide 1` |
| スライド画像URL | `data-url` 属性 | フルサイズ画像URL |
| プレビュー画像URL | `data-preview-url` 属性 | サムネイル画像URL |
| スライドノート | `data-slide-note` 属性 | 登壇者ノート（設定されている場合） |
| スライド内テキスト | `div.sd-player-slides--text` | 抽出済みテキスト全文（末尾に改ページ文字 `\x0c` を含む） |

### 3.3 検索結果ページ (`https://speakerdeck.com/search?q={query}&lang={lang}&page={n}`)

| 要素 / 項目 | セレクタ / 属性 | 備考 |
| --- | --- | --- |
| スライドカード一覧 | `div.card.deck-preview` | `{"card", "deck-preview"}.issubset(...)` で取得（ハイフン付き内部要素の誤マッチ防止） |
| プレゼンテーションID | `data-id` 属性 | プレイヤー・画像特定用ID |
| スライド枚数 | `data-slide-count` 属性 | スライド総数（int変換） |
| カバー画像URL | `data-cover-image` 属性 | 1枚目のプレビュー画像URL |
| デッキURL | `a.deck-preview-link` の `href` | 相対パスのため `https://speakerdeck.com` と結合 |
| スライドタイトル | `a.deck-preview-link` の `title` または `.deck-title` | タイトル |
| 発表者 / ユーザー名 | `.deck-preview-meta a[href^="/"]` | URLパスからユーザー名、`aria-label` / `img[alt]` / テキストから表示名 |
| スター数 | `svg.icon-star` の親要素テキスト | 数値を抽出（0含む） |
| 閲覧数 | `span[title$="views"]` の `title` 属性またはテキスト | `title="5,959 views"` から正確な数値、テキストから `6k` などの短縮表記 |
| ページネーション | `nav.pagy-bootstrap-nav` | `li.page-item.next` が存在し `disabled` クラスでなく `a` リンクを持つ場合に次ページあり |

---

## 4. テキスト抽出と整形ルール

1. **改ページ記号の除去**:
   - `sd-player-slides--text` の末尾には改ページ制御文字 `\x0c`（`\f`）が含まれるため、除去する。
2. **改行・空白の正規化**:
   - 連続する空行を1行に集約する。
   - 前後の不要な空白文字を除去する。
3. **空スライドの扱い**:
   - 表紙・写真のみのスライドなどでテキストが抽出されていない場合、エラーとせず空文字列または `*（スライドテキストなし）*` として扱う。
