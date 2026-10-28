# 外部資料の流れ（links → materials → data）

企業・リクルーターを理解するために参照した外部情報は、次の一方向の流れで置く。各段から次の段を辿れる。

| 段 | 置き場所 | 役割 | 日付の正本 |
| --- | --- | --- | --- |
| 入口 | `index.md` のフロントマター `links` | 参照した URL の一覧 | material が無い link は `links[].fetched_at` |
| 永続する要約 | `materials/{slug}.md`（`MaterialDoc`） | 判断に使う要約・文字起こし | material の `fetched_at`（要約を書いた・見直した日） |
| 使い捨ての生データ | `data/` の取得単位（`deck.json`、note 記事 Markdown 等） | 要約の元。消えても material で判断できる前提 | 生データ側の `fetched_at`（material には `raw_fetched_at` として写す） |

- material がある link には `fetched_at` を書かない（併記は `validate.py` が警告する）。
- フロントマターのキーと型は [schema.md](schema.md) の `MaterialDoc` / `ReferenceLink` が正。

## 相互参照

- material → 生データ: `raw_data`（`data/` で始まるリポジトリルート相対パスのリスト。ディレクトリは末尾 `/`）
- 生データ → material: 生データファイルの `materials` キー（JSON は同名キー、Markdown はフロントマター。material のリポジトリルート相対パスのリスト）。読み書きは `scripts/common/storage.py` の `read_material_refs` / `add_material_refs`。取得スクリプトが `--force` で上書き保存しても引き継ぐ

## 作成・更新（`scripts/vault/add_material.py`）

```powershell
uv run python scripts/vault/add_material.py <URL> -c <company-key> -s     # 企業の material を作り links に登録
uv run python scripts/vault/add_material.py <URL> -r <recruiter-key> -s   # リクルーターの material
uv run python scripts/vault/add_material.py <URL> -c <company-key> --no-material   # links だけ登録（link に fetched_at）
uv run python scripts/vault/add_material.py --refresh <material のパス>             # 生データを取り直す
uv run python scripts/vault/add_material.py --refresh <slug> -c <company-key>
```

| URL | 生データ（`data/`） | material の本文 |
| --- | --- | --- |
| Speaker Deck | `data/speakerdeck/{company_key or username}/{deck_slug}/`（`deck.json` に逆参照） | スライドの文字起こし |
| note | `data/note/companies/{company_key}/{key}.md` 等（フロントマターに逆参照） | 記事本文 |
| その他の Web ページ | 保存しない | ページから抜き出した本文 |

- 新規作成時は `fetched_at`（今日）・`source_url`・`raw_data`・`raw_fetched_at` を書く。既存の material は `--force` が無ければ上書きしない（AI が書き直した要約を潰さないため）。
- `--refresh` は material の `source_url` から生データを取り直し（既存の `raw_data` と同じ場所へ）、`raw_data`・`raw_fetched_at` を更新する。**要約本文と `fetched_at` は変えない**。stdout に material と保存した生データのパスを返すので、AI が生データと見比べて要約を直し、そのとき `fetched_at` を今日にする。生データを保存する経路が無い資料（Speaker Deck・note 以外）は対象外で、元ページを見て直接直す。
- Speaker Deck は `scripts/speakerdeck/fetch_deck.py --save-to-vault` でも同じ material を作れる（[docs/speakerdeck/README.md](../speakerdeck/README.md)）。

## 生データの保持期間（`scripts/common/data_retention.py`）

`data/` の生データは保持期間（既定 60 日）を過ぎたら削除する。material の要約で判断できる前提なので、古い material を見直すときは `--refresh` で生データも取り直す。保持ポリシー表（`RULES`）・保護対象・取得日の判定はコードが正で、ここでは概要だけを書く。

- **対象**: ポリシー表に載ったディレクトリだけ。`*/jobs/`・`openwork/reviews/`・`gmail/threads/`・`note/articles/`・`note/companies/`・Speaker Deck のスライドディレクトリ、および `searches/`・`messages/`・`likes/`・`favorites/`・`resume/`・`profile/`・`gcal/` 等の**ファイル名に日付がある**スナップショット。
- **削除単位**: 同じ stem の `.md` / `.json` の組、Speaker Deck はスライドのディレクトリごと。
- **取得日**: data 側の `fetched_at` → ファイル名の日付 → mtime の順に判定し、単位内で最も新しい日を使う。
- **消さないもの**: `backups/` 配下、`latest*`・`backup_*`、ドットファイル（`.gitkeep`・`.prune_state.json` 等）、`exports/`、`vault_index.sqlite`、ファイル名に日付の無い固定名の現在値（`messages_all.json`・`profile.json` 等）、**vault 本文から参照されている取得単位**。material の `raw_data` からの参照では保護しない（消えたら取り直す）。

```powershell
uv run python scripts/vault/prune_data.py -s              # 削除候補と、vault から参照されていて残すもの（dry-run）
uv run python scripts/vault/prune_data.py --days 30 -s    # 保持日数を変えて試す
uv run python scripts/vault/prune_data.py --apply -s      # 削除する
```

## 古くなった資料・生データ参照の検知（`scripts/vault/find_chores.py`）

条件の詳細は [chores.md](chores.md) の検出器表が正。片付け方は `sweep-chores` スキル。

| 検出器 | 意味 | 片付け方 |
| --- | --- | --- |
| `material-stale` | 進行中の企業・`active` のリクルーターの material の `fetched_at` が 60 日（`--material-days`）以上前 | `--refresh` で取り直して要約を見直し、`fetched_at` を今日にする |
| `material-raw-missing` | 上の条件に加えて `raw_data` が消えている（`material-stale` の代わりに出る） | 同上（要約が新しいうちに生データが消えるのは正常なので出さない） |
| `data-ref` | vault 本文が保持期間で消える `data/` のパスを直接参照している | 判断に使った内容を本文か material に要約し、`data/` への参照を外す |

Web UI の企業・リクルーター詳細は、material が紐付いた link に資料側の `fetched_at`（要約の更新日）を、資料タブに `raw_fetched_at`（生データの取得日）と元資料のリンクを表示する。
