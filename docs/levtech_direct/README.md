# レバテックダイレクト 自動化スクリプト利用ガイド

本ディレクトリでは、レバテックダイレクト（[levtech-direct.jp](https://levtech-direct.jp/)）における求人検索、求人詳細ダウンロード、および横断検索連携を行うためのスクリプト群の使い方と運用手順をまとめています。

> [!TIP]
> サイト構造、主要画面、Next.jsの `__NEXT_DATA__` スキーマ、セレクタ・API仕様の詳細は [site_structure.md](site_structure.md) を参照してください。

---

## 目次

1. [概要とできること](#1-概要とできること)
2. [スクリプト構成一覧](#2-スクリプト構成一覧)
3. [前提条件と環境準備](#3-前提条件と環境準備)
4. [各スクリプトの詳細な使い方](#4-各スクリプトの詳細な使い方)
   - [4.1 求人検索・詳細一括ダウンロード: `search_jobs.py`](#41-求人検索詳細一括ダウンロード-search_jobspy)
   - [4.2 メッセージ・スカウト一覧・詳細取得: `navigate_messages.py`](#42-メッセージスカウト一覧詳細取得-navigate_messagespy)
   - [4.3 マイページ統合プロファイル管理: `manage_profile.py`](#43-マイページ統合プロファイル管理-manage_profilepy)
     - [基本情報セクション (`basic`)](#431-基本情報セクション-basic-mypageprofilebasic)
     - [経歴企業・職歴セクション (`company`)](#432-経歴企業職歴セクション-company-mypageprofilecompany)
     - [職務経歴・自己PRセクション (`resume`)](#433-職務経歴自己prセクション-resume-mypageprofileresume)
     - [希望条件セクション (`condition`)](#434-希望条件セクション-condition-mypageprofilecondition)
     - [保有スキルセクション (`skill`)](#435-保有スキルセクション-skill-mypageprofileskill)
     - [全セクション一括同期 (`sync`)](#436-全セクション一括同期-sync)
     - [旧スクリプト後方互換性](#437-旧スクリプト後方互換性)
5. [実践シナリオ別ワークフロー](#5-実践シナリオ別ワークフロー)
6. [データ格納仕様](#6-データ格納仕様)

---

## 1. 概要とできること

レバテックダイレクトにおける求人探索・情報収集の自動化を目的として、以下の機能を提供します。

- **公開求人の検索 & 一覧永続化**: キーワード、最低年収、ソート順、リモート形態等の条件でレバテックダイレクト上の求人を高速検索し、検索結果一覧Markdown/JSONを自動生成（`search_jobs.py`）。
- **求人詳細の一括ダウンロード**: 検索結果でヒットした求人詳細を一括取得し、Next.jsのSSRデータ（`__NEXT_DATA__`）を活用して `data/levtech_direct/jobs/{id}.md` として自動保存。
- **スカウト・メッセージ一覧およびスレッド履歴の自動取得**: 共通ブラウザプロファイル `job-hunt` を活用し、内部REST API経由で既読化を回避しながらメッセージ・スカウト一覧、添付求人、やり取り本文を高速抽出・永続化（`navigate_messages.py`）。
- **マイページプロファイルの統合管理・SSOT同期**: 基本情報、経歴企業、職務経歴・自己PR、希望条件、保有スキルの全5セクションを単一CLI（`manage_profile.py`）から閲覧（`fetch`）、個別更新（`update`）、および `vault/profile/`・`vault/tracks/` からの自動同期（`sync`）可能。全セクション一括同期（`manage_profile.py sync`）にも対応。
- **安全ガードの標準完備**: 変更操作前の自動バックアップ（タイムスタンプ付きJSON）および `--dry-run` による Unified Diff プレビューを全セクションで標準装備。
- **高速・ヘッドレス実行 & 認証ハンドオフ**: 公開求人ページはPlaywright不要の標準HTTPリクエスト（`httpx`）で動作。マイページ機能は共通認証エンジン（`auth_engine.py`）により、未ログイン時にOSトースト通知と手動ログイン待機ハンドオフを自動適用。
- **プロジェクト共通求人フォーマット対応**: 保存された求人はプロジェクト共通仕様（`.agents/rules/job-data-format.md`）に準拠し、`scripts/common/search_local_jobs.py` で他媒体（Findy, Bizreach, Forkwell, OpenWork, LinkedIn等）とシームレスに横断検索・フィルタリング可能。

---

## 2. スクリプト構成一覧

| スクリプト | 種別 | 主な役割 |
|---|---|---|
| [`scripts/levtech_direct/search_jobs.py`](../../scripts/levtech_direct/search_jobs.py) | Python CLI | 求人検索・条件絞り込み・検索結果一覧保存・求人詳細一括ダウンロード |
| [`scripts/levtech_direct/navigate_messages.py`](../../scripts/levtech_direct/navigate_messages.py) | Python CLI | メッセージ・スカウト一覧取得・スレッド詳細抽出・Markdown/JSON永続化 |
| [`scripts/levtech_direct/manage_profile.py`](../../scripts/levtech_direct/manage_profile.py) | Python CLI | マイページプロファイル統合管理（基本情報・経歴企業・職務経歴・希望条件・保有スキル）閲覧・更新・SSOT同期・自動バックアップ |
| [`scripts/levtech_direct/manage_profile.mjs`](../../scripts/levtech_direct/manage_profile.mjs) | Playwright JS | プロファイル画面DOM操作・フォーム入力・保存・バリデーション制御（全セクション統合） |
| `scripts/levtech_direct/manage_profile_*.py`（5ファイル） | Python CLI | 旧スクリプト後方互換用ラッパー（`manage_profile.py` の各サブコマンドを呼出） |

---

## 3. 前提条件と環境準備

- **Python**: 3.13 以上（`uv` 使用推奨）
- **Node.js / Playwright**: Playwright CLI（メッセージ取得時およびプロファイル管理時に使用）
- **依存ライブラリ**: `httpx`, `beautifulsoup4`, `pydantic`, `pyyaml` 等（プロジェクト仮想環境に含まれます）
- **認証**:
  - **求人検索・詳細取得**: 完全公開のため、ログインやセッション不要で即座に実行可能です。
  - **メッセージ・プロファイル管理**: 会員専用機能のため、共通ブラウザプロファイル `job-hunt`（`%LOCALAPPDATA%\claude-browser-profiles\job-hunt`）のログインセッションを使用します。未認証時は自動でOSトースト通知が送られ、手動ログイン待機モードへ移行します。

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
> デフォルト実行時は [scripts-entrypoint.md](../../.agents/rules/scripts-entrypoint.md) 規約に従い、標準出力（stdout）には生成されたファイルのパスのみを出力します。人間向けの要約を確認したい場合は `--summary`（または `-s`）を付与してください。

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

### 4.3 マイページ統合プロファイル管理: `manage_profile.py`

レバテックダイレクトのマイページ各画面にアクセスし、全プロファイル情報（基本情報、経歴企業、職務経歴・自己PR、希望条件、保有スキル）の閲覧（`fetch`）、個別更新（`update`）、および `vault/profile/`・`vault/tracks/` からの自動同期（`sync`）を行います。

変更操作の実行前には必ず変更前最新プロファイルの自動バックアップ（タイムスタンプ付きJSON）が保存され、`--dry-run` オプションで安全に変更前後の差分（Unified Diff）をプレビュー確認できます。

#### CLI構成 & 共通オプション

```text
manage_profile.py [共通オプション] {basic,company,resume,condition,skill,sync} [アクション] [オプション]
```

- **共通オプション**:
  - `--session`: ブラウザプロファイルセッション名（デフォルト: `job-hunt`）
  - `--summary`, `-s`: コンソール向け整形サマリ表示（デフォルトは更新・保存されたファイルパスのみ出力）
  - `--json`: 結果JSON出力

---

#### 4.3.1 基本情報セクション (`basic`: `/mypage/profile/basic`)

氏名、生年月日、電話番号、住所、年収、学歴、語学、資格情報の閲覧・更新・SSOT同期。

- **アクション**:
  - `fetch`: 現在の基本情報を取得して Markdown / JSON 保存
  - `update`: 個別項目の更新（`--dry-run` 対応）
    - `--annual-income`: 現在年収（万円単位）
    - `--last-name`, `--first-name`: 氏名（漢字）
    - `--kana-last-name`, `--kana-first-name`: 氏名（カタカナ）
    - `--birthday`: 生年月日 (`YYYY-MM-DD`)
    - `--gender`: 性別 (`1`: 男性, `2`: 女性, `3`: 無回答)
    - `--phone`: 電話番号（ハイフンなし）
    - `--toeic`: TOEICスコア
    - `--certification`: 保有資格テキスト
    - `--payload` / `--payload-file`: JSON直接指定
  - `sync`: `vault/profile/resume.md` から基本情報を抽出して自動反映（`--dry-run` 対応）

**実行例**:
```powershell
# 1. 基本情報を取得して保存
uv run python scripts/levtech_direct/manage_profile.py basic fetch --summary

# 2. vault/profile/resume.md との差分をプレビュー（dry-run）
uv run python scripts/levtech_direct/manage_profile.py basic sync --dry-run --summary

# 3. 年収・TOEIC更新をプレビュー
uv run python scripts/levtech_direct/manage_profile.py basic update --dry-run --annual-income 450 --toeic 950 --summary
```

---

#### 4.3.2 経歴企業・職歴セクション (`company`: `/mypage/profile/company`)

就業状況、現在の業務形態、経験社数、在籍企業一覧（企業名、ブロック設定、雇用形態、在籍期間、プロジェクト一覧、開発規模、ポジション、担当工程、詳細）の閲覧・更新・SSOT同期。

- **アクション**:
  - `fetch`: 現在の経歴企業・職歴を取得して Markdown / JSON 保存
  - `update`: 個別項目の更新（`--dry-run` 対応）
    - `--working-state`: 就業状況ID（例: `1`）
    - `--business-status`: 現在の業務形態（例: `'business_company'`）
    - `--payload` / `--payload-file`: 経歴企業JSONの直接指定
  - `sync`: `vault/profile/resume.md` から職歴企業・在籍期間・プロジェクトを抽出して自動反映（`--dry-run` 対応）

**実行例**:
```powershell
# 1. 経歴企業一覧を取得して保存
uv run python scripts/levtech_direct/manage_profile.py company fetch --summary

# 2. vault/profile/resume.md との同期内容を dry-run プレビュー
uv run python scripts/levtech_direct/manage_profile.py company sync --dry-run --summary

# 3. 就業状況の更新をプレビュー
uv run python scripts/levtech_direct/manage_profile.py company update --dry-run --working-state 1 --business-status business_company --summary
```

---

#### 4.3.3 職務経歴・自己PRセクション (`resume`: `/mypage/profile/resume`)

「職務経歴・自己PR」テキストエリア（最大30,000文字）の閲覧・更新・SSOT同期。文字数バリデーション（10〜30,000文字）付き。

- **アクション**:
  - `fetch`: 現在の職務経歴・自己PRテキストを取得して Markdown / JSON 保存
  - `update`: 直接指定テキストでの更新（`--dry-run` 対応）
    - `--resume`: 職務経歴テキスト
    - `--resume-file`: 職務経歴テキストファイルパス
  - `sync`: `vault/profile/resume.md` + `vault/profile/skills.md` から統合職務経歴テキストを自動生成して反映（`--dry-run` 対応）

**実行例**:
```powershell
# 1. 職務経歴・自己PRを取得して保存
uv run python scripts/levtech_direct/manage_profile.py resume fetch --summary

# 2. vault/profile/ からの同期内容を dry-run プレビュー
uv run python scripts/levtech_direct/manage_profile.py resume sync --dry-run --summary

# 3. テキストファイルを指定して dry-run プレビュー
uv run python scripts/levtech_direct/manage_profile.py resume update --resume-file path/to/text.txt --dry-run --summary
```

---

#### 4.3.4 希望条件セクション (`condition`: `/mypage/profile/condition`)

希望年収、転職希望時期、事業形態、リモート条件、企業規模、希望勤務地、職種、スキル、雇用形態、こだわり条件、業務内容・技術領域への意欲の閲覧・更新・SSOT同期。

- **アクション**:
  - `fetch`: 現在の希望条件を取得して Markdown / JSON 保存
  - `update`: 個別項目の更新（`--dry-run` 対応）
    - `--annual-income`: 希望年収（万円単位）
    - `--payload` / `--payload-file`: 希望条件JSONの直接指定
  - `sync`: `vault/tracks/domestic/strategy.md` および `vault/profile/` から希望条件を抽出して自動反映（`--dry-run` 対応）

**実行例**:
```powershell
# 1. 希望条件を取得して保存
uv run python scripts/levtech_direct/manage_profile.py condition fetch --summary

# 2. SSOT との同期内容を dry-run プレビュー
uv run python scripts/levtech_direct/manage_profile.py condition sync --dry-run --summary

# 3. 希望年収の変更を dry-run プレビュー
uv run python scripts/levtech_direct/manage_profile.py condition update --dry-run --annual-income 600 --summary
```

---

#### 4.3.5 保有スキルセクション (`skill`: `/mypage/profile/skill`)

保有スキル（スキル名・経験年数）、現在の職種、マネジメント規模等の閲覧・更新・SSOT同期。

- **アクション**:
  - `fetch`: 現在の保有スキルを取得して Markdown / JSON 保存
  - `update`: 個別項目の更新（`--dry-run` 対応）
    - `--payload` / `--payload-file`: スキルリストJSONの直接指定
  - `sync`: `vault/profile/skills.md` から保有スキル・経験年数を解析して自動反映（`--dry-run` 対応）

**実行例**:
```powershell
# 1. 保有スキルを取得して保存
uv run python scripts/levtech_direct/manage_profile.py skill fetch --summary

# 2. vault/profile/skills.md との同期内容を dry-run プレビュー
uv run python scripts/levtech_direct/manage_profile.py skill sync --dry-run --summary
```

---

#### 4.3.6 全セクション一括同期 (`sync`)

`vault/profile/` および `vault/tracks/` のSSOTから、全セクション（`basic`, `company`, `resume`, `condition`, `skill`）を一括で連続同期します。

- **オプション**:
  - `--dry-run`: 保存を実行せず全セクションの変更差分のみをプレビュー表示
  - `--sections`: 同期対象セクションのカンマ区切り指定（デフォルト: `all`）

**実行例**:
```powershell
# 1. 全セクションの一括同期差分を安全にプレビュー（dry-run）
uv run python scripts/levtech_direct/manage_profile.py sync --dry-run --summary

# 2. 対象セクションを絞って一括同期プレビュー
uv run python scripts/levtech_direct/manage_profile.py sync --sections basic,condition --dry-run --summary

# 3. 全セクションの一括同期を実行
uv run python scripts/levtech_direct/manage_profile.py sync --summary
```

---

#### 4.3.7 旧スクリプト後方互換性

既存のスクリプト実行コマンドやスキルの後方互換性を保つため、以下の旧スクリプトは `manage_profile.py` の対応サブコマンドを呼び出すラッパーとして維持されています。非推奨（Deprecated）の警告が表示されますが、従来通りの引数で呼び出し可能です。

- `scripts/levtech_direct/manage_profile_basic.py` → `manage_profile.py basic`
- `scripts/levtech_direct/manage_profile_company.py` → `manage_profile.py company`
- `scripts/levtech_direct/manage_profile_resume.py` → `manage_profile.py resume`
- `scripts/levtech_direct/manage_profile_condition.py` → `manage_profile.py condition`
- `scripts/levtech_direct/manage_profile_skill.py` → `manage_profile.py skill`

---

## 5. 実践シナリオ別ワークフロー

### シナリオ1: 高年収リモート求人の収集と他媒体との横断比較

```powershell
# 1. レバテックダイレクトから希望条件の求人を検索＆詳細ダウンロード
uv run python scripts/levtech_direct/search_jobs.py "Go" --min-salary 800 --remote "フルリモート" --download --summary

# 2. 横断検索スクリプトで全媒体（Findy, Bizreach, Forkwell, Levtech Direct等）から比較
uv run python scripts/common/search_local_jobs.py "Go" --min-salary 800 --remote "フルリモート" --summary
```

### シナリオ2: レバテックダイレクト上の新着スカウト定期巡回

```powershell
# 1. 未読・新着スカウトを確認・保存
uv run python scripts/levtech_direct/navigate_messages.py --tab unread --summary

# 2. 最新のアクティブメッセージ一覧を保存
uv run python scripts/levtech_direct/navigate_messages.py --summary
```

### シナリオ3: プロファイルの一括同期（SSOTからdry-run確認後に反映）

```powershell
# 1. 全セクションの同期差分をプレビュー確認
uv run python scripts/levtech_direct/manage_profile.py sync --dry-run --summary

# 2. 差分を確認後、実際に一括反映
uv run python scripts/levtech_direct/manage_profile.py sync --summary
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
