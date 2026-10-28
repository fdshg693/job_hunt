# note.com サイト構造・API仕様書

## 1. サイト概要

note.com はクリエイターが文章や画像、音声などを投稿できるメディアプラットフォーム。
多くのITエンジニア、採用担当者、CXOがテックブログ、転職体験談、入社エントリ、企業カルチャーなどを投稿している。

- ベースURL: `https://note.com`
- 認証要件: 不要（公開記事および全体検索は非ログインで完全取得可能）
- データ取得方式: 公開JSON API（`api/v3`）
  - 単一記事および検索結果は、サーバーの内部API（`GET /api/v3/notes/{key}`, `GET /api/v3/searches`）を直接呼び出すことで高速・高信頼に取得可能。
  - Playwright等のヘッドレスブラウザは不要。標準のHTTP GETリクエスト（一般的なブラウザの `User-Agent` 付与）で数ミリ秒〜数十ミリ秒でJSONを取得できる。

---

## 2. URL体系

| 種類 | URL形式 / エンドポイント | 用途・説明 |
| --- | --- | --- |
| 記事Webページ | `https://note.com/{urlname}/n/{note_key}` | 通常の記事閲覧URL。`{note_key}` は `n` で始まる13桁前後の英数字。 |
| 独自ドメイン記事 | `https://{custom_domain}/n/{note_key}` | 法人等で独自ドメイン運用されているnote記事URL。 |
| 検索Webページ | `https://note.com/search?q={query}&context=note&mode=search` | note全体のキーワード検索ページ。 |
| 単一記事API | `https://note.com/api/v3/notes/{note_key}` | 単一記事のタイトル、本文（HTML）、著者情報、スキ数、タグ等の完全なメタデータを返すJSON API。 |
| 検索API | `https://note.com/api/v3/searches?q={query}&context=note&mode=search&size={size}&note_cursor={cursor}` | キーワード検索結果の記事一覧を返すJSON API。 |
| アイキャッチ画像 | `https://assets.st-note.com/...` | 記事のサムネイル・アイキャッチ画像URL。 |

---

## 3. 公開API仕様

### 3.1 単一記事取得API

- **エンドポイント**: `GET https://note.com/api/v3/notes/{note_key}`
- **認証**: 不要
- **必須ヘッダー**:
  - `User-Agent`: `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36`

#### 主要レスポンスフィールド (`data`)

| フィールド名 | 型 | 説明・例 |
| --- | --- | --- |
| `key` | `string` | 記事の一意な識別キー（例: `"n24f8414083da"`） |
| `name` | `string` | 記事タイトル |
| `body` | `string` | 整形済み本文HTML。`<p>`, `<h2>`, `<figure>`, `<a>` 等を含む |
| `status` | `string` | 公開ステータス（通常 `"published"`） |
| `publish_at` | `string` | 公開日時（ISO 8601形式: `"2026-10-21T19:41:29.000+09:00"`） |
| `like_count` | `int` | スキ（いいね）数 |
| `comment_count` | `int` | コメント件数 |
| `price` | `int` | 記事価格（`0` は無料記事） |
| `can_read` | `bool` | 現在の閲覧者が全文を読めるか（無料記事は `true`） |
| `eyecatch` | `string` | アイキャッチ画像URL（未設定時は `null`） |
| `user.id` | `int` | 著者のユーザーID |
| `user.urlname` | `string` | 著者のURL識別名（アカウント名、例: `"narumiruna19"`） |
| `user.nickname` | `string` | 著者の表示名（例: `"渡辺 成美"`） |
| `user.user_profile_image_path` | `string` | 著者のアバター画像URL |
| `hashtag_notes` | `list[dict]` | ハッシュタグ一覧。各要素の `hashtag.name`（例: `"#新米"`） |

#### 有料・限定公開記事の挙動
- `price > 0` かつ `can_read == false` の場合、`body` には無料試し読み部分のHTMLのみが含まれる。
- メタデータとして `price`（金額）と `can_read: false` を記録し、有料記事であることを明示する。

---

### 3.2 検索API

- **エンドポイント**: `GET https://note.com/api/v3/searches`
- **クエリパラメータ**:

| パラメータ | 必須 | デフォルト | 説明 |
| --- | --- | --- | --- |
| `q` | 必須 | - | 検索キーワード（URLエンコード必須） |
| `context` | 必須 | `note` | 検索コンテキスト（`note` で記事を対象とする） |
| `mode` | 必須 | `search` | 検索モード（`search` 固定） |
| `size` | 任意 | `20` | 1回のリクエストで取得する件数（最大 `20`） |
| `note_cursor` | 任意 | なし | ページネーション用カーソル。2ページ目以降は前回レスポンスの `data.note_cursor` の値を指定する |

#### レスポンス構造 (`data`)

```json
{
  "data": {
    "note_cursor": 20,
    "notes": {
      "total_count": 10000,
      "is_last_page": null,
      "contents": [
        {
          "key": "n13efd16189c5",
          "name": "文系の事務職からIT転職、求人は本当に多いのか...",
          "publish_at": "2026-10-02T11:54:37.000+09:00",
          "like_count": 766,
          "price": 0,
          "eyecatch": "https://assets.st-note.com/...",
          "user": {
            "urlname": "bunkeiawssan",
            "nickname": "文系AWS系クラウドエンジニアさん"
          }
        }
      ]
    }
  }
}
```

#### ページネーション制御
1. 1ページ目は `note_cursor` を付けずにリクエストする。
2. 次ページを取得する場合は、レスポンスの `data.note_cursor` をパラメータに指定する。
3. `contents` が空リスト、または `data.note_cursor` が `null` になった時点で末尾に到達したと判定する。

---

## 4. 本文HTMLからMarkdownへの変換ルール

`body` に格納されているHTMLは整然とした構造を持っており、BeautifulSoup（`bs4`）を用いて以下のルールでMarkdown化する:

| HTML要素 | 変換ルール | 備考 |
| --- | --- | --- |
| `<h2>` | `## {text}\n\n` | 大見出し |
| `<h3>` | `### {text}\n\n` | 中見出し |
| `<p>` | `{text}\n\n` | 段落。内部の `<br>` は改行に置換 |
| `<ul>`, `<ol>` | 箇条書き / 番号付きリスト | `<li>` を `- {text}` / `1. {text}` に変換 |
| `<strong>`, `<b>` | `**{text}**` | 太字 |
| `<em>`, `<i>` | `*{text}*` | 斜体 |
| `<a>` | `[{text}]({href})` | ハイパーリンク |
| `<figure>` / `<img>` | `![{alt}]({src})\n\n*{caption}*\n\n` | 画像とキャプション |
| `<blockquote>` | `> {text}\n\n` | 引用ブロック |
| `<pre><code>` | ````{lang}\n{text}\n````\n\n | コードブロック |
| `<hr>` | `---\n\n` | 水平線 |
| `<table-of-contents>` | スキップ（無視） | note側で動的生成される目次要素は除外 |

---

## 5. 永続化フォーマットとファイル配置

### 5.1 単一記事の保存先
- 通常保存: `data/note/articles/{urlname}/{note_key}.md`
- 企業ログ紐付け時（`--company-key {key}` 指定）:
  `vault/tracks/{track}/companies/{key}/note_{note_key}.md` または `vault/tracks/{track}/companies/{key}/research/note_{note_key}.md`

### 5.2 記事Markdownのフロントマター仕様
```markdown
---
id: n24f8414083da
source: note
title: "土楽さんの土鍋で炊いた新米を食べたら、「おいしい」の感じ方が変わってきた。"
author: "渡辺 成美"
author_urlname: "narumiruna19"
url: "https://note.com/narumiruna19/n/n24f8414083da"
published_at: "2026-10-21T19:41:29.000+09:00"
fetched_at: "2026-10-24T00:40:00+09:00"
likes: 62
price: 0
can_read: true
tags:
  - "奈良"
  - "新米"
  - "土鍋"
eyecatch: "https://assets.st-note.com/production/uploads/..."
---

（ここにMarkdown変換された本文）
```

### 5.3 検索結果の保存先
- 保存先: `data/note/searches/{YYYYMMDD_HHMMSS}_{query_slug}.md`
- 形式: 検索条件、ヒット件数、上位記事一覧（タイトル、著者、スキ数、公開日、URL）を記載したMarkdownテーブル。
