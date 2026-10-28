# using-job-hunt-scripts スキルについて

人間のメンテナ向け。AI が実行時に読むのは [SKILL.md](SKILL.md) で、このファイルは読まない。

## 目的

`scripts/` の CLI が 80 本を超え、常時読み込みの `goal.md` にスクリプトを列挙するのをやめた（カテゴリ概要だけ残す）。代わりに「何をしたいときに、どれをどの順で使うか」をこのスキルに置き、使う場面でだけ読まれるようにした。

## 正本の分担（書き写さない）

| 情報 | 正本 |
| --- | --- |
| スクリプトの一覧・1 行説明 | 各スクリプトの docstring 1 行目 → 生成物 [docs/scripts/catalog.md](../../../docs/scripts/catalog.md) |
| オプション・使用例・前後に使うスクリプト | 各スクリプトの `--help`（`tests/test_script_help.py` で担保） |
| 出力・終了コード・フラグの規約 | [scripts-entrypoint.md](../../rules/scripts-entrypoint.md) |
| サイト構造・詳しい手順 | `docs/{site}/` |
| 場面 → スクリプトの選び方と順序 | このスキル |
| 企業相談・メール・日程・雑務の手順 | `consult-company-job` / `read-job-mail` / `schedule-interview` / `sweep-chores` |

SKILL.md にオプションの説明や一覧表を足したくなったら、まず `--help` か catalog に足せないかを考える。

## このスキルを更新するタイミング

- 新しい場面を作るスクリプトを足したとき（例: 新しい情報源、新しい種類の取得）→ 該当する場面の節に 1 行足す。既存の場面に同じ役割の媒体が増えただけ（`{site}/search_jobs.py` 等の命名に乗っている）なら直さなくてよい。
- スクリプトを改名・非推奨化したとき → 本文に名前を書いていれば直す（`rg "<旧名>" .agents/skills/using-job-hunt-scripts`）。
- 終了コードや認証ハンドオフの仕組みが変わったとき → 「共通の使い方」の表。
- 場面が増えて SKILL.md が長くなったら（目安 200 行）、場面ごとに `references/{scene}.md` に分け、SKILL.md は共通の使い方と目次に留める。
