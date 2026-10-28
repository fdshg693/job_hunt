<!-- 自動生成ファイル: .agents/rules/company-log.md から scripts/dev/sync_agents.py で生成。直接編集せず .agents/rules/company-log.md を編集して再同期すること -->

> **適用条件**: ユーザーから企業名や求人URLについて質問・相談を受け調査・回答する際、または vault/tracks/*/companies/・vault/tracks/*/screening/ 配下の企業ログを作成・参照・更新する際に適用

# 企業調査・求人相談ログ (`vault/tracks/{track}/companies/`) 運用ルール

ユーザーからの特定の企業・求人に関する質問・相談を受け、調査および回答を行う際は、該当 track の [`vault/tracks/{track}/companies/`](../../vault/tracks/) 配下に**1社1フォルダ**で企業ログを作成・蓄積します。track の定義・振り分け基準は [tracks.md](tracks.md) を参照。

## 目的と位置づけ

- 個別の企業・求人に関するユーザーからの相談内容、実施した多角的調査、プロファイル更新履歴、最終回答を永続化する。
- 企業フォルダの `index.md` は企業ごとの**最新状況を簡潔にまとめたメインファイル**として機能する。各回の面談・面接の詳細メモは同じフォルダに `{YYYY-MM-DD}_{stage}.md` として同居させる（[面談詳細ログルール](interview-log.md)）。
- 検索性（フロントマターやキーワード検索）を高く保ち、後から選考状況や他社比較に再利用可能とする。
- 関連スキル: [`consult-company-job`](../skills/consult-company-job/SKILL.md)
- 関連ルール: [track 運用ルール](tracks.md), [面談詳細ログルール](interview-log.md), [リクルーター評価ログルール](recruiter-log.md)

## ディレクトリ構成

```
vault/tracks/{track}/
├── companies/{company-key}/
│   ├── index.md                     # 企業ログ（調査・相談・最新状況サマリ）
│   ├── application.md               # 応募書類の応募先別記入事項（志望動機等。export_rirekisho.py が読む）
│   ├── materials/                   # 外部資料要約Markdown（スライド文字起こし、記事要約等）
│   │   └── {slug}.md
│   └── {YYYY-MM-DD}_{stage}.md      # 面談・選考詳細ログ（interview-log.md）
├── screening/{YYYY-MM-DD}_{topic}.md  # スクリーニング早期打ち切りの集約ログ
├── archive.md                       # 見送り台帳（終了企業・古いスクリーニングを 1 社数行に圧縮）
└── pipeline.md                      # 選考ダッシュボード（build_pipeline.py で一覧を生成）
vault/profile/employers/{company-key}.md  # 前職・現職（track 非依存、status: employer）
```

- **ステータスはフロントマターの `status` のみで管理する**。ステータスによるフォルダ分け・`git mv` による移動は行わない（辞退・不合格になってもフォルダはそのまま。一定期間後に見送り台帳へ圧縮する。後述）。
- **外部資料（`materials/`）**: 採用ピッチスライドの文字起こしやテックブログ・インタビュー等の要約を置く。**配置するのは Markdown のみ**とし、画像やPDF原本などの生バイナリは置かない（生データは `data/` に置き、保持期間を過ぎると消える）。流れ・日付は必須原則 7。
- **前職・現職**は選考対象ではなく経歴の一部のため、track 配下ではなく [`vault/profile/employers/`](../../vault/profile/employers/) に置き、`status: "employer"` とする。
- **新規作成**: `vault/tracks/{track}/companies/{company-key}/index.md`。track は相談開始時に [tracks.md](tracks.md) の基準で判定する。

## 命名規則

- **企業キー (`company-key`)**: 企業名の英数字小文字ハイフン区切り（kebab-case）。例: `mercari`, `smartdrive`, `line-yahoo`。日本語社名は代表的な略称・アルファベット表記を優先し、一意に定める。フォルダ名とフロントマター `company_key` を一致させる。
- **再相談・継続履歴**: 同一企業への再相談は別ファイルを作らず、既存 `index.md` に日付付き見出し（例: `### 追記: 2026-10-15`）で追記する。
- **同一企業が両 track に現れる場合**（例: 国内で辞退した企業の海外拠点ポジション）は、各 track に別フォルダを作り、`index.md` 本文で相互に相対リンクする。

## スクリーニング早期打ち切り集約ログ (`screening/`)

- **パス**: `vault/tracks/{track}/screening/{YYYY-MM-DD}_{topic}.md`
- 求人票の一次スクリーニング等で、足切り条件（その track の `criteria.md`）抵触や志向不一致により「細かい調査まで行わずに早めに打ち切った企業」は、1社1フォルダにせず**調査バッチごとに1ファイル**にまとめて記録する。
- ファイル先頭の `companies:` リストに対象社名を漏れなく列挙する。`check_company.py` がこのリストを走査し、スクリーニング済み（`discarded`）として重複判定する。
- 古いバッチは企業フォルダと同じ周期で見送り台帳（`archive.md`）に畳み込み、ファイルは消す（後述）。

## 見送り企業の圧縮（見送り台帳 `archive.md`）

終了した企業フォルダ（index.md ＋面談ログ）は見送りのたびに増えるので、一定期間を過ぎたら track ごとの見送り台帳 `vault/tracks/{track}/archive.md` に **1 社数行**で圧縮し、フォルダは `git rm` する（詳細は git 履歴に残る）。台帳はフロントマターの `companies` が正（スキーマは `docs/vault/schema.md` の `ArchiveDoc` / `ArchivedCompany`）。

- **対象**: `declined` / `rejected` / `blacklisted` で `updated_at` から 14 日（既定）経過した企業フォルダと、同じ期間を過ぎたスクリーニングバッチ。見送り直後は再提案・振り返りで詳細を見直すことがあるので、すぐには畳まない。データが少ないうちはユーザーの判断で早めに畳んでもよい（`--key` で期間に関係なく個別に圧縮できる）。
- **タイミング**: 定期実行はしない。相談やパイプライン整理のついでに `list` を流し、候補があればユーザーに圧縮を提案する。どれを畳むかはユーザーが決める。雑務整理スキル [`sweep-chores`](../skills/sweep-chores/SKILL.md)（`scripts/vault/find_chores.py`）でも圧縮候補が `compact` として出る。
- **手順**（[`scripts/vault/compact_closed.py`](../../scripts/vault/compact_closed.py)）:
  ```powershell
  uv run python scripts/vault/compact_closed.py list --track domestic --summary          # 候補一覧
  uv run python scripts/vault/compact_closed.py draft --key <company-key> --summary      # 要約の材料（index.md・面談ログ）とエントリ下書き
  uv run python scripts/vault/compact_closed.py apply --key <company-key> --reason "..." --reconsider-if "..."  # 台帳に追記して git rm
  uv run python scripts/vault/compact_closed.py apply --screening vault/tracks/domestic/screening/<file>.md     # バッチを機械的に畳み込む
  ```
  `apply` は未コミットの変更があるフォルダを拒否するので、先にコミットしておく。終わったら `validate.py` と `build_pipeline.py --track {track}` を流す。
- **エントリに書く本質**: `reason` は「何が合わなかったか」を**条件の言葉で** 1〜2 文（例: 「週3出社必須」「業務の中心がレガシー保守」）。会社の説明や経緯は書かない。`reconsider_if` には「何が変われば再検討してよいか」を書く。再相談のとき、その条件が今も変わっていないかを確かめるだけで判断できるようにするため。`decline_reason` を写すだけにせず、面談ログがあれば読んで本当の見送り理由を拾う。要約は AI が書き、ユーザーの確認を取ってから `apply` する。
- **学びの吸収確認**: 圧縮のたびに「この見送りで初めて分かった条件・志向」が無いかを確認し、あれば台帳ではなく `vault/profile/`（`preferences.md` 等）や track の `criteria.md` への追記をユーザーに提案する（振り分けは [user-profile.md](user-profile.md)）。一般化できる学びを台帳に閉じ込めない。
- **リクルーターログ**の `introduced_companies` の `company_key` は書き換えない（台帳のキーで解決される）。
- **再検討することになった会社**は、台帳のエントリを消してから新しい企業フォルダを作り、新 `index.md` の「1. 相談・リクエスト内容」に台帳の要約（見送り理由・再検討条件）を引き写す。台帳と企業フォルダに同じキーが同時にあると検証エラーになる。

## 重複チェックと除外判定（相談開始時の必須実行）

ユーザーから企業名や求人URLについて質問・相談を受けた際は、求人票精査や詳細調査、ログ作成に着手する前に必ず **`scripts/common/check_company.py`** を、判定した track を指定して実行する。

```powershell
uv run python scripts/common/check_company.py --track domestic -s <company-name>
```

- **判定結果に応じた振る舞い**:
  - `[EXCLUDED]`（同一 track の `declined`, `rejected`, `discarded`、および全 track 共通の `blacklisted`, `employer`）:
    - 過去に見送った企業、不合格になった企業、スクリーニングで打ち切った企業、ブラックリスト企業、または前職・現職企業。出所は企業フォルダ・スクリーニング集約ログ・見送り台帳（`archive.md`）・`vault/profile/employers/`。
    - 即座に過去の経緯・却下理由（`decline_reason`、台帳由来なら `reason` と再検討条件 `reconsider_if`）および既存ログの該当箇所を提示し、不要な再調査コストを回避する（ユーザーが再検討を指示した場合を除く）。
  - `[OTHER TRACK]`:
    - 別 track で履歴がある企業（例: 国内で週3出社を理由に辞退した企業の海外ポジション）。除外扱いにはせず、過去ログと理由を参考情報として提示した上で、この track の条件で改めて判断する。
  - `[EXISTING]`（active 系ステータス）:
    - 既に検討中・選考中の企業。新規フォルダは作らず、既存 `index.md` に日付付き見出しで追記する。
  - `[NOT FOUND]`（未登録）:
    - 新規企業として通常通り調査を進め、`vault/tracks/{track}/companies/{company-key}/index.md` を新規作成する。

## フロントマター仕様

- キー・型・許容値の正は [`scripts/vault/schema/`](../../scripts/vault/schema/)。一覧は生成物 [`docs/vault/schema.md`](../../docs/vault/schema.md)（企業ログは `CompanyDoc`、スクリーニング集約ログは `ScreeningBatchDoc`）を見る。このルールにフィールド表は書かない（[vault-schema.md](vault-schema.md)）。
- 新規作成はテンプレート [company_template.md](../skills/consult-company-job/references/company_template.md) から始める。
- 作成・更新したら `uv run python scripts/vault/validate.py` を実行してエラー0にし、続けて `uv run python scripts/vault/build_pipeline.py --track {track}` で `pipeline.md` を再生成する。

### 値の決め方（スキーマで表せない運用方針）

- **`status` は必ず記入する**。値の意味・分類（進行中 / 終了 / 除外）・除外範囲は `docs/vault/schema.md` の `CompanyStatus` を見る。面接の「通過」は次ステージの status に進めて表す。
- **`rejected` と `declined` の区別**: 企業が決めた＝`rejected`、自分が決めた＝`declined`。判断に迷う場合はユーザーに確認する。どちらの場合も `decline_reason` を書く。
- **`fit_score_min` / `fit_score_max`** は必ず幅を持たせる（後述「必須原則 2」）。理由は `fit_summary` に書く。主観的な志望度はユーザー本人の気持ちとして `interest`（1〜5）に分けて書き、AI が推測で埋めない。
- **年収は万円単位の整数**（`salary_min` / `salary_max`）。固定残業込み・手当別途などの補足は `salary_note` へ。
- **勤務形態**は `remote_type`（enum）＋`office_days_per_week`（数値）で表し、勤務地・出社曜日などの補足は `remote_note` へ。自由文を enum 欄に書かない。
- リクルーター経由なら `recruiter` にリクルーターキーだけを書く（パスは書かない。リンクはキーから解決する）。
- **直近アクション管理（`action_type`, `next_action`, `next_due`）**:
  - 選考中・応募中の進行中タスクを追跡し、`pipeline.md` の冒頭に「🔴 要対応」「📅 確定済予定」「⏳ 結果・連絡待ち」として自動集約表示する（`build_pipeline.py`）。Web UI のダッシュボードにも出る。
  - `action_required`: 自分側の対応（日程調整返信、応募判断、課題提出等）／`scheduled`: 日時が確定した面談・面接／`waiting`: 相手側の返信・結果待ち／`none`: タスクなし（既定）。
  - `next_due` は `YYYY-MM-DD` または `YYYY-MM-DD HH:MM`。`action_required` と `scheduled` はこの昇順（直近が上）に並ぶ。期限切れは `validate.py --today` で警告される。
  - アクションの完了・進捗時は `action_type` / `next_action` / `next_due` / `updated_at` を更新する。
- **外部リソース・資料リンク（`links`）**:
  - 企業を理解・評価するために参照した外部情報源（会社概要、採用ピッチスライド、Entrance Book、テックブログ、口コミ、ニュース等）は、マークダウン本文中に直書きするだけでなくフロントマターの `links` リストに構造化して保持する。
  - 要素のキーは `docs/vault/schema.md` の `ReferenceLink`。要約を `materials/` に作ったら `material` で紐付け、その link には `fetched_at` を書かない（日付は資料側。必須原則 7）。
  - Web UI のリソースリンクカード表示や将来のAI要約・検索クエリとして活用される。
- ステータス変更時は `status` / `status_note` / `updated_at`（必要に応じ `decline_reason`）を更新する。

### スクリーニング集約ログ（`screening/`）

- `companies` に打ち切った企業を漏れなく列挙し、各社に `name` と `reason`（必要なら `aliases`）を書く。`check_company.py` はこの `name` / `aliases` で照合する。

## 本文セクション構成（`index.md`）

テンプレートは [company_template.md](../skills/consult-company-job/references/company_template.md)。

1. `# {company} 求人相談・調査ログ`
2. `## 1. 相談・リクエスト内容`: ユーザーが提示したURL、社名、紹介元リクルーター/エージェント（該当する場合）、質問の焦点や懸念点
3. `## 2. 実施した調査と検証スコープ（何をどこまで確かめたか）`:
   - **調査スコープチェックリスト**:
     - [x] 求人票詳細（Findy / BizReach等）
     - [x] / [ ] 口コミ・退職理由（OpenWork等）
     - [x] / [ ] 企業発信情報・WEB調査（テックブログ、採用ピッチ・Speaker Deckスライド、IR）
     - [ ] 面談による一次情報（未実施・未検証事項）
   - **収集データ**: 雇用条件・技術環境・組織カルチャー（各ツールの実行結果・口コミ分析）
   - **プロフィールとの照合・ギャップ分析**: track の `criteria.md` による Dealbreakers 判定、`strategy.md`（年収・出社等）と `vault/profile/preferences.md`（志向軸）の照合
   - **暫定適合度スコア（レンジ理由）**: 上限の根拠と、未検証の内情リスクによる下振れ幅を明記
4. `## 3. ユーザープロファイル確認・更新（深掘りヒアリング）`:
   - ユーザーへ投げかけた能動的な追加質問
   - ユーザーからの回答および得られた新情報
   - `vault/profile/`・track の `strategy.md` / `criteria.md` への反映内容と更新差分
5. `## 4. 最終回答・総合所見`:
   - ユーザーへのダイレクトな回答・推奨度（レンジ表示）
   - メリット・魅力 / 懸念点・リスク
   - 未検証事項（今後確かめるべき論点）
   - 次のアクション提案（カジュアル面談、応募、様子見など）
6. `## 5. 選考・面談サマリ（進捗時）`:
   - カジュアル面談や各次面接の実施結果サマリ
   - 同フォルダの面談ログへのリンク（例: `[カジュアル面談メモ (2026-10-15)](2026-10-15_casual.md)`）

## 遵守すべき必須原則

1. **調査範囲・エビデンスレベルの完全明記**:
   - 必ず「何をどこまで確かめたか（求人票のみか、口コミまで見たか、Web横断か、一次情報か）」を客観的に明記すること。
   - 確認できた事実と、未検証の懸念事項を明確に切り分ける。
2. **fit_score・statusの幅（レンジ）管理（決めつけ厳禁）**:
   - 求人票は企業の「公募用・建前のスペック」であり、ネガティブな内情は書かれていない。求人情報しか見ていない状況での判断に確定的な価値はないため、**fit_scoreは必ず `fit_score_min: 50` / `fit_score_max: 90` のように幅を持たせること**（同値にしない）。
   - 口コミ調査・Web調査・面談進行に伴い段階的に幅を絞り込む。安易に「85点」や「95点」など断定的な数字を並べない。
   - statusも情報の検証度合いに応じた慎重な位置づけを行う。
3. **プロファイルの能動的更新（最重要）**:
   - 単に `vault/profile/` や track の条件ファイルを参照して照合するだけで終わらせてはならない。
   - 求人票の記述（必須/歓迎要件、働き方、カルチャーなど）をトリガーに、**常にユーザーへ積極的に質問を投げかけ、まだ書かれていない志向やエピソードを引き出して追記する**こと（振り分け先は [user-profile.md](user-profile.md)）。
4. **多角的な調査の実施**:
   - 保存済み求人のローカル検索、媒体スクリプト（求人票・口コミ等）、ブラウザ・Web調査（採用ページ、テックブログ、評判等）を適宜組み合わせて調査する。どのスクリプトをどの順で使うかは [`using-job-hunt-scripts`](../skills/using-job-hunt-scripts/SKILL.md)、使い方は各スクリプトの `--help`。
   - Speaker Deckの会社紹介・登壇スライドは文字起こしを取得できる。初回は基本不要だが、カジュアル面談前やスカウト受諾判断に迷うタイミングでは中身を確認することを検討する。
   - 必要に応じて `sharing-browser-with-user` を利用し、画面調査や認証セッションを活用する（`.agents/rules/playwright-action.md` 遵守）。
5. **機密情報の管理**:
   - `vault/profile/internal/` と各 track の `criteria.md`・`ratings.md`（`visibility: "internal"`）は内部照合・意思決定支援に用いるが、外部提出・連絡用文章の生成時には露出させないこと。
6. **リンクは相対パス**:
   - 本文中のリンクは相対パスで書く（`file:///c:/...` の絶対パスは使わない）。フロントマターにはパスを書かず、キー（`company_key` / `recruiter` 等）で参照する。
7. **外部資料は links → materials → data の流れで置く**（仕様・手順の正本は [`docs/vault/materials.md`](../../docs/vault/materials.md)）:
   - **links（入口）**: 参照した外部資料（会社説明デック、Entrance Book、テックブログ、口コミ等）の URL はフロントマターの `links` に登録する。
   - **materials（永続する要約）**: 判断に使う要約・文字起こしは `materials/{slug}.md`（フロントマターに `fetched_at`・`source_url`・`raw_data`）に置き、`links[].material` で紐付ける。作成は `uv run python scripts/vault/add_material.py <URL> -c <company-key> -s`（Speaker Deck は `fetch_deck.py --save-to-vault` でも可）。
   - **data（使い捨ての生データ）**: 保持期間（60 日）を過ぎると自動で消える。判断に必要な内容は material の要約に残し、本文から `data/` を直接参照しない。
   - **見直すとき**: `add_material.py --refresh <material のパス>` で生データを取り直してから要約を直し、`fetched_at` を今日にする。古い資料は `find_chores.py` が `material-stale` として出す。
   - 外部資料の調査は「必要に応じて」行う（最初から全社全資料を要約しない。カジュアル面談前やスカウト検討で重要な論点がある場合に絞る）。


