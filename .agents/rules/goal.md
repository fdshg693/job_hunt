---
trigger: always_on
---

# 就活サポートレポジトリ

就活をサポートするための、AI用ツール・メモリを整備していく

## 必要機能

- 就活情報の検索機能
    - 会社情報などを検索できる
    - 企業名や技術スタック・職種キーワードからオンライン検索し、求人一覧や詳細URLを探索できる（Findy等）
    - 必要に応じて、オンライン検索結果からの自動取得や、手動コピー・Playwright等で取得したドキュメントをローカルに格納して、高速に検索・フィルタリングできるようにする
- 記憶
    - 個人的な選好・今までの経歴・転職状況等を保存できる必要がある
    - 個人データはすべて `vault/` 配下にFrontmatter付きMarkdownで置き、ユーザー情報の唯一の正本（SSOT）として管理する（地図は `vault/README.md`）
        - `vault/profile/`: 人の共通情報（track 非依存。`.agents/rules/user-profile.md` 参照）
            - `resume.md`: 職務経歴書マスター / `rirekisho.md`: 履歴書の汎用項目（住所・学歴/職歴・免許資格） / `skills.md`: 保有スキル・自己PR・実績集
            - `preferences.md`: 共通の志向軸（職種・技術志向・ドメイン観・共通NG）
            - `accounts.md`: 求人媒体の登録・連携状況
            - `employers/`: 前職・現職の企業ログ
            - `tech/`: 技術詳細ノート（`projects/` にプロジェクトの細部・現在地、`areas/` に技術領域ごとの理解度。履歴書・自己PRの要約に書き切れない一次情報。外部提出物には直接使わない）
            - `internal/notes.md`: 非公開の転職理由・キャリア観メモ（外部露出厳禁）
            - `en/`: 英語媒体連携用の派生英語版プロフィール（`resume.md`, `skills.md`, `preferences.md`。`scripts/profile/sync_en.py` でSSOTとの差分管理・メタデータ同期）
        - `vault/tracks/{domestic,overseas}/`: 転職活動の単位（track）ごとの条件・企業・選考状況（`.agents/rules/tracks.md` 参照）
            - `strategy.md`: track 固有の希望条件（年収・出社/勤務地・企業フェーズ）
            - `criteria.md` / `ratings.md`: 非公開の足切り・企業格付け（外部露出厳禁）
            - `pipeline.md`: 選考ダッシュボード（選考企業一覧は `scripts/vault/build_pipeline.py` で自動生成）
            - `companies/{company-key}/`: 1社1フォルダ。`index.md` に相談履歴・調査内容・プロファイル更新ログ・最新選考サマリ、同フォルダの `{YYYY-MM-DD}_{stage}.md` に面談・選考詳細ログ（`.agents/rules/company-log.md`, `.agents/rules/interview-log.md` 参照）
            - `screening/`: スクリーニング早期打ち切りの集約ログ
            - `archive.md`: 見送り台帳。終了した企業フォルダ・古いスクリーニングを 1 社数行（見送り理由の核心・再検討条件）に圧縮して残す（`scripts/vault/compact_closed.py`）
        - `vault/recruiters/{recruiter-key}/`: 人単位（リクルーター・ヘッドハンター・エージェント）評価ログ。track 横断で、`index.md` にスカウト・求人提案、マッチング精度、提案案件の質、Dealbreaker遵守度、やり取り履歴、同フォルダに事前面談ログ（`.agents/rules/recruiter-log.md` 参照）
        - ステータスはフォルダではなくフロントマターのみで管理する（ステータス変更でファイルを移動しない）
        - 公開リポジトリ向けの空の雛形は `templates/vault/`（`vault/` と同じ構成）
        - フロントマターのキー・型・許容値は `scripts/vault/schema/`（Pydantic）を唯一の正とし、一覧は生成物 `docs/vault/schema.md`。年収・勤務形態・fit_score などフィルタに使う値は構造化フィールドで持つ（`.agents/rules/vault-schema.md` 参照）
    - 構造化されたフロントマター・フォルダ構造を使い、AIが効率よく情報を検索できるようにする
        - vault と `data/*/jobs` から派生キャッシュの SQLite 索引（`data/vault_index.sqlite`、FTS5 trigram の日本語全文検索）を作り、横断検索・フィルタに使う（`scripts/vault/build_index.py`）
        - 巨大になってきたら、ベクトル検索も併用する
    - 転職状況など、流動的に変わりうるデータを適切に更新することで、古いデータに引き継がれないようにする
- スキルの整備
    - 場面によって、会社を探したいのか、求人を評価したいのか、など行うべきタスクは大きく異なるので、タスクごとに必要なスキルを整理しておく
    - 整備済みスキル:
        - `consult-company-job`: ユーザーからの求人・企業・リクルーター（ヘッドハンター）相談に対して、プロファイルの確認・積極的質問による追加更新、ローカル検索・スクリプト・ブラウザ操作による調査、track 判定、および `vault/tracks/{track}/companies/`・`vault/recruiters/` への記録・最終回答を行うスキル
        - `read-job-mail`: Gmail に届いた就活関連メール（スカウト・日程調整・選考結果・媒体通知）を読み取り専用で検索・取得し、`consult-company-job`・企業ログの `status` / `next_action` 更新・各媒体スクリプトへ振り分けるスキル
        - `schedule-interview`: 面談・面接の日程調整で、Google カレンダーの空き時間から候補日を算出して返信下書きを示し、確定後はユーザー確認を取って予定を登録、企業ログの `action_type` / `next_due`・面談ログ雛形・`pipeline.md` を更新するスキル（リスケ・辞退時の予定更新・削除を含む）
        - `sweep-chores`: vault にたまった雑務（期限切れ・面談結果の未記入・pipeline.md 手書き部の停滞・放置企業・古い外部資料の要約・圧縮候補・英語版の未同期 等）を `scripts/vault/find_chores.py` と AI の読み取りで見つけ、優先度順に自動修正（差分提示）／承認／ヒアリングで片付けるスキル
        - `using-job-hunt-scripts`: 求人検索・求人詳細の取得・企業調査・メッセージ収集・媒体プロフィール更新・vault の整備・応募書類の出力の場面ごとに、どのスクリプトをどの順で使うかと、出力の読み方・認証切れ（終了コード 2）の扱いを示すスキル
        - `understanding-repo-architecture`: 仕組み（スクリプト・スキル・ルール・docs・vault スキーマ・公開同期等）を新規作成・改修・再構成する前に、レイヤーごとの役割分担と正本・設計思想・変更時に一緒に直すべき箇所（波及チェックリスト）と検証コマンドを確認するメタスキル
        - 汎用スキル（ドメイン非依存）:
            - `sharing-browser-with-user`: ログインが必要なサイトで、ユーザーが自分でログインする可視ブラウザを開き、永続プロファイルにセッションを残して以降の操作を自動化するスキル
            - `using-playwright-cli`: `playwright-cli` でブラウザ操作（遷移・クリック・スナップショット・スクリーンショット・セッション管理）やテスト実行を行うスキル
            - `writing-skill`: `SKILL.md` の作成・編集・評価の手順とチェックリスト
            - `writing-rules`: `.agents/rules/*.md` の作成・更新・一括初期化の手順と書式基準
            - `agent-tools-meta`: Claude Code / Antigravity 自体の CLI・公式ドキュメント・記憶・サブエージェント・`claude -p` への委譲を、CLI ヘルプと最新の公式ドキュメントに基づいて調べるメタスキル
- スクリプト（CLI）
    - AI エージェントは `scripts/` の CLI で外部サービスからの取得・検索・vault の整備を行う。説明の正は各スクリプトの docstring 1 行目で、一覧は生成物 `docs/scripts/catalog.md`（`scripts/dev/gen_script_catalog.py`）。オプション・使用例・関連スクリプトは各スクリプトの `--help`、場面ごとの使い分けは `using-job-hunt-scripts` スキル、サイト構造・手順の詳細は `docs/{site}/`
    - カテゴリ:

        | カテゴリ | 場所 | できること |
        |---|---|---|
        | 求人媒体 | `scripts/{findy,bizreach,openwork,forkwell,linkedin,levtech_direct,green,youtrust,wellfound,herp}/` | 求人検索・詳細取得、メッセージ・スカウト・いいね等の取得、媒体プロフィールの取得・更新（更新系は安全ガード・事前バックアップ・`--dry-run` 付き）、OpenWork の口コミ・企業 ID 解決 |
        | 記事・スライド | `scripts/{note,speakerdeck}/` | 企業の記事・登壇スライドの検索と文字起こし |
        | Google | `scripts/{google,gmail,gcal}/` | 共通 OAuth 認証、Gmail の読み取り専用検索・スレッド取得、カレンダーの空き枠算出・面談予定の作成・更新・削除（自分が作った予定だけ） |
        | Web 調査 | `scripts/web/` | Tavily による一般 Web 検索・既知 URL の本文抽出（API キーは直下 `.env`） |
        | vault 道具 | `scripts/vault/` | フロントマター検証、`pipeline.md` 生成、SQLite 索引、雑務検出、見送り台帳への圧縮、外部資料の要約、`data/` の保持期間管理、スキーマ文書生成 |
        | 横断ツール | `scripts/common/`（CLI） | 企業の重複・除外判定（`check_company.py`）、保存済み求人のローカル横断検索 |
        | プロフィール出力 | `scripts/profile/` | 職務経歴書・英文レジュメ・履歴書の PDF 出力（漏洩ガード付き）、英語版プロフィールの同期検査 |
        | 定期実行 | `scripts/automation/` | YAML で定義したルーチン（スクリプト→`claude -p` / `agy` のステップ）を無人実行して「今日やること」のブリーフを作る、Windows タスク スケジューラへの登録・解除（`docs/automation/README.md`） |
        | 共通基盤 | `scripts/common/`（モジュール） | CLI 基盤・認証ハンドオフ・正規化・保存・crawler パイプライン・パス定数（`docs/common/README.md`） |
        | 開発 | `scripts/{dev,templates}/` | `.agents/` → `.claude/` 同期、公開漏れ検査、スクリプト一覧生成、新規媒体の雛形（`docs/guides/new_site_scraper_guide.md`） |
- ブラウザ自動化とセッション管理
    - 各転職サービス（Findy、ビズリーチ等）の非公開画面（いいね一覧、スカウトメッセージ、応募状況等）をスクリプト経由で自動閲覧・取得できる
    - 就活関連のブラウザログインセッションは共通プロファイル `job-hunt`（`%LOCALAPPDATA%\claude-browser-profiles\job-hunt`）に集約・永続化する
    - 未認証時やセッション切れ時は安全にユーザー手動ログインへハンドオフし、資格情報をコンテキストに漏洩させない
- スクリプトの規約
    - エントリポイントスクリプト出力規約: 各CLIスクリプトは標準出力に作成・該当したデータファイルパスを返し、テキストサマリは `--summary` オプション時のみ出力する（`.agents/rules/scripts-entrypoint.md` 準拠）
    - スクリプト・サイト構造ドキュメント同期規約: スクリプト作成・改修時は事前に `docs/{site}/` を参照してサイト構造・セレクタ・認証仕様を理解した上で実装し、変更・新規作成時は必ず `docs/{site}/` を最新化してコードとドキュメントの同期を徹底する（`.agents/rules/scripts-entrypoint.md` 準拠）
- 定期実行（今日やることブリーフ）
    - PC にログオンしている間、タスク スケジューラから AI エージェントを無人実行し、雑務・メール・予定を確かめて「今日ユーザーがやること」を `data/automation/briefs/` に出してトースト通知する。手順・プロンプト・スケジュールは `vault/automation/routines.yaml`（非公開。雛形は `templates/vault/automation/`）で定義する。外向き・取り消しにくい操作はせず、ユーザーの判断が要るものはブリーフに回す
- 人間用の閲覧 Web UI（読み取り専用、`webui/`）
    - 役割分担: AIエージェントは CLI で検索・取得・vault への記録を行い、人間は Web UI で絞り込み・閲覧する
    - ダッシュボード（要対応・予定・連絡待ち）、企業一覧/詳細（会社名検索・進行中だけ・fit_score 下限等のフィルタ）、リクルーター、スクリーニング、求人、全文検索
    - FastAPI + Jinja2 + htmx。`uv run python -m webui` で起動し 127.0.0.1 のみで待ち受ける。vault への書き込みはしない（`.agents/rules/webui.md` 参照）

## リポジトリ公開・パブリック同期規約

- プライベートリポジトリ（`fdshg693/job_hunt_private`）を正本（SSOT）として運用する。
- パブリックリポジトリ（`fdshg693/job_hunt`）への公開は、GitHub Actions（`.github/workflows/sync-public.yml`）による自動同期で行う。
- **安全同期アーキテクチャ**:
    - **ホワイトリスト方式**: 公開対象ディレクトリ（`scripts/`, `docs/`, `tests/`, `templates/`, `webui/`, `.agents/{rules,skills,agents}/`, `.claude/{rules,skills,agents}/`, `ai/tools/` 等）およびプロジェクト設定ファイルのみを抽出して同期する。
    - **ハードリライト（単一コミット force push）**: コミット履歴や過去の差分に個人情報が残らないよう、パブリックリポジトリ側は常に単一コミットで force push する。
    - **機密ディレクトリの完全除外**: ユーザーの個人情報・選考状況・社内メモ・進行中プラン等（`vault/`, `data/`, `ai/plans/`, `internal/`, `.scratch/`）はパブリックに一切同期・公開されない。
    - **禁止語ガード**: 公開対象パスに個人情報（氏名・スラッグ・年収・スコア・完成文等）が混入していないか、CI Secret `PUBLIC_DENYLIST` およびローカル `scripts/dev/check_public_leak.py`（pre-commit フック）で同期前に機械的に検査・停止する。


## スカウト・メッセージ・求人評価の基本原則（機械化の誤用防止）

- **機械的フィルタの過信禁止・総合判断の義務**:
  - キーワード検索、正規表現、自動スコアリング等の機械的フィルタは、あくまで初期の粗削りな「事前フィルタ（参考情報）」に過ぎない。
  - スクリプトのスコアや機械的判定のみで最終決定（返信・保存・削除/アーカイブ、足切り等）を下すことは厳禁とする。
  - 必ずユーザーのプロファイル（経歴、志向軸、Dealbreaker、希望条件）と照らし合わせ、送信者・企業・職種・文脈を総合的に吟味して判断すること。
  - たかだか数十件程度の規模のメッセージ・求人に対して、思考停止して安易な完全自動化で楽をしようとしてはならない。
- **調査スキップ時の理由明記義務**:
  - 事前フィルタ（古い日付、明らかな営業アンケート等）を理由にそれ以上の詳細調査（スレッド本文開封、企業調査、リクルーター調査等）を行わない場合は、**「〜を理由に詳細調査はスキップ」と必ずその旨と根拠を明記・記録**すること。
- **面談日程調整・候補日時提示の基本原則（目いっぱい提示・順序の絶対遵守）**:
  - 面談を最優先とし、候補枠算出時は前後にバッファを取らない（`--buffer 0`）。既存予定の間（例: 12:00まで予定、次が14:00〜なら 12:00〜14:00、15:00まで予定、次が17:00〜なら 15:00〜17:00）を目いっぱいに使う。
  - 候補日時は**基本的に目いっぱい（全枠・各日の目いっぱいの時間帯レンジ）提示**する。
  - AIが勝手に「3〜5枠に絞る」「一部の時間帯を削る」などと間引いてはならない。
  - 不都合・不要な枠があれば**ユーザーが自分で間引く**。**絶対にこの順序を逆にしない**。
