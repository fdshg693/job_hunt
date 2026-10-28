<!-- 自動生成ファイル: scripts/dev/gen_script_catalog.py が各スクリプトの docstring 1 行目から生成する。手で編集しない -->

# スクリプト一覧

`scripts/` 配下の CLI エントリポイントの一覧。説明の正（SSOT）は各スクリプトのモジュール docstring の 1 行目。
スクリプトを追加・改名したら `uv run python scripts/dev/gen_script_catalog.py` でこの文書を再生成する。

- オプション・使用例・関連スクリプトは各スクリプトの `--help`、サイト構造や詳しい手順は各ディレクトリの docs を見る。
- 出力規約（stdout はパス・`-s` でサマリ等）は [`.agents/rules/scripts-entrypoint.md`](../../.agents/rules/scripts-entrypoint.md)。
- 「非推奨:」の行は互換ラッパー。新しく使わず、書かれた代わりのスクリプトを使う。

## 目次

- 求人媒体（取得・検索・プロフィール管理）: `findy`, `bizreach`, `openwork`, `forkwell`, `linkedin`, `levtech_direct`, `green`, `youtrust`, `wellfound`, `herp`
- 記事・スライド: `note`, `speakerdeck`
- Google（Gmail・カレンダー）: `google`, `gmail`, `gcal`
- Web 調査（Tavily）: `web`
- vault 道具: `vault`
- 求人・企業の横断ツール: `common`
- プロフィール出力・同期: `profile`
- 定期実行（無人ブリーフ）: `automation`
- 開発・メンテナンス: `dev`, `templates`

## 求人媒体（取得・検索・プロフィール管理）

### `scripts/findy/`

詳細: [`docs/findy/README.md`](../findy/README.md)

| スクリプト | 説明 |
|---|---|
| `scripts/findy/fetch_job.py` | Findy の求人詳細を URL（複数可）から取得して Markdown 保存する CLI |
| `scripts/findy/fetch_profile.py` | Findy のプロフィール（キャリア・スキル）を取得して保存する CLI |
| `scripts/findy/fetch_recommends.py` | Findy のおすすめ求人を取得・条件で絞り込んで保存する CLI |
| `scripts/findy/manage_work_history.py` | Findy の職歴・プロジェクトを一覧・追加・更新・削除する CLI |
| `scripts/findy/navigate_likes.py` | Findy のいいね求人一覧（タブ別）を取得して保存する CLI |
| `scripts/findy/navigate_messages.py` | Findy のメッセージ・スカウト一覧を取得して保存する CLI |
| `scripts/findy/search_online.py` | Findy の公開求人検索でキーワード検索し、一覧と詳細を保存する CLI |

### `scripts/bizreach/`

詳細: [`docs/bizreach/README.md`](../bizreach/README.md)

| スクリプト | 説明 |
|---|---|
| `scripts/bizreach/fetch_job.py` | ビズリーチの求人詳細を URL/ID から取得して Markdown 保存する CLI |
| `scripts/bizreach/fetch_message_jobs.py` | ビズリーチのメッセージに添付された求人を抽出して Markdown 保存する CLI |
| `scripts/bizreach/fetch_resume.py` | ビズリーチの職務経歴書（基本情報・職務経歴・フリーフォーマット）を取得・保存する CLI |
| `scripts/bizreach/manage_resume.py` | ビズリーチの WEB 履歴書（フリーフォーマット・職務経歴）を閲覧・更新する CLI |
| `scripts/bizreach/navigate_messages.py` | ビズリーチのメッセージ・スカウト一覧を取得して保存する CLI |
| `scripts/bizreach/search_jobs.py` | ビズリーチの求人を条件検索し、一覧と詳細を Markdown 保存する CLI |

### `scripts/openwork/`

詳細: [`docs/openwork/README.md`](../openwork/README.md)

| スクリプト | 説明 |
|---|---|
| `scripts/openwork/fetch_job.py` | OpenWork の求人詳細を URL/ID から取得して Markdown 保存する CLI |
| `scripts/openwork/fetch_resume.py` | OpenWork の WEB 履歴書を取得して保存する CLI |
| `scripts/openwork/fetch_reviews.py` | OpenWork の社員クチコミを会社名・企業 ID から取得して保存する CLI |
| `scripts/openwork/navigate_messages.py` | OpenWork のメッセージ・スカウト一覧を取得して保存する CLI |
| `scripts/openwork/resolve_company.py` | OpenWork で会社名から企業 ID（m_id）・口コミ URL を解決する CLI |
| `scripts/openwork/search_jobs.py` | OpenWork の求人を条件検索し、一覧と詳細を Markdown 保存する CLI |

### `scripts/forkwell/`

詳細: [`docs/forkwell/README.md`](../forkwell/README.md)

| スクリプト | 説明 |
|---|---|
| `scripts/forkwell/fetch_job.py` | Forkwell Jobs の求人詳細を ID/URL から取得して Markdown 保存する CLI |
| `scripts/forkwell/fetch_profile.py` | Forkwell のプロフィール（キャリア・希望・スキル）を取得して保存する CLI |
| `scripts/forkwell/manage_profile.py` | Forkwell の自己紹介・やりたいこと・スカウト設定を閲覧・更新する CLI |
| `scripts/forkwell/manage_work_history.py` | Forkwell の職歴（企業）・プロジェクトを一覧・追加・更新・削除する CLI |
| `scripts/forkwell/navigate_messages.py` | Forkwell のスカウト・メッセージ一覧と詳細を取得して保存する CLI |
| `scripts/forkwell/search_jobs.py` | Forkwell Jobs を条件検索し、求人一覧と詳細を保存する CLI |

### `scripts/linkedin/`

詳細: [`docs/linkedin/README.md`](../linkedin/README.md)

| スクリプト | 説明 |
|---|---|
| `scripts/linkedin/evaluate_messages.py` | LinkedIn の Other メッセージを機械的に事前仕分けし参考区分を出す CLI |
| `scripts/linkedin/fetch_invitations.py` | LinkedIn の受信つながり申請を取得し、価値を評価して保存する CLI |
| `scripts/linkedin/fetch_job.py` | LinkedIn の求人詳細を URL・ID から取得して Markdown 保存する CLI |
| `scripts/linkedin/fetch_profile.py` | LinkedIn の自分のプロフィール（Headline・About・Skills）を取得・保存する CLI |
| `scripts/linkedin/fetch_single_thread.py` | LinkedIn のメッセージスレッド 1 件を取得して JSON で出力する CLI |
| `scripts/linkedin/manage_experience.py` | LinkedIn の職歴（Experience）を一覧・追加・更新・削除する CLI |
| `scripts/linkedin/manage_profile.py` | LinkedIn の Headline・About を表示・更新する CLI |
| `scripts/linkedin/manage_skills.py` | LinkedIn の保有スキル（Skills）を一覧・追加・削除する CLI |
| `scripts/linkedin/navigate_messages.py` | LinkedIn のメッセージ会話一覧（任意でスレッド本文）を取得・保存する CLI |
| `scripts/linkedin/search_jobs.py` | LinkedIn で求人をキーワード・勤務地で検索し一覧・詳細を保存する CLI |

### `scripts/levtech_direct/`

詳細: [`docs/levtech_direct/README.md`](../levtech_direct/README.md)

| スクリプト | 説明 |
|---|---|
| `scripts/levtech_direct/manage_profile.py` | レバテックダイレクトのプロフィール各セクションを閲覧・更新・SSOT 同期する CLI |
| `scripts/levtech_direct/navigate_messages.py` | レバテックダイレクトのスカウト・メッセージ一覧と詳細を取得して保存する CLI |
| `scripts/levtech_direct/search_jobs.py` | レバテックダイレクトを条件検索し、求人一覧と詳細を保存する CLI |
| `scripts/levtech_direct/manage_profile_basic.py` | 非推奨: 代わりに scripts/levtech_direct/manage_profile.py basic を使う |
| `scripts/levtech_direct/manage_profile_company.py` | 非推奨: 代わりに scripts/levtech_direct/manage_profile.py company を使う |
| `scripts/levtech_direct/manage_profile_condition.py` | 非推奨: 代わりに scripts/levtech_direct/manage_profile.py condition を使う |
| `scripts/levtech_direct/manage_profile_resume.py` | 非推奨: 代わりに scripts/levtech_direct/manage_profile.py resume を使う |
| `scripts/levtech_direct/manage_profile_skill.py` | 非推奨: 代わりに scripts/levtech_direct/manage_profile.py skill を使う |

### `scripts/green/`

詳細: [`docs/green/README.md`](../green/README.md)

| スクリプト | 説明 |
|---|---|
| `scripts/green/fetch_job.py` | Green の求人詳細を ID/URL から取得して Markdown 保存する CLI |
| `scripts/green/manage_profile.py` | Green のプロフィール（基本情報・職歴・スキル・経歴書）を閲覧・更新・同期する CLI |
| `scripts/green/navigate_favorites.py` | Green の「気になる」一覧（受信・送信・マッチ）を取得して保存する CLI |
| `scripts/green/navigate_messages.py` | Green のメッセージ・スカウト一覧とスレッド本文を取得して保存する CLI |
| `scripts/green/search_jobs.py` | Green を条件検索し、求人一覧と詳細を保存する CLI |

### `scripts/youtrust/`

詳細: [`docs/youtrust/README.md`](../youtrust/README.md)

| スクリプト | 説明 |
|---|---|
| `scripts/youtrust/manage_background.py` | YOUTRUST の職歴・学歴を閲覧・追加・更新・削除・SSOT 同期する CLI |
| `scripts/youtrust/manage_profile.py` | YOUTRUST のプロフィール（自己紹介・居住地等）を閲覧・更新・同期する CLI |
| `scripts/youtrust/navigate_messages.py` | YOUTRUST のチャット一覧・スレッド本文を取得して保存する CLI |

### `scripts/wellfound/`

詳細: [`docs/wellfound/README.md`](../wellfound/README.md)

| スクリプト | 説明 |
|---|---|
| `scripts/wellfound/manage_profile.py` | Wellfound のプロフィール（Bio・職歴・スキル等）を閲覧・更新する CLI |

### `scripts/herp/`

詳細: [`docs/herp/README.md`](../herp/README.md)

| スクリプト | 説明 |
|---|---|
| `scripts/herp/fetch_job.py` | HERP Careers の求人票を URL/ID から取得して Markdown 保存する CLI |

## 記事・スライド

### `scripts/note/`

詳細: [`docs/note/README.md`](../note/README.md)

| スクリプト | 説明 |
|---|---|
| `scripts/note/fetch_article.py` | note.com の記事 1 件を URL・key から取得して Markdown・JSON 保存する CLI |
| `scripts/note/search_notes.py` | note.com の記事をキーワードで検索し、一覧（任意で本文）を保存する CLI |

### `scripts/speakerdeck/`

詳細: [`docs/speakerdeck/README.md`](../speakerdeck/README.md)

| スクリプト | 説明 |
|---|---|
| `scripts/speakerdeck/fetch_deck.py` | Speaker Deck のスライドを文字起こしして Markdown・JSON 保存する CLI |
| `scripts/speakerdeck/search_decks.py` | Speaker Deck のスライドを検索し、一覧（任意で文字起こし）を保存する CLI |

## Google（Gmail・カレンダー）

### `scripts/google/`

詳細: [`docs/google/README.md`](../google/README.md)

| スクリプト | 説明 |
|---|---|
| `scripts/google/auth.py` | Google API（Gmail・Calendar 共通）の初回認可・トークン確認 CLI |

### `scripts/gmail/`

詳細: [`docs/gmail/README.md`](../gmail/README.md)

| スクリプト | 説明 |
|---|---|
| `scripts/gmail/fetch_thread.py` | Gmail のスレッド本文を ID 指定で取得して保存する CLI（読み取り専用） |
| `scripts/gmail/search_messages.py` | Gmail を JOB ラベル配下で検索し、ヒット一覧を保存する CLI（読み取り専用） |

### `scripts/gcal/`

詳細: [`docs/gcal/README.md`](../gcal/README.md)

| スクリプト | 説明 |
|---|---|
| `scripts/gcal/find_slots.py` | Google カレンダーの空きから面談候補枠を算出・保存する CLI（読み取り専用） |
| `scripts/gcal/list_calendars.py` | 参照できる Google カレンダーの一覧を保存する CLI（読み取り専用） |
| `scripts/gcal/list_events.py` | Google カレンダーの期間内の予定一覧を保存する CLI（読み取り専用） |
| `scripts/gcal/manage_events.py` | Google カレンダーの面談予定を作成・参照・更新・削除する CLI（安全ガード付き） |

## Web 調査（Tavily）

### `scripts/web/`

詳細: [`docs/web/README.md`](../web/README.md)

| スクリプト | 説明 |
|---|---|
| `scripts/web/extract.py` | Tavily で既知の URL（複数可）の本文を Markdown で取り、data/web/extracts/ に保存する CLI |
| `scripts/web/search.py` | Tavily で一般 Web を検索し、結果の抜粋を data/web/searches/ に保存する CLI |

## vault 道具

### `scripts/vault/`

詳細: [`docs/vault/schema.md`](../vault/schema.md)、[`docs/vault/chores.md`](../vault/chores.md)、[`docs/vault/materials.md`](../vault/materials.md)

| スクリプト | 説明 |
|---|---|
| `scripts/vault/add_material.py` | Web 資料の要約を企業・リクルーターの materials/ に作り links に登録する CLI |
| `scripts/vault/build_index.py` | vault と data/*/jobs から SQLite の派生索引（data/vault_index.sqlite）を作る CLI |
| `scripts/vault/build_pipeline.py` | track 別 pipeline.md の選考企業一覧を企業ログから再生成する CLI |
| `scripts/vault/compact_closed.py` | 終了企業・古いスクリーニングを見送り台帳 archive.md に圧縮する CLI |
| `scripts/vault/find_chores.py` | vault にたまった雑務（記録の更新漏れ・放置）を洗い出す CLI |
| `scripts/vault/gen_schema_doc.py` | vault スキーマから docs/vault/schema.md を生成・差分検査する CLI |
| `scripts/vault/prune_data.py` | data/ の保持期間を過ぎた生データを一覧・削除する CLI |
| `scripts/vault/validate.py` | vault のフロントマターをスキーマと配置ルールで検証する CLI |

## 求人・企業の横断ツール

### `scripts/common/`

詳細: [`docs/common/README.md`](../common/README.md)

| スクリプト | 説明 |
|---|---|
| `scripts/common/check_company.py` | 企業名を vault の企業ログ・見送り台帳と照合し重複・除外を判定する CLI |
| `scripts/common/search_local_jobs.py` | data/*/jobs の求人 Markdown を条件で横断検索・フィルタするローカル検索 CLI |
| `scripts/common/search_jobs.py` | 非推奨: 代わりに scripts/common/search_local_jobs.py を使う |

## プロフィール出力・同期

### `scripts/profile/`

詳細: [`docs/profile/README.md`](../profile/README.md)

| スクリプト | 説明 |
|---|---|
| `scripts/profile/export_pdf.py` | 職務経歴書・英文レジュメを vault/profile から PDF 出力する CLI |
| `scripts/profile/export_rirekisho.py` | 履歴書（厚労省様式例準拠）を vault/profile から PDF 出力する CLI |
| `scripts/profile/sync_en.py` | 英語版プロフィール（vault/profile/en/）の同期状態を検査・メタ更新する CLI |

## 定期実行（無人ブリーフ）

### `scripts/automation/`

詳細: [`docs/automation/README.md`](../automation/README.md)

| スクリプト | 説明 |
|---|---|
| `scripts/automation/run_routine.py` | 定期実行エージェントルーチンの YAML を検証・実行する CLI |

## 開発・メンテナンス

### `scripts/dev/`

| スクリプト | 説明 |
|---|---|
| `scripts/dev/check_public_leak.py` | 公開対象パスに個人情報（禁止語）が混入していないか検査する CLI |
| `scripts/dev/gen_script_catalog.py` | エントリポイントの docstring からスクリプト一覧 docs/scripts/catalog.md を生成・差分検査する CLI |
| `scripts/dev/sync_agents.py` | .agents/（正本）から .claude/ を生成・差分検査する同期 CLI |

### `scripts/templates/`

詳細: [`docs/guides/new_site_scraper_guide.md`](../guides/new_site_scraper_guide.md)

| スクリプト | 説明 |
|---|---|
| `scripts/templates/site_scraper_template.py` | 新規求人サイトの求人を検索・保存する CLI の雛形（コピーして使う） |
