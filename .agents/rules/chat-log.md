---
trigger: model_decision
description: ユーザーから企業名や求人URLについて質問・相談を受け調査・回答する際、または chat/ 配下の求人相談ログを作成・参照・更新する際に適用
---

# 求人相談・調査ログ (`chat/`) 運用ルール

ユーザーからの特定の企業・求人に関する質問・相談を受け、調査および回答を行う際は、プロジェクトルートの [`chat/`](../../chat/) ディレクトリ配下に企業別ログを作成・蓄積します。

## 目的と位置づけ

- 個別の企業・求人に関するユーザーからの相談内容、実施した多角的調査、プロファイル更新履歴、最終回答を永続化する。
- 企業ごとの**最新状況を簡潔にまとめたメインファイル**として機能する（詳細な面談メモ・生ログ・一次情報は [`interviews/{company-name}/`](../../interviews/) に蓄積し、相互にリンクする）。
- 検索性（Frontmatterメタデータやキーワード検索）を高く保ち、後から選考状況や他社比較に再利用可能とする。
- 関連スキル: [`consult-company-job`](../skills/consult-company-job/SKILL.md)
- 関連ルール: [面談詳細ログルール](interview-log.md), [リクルーター評価ログルール](recruiter-log.md)

## 状態別サブフォルダ構成（必須）

`chat/` 直下には [`README.md`](../../chat/README.md) のみを置き、個別企業ログは状態に応じて以下のサブフォルダに格納する。

| フォルダ | 意味 | 配置基準 |
|---|---|---|
| `chat/active/` | 検討中 | `status` が unverified / researching / considering / low_priority / applied / casual_interview / first_interview / passed / on_hold |
| `chat/rejected/` | 選考で落とされた（企業側の判断） | 書類落ち・面談後/面接後に企業から不合格通知を受けた（`status: rejected`） |
| `chat/declined/` | 自分から見送り・辞退（ユーザー側の判断） | カジュアル面談の前後を問わず、興味喪失・足切り抵触等でユーザーが見送り/辞退した（`status: declined`） |
| `chat/employer/` | 前職・現職など特別枠 | 前職・現職企業（例: `headwaters.md`, `plus-alpha-consulting.md`）。ステータスに関わらずここに固定 |
| `chat/discarded/` | スクリーニング打ち切りの集約ログ | 下記「早期打ち切り集約ログ」参照 |

- **新規作成は `chat/active/` が既定**。前職・現職の企業のみ最初から `employer/`。
- **移動ルール**: ステータスが変わり「いらなくなった」時点で、`git mv chat/active/{company-name}.md chat/{rejected|declined}/` で移動し、フロントマターの `status` / `status_note` / `updated_at` を更新する。
- **`rejected` と `declined` の区別**: 企業が決めた＝`rejected`、自分が決めた＝`declined`。判断に迷う場合はユーザーに確認する。旧来 `status: rejected` と書かれていてもユーザー主導の見送りなら `declined` に補正する。
- **移動時の整合性**: ファイル内の相対リンク（`../../interviews/...` など、`chat/{folder}/` からの深さ）、`interviews/*` の `chat_log`、`profile/status.md`・`profile/internal/companies.md` 内のリンクパスも同時に更新する。
- **検索**: 企業ログの存在確認は `chat/*/{company-name}.md`（全サブフォルダ横断）で行う。

## ファイル命名規則

- **個別企業ログ（詳細調査・通常相談）**:
  - **パス形式**: `chat/{active|rejected|declined|employer}/{company-name}.md`
  - **命名規則**:
    - 企業名（英数字小文字ハイフン区切り、kebab-case）を原則とする（例: `chat/active/mercari.md`, `chat/active/smartdrive.md`, `chat/active/line-yahoo.md`）。
    - 日本語社名等の場合は代表的な略称・アルファベット表記を優先し、一意に定まるようにする。
  - **再相談・継続履歴の集約**:
    - 同一企業について再度相談や追加質問があった場合は、別ファイルを作成せず既存の `chat/*/{company-name}.md` に日付付き見出し（例: `### 追記: 2026-10-15`）を追加して追記・更新する。
- **スクリーニング早期打ち切り・見送り集約ログ（サブフォルダ運用）**:
  - **パス形式**: `chat/discarded/{YYYY-MM-DD}_{topic}.md`
  - **位置づけ**:
    - 求人票の一次スクリーニング等で、足切り条件（Dealbreakers）抵触や志向不一致により「旨味がなさそうで細かい調査まで行わずに早めに打ち切った企業」は、1社1ファイルにせず**調査バッチごとに1ファイルにまとめて記録**する（1社ごとの個別ファイル作成による肥大化を防ぎつつ、打ち切り理由を確実に蓄積する）。
  - **重複調査防止のためのフロントマター仕様**:
    - ファイル先頭の `companies:` リストに対象社名を漏れなく列挙する。
    - 次回以降の未調査企業抽出時には、`chat/*/*.md`（active/rejected/declined/employer）に加え、`chat/discarded/*.md` の `companies` も走査・照合することで、すでにスクリーニング済みの企業を重複して調査しないようにする。

## 重複チェックと除外判定（相談開始時の必須実行）

ユーザーから企業名や求人URLについて質問・相談を受けた際は、求人票精査や詳細調査、ログ作成に着手する前に必ず **`scripts/common/check_company.py`** を実行して重複・除外判定を行う。

```powershell
python scripts/common/check_company.py --query <company-name>
```

- **判定結果に応じた振る舞い**:
  - `[EXCLUDED]`（`declined`, `rejected`, `discarded`, `blacklisted`, `employer`）:
    - 過去に見送った企業、不合格になった企業、スクリーニングで打ち切った企業、または前職・現職企業。
    - 即座に過去の経緯・却下理由（`decline_reason`）および既存ログの該当箇所を提示し、不要な再調査コストを回避する（ユーザーが再検討を指示した場合を除く）。
  - `[EXISTING]`（`active`）:
    - 既に検討中・選考中の企業。新規ファイルは作らず、既存の `chat/active/{company-name}.md` に日付付き見出しを追加して追記する。
  - `[NOT FOUND]`（未登録）:
    - 新規企業として通常通り調査を進め、`chat/active/{company-name}.md` を新規作成する。

## フロントマター仕様

検索性・フィルタリングを担保するとともに、調査深度と不確実性を反映するため、ファイル先頭に以下のYAMLフロントマターを必ず付与する。

```yaml
---
company: "株式会社〇〇"
company_key: "company-name"
aliases:                  # 企業名の別名・略称・英語表記・通称リスト
  - "〇〇"
  - "Example Inc."
date: "YYYY-MM-DD"        # 初回相談日
updated_at: "YYYY-MM-DD"  # 最終更新日
job_url: "https://..."     # 対象求人URL
job_title: "職種名"
sources:                  # 参照した情報源（媒体・サイト）
  - "findy"
  - "openwork"
  - "corporate_site"
evidence_level: "reviews_verified" # job_post_only | web_researched | reviews_verified | interview_verified
verified_items:           # 確認できた事項
  - "求人票詳細（必須/歓迎要件、提示給与、リモート規定）"
  - "OpenWork口コミ（組織風土、退職理由、残業実態）"
unverified_items:         # 未検証・今後確かめるべき事項
  - "実コードベース品質・技術的負債の実態"
  - "現場のシニアエンジニア稼働実態"
tags:                     # 技術スタック、業界、勤務形態等の検索用タグ
  - "Go"
  - "AWS"
  - "フルリモート"
status: "considering"     # unverified | researching | considering | applied | casual_interview | first_interview | passed | on_hold | rejected（企業に落とされた）| declined（自分から見送り・辞退）
status_note: "求人条件・口コミ良好。実開発体制の確認待ち"
decline_reason: "技術スタック不一致（レガシーPHP中心）、年収レンジ上限不足" # declined または rejected の場合の理由
salary_range: "800万円〜1,100万円"
remote_type: "フルリモート"
fit_score: "65〜85/100"   # 必ず幅（レンジ）を持たせる。求人票のみの段階で確定値の決め打ちは厳禁（例: 50〜90/100）
fit_summary: "技術スタック・条件面は高合致。求人票＋口コミ段階の暫定評価であり、実開発体制により上下の可能性あり"
interview_dir: "interviews/company-name/" # 詳細面談ログが存在する場合のパス
recruiter: "bizreach_yamada-taro" # エージェント/ヘッドハンター経由の場合のリクルーターキー
recruiter_link: "recruiters/active/bizreach_yamada-taro.md" # リクルーター評価ログへのリンク
---
```

### スクリーニング早期打ち切り集約ログ (`chat/discarded/`) フロントマター仕様

```yaml
---
date: "YYYY-MM-DD"
type: "discarded_batch"
topic: "調査・スクリーニングのテーマ"
companies:
  - name: "株式会社〇〇"
    aliases:
      - "〇〇"
    reason: "自社開発ではなく受託開発メインのため見送り"
  - name: "△△株式会社"
    reason: "出社週3日必須のため足切り"
---
```
- `companies`: 打ち切り対象となった企業をYAMLリストで完全列挙する。構造化オブジェクト（`name`, `aliases`, `reason`）を標準とし、単一文字列形式も許容する。未調査企業スクリーニングや重複チェックエンジン（`scripts/common/check_company.py`）が本リストを参照し、調査済み（見送り済み）として重複判定できるようにする。

## 本文セクション構成

以下の5セクションを標準として構成する。

1. `# {company} 求人相談・調査ログ`
2. `## 1. 相談・リクエスト内容`: ユーザーが提示したURL、社名、紹介元リクルーター/エージェント（該当する場合）、質問の焦点や懸念点
3. `## 2. 実施した調査と検証スコープ（何をどこまで確かめたか）`:
   - **調査スコープチェックリスト**:
     - [x] 求人票詳細（Findy / BizReach等）
     - [x] / [ ] 口コミ・退職理由（OpenWork等）
     - [x] / [ ] 企業発信情報・WEB調査（テックブログ、採用ピッチ、IR）
     - [ ] 面談による一次情報（未実施・未検証事項）
   - **収集データ**: 雇用条件・技術環境・組織カルチャー（各ツールの実行結果・口コミ分析）
   - **プロフィール（`profile/`）との照合・ギャップ分析**: Dealbreakers判定、志向軸照合
   - **暫定適合度スコア（レンジ理由）**: 上限の根拠と、未検証の内情リスクによる下振れ幅を明記
4. `## 3. ユーザープロファイル確認・更新（深掘りヒアリング）`:
   - ユーザーへ投げかけた能動的な追加質問
   - ユーザーからの回答および得られた新情報
   - `profile/`（`preferences.md`, `skills.md`, `resume.md`, `status.md`, `internal/`）への反映内容と更新差分
5. `## 4. 最終回答・総合所見`:
   - ユーザーへのダイレクトな回答・推奨度（レンジ表示）
   - メリット・魅力 / 懸念点・リスク
   - 未検証事項（今後確かめるべき論点）
   - 次のアクション提案（カジュアル面談、応募、様子見など）
6. `## 5. 選考・面談サマリ（進捗時）`:
   - カジュアル面談や各次面接の実施結果サマリ
   - 各回の詳細メモ・一次情報へのリンク（`[カジュアル面談メモ (2026-10-15)](../interviews/{company-name}/2026-10-15_casual.md)`）

## 遵守すべき必須原則

1. **調査範囲・エビデンスレベルの完全明記**:
   - 必ず「何をどこまで確かめたか（求人票のみか、口コミまで見たか、Web横断か、一次情報か）」を客観的に明記すること。
   - 確認できた事実と、未検証の懸念事項を明確に切り分ける。
2. **fit_score・statusの幅（レンジ）管理（決めつけ厳禁）**:
   - 求人票は企業の「公募用・建前のスペック」であり、ネガティブな内情は書かれていない。求人情報しか見ていない状況での判断に確定的な価値はないため、**fit_scoreは必ず「50〜90/100」のように幅を持たせること**。
   - 口コミ調査・Web調査・面談進行に伴い段階的に幅を絞り込む。安易に「85点」や「95点」など断定的な数字を並べない。
   - statusも情報の検証度合いに応じた慎重な位置づけを行う。
3. **プロファイルの能動的更新（最重要）**:
   - 単に `profile/` を参照して照合するだけで終わらせてはならない。
   - 求人票の記述（必須/歓迎要件、働き方、カルチャーなど）をトリガーに、**常にユーザーへ積極的に質問を投げかけ、まだ書かれていない志向やエピソードを引き出して `profile/` に追加情報を書き込む**こと。
4. **多角的な調査の実施**:
   - ローカル求人DB（`scripts/common/search_jobs.py`）、スクリプト実行（Findy, BizReach, OpenWork等）、ブラウザ・Web調査（採用ページ、テックブログ、評判等）を適宜組み合わせて調査する。
   - 必要に応じて `sharing-browser-with-user` を利用し、画面調査や認証セッションを活用する（`.agents/rules/playwright-action.md` 遵守）。
5. **機密情報の管理**:
   - `profile/internal/`（足切り基準や本音メモ）は内部照合・意思決定支援に用いるが、外部提出・連絡用文章の生成時には露出させないこと。
