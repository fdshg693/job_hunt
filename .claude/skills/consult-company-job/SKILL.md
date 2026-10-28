---
name: consult-company-job
description: ユーザーが求人URLや企業名、またはエージェント担当者・ヘッドハンターからのスカウトや紹介内容を提示して質問・相談した際に適用。profile（職歴・希望条件・スキル・本音基準）の確認と能動的質問による追加更新、ローカルスクリプトやブラウザ操作（Playwright/sharing-browser-with-user）による企業・求人調査、人単位（リクルーター・ヘッドハンター）の評価・見極め、転職 track（domestic / overseas）の判定、および vault/tracks/{track}/companies/ や vault/recruiters/ への構造化ログ記録・最終回答を行う。
meta:
  tag: [job-consultation, recruiter-evaluation, profile-update, browser-investigation, company-research]
  requires_repo_tools: all
  requires_env: none
  dependencies: playwright, python
  requires_install: none
  requires_hooks: none
  requires_skills: sharing-browser-with-user, using-playwright-cli, writing-rules, schedule-interview, using-job-hunt-scripts
  status: stable
  version: 2.0.0
---

<!-- 自動生成ファイル: .agents/skills/consult-company-job/SKILL.md から scripts/dev/sync_agents.py で生成。直接編集せず .agents/skills/consult-company-job/SKILL.md を編集して再同期すること -->

# 企業・求人・リクルーター相談・調査・評価スキル (`consult-company-job`)

ユーザーから企業名、求人URL、または特定の募集内容について質問・相談を受けた際、および**エージェント担当者・ヘッドハンターからのスカウトや求人紹介・担当者自身に関する相談**を受けた際に、以下の原則と4本柱を一体として実行するスキルです。

> [!CAUTION]
> **【重要原則・アンチパターン】求人の中身すら見ない雑なレコメンド列挙、および限定情報での決めつけ評価の完全厳禁**
> 1. **求人票の中身精査なしの列挙禁止**: 転職サイトのレコメンド一覧や検索結果から、タイトル・年収レンジ・タグだけを抜き出して機械的に並べる回答は一切の価値がない。必ず**求人票の詳細（具体的な業務内容、必須・歓迎要件、開発環境・アーキテクチャ、リモートワーク実態、組織カルチャー、足切り条件）まで中身を精査・分析**すること。
> 2. **調査範囲・エビデンスレベル（何をどこまで確かめたか）の完全明記**: 回答およびログには、必ず**自分が何をどこまで確かめたか（求人票詳細だけか、OpenWork等の口コミ・退職理由まで見たのか、WEB検索・テックブログ・IR等を横断調査したか、面談による一次情報か）**を客観的に明記すること。
> 3. **fit_score・statusの幅（レンジ）設定（決めつけ厳禁）**: 求人票は企業の「公募用・建前のスペック」に過ぎず、ネガティブな内情（高残業、レガシーコード負債、シニア不在、トップダウン、離職率など）は書かれていない。**求人情報しか見ていない状況での判断に確定的な価値はあまりないため、fit_scoreは `fit_score_min: 50` / `fit_score_max: 90` のように必ず幅を持たせること**。「80」や「90」など確定的な数字を安易に並べて決めつけることは厳禁。調査の深まり（口コミ調査 ➔ Web横断 ➔ 一次情報面談）に応じて段階的に幅を絞り込む。statusも安易に断定せず、情報の検証度合いに応じた慎重な位置づけを行う。
> 4. **会社単位だけでなく「人単位（リクルーター・ヘッドハンター）」での評価・見極め**:
>    求人票の良し悪しだけでなく、「誰が紹介してきたか（エージェント担当者・ヘッドハンター）」に着目する。ユーザーの希望条件や足切り基準を真に理解した質の高い提案か、定型文コピペのバラ撒きや希望無視の地雷案件（SES・出社必須・激務）の押し付けかを見極め、リクルーター単位の評価・信頼度を独立して蓄積する。

## 運用の4本柱

1. **プロファイルの確認・能動的更新**:
   - 既存の `vault/profile/`（職歴・スキル・共通の志向）と該当 track の `strategy.md`（年収・出社等）・`criteria.md`（本音の足切り基準）を確認し、今回の求人・提案との適合度を判定。
   - **「常に積極的に質問して、ただ確認だけにとどまらず追加情報をのせることを心がける」**: ユーザーへ深掘り質問を投げかけ、新たな志向やエピソードを引き出して能動的に追記する。
2. **多角的・段階的な調査（エビデンスレベルの明示）**:
   - ローカル求人検索・媒体スクリプトで求人票を精読し、さらに口コミ・退職理由、テックブログ、IR情報、採用ピッチ資料などを調査する。どのスクリプトをどの順で使うかは [`using-job-hunt-scripts`](../using-job-hunt-scripts/SKILL.md)。
   - 企業・リクルーターとのメールのやり取り（スカウト本文、日程調整、選考結果）を確かめる必要があれば、[`read-job-mail`](../read-job-mail/SKILL.md) の手順で Gmail を読み取り専用で検索・取得する（本文は `data/gmail/` にだけ保存し、ログには要約と参照だけを書く）。
   - 各段階で「確認できた事実」と「未検証の懸念事項」を明確に切り分ける。認証画面や画面調査が必要な場合は `sharing-browser-with-user` を活用。
3. **人単位（リクルーター／ヘッドハンター）の評価・見極め**:
   - 提案元エージェント担当者・ヘッドハンターの提案品質（マッチング精度、Dealbreakerへの配慮、メッセージの質）を検証。
   - 信頼できるパートナー（`status: trusted`）か、通常検討（`active`）か、見送り（`declined`）か、悪質・要注意（`blacklisted`）かを判定。
4. **`vault/` への構造化永続化と連携**:
   - 企業ログ `vault/tracks/{track}/companies/{company-key}/index.md` と リクルーターログ `vault/recruiters/{recruiter-key}/index.md` に双方向リンクを持たせて記録。
   - 面談ログは各フォルダに `{YYYY-MM-DD}_{stage}.md` として同居させ、全体の進捗一覧は track の `pipeline.md`（`scripts/vault/build_pipeline.py` で生成）で俯瞰管理する。

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
2. **転職 track の判定**（[`.agents/rules/tracks.md`](../../rules/tracks.md)）:
   - **雇用・契約主体が日本法人**（外資系企業の日本法人を含む）なら `domestic`。
   - **日本国外の法人に雇用・契約される**（現地就労・リロケーション・海外企業へのフルリモート勤務を含む）なら `overseas`。
   - 求人票から雇用主体が判別できない場合はユーザーに確認する。
3. **【必須実行】重複チェック・除外判定スクリプトの実行**:
   企業名が特定されたら、詳細調査に着手する前に必ず **`scripts/common/check_company.py`** を判定した track 指定で実行する。
   ```powershell
   uv run python scripts/common/check_company.py --track <domestic|overseas> -s <company-name>
   ```
   - **分岐アクション**:
     - `[EXCLUDED]`（同一 track の `declined`, `rejected`, `discarded`、全 track 共通の `blacklisted`, `employer`）:
       - 過去に見送った/不合格になった/スクリーニングで打ち切った企業、ブラックリスト企業、または前職・現職。
       - **不要な再調査（口コミ取得やテックブログ精査）はスキップ**し、既存ログの該当パスと却下理由（`decline_reason`）をユーザーに即座に提示する（ユーザーから「再度受けてみたい」等の再検討指示がある場合を除く）。
       - 見送り台帳（`archive.md`）由来のときは、見送り理由（`reason`）と再検討条件（`reconsider_if`）を提示し、今回の求人でその条件が変わっていそうなら再検討を提案する。再検討する場合は台帳エントリを消してから新フォルダを作る（`.agents/rules/company-log.md` の「見送り企業の圧縮」）。
     - `[OTHER TRACK]`:
       - 別 track で履歴がある企業。除外扱いにはせず、過去ログと理由を参考情報として提示した上で、この track の条件で改めて判断する（新規フォルダはこの track 側に作る）。
     - `[EXISTING]`（active 系ステータス）:
       - 既に検討中・選考中の企業。新規ログは作成せず、既存の `index.md` に日付付き追記を行う方針とする。
     - `[NOT FOUND]`（未登録）:
       - 新規企業として Step 2 以降の調査・プロファイル照合・ヒアリング・新規ファイル作成へ進む。
4. 識別キーの決定:
   - **企業キー (`company-name`)**: kebab-case（例: `mercari`, `smartdrive`, `graffer`）
   - **リクルーターキー (`recruiter-key`)**: `{agency-or-platform}_{name}`（例: `bizreach_yamada-taro`, `recruit_suzuki-ichiro`）
5. 既存ログの確認:
   - **企業ログ**: `check_company.py` の判定結果（参照ファイル）および `vault/tracks/{track}/companies/{company-key}/` を参照。
   - **リクルーターログ**: `vault/recruiters/{recruiter-key}/index.md` を確認（キーが不明なら `vault/recruiters/*/index.md` の `name:` / `agency:` を検索）。過去に接触・評価済みであれば、過去の評価ランク（S〜D）や紹介履歴を参照する。

---

### Step 2: ユーザープロフィールと track 条件の確認・適合性評価

`vault/profile/`（人の共通情報）と該当 track のファイルを確認する（`.agents/rules/user-profile.md` 準拠。パスはリポジトリルート相対）。

- **確認対象ファイル**:
  - `vault/profile/preferences.md`: 共通の志向軸（職種、技術志向、ドメイン観、共通NG）
  - `vault/profile/resume.md`: 職務経歴書マスター
  - `vault/profile/skills.md`: スキルスタック詳細、強み、自己PR素材
  - `vault/profile/tech/areas/`・`tech/projects/`: 技術領域ごとの理解度（`depth`・説明できないこと）とプロジェクトの細部。求人の技術要件と照らし合わせる際に見る
  - `vault/tracks/{track}/strategy.md`: track 固有の希望条件（年収、出社・勤務地、企業フェーズ、英語環境の位置づけ）
  - `vault/tracks/{track}/pipeline.md`: 現在の選考フェーズ、併願状況
  - `vault/tracks/{track}/criteria.md`: 本音の足切り基準（外部露出厳禁）
  - `vault/tracks/{track}/ratings.md`: 企業格付け・ブラックリスト（外部露出厳禁）
  - `vault/profile/internal/notes.md`: 本音の転職理由メモ（外部露出厳禁）
- **照合・チェックポイント**:
  - **企業の照合**: Dealbreakers抵触有無、Must/Nice-to-have要件充足度、年収・リモート条件。
  - **技術要件の照合**: 必須/歓迎の技術を `tech/areas/` の `depth` と「説明できないこと・未経験」で照らす。ノートが無い・浅い領域は、Step 3 のヒアリングで経験を聞き、ノートの追記を提案する対象にする。
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
     - **働き方・条件**: 「この企業は週2日出社を推奨していますが、現在のフルリモート志向から許容範囲に入りますか？ `strategy.md` を調整しますか？」
     - **リクルーターとの付き合い**: 「このヘッドハンターは〇〇領域に強みがあるようですが、こうしたエージェント経由での応募と直接応募のどちらを優先したいですか？」
2. **プロフィール・track 条件への即時反映・追記**:
   - ユーザーからの回答や判明した新たな志向・スキル・エピソード・制約を、該当ファイルに追記する。共通の志向・スキルは `vault/profile/`、年収・出社・足切りなど track 固有の条件は `vault/tracks/{track}/strategy.md` / `criteria.md`（迷ったら track 側）。
   - 更新時は Frontmatter の `updated_at` を当日の日付（YYYY-MM-DD）に更新する。

---

### Step 4: 企業・求人の多角的調査とリクルーター提案精度の検証

単一の情報源を鵜呑みにせず、エビデンスレベルを意識して多角的に調査する。

1. **企業・求人の多角的調査**:
   使うスクリプトは [`using-job-hunt-scripts`](../using-job-hunt-scripts/SKILL.md) の「求人詳細を取る」「企業を調べる」。
   - **Level 1 (求人票詳細)**: 求人票の本文を精査する。
   - **Level 2 (口コミ・退職理由)**: OpenWork の口コミで残業実態、風土、退職理由を調査。
   - **Level 3 (Web横断・企業資料)**: 公式ブログ、IR情報、ニュースを調査。画面調査が必要な場合は `sharing-browser-with-user` を利用。
     - **資料の要約は `materials/` に残す**: 判断に使った資料は `scripts/vault/add_material.py <URL> -c <company-key> -s` で要約を作り `links` から辿れるようにする（生データの `data/` は保持期間で消える）。既存の要約を見直すときは `--refresh` で生データを取り直してから直し、`fetched_at` を今日にする（[`docs/vault/materials.md`](../../../docs/vault/materials.md)）。本文から `data/` を直接参照しない。
     - **Speaker Deck（スライド検索・文字起こし取得）**:
       - 会社名や技術スタックで会社紹介資料・採用ピッチ・登壇資料を検索し、深掘りするスライドだけ文字起こしを取得して中身を確認する。
       - **確認タイミングの原則**:
         - *初回（求人票・スカウトの初期スクリーニング時）*: **基本は見に行かなくてよい**（調査コスト抑制と情報過多防止のため）。
         - *カジュアル面談前*: **見に行くべき**。逆質問の準備、事業モデル・開発体制・AI活用・組織カルチャーの解像度を高め、面談でのミスマッチを防ぐため。
         - *スカウトを受けるか迷うようなタイミング*: **見に行くべき**。求人票やスカウト文面のスペックだけでは魅力や内情が掴めず当落線上の場合に、スライド資料の一次情報を深掘りして受託/辞退を判断するため。
   - **Level 4 (一次情報)**: 面談・直接対話、企業・リクルーターとのメール（`read-job-mail`）（未実施事項は論点として整理）。
2. **リクルーターの提案品質・マッチング精度の見極め**:
   - **マッチング精度 (matching_accuracy)**: ユーザーの経歴や希望に沿ったピンポイント提案か？
   - **Dealbreaker配慮 (dealbreaker_adherence)**: 出社必須やSES、年収下限未満などの足切り条件を平然と提案していないか？
   - **メッセージ品質 (communication_quality)**: レジュメを熟読した個別スカウトか、キーワード機械一致による一括バラ撒きコピペか？

---

### Step 5: ログの作成・更新と双方向連携 (`vault/tracks/{track}/companies/` & `vault/recruiters/`)

#### 1. 企業ログの作成・更新（`vault/tracks/{track}/companies/{company-key}/index.md`）
詳細は [`.agents/rules/company-log.md`](../../rules/company-log.md) および [company_template.md](references/company_template.md) 参照。
- フロントマターに `track` を必ず記入し、配置先 track と一致させる。
- ステータスはフロントマターの `status` のみで管理する（辞退・不合格でもフォルダは移動しない）。
- リクルーター経由の場合はフロントマターにリクルーターキーを紐付ける（`recruiter: "agency_recruiter-name"`）。
- 調査範囲、収集データ、プロファイル適合分析（fit_score はレンジで `fit_score_min` / `fit_score_max` に書く。例: 50〜90）、ヒアリング内容、最終回答を記録。
- スクリーニング早期打ち切り企業は `vault/tracks/{track}/screening/{YYYY-MM-DD}_{topic}.md` にバッチ記録。
- フロントマターのキー・許容値は [`docs/vault/schema.md`](../../../docs/vault/schema.md)（生成物）を見る。年収は万円の整数（`salary_min` / `salary_max`）、勤務形態は `remote_type` enum ＋ `office_days_per_week`、補足は各 `*_note` に書く。

#### 2. リクルーターログの作成・更新（`vault/recruiters/{recruiter-key}/index.md`）
詳細は [`.agents/rules/recruiter-log.md`](../../rules/recruiter-log.md) および [recruiter_template.md](references/recruiter_template.md) 参照。
- 該当リクルーターの評価ログが存在しない場合は `vault/recruiters/{recruiter-key}/index.md` を `status: active` で新規作成（明らかに悪質スパムなら `blacklisted`）。
- 既に存在する場合は、`introduced_companies:` リストに今回の企業（企業ログがあれば `company_key`、無ければ `note` に所感）を追記し、紹介企業の track が `tracks:` に無ければ追加する。
- 提案内容を踏まえて `matching_accuracy`、`rating`（S/A/B/C/D）、`dealbreaker_adherence`、所感を最新化。

#### 3. 検証とダッシュボード再生成（ログを書いたら毎回）
1. `uv run python scripts/vault/validate.py` — スキーマ違反・フォルダ名との不一致・存在しないリクルーターキー等を検出する。エラーが0になるまで直す（`--summary` で一覧表示）。
2. `uv run python scripts/vault/build_pipeline.py --track {track}` — `pipeline.md` の選考企業一覧を再生成する。
- Web UI（`uv run python -m webui`）の索引は正本の変更を検知して自動で作り直されるため、追加の操作は不要。

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
   - `vault/tracks/{track}/companies/{company-key}/index.md`
   - `vault/recruiters/{recruiter-key}/index.md`
5. **能動的な追加質問の提示**: 次のアクションを後押しする質問。

---

### Step 7: 面談・選考ログの作成と連携（面談前後ワークフロー）

詳細は [`.agents/rules/interview-log.md`](../../rules/interview-log.md) 参照。

1. **企業面談**:
   - 日程調整（候補日出し・返信下書き）、日程確定時のカレンダー登録、リスケ・辞退時の予定の更新・削除は [`schedule-interview`](../schedule-interview/SKILL.md) に従う。面談が確定したらカレンダー登録をユーザーに提案する。
   - カジュアル面談前の事前準備として、Speaker Deckの会社紹介資料等があれば `scripts/speakerdeck/fetch_deck.py` で文字起こしを確認し（既に `materials/` に要約があり古ければ `add_material.py --refresh` で取り直して見直す）、事業・開発体制を踏まえた逆質問や深掘り論点を整理する。
   - 企業フォルダ `vault/tracks/{track}/companies/{company-key}/{YYYY-MM-DD}_{stage}.md` に事前論点・一次情報・感想を記録し、同フォルダの `index.md` と track の `pipeline.md` に同期。
2. **リクルーター・エージェント面談**:
   - ヘッドハンターとの事前面談・キャリア相談は `vault/recruiters/{recruiter-key}/{YYYY-MM-DD}_{stage}.md` に記録。
   - 面談で得られた市場情報や担当者の信頼度を同フォルダの `index.md` に反映。
