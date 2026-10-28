---
# 前提: uv で依存導入済み（`uv sync`）。ブラウザを使う媒体スクリプトは playwright-cli と共通プロファイル `job-hunt`、Google 系は scripts/google/auth.py の初回認可、Web 調査はリポジトリ直下 .env の TAVILY_API_KEY が要る。
# 依存: 認証ハンドオフは sharing-browser-with-user。Gmail・カレンダー・vault 雑務の手順は read-job-mail / schedule-interview / sweep-chores、企業相談の全体手順は consult-company-job が持つ（このスキルからはそこへ振り分けるだけ）。
#       逆方向: consult-company-job / read-job-mail / schedule-interview / sweep-chores が requires_skills でこのスキルを参照する。
# 正本を書き写さない方針: スクリプト一覧は docs/scripts/catalog.md（生成物）、オプション・使用例は各スクリプトの --help、出力規約は .agents/rules/scripts-entrypoint.md。
#       ここは「場面 → どのスクリプトをどの順で使うか」だけを持つ。メンテナ向けは同階層の README.md。
name: using-job-hunt-scripts
description: このリポジトリの scripts/ の CLI（求人媒体・口コミ・スライド・note・Web 調査・vault 道具・プロフィール出力・定期実行）のうち、どれをどの順で使えばよいか迷ったとき、または求人検索・求人詳細の取得・企業調査・メッセージ収集・媒体プロフィール更新・vault の整備・応募書類の出力・定期実行ルーチンの確認や変更を始める前に使う。スクリプトの出力の読み方、認証切れ（終了コード 2）のときの扱いも含む。スクリプトそのものを新規作成・改修するときは使わない（understanding-repo-architecture と scripts-entrypoint ルール）。
meta:
  tag: [scripts, cli, job-search, company-research]
  requires_repo_tools: all
  requires_env: TAVILY_API_KEY (scripts/web のみ)
  dependencies: python, playwright
  requires_install: none
  requires_hooks: none
  requires_skills: sharing-browser-with-user, consult-company-job, read-job-mail, schedule-interview, sweep-chores
  status: beta
  version: 1.0.0
---

<!-- 自動生成ファイル: .agents/skills/using-job-hunt-scripts/SKILL.md から scripts/dev/sync_agents.py で生成。直接編集せず .agents/skills/using-job-hunt-scripts/SKILL.md を編集して再同期すること -->

# 就活スクリプトの使い分け

場面ごとに「どのスクリプトをどの順で使うか」だけを示す。全スクリプトの一覧は [docs/scripts/catalog.md](../../../docs/scripts/catalog.md)、オプション・使用例・関連スクリプトは各スクリプトの `--help` が正。

> [!CAUTION]
> 1. **オプションを推測しない**: 初めて使うスクリプトは `uv run python scripts/<dir>/<name>.py --help` を見てから実行する。使い方を知るためだけにソースや `docs/` を読まない（サイト構造を知りたいときだけ `docs/{site}/`）。
> 2. **媒体への書き込みは `--dry-run` から**: `manage_*` 系は更新前に必ず `--dry-run` で差分を見せ、ユーザーの承認を取ってから本実行する。
> 3. **スクリプトの結果だけで決めない**: 検索ヒット・`evaluate_messages.py` の区分・`find_chores.py` の候補は事前フィルタにすぎない（[goal.md](../../rules/goal.md) の「機械化の誤用防止」）。
> 4. **非推奨のスクリプトを使わない**: 一覧で「非推奨:」とある互換ラッパーは、書かれた代わりのスクリプトを使う。

## 共通の使い方

- **実行**: リポジトリ直下で `uv run python scripts/...`。
- **出力**: stdout は保存したファイルのパスだけ（1 行 1 パス）。そのパスを Read して中身を見る。`-s`（`--summary`）は人間向けの一覧で、会話に一覧を出すだけで足りるときに付ける。
- **キャッシュ**: `fetch_job.py` 等は保存済みなら取得せず既存パスを返す。取り直すときだけ `--force`。
- **`data/` は使い捨て**: 取得結果は保持期間（60 日）で消える。判断に使う資料は `scripts/vault/add_material.py` で企業・リクルーターの `materials/` に要約を残す（[docs/vault/materials.md](../../../docs/vault/materials.md)）。vault 本文から `data/` を直接参照しない。
- **終了コード**: `0` 成功、`1` エラー（Web 調査は 0 件も含む）、`2` 認証・設定の不足。`2` は直さずにやり直さない。

| `2` が出たスクリプト | 対応 |
| --- | --- |
| ブラウザを使う媒体スクリプト | stderr に出たログイン用コマンドを示し、ユーザーにログインしてもらう。Claude Code では [sharing-browser-with-user](../sharing-browser-with-user/SKILL.md) の手順で同じプロファイル（`job-hunt`）の可視ブラウザを開いてよい。ログイン後に同じコマンドを再実行 |
| `scripts/gmail/`・`scripts/gcal/` | ユーザーに外部ターミナルで `uv run python scripts/google/auth.py` を実行してもらう（エージェントは認可しない） |
| `scripts/web/` | `TAVILY_API_KEY` がリポジトリ直下の `.env` に無い。ユーザーに設定を頼む |

## 場面別の判断フロー

当てはまる場面を開く。複数に当てはまるなら上から順に進める。

### 求人を探す

1. 保存済みの求人から探す: `scripts/common/search_local_jobs.py`（全媒体の `data/*/jobs/` を横断）。
2. 足りなければ媒体でオンライン検索する: `scripts/{site}/search_jobs.py`（Findy は `search_online.py`）。詳細まで保存するかは `--help` の `--download` を見る。Findy のおすすめは `fetch_recommends.py`。
3. 気になった求人は次の「求人詳細を取る」で本文を読む。一覧のタイトル・年収・タグだけで評価しない。

### 求人詳細を取る（URL・ID が分かっている）

- URL のドメインが対応媒体（catalog の「求人媒体」節）なら、その媒体の `fetch_job.py`。HERP Careers（`herp.careers`）も `scripts/herp/fetch_job.py`。
- 対応媒体に無い採用ページは `scripts/web/extract.py <URL>`。ログインが要る・JS で描画されて取れないページは [sharing-browser-with-user](../sharing-browser-with-user/SKILL.md)。

### 企業を調べる

企業相談として調べるなら手順の全体は [consult-company-job](../consult-company-job/SKILL.md)。最初に必ず `scripts/common/check_company.py --track <track> -s <会社名>` で重複・除外を確かめる。そのうえで必要な深さまで:

| 知りたいこと | スクリプト（順） |
| --- | --- |
| 口コミ・残業・退職理由 | `scripts/openwork/fetch_reviews.py <会社名>`（同名・表記ゆれで迷うときは先に `resolve_company.py` で企業 ID を解決） |
| 会社紹介・採用ピッチ・登壇スライド | `scripts/speakerdeck/search_decks.py` → `fetch_deck.py`（文字起こし） |
| 社員・採用担当の記事 | `scripts/note/search_notes.py` → `fetch_article.py` |
| ニュース・IR・公式ブログなど上記以外 | `scripts/web/search.py` → 全文が要る結果だけ `scripts/web/extract.py`（[docs/web/README.md](../../../docs/web/README.md) の判断フロー） |
| 判断に使った資料を残す | `scripts/vault/add_material.py <URL> -c <company-key>`（リクルーターは `-r`） |

### メッセージ・スカウトを集める

- 媒体のメッセージ・スカウト: `scripts/{site}/navigate_messages.py`。
- 媒体ごとの追加の入口: Findy のいいね `navigate_likes.py`、Green の気になる `navigate_favorites.py`、ビズリーチのメッセージ添付求人 `fetch_message_jobs.py`、LinkedIn のつながり申請 `fetch_invitations.py`・スレッド 1 件 `fetch_single_thread.py`。
- LinkedIn の `evaluate_messages.py` は事前仕分けの参考区分だけ。返信・無視は本文を読んで判断する。
- Gmail に届いたメールは [read-job-mail](../read-job-mail/SKILL.md)、日程調整は [schedule-interview](../schedule-interview/SKILL.md)。
- 中身が企業・リクルーターの相談になったら [consult-company-job](../consult-company-job/SKILL.md) へ。

### 媒体プロフィールを更新する

1. 現状を取る: その媒体の `fetch_profile.py` / `fetch_resume.py`、または `manage_*.py` の `fetch`。
2. 正本は `vault/profile/`（英語媒体は `vault/profile/en/`、希望条件は track の `strategy.md`）。媒体側の値を正本にしない。英語版が古ければ先に `scripts/profile/sync_en.py -s` で確かめる。
3. `manage_*.py` を `--dry-run` で実行して差分を見せ、承認後に本実行する（自動バックアップが `data/{site}/profile/backups/` に残る）。`visibility: internal` の内容は送らない。

### vault を整える

- 記録を書いたら毎回: `scripts/vault/validate.py`（エラー 0 まで）→ `scripts/vault/build_pipeline.py --track <track>`。
- たまった更新漏れ: `scripts/vault/find_chores.py`。片付けは [sweep-chores](../sweep-chores/SKILL.md)。
- 終了した企業の圧縮: `scripts/vault/compact_closed.py`（手順は [company-log.md](../../rules/company-log.md) の見送り台帳）。
- 横断検索の索引の作り直し: `scripts/vault/build_index.py`。`data/` の古い生データ: `scripts/vault/prune_data.py`（既定は候補の一覧だけ。見せてから `--apply`）。

### 定期実行・今日のブリーフ

- 今日のブリーフを見る: `scripts/automation/run_routine.py last` が出すパスを読む（実行ログは同じ日付の `data/automation/runs/`）。
- ルーチン（ステップ・プロンプト・スケジュール）を変える: `vault/automation/routines.yaml` を直す → `run_routine.py validate` → `run <routine> --dry-run` → 必要なら `run <routine> --force`。スケジュールを変えたら `register --dry-run` で差分を見せ、承認後に `register`（OS の設定を変える）。
- 動いていない・ブリーフに警告が出る: `run_routine.py status`。書き方・権限・トラブルシュートは [docs/automation/README.md](../../../docs/automation/README.md)。

### 応募書類を出す

- 職務経歴書・英文レジュメ: `scripts/profile/export_pdf.py`。連絡先は `--contact` 指定時だけ載る。
- 履歴書: `scripts/profile/export_rirekisho.py`。志望動機など応募先ごとの記入事項は企業フォルダの `application.md` に書き、`--company` で差し込む。
- 詳細は [docs/profile/README.md](../../../docs/profile/README.md)。
