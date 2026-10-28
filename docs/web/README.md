# Web 調査（Tavily）

媒体スクリプトの対象外の一般 Web（公的機関の一次情報、ニュース、サービス比較、裏取り）を、[Tavily](https://tavily.com/) の API で検索・本文抽出する CLI。ブラウザ・ログインは使わない。

| スクリプト | 役割 | 保存先 |
| --- | --- | --- |
| [`scripts/web/search.py`](../../scripts/web/search.py) | キーワードから検索し、各結果の関連抜粋を保存 | `data/web/searches/{YYYYMMDD_HHMMSS}_{slug}/` |
| [`scripts/web/extract.py`](../../scripts/web/extract.py) | 既知の URL（複数可）の本文を Markdown で保存 | `data/web/extracts/{YYYYMMDD_HHMMSS}_{slug}/` |
| [`scripts/web/tavily_client.py`](../../scripts/web/tavily_client.py) | API キー解決・Tavily 呼び出し・保存の共通部 | — |

オプションは各スクリプトの `--help` が正。ここには転記しない。

## セットアップ

`TAVILY_API_KEY` をリポジトリ直下の `.env` に書く（書式は [`.env.example`](../../.env.example)）。環境変数が既にあればそちらが優先される。

## 判断フロー

```text
1. 対象 URL が分かっているか?
   Yes -> extract.py <url> [url ...]
   No  -> search.py "<query>"

2. search の抜粋で足りるか?
   足りる -> そのまま使う
   全文が要る -> 結果ファイルの `URL:` 行を extract.py に渡す
```

- サイト全体の一覧・クロール・AI 調査レポートは無い。必要なページだけ search → extract で足す。
- 企業・リクルーターの判断材料として残すなら、`data/web/` を vault から直接参照せず [`scripts/vault/add_material.py`](../../scripts/vault/add_material.py) で `materials/` に要約を作る（[materials.md](../vault/materials.md)）。
- ログインが要るページ・JS で描画されるページの画面調査は [sharing-browser-with-user](../../.agents/skills/sharing-browser-with-user/SKILL.md) を使う。

## クエリとドメイン

- クエリは日本語でよい。製品名・機能名・正式文書名は英語の方が強いことがある。弱ければ英語または日英混在で再実行する。
- `--include-domain` は優先・許可の強い絞り込みで、完全一致の隔離フィルタではない。広い host（`homeaffairs.gov.au`）より狭い host（`immi.homeaffairs.gov.au`）を優先し、想定外の URL は結果を見て捨てる。`--exclude-domain` も繰り返し指定できる。
- `extract.py --query` は本文全体ではなく関連チャンクだけを返す。出力の `[...]` はチャンク境界で、抽出失敗ではない。**全文が欲しいときは `--query` を付けない。**

## 出力と読み方

stdout は `index.md` のパスだけ（[scripts-entrypoint.md](../../.agents/rules/scripts-entrypoint.md)）。

1. `index.md` を読む。フロントマターに `kind` / `query` / `urls` / `fetched_at`、本文に各結果へのリンクと文字数がある。
2. タイトルと文字数から読むファイル（`0001.md` …）を選び、必要なものだけ読む。
3. 各結果ファイルの先頭付近に `URL:`、search には `Score:` もある。深掘りはその URL を extract.py に渡す。

同じクエリ・URL を再実行しても上書きせず、新しいフォルダが増える（同じ秒なら末尾に `-2` …）。フォルダ単位で保持期間（60 日）を過ぎると消える（[`data_retention.py`](../../scripts/common/data_retention.py)）。

| 終了コード | 意味 |
| --- | --- |
| 0 | 成功 |
| 1 | エラー、または結果 0 件（stderr に `No results.`、フォルダは作らない） |
| 2 | `TAVILY_API_KEY` 未設定（ネットワークは叩かない） |

## 実装していないもの

- Tavily の `map` / `crawl` / `research`、`--topic`（news 等）、検索時の `include_answer` / `include_raw_content`。就活調査では「search で候補を出し、必要なページだけ extract」で足り、クロールや AI 要約はコンテキストと API クレジットの消費が大きいため。必要になったら `tavily_client.py` に足してからこの文書に書く。
- 旧 `web-lookup` スキル（スキル同梱 CLI）の `available` サブコマンドと `WEB_LOOKUP_OUTPUT_DIR`。前者はスキル読み込み時の動的判定用だったので終了コード 2 に、後者は保存先を `data/web/` に固定したため廃止した。
