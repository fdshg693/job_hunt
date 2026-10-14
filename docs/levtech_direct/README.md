# レバテックダイレクト 自動化スクリプト利用ガイド

本ディレクトリでは、レバテックダイレクト（[levtech-direct.jp](https://levtech-direct.jp/)）における求人検索、求人詳細ダウンロード、および横断検索連携を行うためのスクリプト群の使い方と運用手順をまとめています。

> [!TIP]
> サイト構造、主要画面、Next.jsの `__NEXT_DATA__` スキーマ、セレクタ・API仕様の詳細は [site_structure.md](site_structure.md) を参照してください。

---

## 目次

1. [概要とできること](#1-概要とできること)
2. [スクリプト構成一覧](#2-スクリプト構成一覧)
3. [前提条件と環境準備](#3-前提条件と環境準備)
15: 4. [各スクリプトの詳細な使い方](#4-各スクリプトの詳細な使い方)
16:    - [4.1 求人検索・詳細一括ダウンロード: `search_jobs.py`](#41-求人検索詳細一括ダウンロード-search_jobspy)
17:    - [4.2 メッセージ・スカウト一覧・詳細取得: `navigate_messages.py`](#42-メッセージスカウト一覧詳細取得-navigate_messagespy)
18:    - [4.3 基本情報閲覧・更新・同期: `manage_profile_basic.py`](#43-基本情報閲覧更新同期-manage_profile_basicpy)
19:    - [4.4 希望条件閲覧・更新・同期: `manage_profile_condition.py`](#44-希望条件閲覧更新同期-manage_profile_conditionpy)
20:    - [4.5 職務経歴・自己PR記載対応: `manage_profile_resume.py`](#45-職務経歴自己pr記載対応-manage_profile_resumepy)
21:    - [4.6 保有スキル閲覧・追加・削除・更新・同期: `manage_profile_skill.py`](#46-保有スキル閲覧追加削除更新同期-manage_profile_skillpy)
22:    - [4.7 経歴企業・職歴閲覧・追加・削除・更新・同期: `manage_profile_company.py`](#47-経歴企業職歴閲覧追加削除更新同期-manage_profile_companypy)
23: 5. [実践シナリオ別ワークフロー](#5-実践シナリオ別ワークフロー)
24: 6. [データ格納仕様](#6-データ格納仕様)
25: 
26: ---
27: 
28: ## 1. 概要とできること
29: 
30: レバテックダイレクトにおける求人探索・情報収集の自動化を目的として、以下の機能を提供します。
31: 
32: - **公開求人の検索 & 一覧永続化**: キーワード、最低年収、ソート順、リモート形態等の条件でレバテックダイレクト上の求人を高速検索し、検索結果一覧Markdown/JSONを自動生成（`search_jobs.py`）。
33: - **求人詳細の一括ダウンロード**: 検索結果でヒットした求人詳細を一括取得し、Next.jsのSSRデータ（`__NEXT_DATA__`）を活用して `data/levtech_direct/jobs/{id}.md` として自動保存。
34: - **スカウト・メッセージ一覧およびスレッド履歴の自動取得**: 共通ブラウザプロファイル `job-hunt` を活用し、内部REST API経由で既読化を回避しながらメッセージ・スカウト一覧、添付求人、やり取り本文を高速抽出・永続化（`navigate_messages.py`）。
35: - **マイページ基本情報の閲覧・更新・プロファイル同期**: 氏名、生年月日、電話番号、住所、年収、学歴、語学、資格の取得（`fetch`）、個別更新（`update`）、および `profile/resume.md` からの自動反映（`sync`）に対応。変更前自動バックアップと `--dry-run` 差分プレビューを標準完備（`manage_profile_basic.py`）。
36: - **マイページ希望条件の閲覧・更新・プロファイル同期**: 希望年収、転職希望時期、事業形態、リモート条件、企業規模、希望勤務地、職種、スキル、雇用形態、こだわり条件、業務内容・技術領域への意欲の閲覧（`fetch`）、個別更新（`update`）、および `profile/preferences.md` からの自動同期（`sync`）に対応。変更前自動バックアップと `--dry-run` 差分プレビューを標準完備（`manage_profile_condition.py`）。
37: - **マイページ職務経歴・自己PRの閲覧・更新・プロファイル同期**: 職務経歴・自己PRテキスト（最大30,000文字）の取得（`fetch`）、個別更新（`update`）、および `profile/resume.md` + `profile/skills.md` からの自動生成反映（`sync`）に対応（`manage_profile_resume.py`）。
38: - **マイページ保有スキルの閲覧・追加・削除・年数更新・プロファイル同期**: 保有スキル（スキル名・年数）、現在の職種、担当工程、マネジメント規模等の取得（`fetch`）、個別追加/削除/更新（`update`）、および `profile/skills.md` からの自動抽出同期（`sync`）に対応。変更前自動バックアップと `--dry-run` 差分プレビューを標準完備（`manage_profile_skill.py`）。
39: - **マイページ経歴企業・職歴の閲覧・追加・削除・更新・プロファイル同期**: 就業状況、現在の業務形態、経験企業数、在籍企業（企業名、ブロック設定、雇用形態、在籍期間、プロジェクト一覧、開発規模、ポジション、担当工程、詳細）の取得（`fetch`）、個別追加/更新/削除（`update`）、および `profile/resume.md` からの自動同期（`sync`）に対応。変更前自動バックアップと `--dry-run` 差分プレビューを標準完備（`manage_profile_company.py`）。
40: - **高速・ヘッドレス実行 & 認証ハンドオフ**: 公開求人ページはPlaywright不要の標準HTTPリクエスト（`httpx`）で動作。マイページ機能は共通認証エンジン（`auth_engine.py`）により、未ログイン時にOSトースト通知と手動ログイン待機ハンドオフを自動適用。
41: - **プロジェクト共通求人フォーマット対応**: 保存された求人はプロジェクト共通仕様（`.agents/rules/job-data-format.md`）に準拠し、`scripts/common/search_jobs.py` で他媒体（Findy, Bizreach, Forkwell, OpenWork, LinkedIn等）とシームレスに横断検索・フィルタリング可能。
42: 
43: ---
44: 
45: ## 2. スクリプト構成一覧
46: 
47: | スクリプト | 種別 | 主な役割 |
48: |---|---|---|
49: | [`scripts/levtech_direct/search_jobs.py`](file:///c:/C/job_hunt/scripts/levtech_direct/search_jobs.py) | Python CLI | 求人検索・条件絞り込み・検索結果一覧保存・求人詳細一括ダウンロード |
50: | [`scripts/levtech_direct/navigate_messages.py`](file:///c:/C/job_hunt/scripts/levtech_direct/navigate_messages.py) | Python CLI | メッセージ・スカウト一覧取得・スレッド詳細抽出・Markdown/JSON永続化 |
51: | [`scripts/levtech_direct/manage_profile_basic.py`](file:///c:/C/job_hunt/scripts/levtech_direct/manage_profile_basic.py) | Python CLI | マイページ基本情報（`/mypage/profile/basic`）閲覧・更新・同期・バックアップ |
52: | [`scripts/levtech_direct/manage_profile_basic.mjs`](file:///c:/C/job_hunt/scripts/levtech_direct/manage_profile_basic.mjs) | Playwright JS | 基本情報画面DOM取得・React Hook Form入力・保存・バリデーション制御 |
53: | [`scripts/levtech_direct/manage_profile_condition.py`](file:///c:/C/job_hunt/scripts/levtech_direct/manage_profile_condition.py) | Python CLI | マイページ希望条件（`/mypage/profile/condition`）閲覧・更新・同期・バックアップ |
54: | [`scripts/levtech_direct/manage_profile_condition.mjs`](file:///c:/C/job_hunt/scripts/levtech_direct/manage_profile_condition.mjs) | Playwright JS | 希望条件画面DOM取得・MUIフォーム入力・保存・バリデーション制御 |
55: | [`scripts/levtech_direct/manage_profile_resume.py`](file:///c:/C/job_hunt/scripts/levtech_direct/manage_profile_resume.py) | Python CLI | マイページ職務経歴・自己PR（`/mypage/profile/resume`）閲覧・更新・同期・バックアップ |
56: | [`scripts/levtech_direct/manage_profile_resume.mjs`](file:///c:/C/job_hunt/scripts/levtech_direct/manage_profile_resume.mjs) | Playwright JS | 職務経歴画面DOM取得・テキストエリア入力・文字数バリデーション・保存制御 |
57: | [`scripts/levtech_direct/manage_profile_skill.py`](file:///c:/C/job_hunt/scripts/levtech_direct/manage_profile_skill.py) | Python CLI | マイページ保有スキル（`/mypage/profile/skill`）閲覧・更新・同期・バックアップ |
58: | [`scripts/levtech_direct/manage_profile_skill.mjs`](file:///c:/C/job_hunt/scripts/levtech_direct/manage_profile_skill.mjs) | Playwright JS | スキル画面DOM取得・MUI Autocomplete入力・行追加削除・保存制御 |
59: | [`scripts/levtech_direct/manage_profile_company.py`](file:///c:/C/job_hunt/scripts/levtech_direct/manage_profile_company.py) | Python CLI | マイページ経歴企業（`/mypage/profile/company`）閲覧・更新・同期・バックアップ |
60: | [`scripts/levtech_direct/manage_profile_company.mjs`](file:///c:/C/job_hunt/scripts/levtech_direct/manage_profile_company.mjs) | Playwright JS | 経歴企業画面DOM取得・MUIモーダル入力・カード編集削除・保存制御 |

---

## 3. 前提条件と環境準備

- **Python**: 3.13 以上（`uv` 使用推奨）
- **Node.js / Playwright**: Playwright CLI（メッセージ取得時のみ使用）
- **依存ライブラリ**: `httpx`, `beautifulsoup4`, `pydantic`, `pyyaml` 等（プロジェクト仮想環境に含まれます）
- **認証**:
  - **求人検索・詳細取得**: 完全公開のため、ログインやセッション不要で即座に実行可能です。
  - **メッセージ・スカウト取得**: 会員専用機能のため、共通ブラウザプロファイル `job-hunt`（`%LOCALAPPDATA%\claude-browser-profiles\job-hunt`）のログインセッションを使用します。未認証時は自動でOSトースト通知が送られ、手動ログイン待機モードへ移行します。

---

## 4. 各スクリプトの詳細な使い方

### 4.1 求人検索・詳細一括ダウンロード: `search_jobs.py`

レバテックダイレクトの検索画面からキーワードや年収、リモート条件で求人を検索し、検索結果一覧ファイルと求人詳細を一括保存します。

#### コマンドライン引数

| 引数 | 省略形 | デフォルト | 説明 |
|---|---|---|---|
| `query` | - | （必須） | 検索キーワード（職種名、技術スタック、企業名など） |
| `--limit` | `-n` | `20` | 取得する最大求人数 |
| `--min-salary` | - | `None` | 最低年収（万円単位、例: `800`） |
| `--remote` | - | `None` | リモート形態絞り込み（`フルリモート`、`ハイブリッド`、`出社`、英語エイリアス `full`, `hybrid`, `remote` にも対応） |
| `--sort` | - | `new` | ソート順（`new`: 新着順、`salary_max`: 年収上限高い順、`salary_min`: 年収下限低い順） |
| `--download` | - | `False` | 検索にヒットした求人詳細Markdownを一括ダウンロード保存 |
| `--download-limit` | - | `5` | 詳細をダウンロードする件数の上限（デフォルト: 5件） |
| `--summary` | `-s` | `False` | 処理結果のテキストサマリ（コンソール表示用）を出力 |
| `--json` | - | `False` | 検索結果およびファイルパスを構造化JSONとして標準出力に出力 |
| `--force` | - | `False` | 既存の求人詳細ファイルが存在する場合も強制上書き取得 |

#### 実行例

```powershell
# 1. 基本検索（キーワード検索、結果一覧ファイルのパスのみ出力）
uv run python scripts/levtech_direct/search_jobs.py "Python" -n 10

# 2. 最低年収800万円、サマリ表示付き
uv run python scripts/levtech_direct/search_jobs.py "Go" --min-salary 800 --summary

# 3. フルリモート求人に絞り込み、ヒットした求人詳細を一括ダウンロード
uv run python scripts/levtech_direct/search_jobs.py "TypeScript" --remote "フルリモート" --download --summary

# 4. 年収上限が高い順にソートして上位5件を詳細ダウンロード
uv run python scripts/levtech_direct/search_jobs.py "テックリード" --sort salary_max -n 5 --download --summary
```

> [!NOTE]
> デフォルト実行時は [scripts-entrypoint.md](file:///c:/C/job_hunt/.agents/rules/scripts-entrypoint.md) 規約に従い、標準出力（stdout）には生成されたファイルのパスのみを出力します。人間向けの要約を確認したい場合は `--summary`（または `-s`）を付与してください。

### 4.2 メッセージ・スカウト一覧・詳細取得: `navigate_messages.py`

レバテックダイレクトのマイページメッセージ画面（`/mypage/message`）から、スカウト・メッセージ一覧およびやり取り本文を取得し、Markdown/JSON形式で永続化します。

#### コマンドライン引数

| 引数 | 省略形 | デフォルト | 説明 |
|---|---|---|---|
| `--tab` | - | `active` | 取得対象タブ（`active`: 通常メッセージ、`unread`: 未読、`company`: 企業直接、`headhunter`: エージェント、`trash`: ゴミ箱、`all`: 全件） |
| `--limit` | `-n` | `0`（全件） | 取得件数の上限（`0` は全件取得） |
| `--no-details` | - | `False` | スレッド内やり取り履歴の取得をスキップ（高速一覧取得） |
| `-o`, `--output-dir` | - | `data/levtech_direct/messages` | 結果出力先ディレクトリ |
| `--summary` | `-s` | `False` | 処理結果の整形テキストサマリを標準出力に表示 |
| `--json` | - | `False` | 取得結果を構造化JSONとして標準出力に出力 |
| `--no-save` | - | `False` | ファイル保存を行わず画面表示のみ行う |
| `--session` | - | `job-hunt` | Playwright CLIセッション名 |
| `--timeout` | - | `120` | 未ログイン時の手動ログイン待機タイムアウト秒数 |
| `--no-notify` | - | `False` | 認証壁検知時のOSトースト通知を抑制 |
| `--keep-open` | - | `False` | 処理完了後にブラウザセッションを閉じずに保持 |

#### 実行例

```powershell
# 1. アクティブなメッセージ一覧を取得（デフォルト: ファイルパスのみ出力）
uv run python scripts/levtech_direct/navigate_messages.py

# 2. 直近3件をサマリ表示付きで取得
uv run python scripts/levtech_direct/navigate_messages.py --summary --limit 3

# 3. 未読メッセージのみを高速取得（スレッド詳細スキップ）
uv run python scripts/levtech_direct/navigate_messages.py --tab unread --no-details --summary

# 4. 企業直接のスカウトのみを取得
uv run python scripts/levtech_direct/navigate_messages.py --tab company --summary
```

---

### 4.3 基本情報閲覧・更新・同期: `manage_profile_basic.py`

レバテックダイレクトのマイページ基本情報画面（`/mypage/profile/basic`）にアクセスし、氏名、生年月日、電話番号、住所、年収、学歴、語学、資格情報の閲覧（`fetch`）、個別更新（`update`）、および `profile/resume.md` からの自動抽出反映（`sync`）を行います。

更新系操作の実行前には必ず変更前プロフィールの自動バックアップが保存され、`--dry-run` オプションで安全に差分（Unified Diff）を確認できます。

#### サブコマンド & オプション

```text
manage_profile_basic.py [共通オプション] {fetch,update,sync} [サブコマンドオプション]
```

- **共通オプション**:
  - `--session`: ブラウザプロファイルセッション名（デフォルト: `job-hunt`）
  - `--summary`, `-s`: コンソール向け整形サマリ表示
  - `--json`: 結果JSON出力
- **fetch サブコマンド**:
  - `--output-dir`: 保存先ディレクトリ（デフォルト: `data/levtech_direct/profile`）
- **update サブコマンド**:
  - `--dry-run`: 変更を実行せず差分プレビューのみ表示
  - `--annual-income`: 現在年収（万円）
  - `--prefecture`: 都道府県名またはID（例: `東京都` または `1`）
  - `--school-name`: 学校名
  - `--faculty`: 学部/学科/専攻
  - `--graduation-year`, `--graduation-month`: 卒業年月
  - `--toeic`, `--toefl`: 語学スコア
  - `--certification`: 保有資格テキスト
  - `--payload`: JSON文字列による直接指定
- **sync サブコマンド**:
  - `profile/resume.md` から基本情報（氏名、生年月日、現住所、年収、学歴、TOEIC、資格等）を自動抽出し反映
  - `--dry-run`: 変更を実行せず差分プレビューのみ表示

#### 実行例

```powershell
# 1. 現在の基本情報を取得して Markdown / JSON 保存
uv run python scripts/levtech_direct/manage_profile_basic.py fetch

# 2. 基本情報サマリをコンソール表示
uv run python scripts/levtech_direct/manage_profile_basic.py --summary fetch

# 3. profile/resume.md との差分をプレビュー（dry-run）
uv run python scripts/levtech_direct/manage_profile_basic.py --summary sync --dry-run

# 4. 特定項目をプレビュー（年収・TOEIC更新）
uv run python scripts/levtech_direct/manage_profile_basic.py --summary update --dry-run --annual-income 450 --toeic 950
```

---

### 4.4 希望条件閲覧・更新・同期: `manage_profile_condition.py`

レバテックダイレクトのマイページ希望条件画面（`/mypage/profile/condition`）にアクセスし、希望年収、転職希望時期、事業形態、リモート条件、企業規模、希望勤務地、職種、スキル、雇用形態、こだわり条件、業務内容・技術領域への意欲の閲覧（`fetch`）、個別更新（`update`）、および `profile/preferences.md` からの自動抽出反映（`sync`）を行います。

変更操作の実行前には必ず最新希望条件の自動バックアップが保存され、`--dry-run` オプションで安全に変更前後の差分（Unified Diff）をプレビュー確認できます。

#### サブコマンド & オプション

```text
manage_profile_condition.py [共通オプション] {fetch,update,sync} [サブコマンドオプション]
```

- **共通オプション**:
  - `--session`: ブラウザプロファイルセッション名（デフォルト: `job-hunt`）
  - `--summary`, `-s`: コンソール向け整形サマリ表示
  - `--json`: 結果JSON出力
- **fetch サブコマンド**:
  - `--output-dir`: 保存先ディレクトリ（デフォルト: `data/levtech_direct/profile`）
- **update サブコマンド**:
  - `--dry-run`: 変更を実行せず差分プレビューのみ表示
  - `--annual-income`: 希望年収（万円単位、例: `600`）
  - `--remote`: リモート条件（`full_remote`, `hybrid_work`, `none`）
  - `--business-form`: 事業形態（`in_house_development`, `entrusted_development`, `none`）
  - `--project-scale`: 企業規模（`venture_or_startup`, `large_company_or_listed`, `none`）
  - `--job-change-period`: 転職希望時期（`1`: 3ヶ月以内, `2`: 半年以内, `3`: 1年以内, `4`: 良い仕事があれば, `5`: 未定）
  - `--work-places`: 希望勤務地（カンマ区切り、例: `東京都,神奈川県` または `p_1,p_2`）
  - `--occupations`: 希望職種ID（カンマ区切り、例: `16,12`）
  - `--skills`: 希望スキル名（カンマ区切り、例: `Go,Node.js,React,Next.js`）
  - `--employment-statuses`: 希望雇用形態（カンマ区切り、例: `regular_employee`）
  - `--work-styles`: こだわり条件ID（カンマ区切り、例: `15,22`）
  - `--other`: 補足情報・その他希望条件
  - `--no-backup`: 事前バックアップの作成をスキップ
- **sync サブコマンド**:
  - `profile/preferences.md` から希望条件（年収、リモート、事業形態、職種、スキル、意欲等）を自動抽出し反映
  - `--dry-run`: 変更を実行せず差分プレビューのみ表示
  - `--preferences-file`: 希望条件SSOTファイルのパス（デフォルト: `profile/preferences.md`）

#### 実行例

```powershell
# 1. 現在の希望条件を取得して Markdown / JSON 保存
uv run python scripts/levtech_direct/manage_profile_condition.py fetch

# 2. 希望条件サマリをコンソール表示
uv run python scripts/levtech_direct/manage_profile_condition.py --summary fetch

# 3. profile/preferences.md との差分をプレビュー（dry-run）
uv run python scripts/levtech_direct/manage_profile_condition.py --summary sync --dry-run

# 4. 特定項目をプレビュー（年収600万円に変更）
uv run python scripts/levtech_direct/manage_profile_condition.py --summary update --dry-run --annual-income 600
```

---

### 4.5 職務経歴・自己PR記載対応: `manage_profile_resume.py`

レバテックダイレクトのマイページ職務経歴画面（`/mypage/profile/resume`）における「職務経歴・自己PR」テキストエリア（最大30,000文字）の閲覧（`fetch`）、直接更新（`update`）、およびマスターデータ（`profile/resume.md` + `profile/skills.md`）からの自動生成反映（`sync`）を行います。

変更操作前には必ず自動バックアップが作成され、`--dry-run` による Unified Diff プレビューおよび文字数バリデーション（10文字以上、30,000文字以内）を提供します。

#### サブコマンド & オプション

```text
manage_profile_resume.py [共通オプション] {fetch,update,sync} [サブコマンドオプション]
```

- **共通オプション**:
  - `--session`: ブラウザプロファイルセッション名（デフォルト: `job-hunt`）
  - `--summary`, `-s`: コンソール向け整形サマリ表示
  - `--json`: 結果JSON出力
  - `--force`: 確認プロンプトをスキップして保存を実行
- **fetch サブコマンド**:
  - `--output-dir`: 保存先ディレクトリ（デフォルト: `data/levtech_direct/profile`）
- **update サブコマンド**:
  - `--text <str>`: 直接指定したテキストで更新（10〜30,000文字）
  - `--file <path>`: 指定したファイルの内容で更新
  - `--dry-run`: 変更を実行せず差分プレビューのみ表示
  - `--output-dir`: 保存先ディレクトリ
- **sync サブコマンド**:
  - `--dry-run`: 変更を実行せず差分プレビューのみ表示
  - `--output-dir`: 保存先ディレクトリ

#### 実行例

```powershell
# 1. 現在の職務経歴・自己PRを取得（サマリ表示付き）
uv run python scripts/levtech_direct/manage_profile_resume.py fetch --summary

# 2. profile/resume.md + skills.md からの同期内容をプレビュー（dry-run）
uv run python scripts/levtech_direct/manage_profile_resume.py sync --dry-run

# 3. profile/resume.md + skills.md からの同期を実行（対話確認あり）
uv run python scripts/levtech_direct/manage_profile_resume.py sync --summary

# 4. 直接テキストを指定して dry-run プレビュー
uv run python scripts/levtech_direct/manage_profile_resume.py update --text "【職務要約】..." --dry-run
```

---

### 4.6 保有スキル閲覧・追加・削除・更新・同期: `manage_profile_skill.py`

レバテックダイレクトのマイページ保有スキル画面（`/mypage/profile/skill`）にアクセスし、保有スキル（スキル名・経験年数）、現在の職種、担当工程、マネジメント経験等の閲覧（`fetch`）、個別追加/削除/更新（`update`）、および `profile/skills.md` からの自動抽出反映（`sync`）を行います。

変更操作前には必ず最新スキルの自動バックアップが作成され、`--dry-run` による Unified Diff プレビューおよび安全ガードを提供します。

#### サブコマンド & オプション

```text
manage_profile_skill.py [共通オプション] {fetch,update,sync} [サブコマンドオプション]
```

- **共通オプション**:
  - `--session`: ブラウザプロファイルセッション名（デフォルト: `job-hunt`）
  - `--summary`, `-s`: コンソール向け整形サマリ表示
  - `--json`: 結果JSON出力
- **fetch サブコマンド**:
  - `--output-dir`: 保存先ディレクトリ（デフォルト: `data/levtech_direct/profile`）
- **update サブコマンド**:
  - `--add-skill <name>`: スキルの追加（`--years` と併用）
  - `--remove-skill <name>`: スキルの削除
  - `--set-skill <name>`: 既存スキルの年数更新（なければ追加）
  - `--years <str>`: 経験年数（例: `'2年'`, `'2年以上'`, `'半年以上'`。デフォルト: `'2年以上'`）
  - `--current-occupation <name/id>`: 現在の職種（例: `'フルスタックエンジニア'` または ID `69`）
  - `--management-scale <name/id>`: マネジメント経験（例: `'経験なし'` または ID `5`）
  - `--skills-file <path>`: 一括適用するスキルリストJSONファイル
  - `--dry-run`: 変更を実行せず差分プレビューのみ表示
  - `--no-backup`: 事前バックアップの作成をスキップ
  - `--output-dir`: 保存先ディレクトリ
- **sync サブコマンド**:
  - `profile/skills.md` から主要スキル（言語、フレームワーク、インフラ）と経験年数を解析し、レバテックダイレクトの保有スキルへ自動マージ・同期
  - `--dry-run`: 変更を実行せず差分プレビューのみ表示
  - `--skills-ssot <path>`: スキルSSOTファイルのパス（デフォルト: `profile/skills.md`）
  - `--no-backup`: 事前バックアップの作成をスキップ
  - `--output-dir`: 保存先ディレクトリ

#### 実行例

```powershell
# 1. 現在の保有スキル・職種・担当工程を取得（サマリ表示付き）
uv run python scripts/levtech_direct/manage_profile_skill.py fetch --summary

# 2. スキル追加の dry-run プレビュー
uv run python scripts/levtech_direct/manage_profile_skill.py update --add-skill Go --years 半年以上 --dry-run --summary

# 3. 既存スキルの年数更新の dry-run プレビュー
uv run python scripts/levtech_direct/manage_profile_skill.py update --set-skill Python --years 2年以上 --dry-run --summary

# 4. profile/skills.md との同期内容を dry-run プレビュー
uv run python scripts/levtech_direct/manage_profile_skill.py sync --dry-run --summary
```

---

### 4.7 経歴企業・職歴閲覧・追加・削除・更新・同期: `manage_profile_company.py`

レバテックダイレクトのマイページ経歴企業画面（`/mypage/profile/company`）にアクセスし、就業状況、現在の業務形態、経験企業数、在籍企業一覧（企業名、ブロック企業設定、雇用形態、在籍期間、プロジェクト一覧、開発規模、ポジション、担当工程、詳細）の閲覧（`fetch`）、個別追加/更新/削除（`update`）、および `profile/resume.md` からの自動同期（`sync`）を行います。

変更操作前には必ず最新経歴企業の自動バックアップが作成され、`--dry-run` による Unified Diff プレビューおよび安全ガードを提供します。

#### サブコマンド & オプション

```text
manage_profile_company.py [共通オプション] {fetch,update,sync} [サブコマンドオプション]
```

- **共通オプション**:
  - `--session`: ブラウザプロファイルセッション名（デフォルト: `job-hunt`）
  - `--summary`, `-s`: コンソール向け整形サマリ表示
  - `--json`: 結果JSON出力
- **fetch サブコマンド**:
  - `--output-dir`: 保存先ディレクトリ（デフォルト: `data/levtech_direct/profile`）
- **update サブコマンド**:
  - `--working-state <name/id>`: 就業状況（例: `'正社員で就業中'` または ID `1`）
  - `--business-status <name/key>`: 現在の業務形態（例: `'事業会社'` または `'business_company'`）
  - `--company-count <num/id>`: 経験企業数（例: `2`）
  - `--add-company-json <json>`: 追加する企業のJSON文字列
  - `--remove-company <name/idx>`: 削除する企業名またはインデックス番号
  - `--companies-file <path>`: 一括適用する企業リストJSONファイル
  - `--dry-run`: 変更を実行せず差分プレビューのみ表示
  - `--no-backup`: 事前バックアップの作成をスキップ
  - `--output-dir`: 保存先ディレクトリ
- **sync サブコマンド**:
  - `profile/resume.md` から職歴企業2社（株式会社ヘッドウォータース、株式会社プラスアルファ・コンサルティング）の在籍期間・雇用形態・プロジェクト詳細・就業状況を抽出し、レバテックダイレクトの経歴企業フォームへ自動マージ・同期
  - `--dry-run`: 変更を実行せず差分プレビューのみ表示
  - `--resume-ssot <path>`: 職務経歴書SSOTファイルのパス（デフォルト: `profile/resume.md`）
  - `--no-backup`: 事前バックアップの作成をスキップ
  - `--force`: 保存前の対話確認プロンプトをスキップ
  - `--output-dir`: 保存先ディレクトリ

#### 実行例

```powershell
# 1. 現在の経歴企業・職歴・就業状況を取得（サマリ表示付き）
uv run python scripts/levtech_direct/manage_profile_company.py fetch --summary

# 2. profile/resume.md との同期内容を dry-run プレビュー
uv run python scripts/levtech_direct/manage_profile_company.py sync --dry-run --summary

# 3. 就業状況・業務形態・経験社数のみを dry-run プレビュー
uv run python scripts/levtech_direct/manage_profile_company.py update --dry-run --summary --working-state 1 --business-status business_company --company-count 2

# 4. profile/resume.md からの同期を実行（対話確認あり）
uv run python scripts/levtech_direct/manage_profile_company.py sync --summary
```

---

## 5. 実践シナリオ別ワークフロー

### シナリオ1: 高年収リモート求人の収集と他媒体との横断比較

```powershell
# 1. レバテックダイレクトから希望条件の求人を検索＆詳細ダウンロード
uv run python scripts/levtech_direct/search_jobs.py "Go" --min-salary 800 --remote "フルリモート" --download --summary

# 2. 横断検索スクリプトで全媒体（Findy, Bizreach, Forkwell, Levtech Direct等）から比較
uv run python scripts/common/search_jobs.py "Go" --min-salary 800 --remote "フルリモート" --summary
```

### シナリオ2: レバテックダイレクト上の新着スカウト定期巡回

```powershell
# 1. 未読・新着スカウトを確認・保存
uv run python scripts/levtech_direct/navigate_messages.py --tab unread --summary

# 2. 最新のアクティブメッセージ一覧を保存
uv run python scripts/levtech_direct/navigate_messages.py --summary
```

---

## 6. データ格納仕様

共通ストレージ基盤（`scripts/common/storage.py`）および本スクリプトにより、以下のディレクトリ構造に永続化されます。

```text
data/levtech_direct/
  ├── jobs/
  │   └── {job_id}.md                    # 求人詳細Markdown（Frontmatter付き、job-data-format準拠）
  ├── searches/
  │   ├── YYYY-MM-DD-HHMMSS_{query}.md   # 検索結果一覧（Markdown表）
  │   └── YYYY-MM-DD-HHMMSS_{query}.json # 検索結果メタデータ（JSON）
  ├── messages/
  │   ├── messages_{tab}.md              # 最新メッセージ一覧（Markdown表＋本文詳細）
  │   ├── messages_{tab}.json            # 最新メッセージ一覧（構造化JSON）
  │   └── history/
  │       ├── messages_{tab}_{timestamp}.md   # 履歴保存Markdown
  │       └── messages_{tab}_{timestamp}.json # 履歴保存JSON
  └── profile/
      ├── basic_profile.md               # 最新基本情報Markdown
      ├── basic_profile.json             # 最新基本情報構造化JSON
      ├── condition.md                   # 最新希望条件Markdown
      ├── condition.json                 # 最新希望条件構造化JSON
      ├── resume.md                      # 最新職務経歴・自己PR Markdown
      ├── resume.json                    # 最新職務経歴・自己PR 構造化JSON
      ├── skill.md                       # 最新保有スキル・職種 Markdown
      ├── skill.json                     # 最新保有スキル・職種 構造化JSON
      ├── company.md                     # 最新経歴企業・職歴 Markdown
      ├── company.json                   # 最新経歴企業・職歴 構造化JSON
      └── backups/
          ├── basic_{timestamp}.json     # 基本情報変更前自動バックアップJSON
          ├── condition_{timestamp}.json # 希望条件変更前自動バックアップJSON
          ├── resume_{timestamp}.json    # 職務経歴・自己PR変更前自動バックアップJSON
          ├── skill_{timestamp}.json     # 保有スキル変更前自動バックアップJSON
          └── company_{timestamp}.json   # 経歴企業変更前自動バックアップJSON
```

