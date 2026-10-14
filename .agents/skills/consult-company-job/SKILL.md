---
name: consult-company-job
description: ユーザーが求人URLや企業名、またはエージェント担当者・ヘッドハンターからのスカウトや紹介内容を提示して質問・相談した際に適用。profile（職歴・希望条件・スキル・本音基準）の確認と能動的質問による追加更新、ローカルスクリプトやブラウザ操作（Playwright/sharing-browser-with-user）による企業・求人調査、人単位（リクルーター・ヘッドハンター）の評価・見極め、および chat/ や recruiters/ への構造化ログ記録・最終回答を行う。
meta:
  tag: [job-consultation, recruiter-evaluation, profile-update, browser-investigation, company-research]
  requires_repo_tools: all
  requires_env: none
  dependencies: playwright, python
  requires_install: none
  requires_hooks: none
  requires_skills: sharing-browser-with-user, using-playwright-cli, writing-rules
  status: stable
  version: 1.2.0
---

# 企業・求人・リクルーター相談・調査・評価スキル (`consult-company-job`)

ユーザーから企業名、求人URL、または特定の募集内容について質問・相談を受けた際、および**エージェント担当者・ヘッドハンターからのスカウトや求人紹介・担当者自身に関する相談**を受けた際に、以下の原則と4本柱を一体として実行するスキルです。

> [!CAUTION]
> **【重要原則・アンチパターン】求人の中身すら見ない雑なレコメンド列挙、および限定情報での決めつけ評価の完全厳禁**
> 1. **求人票の中身精査なしの列挙禁止**: 転職サイトのレコメンド一覧や検索結果から、タイトル・年収レンジ・タグだけを抜き出して機械的に並べる回答は一切の価値がない。必ず**求人票の詳細（具体的な業務内容、必須・歓迎要件、開発環境・アーキテクチャ、リモートワーク実態、組織カルチャー、足切り条件）まで中身を精査・分析**すること。
> 2. **調査範囲・エビデンスレベル（何をどこまで確かめたか）の完全明記**: 回答およびログには、必ず**自分が何をどこまで確かめたか（求人票詳細だけか、OpenWork等の口コミ・退職理由まで見たのか、WEB検索・テックブログ・IR等を横断調査したか、面談による一次情報か）**を客観的に明記すること。
> 3. **fit_score・statusの幅（レンジ）設定（決めつけ厳禁）**: 求人票は企業の「公募用・建前のスペック」に過ぎず、ネガティブな内情（高残業、レガシーコード負債、シニア不在、トップダウン、離職率など）は書かれていない。**求人情報しか見ていない状況での判断に確定的な価値はあまりないため、fit_scoreは「50〜90/100」のように必ず幅を持たせること**。「80」や「90」など確定的な数字を安易に並べて決めつけることは厳禁。調査の深まり（口コミ調査 ➔ Web横断 ➔ 一次情報面談）に応じて段階的に幅を絞り込む。statusも安易に断定せず、情報の検証度合いに応じた慎重な位置づけを行う。
> 4. **会社単位だけでなく「人単位（リクルーター・ヘッドハンター）」での評価・見極め**:
>    求人票の良し悪しだけでなく、「誰が紹介してきたか（エージェント担当者・ヘッドハンター）」に着目する。ユーザーの希望条件や足切り基準を真に理解した質の高い提案か、定型文コピペのバラ撒きや希望無視の地雷案件（SES・出社必須・激務）の押し付けかを見極め、リクルーター単位の評価・信頼度を独立して蓄積する。

## 運用の4本柱

1. **プロファイルの確認・能動的更新**:
   - 既存の `profile/`（職歴・希望条件・スキル・本音の足切り基準）を確認し、今回の求人・提案との適合度を判定。
   - **「常に積極的に質問して、ただ確認だけにとどまらず追加情報をのせることを心がける」**: ユーザーへ深掘り質問を投げかけ、新たな志向やエピソードを引き出して `profile/` を能動的に更新する。
2. **多角的・段階的な調査（エビデンスレベルの明示）**:
   - ローカル求人検索（`scripts/common/search_jobs.py`）や各種求人媒体スクリプト（Findy, BizReach, OpenWork, Forkwell, LinkedIn）を実行。
   - 求人票の詳細本文精読にとどまらず、OpenWork等の口コミ・退職理由、テックブログ、IR情報、採用ピッチ資料などをWeb検索・ブラウザ操作で調査。
   - 各段階で「確認できた事実」と「未検証の懸念事項」を明確に切り分ける。認証画面や画面調査が必要な場合は `sharing-browser-with-user` を活用。
3. **人単位（リクルーター／ヘッドハンター）の評価・見極め**:
   - 提案元エージェント担当者・ヘッドハンターの提案品質（マッチング精度、Dealbreakerへの配慮、メッセージの質）を検証。
   - 信頼できるパートナー（`recruiters/trusted/`）か、通常検討（`recruiters/active/`）か、見送り（`recruiters/declined/`）か、悪質・要注意（`recruiters/blacklisted/`）かを判定。
4. **`chat/` および `recruiters/` への構造化永続化と連携**:
   - 企業ログ [`chat/{folder}/{company-name}.md`](../../chat/) と リクルーターログ [`recruiters/{folder}/{recruiter-key}.md`](../../recruiters/) に双方向リンクを持たせて記録。
   - 面談ログは [`interviews/`](../../interviews/) に蓄積し、全体の進捗一覧は [`profile/status.md`](../../profile/status.md) で俯瞰管理する。

---

## ワークフロー手順

### Step 1: 相談内容の把握・除外重複判定と対象企業・リクルーターの特定

1. ユーザー入力から以下を特定する:
   - **企業情報**: 企業名（正式名称、通称、略称）、求人URL（提示されていれば）
   - **リクルーター情報（該当する場合）**:
     - 担当者氏名、所属エージェント（例: リクルート、JACリクルートメント、個人ヘッドハンター、企業人事）
     - 接触媒体（BizReach, LinkedIn, Findy, Levtech Direct等）
     - スカウト種別（プラチナスカウト、通常スカウト、メッセージ等）
   - **ユーザーの疑問点・相談の焦点**:
     - 求人・企業について（「マッチするか」「内情は？」「年収は？」「応募すべきか？」）
     - リクルーターについて（「このヘッドハンターと面談すべきか？」「このエージェントの提案はどう評価すべきか？」「怪しくないか？」）
2. **【必須実行】重複チェック・除外判定スクリプトの実行**:
   企業名が特定されたら、詳細調査に着手する前に必ず **`scripts/common/check_company.py`** を実行する。
   ```powershell
   python scripts/common/check_company.py --query <company-name>
   ```
   - **分岐アクション**:
     - `[EXCLUDED]`（`declined`, `rejected`, `discarded`, `blacklisted`, `employer`）:
       - 過去に見送った/不合格になった/スクリーニングで打ち切った企業、または前職・現職。
       - **不要な再調査（口コミ取得やテックブログ精査）はスキップ**し、既存ログの該当パスと却下理由（`decline_reason`）をユーザーに即座に提示する（ユーザーから「再度受けてみたい」等の再検討指示がある場合を除く）。
     - `[EXISTING]`（`active`）:
       - 既に検討中・選考中の企業。新規ログは作成せず、既存ファイル（`chat/active/{company-name}.md`）に日付付き追記を行う方針とする。
     - `[NOT FOUND]`（未登録）:
       - 新規企業として Step 2 以降の調査・プロファイル照合・ヒアリング・新規ファイル作成へ進む。
3. 識別キーの決定:
   - **企業キー (`company-name`)**: kebab-case（例: `mercari`, `smartdrive`, `graffer`）
   - **リクルーターキー (`recruiter-key`)**: `{agency-or-platform}_{name}`（例: `bizreach_yamada-taro`, `recruit_suzuki-ichiro`）
4. 既存ログの確認:
   - **企業ログ**: `check_company.py` の判定結果および `chat/*/{company-name}.md` を参照。
   - **リクルーターログ**: `recruiters/*/{recruiter-key}.md`（全サブフォルダ横断）を走査。過去に接触・評価済みであれば、過去の評価ランク（S〜D）や紹介履歴を参照する。

---

### Step 2: ユーザープロフィール（`profile/`）の確認と適合性評価

プロジェクトルートの [`profile/`](file:///c:/C/job_hunt/profile/) を確認する（`.agents/rules/user-profile.md` 準拠）。

- **確認対象ファイル**:
  - [`profile/preferences.md`](file:///c:/C/job_hunt/profile/preferences.md): 希望条件（年収、リモート比率、技術スタック、企業フェーズ、NG条件）
  - [`profile/resume.md`](file:///c:/C/job_hunt/profile/resume.md): 職務経歴書マスター
  - [`profile/skills.md`](file:///c:/C/job_hunt/profile/skills.md): スキルスタック詳細、強み、自己PR素材
  - [`profile/status.md`](file:///c:/C/job_hunt/profile/status.md): 現在の選考フェーズ、併願状況
  - [`profile/internal/criteria.md`](file:///c:/C/job_hunt/profile/internal/criteria.md): 本音の足切り基準（外部露出厳禁）
  - [`profile/internal/companies.md`](file:///c:/C/job_hunt/profile/internal/companies.md): 企業格付け・ブラックリスト（外部露出厳禁）
  - [`profile/internal/notes.md`](file:///c:/C/job_hunt/profile/internal/notes.md): 本音の転職理由メモ（外部露出厳禁）
- **照合・チェックポイント**:
  - **企業の照合**: Dealbreakers抵触有無、Must/Nice-to-have要件充足度、年収・リモート条件。
  - **リクルーターの照合**: 提示された案件がユーザーの希望条件・本音基準をどれだけ尊重しているか（足切り条件のSES・出社強制・低年収案件を無差別に投げていないか）。

---

### Step 3: 能動的質問とプロファイルの追加更新（最重要原則）

> [!IMPORTANT]
> **「常に積極的に質問して、ただ確認だけにとどまらず追加情報をのせることを心がける」**
> 単に既存のプロファイルを読み取って「合致しています」と答えるだけで終わらせてはならない。

1. **深掘り質問の投げかけ**:
   - 求人票の記述やリクルーターからのメッセージをきっかけに、プロファイルにまだ書かれていない情報を引き出す質問をユーザーへ能動的に投げかける。
   - *質問の切り口例*:
     - **技術・実績**: 「この求人では〇〇（例: Goでの分散トレーシング / Terraformでのマルチクラウド設計）が歓迎されていますが、レジュメに載っていない範囲で触れた経験や学習中のトピックはありますか？」
     - **働き方・条件**: 「この企業は週2日出社を推奨していますが、現在のフルリモート志向から許容範囲に入りますか？ `profile/preferences.md` を調整しますか？」
     - **リクルーターとの付き合い**: 「このヘッドハンターは〇〇領域に強みがあるようですが、こうしたエージェント経由での応募と直接応募のどちらを優先したいですか？」
2. **`profile/` への即時反映・追記**:
   - ユーザーからの回答や判明した新たな志向・スキル・エピソード・制約を、該当ファイルに追記する。
   - 更新時は Frontmatter の `updated_at` を当日の日付（YYYY-MM-DD）に更新する。

---

### Step 4: 企業・求人の多角的調査とリクルーター提案精度の検証

単一の情報源を鵜呑みにせず、エビデンスレベルを意識して多角的に調査する。

1. **企業・求人の多角的調査**:
   - **Level 1 (求人票詳細)**: `scripts/common/search_jobs.py` や媒体別スクリプト（Findy, BizReach, OpenWork等）で本文精査。
   - **Level 2 (口コミ・退職理由)**: `scripts/openwork/fetch_reviews.py` で残業実態、風土、退職理由を調査。
   - **Level 3 (Web横断)**: 公式ブログ、採用ピッチ、IR情報を調査。画面調査が必要な場合は `sharing-browser-with-user` を利用。
   - **Level 4 (一次情報)**: 面談・直接対話（未実施事項は論点として整理）。
2. **リクルーターの提案品質・マッチング精度の見極め**:
   - **マッチング精度 (matching_accuracy)**: ユーザーの経歴や希望に沿ったピンポイント提案か？
   - **Dealbreaker配慮 (dealbreaker_adherence)**: 出社必須やSES、年収下限未満などの足切り条件を平然と提案していないか？
   - **メッセージ品質 (communication_quality)**: レジュメを熟読した個別スカウトか、キーワード機械一致による一括バラ撒きコピペか？

---

### Step 5: ログの作成・更新と双方向連携 (`chat/` & `recruiters/`)

#### 1. 企業ログの作成・更新 ([`chat/active/{company-name}.md`](../../chat/active/))
詳細は [`.agents/rules/chat-log.md`](../../.agents/rules/chat-log.md) および [chat_template.md](references/chat_template.md) 参照。
- フロントマターにリクルーター情報を紐付ける:
  ```yaml
  recruiter: "agency_recruiter-name"
  recruiter_link: "recruiters/active/agency_recruiter-name.md"
  ```
- 調査範囲、収集データ、プロファイル適合分析（fit_scoreレンジ、例: `50〜90/100`）、ヒアリング内容、最終回答を記録。
- スクリーニング早期打ち切り企業は `chat/discarded/{YYYY-MM-DD}_{topic}.md` にバッチ記録。

#### 2. リクルーターログの作成・更新 ([`recruiters/{folder}/{recruiter-key}.md`](../../recruiters/))
詳細は [`.agents/rules/recruiter-log.md`](../../.agents/rules/recruiter-log.md) および [recruiter_template.md](references/recruiter_template.md) 参照。
- 該当リクルーターの評価ログが存在しない場合は `recruiters/active/{recruiter-key}.md` を新規作成（明らかに悪質スパムなら直接 `blacklisted/`）。
- 既に存在する場合は、`introduced_companies:` リストに今回の企業・求人・fit_score・ステータスを追記。
- 提案内容を踏まえて `matching_accuracy`、`rating`（S/A/B/C/D）、`dealbreaker_adherence`、所感を最新化。

---

### Step 6: ユーザーへの回答提示

チャット上では、以下のポイントを明確に伝える:
1. **調査スコープ・エビデンスレベルの明示**:
   - 何をどこまで確かめたか（求人票のみか、口コミ・ブログまで見たか）。
2. **fit_score と status を幅（レンジ）で提示**:
   - 単一の確定値で決めつけず、上限根拠と未検証リスクによる下限根拠を併記。
3. **リクルーターへの評価と対応方針の提示**:
   - 「このヘッドハンターの提案は希望条件をよく理解しているため、事前面談を受けてみる価値があります」
   - 「この提案は週3出社必須で希望条件とズレているため、定型文スカウトの可能性が高いです。見送り推奨です」
   - リクルーターとの付き合い方（継続・警戒・ブロック）を具体的に助言。
4. **作成・更新したログへのリンク提示**:
   - `[chat/active/{company-name}.md](file:///c:/C/job_hunt/chat/active/{company-name}.md)`
   - `[recruiters/active/{recruiter-key}.md](file:///c:/C/job_hunt/recruiters/active/{recruiter-key}.md)`
5. **能動的な追加質問の提示**: 次のアクションを後押しする質問。

---

### Step 7: 面談・選考ログの作成と連携（面談前後ワークフロー）

詳細は [`.agents/rules/interview-log.md`](../../.agents/rules/interview-log.md) 参照。

1. **企業面談**:
   - `interviews/{company-name}/{YYYY-MM-DD}_{stage}.md` に事前論点・一次情報・感想を記録し、`chat/` および `profile/status.md` と同期。
2. **リクルーター・エージェント面談**:
   - ヘッドハンターとの事前面談・キャリア相談は `interviews/recruiters/{recruiter-key}/{YYYY-MM-DD}_{stage}.md` に記録。
   - 面談で得られた市場情報や担当者の信頼度を `recruiters/{folder}/{recruiter-key}.md` に反映。
