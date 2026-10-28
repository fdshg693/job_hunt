# HERP Careers 自動化スクリプト利用ガイド

本ディレクトリでは、HERP Careers（[herp.careers](https://herp.careers)）の求人票を高速に取得・パースし、ローカルに構造化Markdownとして保存するためのスクリプト群の使い方と仕様をまとめています。

> [!TIP]
> サイト構造・新旧URL形式・DOMセレクタ・JSON-LD仕様の詳細は [site_structure.md](site_structure.md) を参照してください。

---

## 目次

1. [概要とできること](#1-概要とできること)
2. [スクリプト構成](#2-スクリプト構成)
3. [前提条件と認証仕様](#3-前提条件と認証仕様)
4. [詳細な使い方](#4-詳細な使い方)
   - [4.1 基本実行](#41-基本実行)
   - [4.2 サマリ表示（--summary）](#42-サマリ表示--summary)
   - [4.3 強制再取得・上書き（--force）](#43-強制再取得上書き--force)
   - [4.4 JSONモード（--json）](#44-jsonモード--json)
5. [下流システムとの連携](#5-下流システムとの連携)
   - [5.1 ローカル求人横断検索](#51-ローカル求人横断検索)
   - [5.2 SQLite 全文検索索引](#52-sqlite-全文検索索引)
6. [データ格納仕様](#6-データ格納仕様)

---

## 1. 概要とできること

HERP Careers は国内の多くのスタートアップ・メガベンチャー・SaaS企業（ナウキャスト、Finatext、LayerX 等）で採用管理システム（ATS）および求人公開基盤として利用されています。エージェントやリクルーターからのスカウトメッセージにも直リンクで届くケースが多く存在します。

本モジュール（`scripts/herp/fetch_job.py`）により、以下の機能を提供します:

- **超高速な静的フェッチ**: 認証不要かつ完全サーバーサイドレンダリングであるため、Playwright ブラウザを起動せず標準の `urllib.request`（HTTP GET）のみで約 0.5 秒で取得完了。
- **URL形式の柔軟な受容と正規化**: 新形式（`/v1/{company}/{jobId}`）、旧形式（`/careers/companies/{company}/jobs/{jobId}`）、ID直指定（`{company}_{jobId}`）のいずれが渡されても、内部で新形式 URL へ自動正規化。
- **構造化データと本文Markdownの高品質抽出**:
  - タイトル・キャッチコピーの分離抽出
  - 応募概要テーブルからの年収範囲（円単位数値化）、勤務地、リモート勤務体系の抽出
  - 企業情報テーブルからの掲載企業名、コーポレートURLの抽出
  - 仕事概要、必須要件、歓迎要件、求める人物像、就業条件、企業情報への統一見出し変換
- **プロジェクト共通求人フォーマット対応**: フロントマター付き Markdown として `data/herp/jobs/{company}_{jobId}.md` に保存され、ローカル検索（`scripts/common/search_local_jobs.py`）や SQLite 索引（`data/vault_index.sqlite`）に即座に反映。

---

## 2. スクリプト構成

| スクリプト | 種別 | 主な役割 |
|---|---|---|
| [`scripts/herp/fetch_job.py`](../../scripts/herp/fetch_job.py) | Python CLI | 単体求人詳細（URL/ID）の取得・Markdown構造化保存・CLIパイプライン |

---

## 3. 前提条件と認証仕様

- **ブラウザ・ログイン不要**: HERP Careers の求人詳細ページは完全公開されており、ログインセッションやクッキーは不要です。
- **レート制限への配慮**: スカウトや相談の都度 1 件ずつ取得する用途を想定しており、通常の Chrome User-Agent ヘッダーを付与してリクエストを行います。
- **募集終了・無効URLの検知**: 募集が終了した求人や存在しない求人に対しては、HERP サーバーから HTTP 404 が返されます。スクリプト側で 404 を検知し、「求人が見つかりませんでした（掲載終了またはURL誤りの可能性があります）」という分かりやすいエラーを出力して終了します。

---

## 4. 詳細な使い方

### 4.1 基本実行

URL または ID を指定して実行します。スクリプト出力規約に従い、成功時は保存されたファイルの相対パスのみを 1 行標準出力に出力します。

```bash
# 新形式 URL
uv run python scripts/herp/fetch_job.py https://herp.careers/v1/finatext/p9U6eu0-JgVR

# 旧形式 URL
uv run python scripts/herp/fetch_job.py https://herp.careers/careers/companies/finatext/jobs/p9U6eu0-JgVR

# ID 直指定
uv run python scripts/herp/fetch_job.py finatext_p9U6eu0-JgVR
```

出力例:
```text
data\herp\jobs\finatext_p9U6eu0-JgVR.md
```

### 4.2 サマリ表示（`--summary`）

人間がターミナルで確認する際や、抽出結果（企業名・タイトル・年収・勤務地・スキル等）をコンソールで見たい場合に指定します。

```bash
uv run python scripts/herp/fetch_job.py https://herp.careers/v1/finatext/p9U6eu0-JgVR --summary
```

### 4.3 強制再取得・上書き（`--force`）

既存ファイルが存在する場合、デフォルトでは取得をスキップして既存パスを出力します。求人情報が更新された場合など、再フェッチしたい場合は `--force` を付与します。

```bash
uv run python scripts/herp/fetch_job.py finatext_p9U6eu0-JgVR --force --summary
```

### 4.4 JSONモード（`--json`）

プログラムや外部ツールからパース結果を構造化データとして受け取る場合に指定します。

```bash
uv run python scripts/herp/fetch_job.py finatext_p9U6eu0-JgVR --json
```

---

## 5. 下流システムとの連携

### 5.1 ローカル求人横断検索

保存された求人は、Bizreach・Findy・Forkwell・Green・LinkedIn・OpenWork の求人と同様にローカル求人検索で即座にヒットします。

```bash
# 「ナウキャスト」または「データ」を含む求人をローカル検索
uv run python scripts/common/search_local_jobs.py -q "ナウキャスト"
uv run python scripts/common/search_local_jobs.py -q "データ" --source herp
```

### 5.2 SQLite 全文検索索引

インデックスビルダーを実行することで、`data/vault_index.sqlite` の `jobs` テーブルおよび FTS5 日本語全文検索（trigram）に自動登録されます。

```bash
uv run python scripts/vault/build_index.py
```

---

## 6. データ格納仕様

- **保存先ディレクトリ**: `data/herp/jobs/`
- **ファイル名規則**: `{company}_{jobId}.md`（例: `finatext_p9U6eu0-JgVR.md`）
- **文字コード**: UTF-8
- **フォーマット規約**: `.agents/rules/job-data-format.md` に完全準拠
