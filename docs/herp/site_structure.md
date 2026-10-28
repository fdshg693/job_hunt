# HERP Careers サイト構造・技術リファレンス

本ドキュメントは、AIエージェントおよび開発者が HERP Careers（[herp.careers](https://herp.careers)）の求人データを取得・パースする際のサイト仕様、URL体系、HTML DOM構造、メタデータ構造をまとめた技術リファレンスです。

---

## 1. サイト基本情報 & 通信仕様

| 項目 | 内容 |
|---|---|
| **メインドメイン** | `https://herp.careers/` |
| **認証要否** | 完全不要（全求人ページが公開・静的レンダリング） |
| **レンダリング方式** | サーバーサイドレンダリング（SSR）。ブラウザ（Playwright）不要で `urllib` / `curl` で全文取得可能 |
| **ボット対策 (WAF)** | 通常の Chrome User-Agent を設定することでブロックなく取得可能 |
| **文字コード** | UTF-8 |
| **募集終了時の挙動** | HTTP 404 を返却（HTML本文にも「お探しの求人が見つかりませんでした」と表示） |

---

## 2. URL体系と正規化仕様

HERP には自社採用ポータル向けの新形式 URL と、ポータル検索向けの旧形式 URL の 2 系統が存在します。

| 形式 | パス形式 | レスポンス容量 | 特徴 |
|---|---|---|---|
| **新形式 (推奨)** | `https://herp.careers/v1/{company}/{jobId}` | 約 60 KB | 当該企業の求人内容のみが含まれるクリーンな構造。広告や推薦ノイズなし |
| **旧形式** | `https://herp.careers/careers/companies/{company}/jobs/{jobId}` | 約 240 KB | 他社求人の推薦やポータル枠が含まれる |

### 検証判明事項と正規化方針
旧形式の求人 URL であっても、`{company}` と `{jobId}` を抽出し新形式 URL（`https://herp.careers/v1/{company}/{jobId}`）にリクエストを送ると、**全く同一の求人詳細が 200 OK で返却されます**。

そのため、スクリプトでは入力された URL や ID をすべて新形式 URL に正規化してフェッチします。これにより、パーサーは新形式のクリーンな HTML 1 系統のみに集中できます。

---

## 3. HTML DOM 構造（新形式 `v1/{company}/{jobId}`）

### 3.1 ヘッダーとタイトル構造

HERP では職種名とキャッチコピーで `h1` が 2 箇所に出現する場合があります。

```html
<div class="requisition-header">
  <!-- 職種名・ポジション名（JSON-LDのtitleと一致。これを title とする） -->
  <h1 class="requisition-header__name">ソフトウェアエンジニア</h1>

  <!-- 企業が任意で設定するキャッチコピー（存在しない場合もある。これを catchcopy とする） -->
  <h1 class="requisition-title">【CTO直下】最先端技術で社会を革新するバックエンド基盤開発</h1>
</div>
```

### 3.2 本文セクション構造 (`<section class="with-heading">`)

求人の本文は `<section class="with-heading">` の繰り返しで構成されています。

```html
<section class="with-heading">
  <h2>仕事概要</h2>
  <div class="with-heading__content">
    <div class="multiline-text markdown">
      <p>自社プロダクトの設計および開発を担当します。</p>
      <ul>
        <li>Pythonでの開発</li>
        <li>AWSの利用</li>
      </ul>
    </div>
  </div>
</section>
```

### 3.3 テーブル構造（応募概要・企業情報）

`応募概要` と `企業情報` は `<table class="kv-table">` または `<table>` で構造化されています。

```html
<table class="kv-table">
  <tbody>
    <tr>
      <th>給与</th>
      <td>年収800万円～1400万円（スキル・経験に応じて決定）</td>
    </tr>
    <tr>
      <th>勤務地</th>
      <td>東京都千代田区1-1-1</td>
    </tr>
    <tr>
      <th>勤務体系</th>
      <td>フルリモートワーク可能（コアタイムなしのフルフレックス制）</td>
    </tr>
    <tr>
      <th>雇用形態</th>
      <td>正社員</td>
    </tr>
    <tr>
      <th>企業名</th>
      <td>株式会社テストテクノロジーズ</td>
    </tr>
    <tr>
      <th>企業サイトURL</th>
      <td><a href="https://example.com" target="_blank">https://example.com</a></td>
    </tr>
  </tbody>
</table>
```

---

## 4. JSON-LD (`application/ld+json`) 仕様

ページ内の `<script type="application/ld+json">` に Google しごと検索向けの構造化データ（Schema.org `JobPosting`）が含まれています。

```json
{
  "@context": "http://schema.org",
  "@type": "JobPosting",
  "title": "ソフトウェアエンジニア",
  "datePosted": "2026-01-15",
  "hiringOrganization": {
    "@type": "Organization",
    "name": "株式会社テストテクノロジーズ"
  },
  "jobLocation": {
    "@type": "Place",
    "address": "東京都千代田区1-1-1"
  },
  "description": "... (※10,000文字で切断される)"
}
```

> [!WARNING]
> JSON-LD の `description` は HERP のシステム仕様上、10,000 文字で末尾が切断されます。そのため、求人本文は HTML の `<section class="with-heading">` から抽出し、JSON-LD は `datePosted` などの補助情報のみに利用します。

---

## 5. 見出しマッピング規則

HERP の各企業が設定する見出しは多様ですが、以下のルールでプロジェクト共通仕様（`.agents/rules/job-data-format.md`）の標準見出しにマッピングします。

| HERP 内の見出し (`h2`) | プロジェクト標準見出し |
|---|---|
| `仕事概要`, `募集概要`, `仕事内容`, `業務内容` | `## 概要・仕事内容` |
| `必須スキル`, `必須要件`, `求めるスキル` | `## 必須要件 (Must)` |
| `歓迎スキル`, `歓迎要件`, `尚可` | `## 歓迎要件 (Desired)` |
| `求める人物像`, `求める人物`, `人物像` | `## 求める人物像` |
| `応募概要`, `募集要項`, `就業条件`, `勤務条件` | `## 勤務地・就業条件・福利厚生` |
| `企業情報`, `会社情報`, `会社概要` | `## 採用企業情報` |
| 上記以外（「開発環境」「チーム構成」「選考フロー」等） | `## {元の h2 テキスト}`（原文を維持） |
