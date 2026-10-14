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
    - `profile/` 配下にFrontmatter付きMarkdownを配置し、ユーザー情報の唯一の正本（SSOT）として管理する（`.agents/rules/user-profile.md` 参照）
        - `profile/resume.md`: 職務経歴書マスター
        - `profile/preferences.md`: 希望条件・転職の軸
        - `profile/status.md`: 転職活動・選考状況
        - `profile/skills.md`: 保有スキル・自己PR・実績集
        - `profile/internal/`: 非公開クライテリア（本音の足切り・企業格付け・転職理由メモ。外部露出厳禁）
        - `profile_en/`: 英語媒体連携用の派生英語版プロフィール（`resume.md`, `skills.md`, `preferences.md`。`scripts/profile/sync_en.py` でSSOTとの差分管理・メタデータ同期）
    - 構造化されたフロントマター・フォルダ構造を使い、AIが効率よく情報を検索できるようにする
        - 巨大になってきたら、ベクトル検索も併用する
    - 転職状況など、流動的に変わりうるデータを適切に更新することで、古いデータに引き継がれないようにする
    - `chat/` 配下の企業別求人相談・調査ログ
        - ユーザーからの企業・求人に関する質問・相談履歴、調査内容、プロファイル更新ログ、最新選考サマリを `chat/{company-name}.md` に保存・蓄積する（`.agents/rules/chat-log.md` 参照）
    - `recruiters/` 配下の人単位（リクルーター・ヘッドハンター・エージェント）評価ログ
        - エージェント担当者やヘッドハンターからのスカウト・求人提案、マッチング精度、提案案件の質、Dealbreaker遵守度、やり取り履歴を `recruiters/{status}/{recruiter-key}.md` に保存・蓄積する（`.agents/rules/recruiter-log.md` 参照）
    - `interviews/` 配下の企業別面談・選考詳細ログおよびリクルーター面談ログ
        - カジュアル面談・各次面接の詳細メモ、質疑応答生ログ、一次情報、所感・感想を `interviews/{company-name}/{YYYY-MM-DD}_{stage}.md`、およびリクルーター面談を `interviews/recruiters/{recruiter-key}/{YYYY-MM-DD}_{stage}.md` に保存・蓄積する（`.agents/rules/interview-log.md` 参照）
- スキルの整備
    - 場面によって、会社を探したいのか、求人を評価したいのか、など行うべきタスクは大きく異なるので、タスクごとに必要なスキルを整理しておく
    - 整備済みスキル:
        - `consult-company-job`: ユーザーからの求人・企業・リクルーター（ヘッドハンター）相談に対して、プロファイルの確認・積極的質問による追加更新、ローカル検索・スクリプト・ブラウザ操作による調査、および `chat/`・`recruiters/` への記録・最終回答を行うスキル
        - `fetch-company-jobs`: 指定した企業の求人情報をスクリプト経由でオンライン検索・取得・保存・要約するスキル
- ブラウザ自動化とセッション管理
    - 各転職サービス（Findy、ビズリーチ等）の非公開画面（いいね一覧、スカウトメッセージ、応募状況等）をスクリプト経由で自動閲覧・取得できる
    - 就活関連のブラウザログインセッションは共通プロファイル `job-hunt`（`%LOCALAPPDATA%\claude-browser-profiles\job-hunt`）に集約・永続化する
    - 未認証時やセッション切れ時は安全にユーザー手動ログインへハンドオフし、資格情報をコンテキストに漏洩させない
        - Findy: おすすめ求人（推薦アルゴリズム準拠）取得・履歴保存（`scripts/findy/fetch_recommends.py`）
        - Findy: オンライン求人検索・一覧取得・保存（`scripts/findy/search_online.py`）
        - Findy: プロフィール（キャリア・スキル）取得・履歴保存（`scripts/findy/fetch_profile.py`）
        - Findy: 職歴・プロジェクトCRUD（`scripts/findy/manage_work_history.py`）
        - Findy: いいね一覧取得・履歴保存（`scripts/findy/navigate_likes.py`）
        - Findy: メッセージ・スカウト一覧取得・履歴保存（`scripts/findy/navigate_messages.py`）
        - ビズリーチ: メッセージ・スカウト一覧取得・履歴保存（`scripts/bizreach/navigate_messages.py`）
        - ビズリーチ: メッセージ添付求人取得・保存（`scripts/bizreach/fetch_message_jobs.py`）
        - ビズリーチ: 求人検索・詳細取得・履歴保存（`scripts/bizreach/search_jobs.py`）
        - ビズリーチ: 職務経歴書（基本情報・職務経歴・フリーフォーマット）取得・履歴保存（`scripts/bizreach/fetch_resume.py`）
        - ビズリーチ: 職務経歴書（フリーフォーマット更新・職務経歴企業・プロジェクトCRUD管理・安全ガード付き）（`scripts/bizreach/manage_resume.py`）
        - OpenWork: 求人検索・一覧取得・詳細保存（`scripts/openwork/search_jobs.py`, `scripts/openwork/fetch_job.py`）
        - OpenWork: WEB履歴書取得・履歴保存（`scripts/openwork/fetch_resume.py`）
        - OpenWork: メッセージ・スカウト一覧取得・履歴保存（`scripts/openwork/navigate_messages.py`）
        - OpenWork: 会社名からの企業ID解決（`scripts/openwork/resolve_company.py`）
        - OpenWork: 会社名からの口コミ取得・詳細保存（`scripts/openwork/fetch_reviews.py`）
        - LinkedIn: 求人検索・詳細取得・履歴保存（`scripts/linkedin/search_jobs.py`, `scripts/linkedin/fetch_job.py`）
        - LinkedIn: 職歴（Experience）CRUD管理（安全ガード・事前バックアップ付き、`scripts/linkedin/manage_experience.py`）
        - LinkedIn: プロフィール（Headline, About, Skills等）取得・履歴保存（`scripts/linkedin/fetch_profile.py`）
        - LinkedIn: プロフィール（Headline, About）更新管理（安全ガード・事前バックアップ付き、`scripts/linkedin/manage_profile.py`）
        - LinkedIn: メッセージ会話一覧・スレッド本文取得・履歴保存（読み取り専用、`scripts/linkedin/navigate_messages.py`）
        - LinkedIn: 受信招待（つながり申請）取得・プロフィール連携・価値検討（`scripts/linkedin/fetch_invitations.py`）
        - Forkwell: 求人検索・一覧取得・詳細保存（`scripts/forkwell/search_jobs.py`, `scripts/forkwell/fetch_job.py`）
        - Forkwell: プロフィール（キャリア・やりたいこと・スキル等）取得・履歴保存（`scripts/forkwell/fetch_profile.py`）
        - Forkwell: プロフィール（自己紹介・やりたいこと・スカウト等）更新・CRUD管理（安全ガード・事前バックアップ付き、`scripts/forkwell/manage_profile.py`）
        - Forkwell: 職歴・プロジェクトCRUD管理（安全ガード・事前バックアップ付き、`scripts/forkwell/manage_work_history.py`）
        - Forkwell: メッセージ・スカウト一覧取得・履歴保存（`scripts/forkwell/navigate_messages.py`）
        - レバテックダイレクト: 求人検索・一覧取得・詳細保存（`scripts/levtech_direct/search_jobs.py`）
        - レバテックダイレクト: メッセージ・スカウト一覧取得・履歴保存（`scripts/levtech_direct/navigate_messages.py`）
        - レバテックダイレクト: 基本情報閲覧・更新・プロファイル同期（`scripts/levtech_direct/manage_profile_basic.py`）
        - レバテックダイレクト: 希望条件閲覧・更新・プロファイル同期（`scripts/levtech_direct/manage_profile_condition.py`）
        - レバテックダイレクト: 職務経歴・自己PR閲覧・更新・プロファイル同期（`scripts/levtech_direct/manage_profile_resume.py`）
        - レバテックダイレクト: 保有スキル閲覧・更新・プロファイル同期（`scripts/levtech_direct/manage_profile_skill.py`）
        - レバテックダイレクト: 経歴企業・職歴閲覧・更新・プロファイル同期（`scripts/levtech_direct/manage_profile_company.py`）
        - Green: プロフィール（基本情報・職歴・スキル・希望条件・職務経歴書等）閲覧・更新・CRUD管理（`scripts/green/manage_profile.py`）
        - Green: メッセージ・スカウト一覧取得・履歴保存（`scripts/green/navigate_messages.py`）
        - Green: 受信気になる一覧取得・履歴保存（`scripts/green/navigate_favorites.py`）
        - Green: 求人検索・サーチバー操作・一覧取得（`scripts/green/search_jobs.py`）
        - Green: 求人詳細取得・保存（`scripts/green/fetch_job.py`）
        - YOUTRUST: プロフィール（基本情報・職歴・スキル・自己紹介等）閲覧・更新・CRUD管理（安全ガード・事前バックアップ付き、`scripts/youtrust/manage_profile.py`）
        - YOUTRUST: 職歴・学歴（Career/Education）閲覧・更新・CRUD管理（安全ガード・事前バックアップ付き、`scripts/youtrust/manage_background.py`）
        - Wellfound: プロフィール（基本情報・職歴・スキル等）閲覧・更新・CRUD管理（安全ガード・事前バックアップ付き、`scripts/wellfound/manage_profile.py`）
        - 共通基盤・設計アーキテクチャ:
            - CLIエントリポイント基盤・標準フラグ体系（`scripts/common/cli.py`）
            - 求人データ正規化・SSOT（`scripts/common/normalizers.py`）
            - Frontmatter付きMarkdown・検索結果永続化パイプライン（`scripts/common/storage.py`）
            - サイト横断ブラウザ認証・ハンドオフ実行エンジン（`scripts/common/auth_engine.py`, `scripts/common/browser_auth.py`）
            - ローカル求人Markdown横断検索・フィルタリング（`scripts/common/search_jobs.py`）
            - 却下済・検討中企業一覧取得・除外重複判定エンジン（`scripts/common/check_company.py`）
            - 新規求人サイト追加テンプレート（`scripts/templates/site_scraper_template.py`）
            - 新規サイト追加開発ガイド（`docs/guides/new_site_scraper_guide.md`）
        - エントリポイントスクリプト出力規約: 各CLIスクリプトは標準出力に作成・該当したデータファイルパスを返し、テキストサマリは `--summary` オプション時のみ出力する（`.agents/rules/scripts-entrypoint.md` 準拠）
        - スクリプト・サイト構造ドキュメント同期規約: スクリプト作成・改修時は事前に `docs/{site}/` を参照してサイト構造・セレクタ・認証仕様を理解した上で実装し、変更・新規作成時は必ず `docs/{site}/` を最新化してコードとドキュメントの同期を徹底する（`.agents/rules/scripts-entrypoint.md` 準拠）
## リポジトリ公開・パブリック同期規約

- プライベートリポジトリ（`fdshg693/job_hunt_private`）を正本（SSOT）として運用する。
- パブリックリポジトリ（`fdshg693/job_hunt`）への公開は、GitHub Actions（`.github/workflows/sync-public.yml`）による自動同期で行う。
- **安全同期アーキテクチャ**:
    - **ホワイトリスト方式**: 公開対象ディレクトリ（`scripts/`, `docs/`, `tests/`, `.agents/rules/`, `.agents/skills/` 等）およびプロジェクト設定ファイルのみを抽出して同期する。
    - **ハードリライト（単一コミット force push）**: コミット履歴や過去の差分に個人情報が残らないよう、パブリックリポジトリ側は常に単一コミットで force push する。
    - **機密ディレクトリの完全除外**: ユーザーの個人情報・選考状況・社内メモ・進行中プラン等（`profile/`, `profile_en/`, `chat/`, `recruiters/`, `interviews/`, `data/`, `temp/`, `.agents/plans/`）はパブリックに一切同期・公開されない。


## 不要機能

- WEB UI
    - WEB UIは不要。CLIで十分。