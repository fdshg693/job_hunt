<!-- 自動生成ファイル: scripts/vault/gen_schema_doc.py が scripts/vault/schema/ から生成する。手で編集しない -->

# vault フロントマタースキーマ

vault 配下の Markdown のフロントマター仕様。正（SSOT）は [`scripts/vault/schema/`](../../scripts/vault/schema/)。
スキーマを変えたら `uv run python scripts/vault/gen_schema_doc.py` でこの文書を再生成する。

- 未知のキーはエラー（`extra="forbid"`）。空文字は未記入（`null`）と同じ扱い。
- 日付は `YYYY-MM-DD`。年収は**万円単位の整数**。
- 「必須」でないキーは省略してよい。省略時は既定値になる。

## ドキュメント種別

| 種別 | モデル | 配置パス |
|---|---|---|
| `company` | [CompanyDoc](#model-companydoc) | `vault/tracks/*/companies/*/index.md` |
| `interview` | [InterviewDoc](#model-interviewdoc) | `vault/tracks/*/companies/*/????-??-??_*.md`<br>`vault/recruiters/*/????-??-??_*.md` |
| `recruiter` | [RecruiterDoc](#model-recruiterdoc) | `vault/recruiters/*/index.md` |
| `screening` | [ScreeningBatchDoc](#model-screeningbatchdoc) | `vault/tracks/*/screening/*.md` |
| `pipeline` | [PipelineDoc](#model-pipelinedoc) | `vault/tracks/*/pipeline.md` |
| `employer` | [EmployerDoc](#model-employerdoc) | `vault/profile/employers/*.md` |
| `archive` | [ArchiveDoc](#model-archivedoc) | `vault/tracks/*/archive.md` |
| `tech_project` | [TechProjectDoc](#model-techprojectdoc) | `vault/profile/tech/projects/*.md` |
| `tech_area` | [TechAreaDoc](#model-techareadoc) | `vault/profile/tech/areas/*.md` |
| `material` | [MaterialDoc](#model-materialdoc) | `vault/tracks/*/companies/*/materials/*.md`<br>`vault/recruiters/*/materials/*.md` |

## フィールド定義

<a id="model-companydoc"></a>

### CompanyDoc

企業ログ: vault/tracks/{track}/companies/{company_key}/index.md

| キー | 型 | 必須 | 既定値 | 制約 | 説明 |
|---|---|---|---|---|---|
| `company` | str | ✔ |  |  | 正式社名（例: 株式会社〇〇） |
| `company_key` | str | ✔ |  | `^[a-z0-9]+(?:-[a-z0-9]+)*$` | kebab-case の企業キー。フォルダ名／ファイル名と一致させる |
| `aliases` | list[str] |  | `[]` |  | 別名・略称・英語表記（check_company の照合に使う） |
| `date` | date | ✔ |  |  | 初回相談日 |
| `updated_at` | date | ✔ |  |  | 最終更新日 |
| `job_url` | str / null |  |  |  | 対象求人URL（主となる1件） |
| `job_title` | str / null |  |  |  | 対象求人の職種名 |
| `sources` | list[str] |  | `[]` |  | 参照した情報源（findy, openwork, corporate_site 等） |
| `evidence_level` | [EvidenceLevel](#enum-evidencelevel) / null |  |  |  | 調査の深さ |
| `verified_items` | list[str] |  | `[]` |  | 確認できた事項 |
| `unverified_items` | list[str] |  | `[]` |  | 未検証・今後確かめる事項 |
| `tags` | list[str] |  | `[]` |  | 技術スタック・業界・勤務形態などの検索用タグ |
| `salary_min` | int / null |  |  | ≥ 0 | 提示年収の下限（万円） |
| `salary_max` | int / null |  |  | ≥ 0 | 提示年収の上限（万円）。上限なしは未記入 |
| `salary_note` | str / null |  |  |  | 年収の補足（固定残業込み、手当別途 等） |
| `remote_type` | [RemoteType](#enum-remotetype) / null |  |  |  | 勤務形態の分類 |
| `office_days_per_week` | float / null |  |  | ≥ 0, ≤ 7 | 週あたりの出社日数（月1回なら 0.25）。不明なら未記入 |
| `remote_note` | str / null |  |  |  | 勤務形態の補足（勤務地、出社曜日、フレックス等） |
| `fit_score_min` | int / null |  |  | ≥ 0, ≤ 100 | 適合度スコアの下限（0〜100） |
| `fit_score_max` | int / null |  |  | ≥ 0, ≤ 100 | 適合度スコアの上限（0〜100） |
| `fit_summary` | str / null |  |  |  | 適合度の要約と、レンジの理由 |
| `track` | [Track](#enum-track) | ✔ |  |  | 配置先 track と一致させる |
| `status` | [CompanyStatus](#enum-companystatus) | ✔ |  |  | 選考・検討ステータス |
| `status_note` | str / null |  |  |  | 現状の一言メモ |
| `decline_reason` | str / null |  |  |  | declined / rejected / blacklisted の理由 |
| `interest` | int / null |  |  | ≥ 1, ≤ 5 | 主観的な志望度（1〜5、任意）。fit_score は AI の評価 |
| `recruiter` | str / null |  |  | `^[a-z0-9]+(?:-[a-z0-9]+)*(?:_[a-z0-9]+(?:-[a-z0-9]+)*)+$` | 紹介元リクルーターのキー（vault/recruiters/{key}/） |
| `thread_url` | str / null |  |  |  | スカウト・やり取りのスレッドURL |
| `related_jobs` | list[[RelatedJob](#model-relatedjob)] |  | `[]` |  | job_url 以外の関連求人 |
| `links` | list[[ReferenceLink](#model-referencelink)] |  | `[]` |  | 外部リソース・資料リンク一覧 |
| `action_type` | [ActionType](#enum-actiontype) |  | `none` |  | 直近アクションの種類 |
| `next_action` | str / null |  |  |  | 直近の具体的アクション |
| `next_due` | date / datetime (YYYY-MM-DD HH:MM) / null |  |  |  | 期日または予定日時（YYYY-MM-DD または YYYY-MM-DD HH:MM） |

<a id="model-relatedjob"></a>

#### RelatedJob

| キー | 型 | 必須 | 既定値 | 制約 | 説明 |
|---|---|---|---|---|---|
| `title` | str | ✔ |  |  | 求人タイトル |
| `url` | str | ✔ |  |  | 求人URL |

<a id="model-referencelink"></a>

#### ReferenceLink

外部リソース・資料リンク.

| キー | 型 | 必須 | 既定値 | 制約 | 説明 |
|---|---|---|---|---|---|
| `category` | [LinkCategory](#enum-linkcategory) | ✔ |  |  | リソースの種別（コーポレート・デック・ブログ・口コミ等） |
| `title` | str | ✔ |  |  | リンクまたは資料のタイトル |
| `url` | str | ✔ |  |  | 外部リソースのURL |
| `summary` | str / null |  |  |  | 要約・概要・着目ポイント |
| `material` | str / null |  |  |  | 同フォルダ配下の要約・資料Markdownパス（例: materials/pitch_deck.md） |
| `fetched_at` | date / null |  |  |  | 資料取得日・確認日 |

<a id="model-interviewdoc"></a>

### InterviewDoc

面談ログ: vault/tracks/{track}/companies/{company_key}/{YYYY-MM-DD}_{stage}.md または vault/recruiters/{recruiter_key}/{YYYY-MM-DD}_{stage}.md

| キー | 型 | 必須 | 既定値 | 制約 | 説明 |
|---|---|---|---|---|---|
| `company` | str / null |  |  |  | 社名（リクルーター面談では省略可） |
| `company_key` | str / null |  |  | `^[a-z0-9]+(?:-[a-z0-9]+)*$` | 企業キー（リクルーター面談では省略可） |
| `track` | [Track](#enum-track) / null |  |  |  | 省略時は配置フォルダから決まる |
| `date` | date | ✔ |  |  | 面談日（ファイル名の日付と一致させる） |
| `stage` | [InterviewStage](#enum-interviewstage) | ✔ |  |  | 面談ステージ（ファイル名の stage と一致させる） |
| `stage_name` | str / null |  |  |  | 表示名を stage の標準ラベルから変えたい場合のみ |
| `interviewer` | str / null |  |  |  | 面談相手（役職・氏名） |
| `result` | [InterviewResult](#enum-interviewresult) |  | `pending` |  | この回の結果 |
| `tags` | list[str] |  | `[]` |  | 検索用タグ |

<a id="model-recruiterdoc"></a>

### RecruiterDoc

リクルーター評価ログ: vault/recruiters/{recruiter_key}/index.md

| キー | 型 | 必須 | 既定値 | 制約 | 説明 |
|---|---|---|---|---|---|
| `name` | str | ✔ |  |  | 担当者氏名 |
| `recruiter_key` | str | ✔ |  | `^[a-z0-9]+(?:-[a-z0-9]+)*(?:_[a-z0-9]+(?:-[a-z0-9]+)*)+$` | {agency-or-platform}_{name}。フォルダ名と一致させる |
| `agency` | str / null |  |  |  | 所属企業・エージェント名 |
| `platform` | [Platform](#enum-platform) | ✔ |  |  | 接触した媒体 |
| `platform_user_id` | str / null |  |  |  | 媒体上のプロフィールURL・スレッドURL・ID |
| `status` | [RecruiterStatus](#enum-recruiterstatus) |  | `active` |  | 付き合いの状態 |
| `tracks` | list[[Track](#enum-track)] | ✔ |  | 1件以上 | 扱う track |
| `rating` | [Rating](#enum-rating) |  | `B` |  | 総合評価 |
| `matching_accuracy` | [MatchingAccuracy](#enum-matchingaccuracy) / null |  |  |  | 希望条件・志向への理解度 |
| `communication_quality` | str / null |  |  |  | コミュニケーションの所感（丁寧・迅速 / 事務的 / 強引・定型文 等） |
| `dealbreaker_adherence` | bool / null |  |  |  | 足切り条件を尊重しているか |
| `tags` | list[str] |  | `[]` |  | 検索用タグ |
| `introduced_companies` | list[[IntroducedCompany](#model-introducedcompany)] |  | `[]` |  | 紹介・提案された企業 |
| `links` | list[[ReferenceLink](#model-referencelink)] |  | `[]` |  | 外部リソース・資料リンク一覧 |
| `date` | date | ✔ |  |  | 初回接触日 |
| `updated_at` | date | ✔ |  |  | 最終更新日 |

<a id="model-introducedcompany"></a>

#### IntroducedCompany

リクルーターから紹介された企業. 企業ログがある場合は company_key で結合し、status / fit_score は企業ログ側を見る.

| キー | 型 | 必須 | 既定値 | 制約 | 説明 |
|---|---|---|---|---|---|
| `company` | str | ✔ |  |  | 社名（非公開なら「〇〇業界の企業（社名非公開）」等） |
| `company_key` | str / null |  |  | `^[a-z0-9]+(?:-[a-z0-9]+)*$` | 企業ログがある場合のキー |
| `job_title` | str / null |  |  |  | 紹介された職種 |
| `date` | date / null |  |  |  | 紹介された日 |
| `note` | str / null |  |  |  | 想定年収・所感など（企業ログが無い場合の記録先） |

<a id="model-screeningbatchdoc"></a>

### ScreeningBatchDoc

スクリーニング集約ログ: vault/tracks/{track}/screening/{YYYY-MM-DD}_{topic}.md（同一 track で除外対象）

| キー | 型 | 必須 | 既定値 | 制約 | 説明 |
|---|---|---|---|---|---|
| `date` | date | ✔ |  |  | スクリーニング実施日 |
| `type` | `discarded_batch` |  | `discarded_batch` |  | 常に discarded_batch |
| `topic` | str | ✔ |  |  | スクリーニングのテーマ |
| `companies` | list[[ScreenedCompany](#model-screenedcompany)] | ✔ |  | 1件以上 | 打ち切った企業（漏れなく列挙） |

<a id="model-screenedcompany"></a>

#### ScreenedCompany

| キー | 型 | 必須 | 既定値 | 制約 | 説明 |
|---|---|---|---|---|---|
| `name` | str | ✔ |  |  | 社名 |
| `aliases` | list[str] |  | `[]` |  | 別名・略称（check_company の照合に使う） |
| `reason` | str | ✔ |  |  | 打ち切り理由 |

<a id="model-pipelinedoc"></a>

### PipelineDoc

選考ダッシュボード: vault/tracks/{track}/pipeline.md（一覧部分は build_pipeline.py が生成）

| キー | 型 | 必須 | 既定値 | 制約 | 説明 |
|---|---|---|---|---|---|
| `title` | str | ✔ |  |  | 見出し |
| `track` | [Track](#enum-track) | ✔ |  |  | 対象 track |
| `updated_at` | date | ✔ |  |  | 最終更新日 |
| `phase` | str / null |  |  |  | 活動フェーズ（情報収集中 等） |
| `target_timing` | str / null |  |  |  | 転職目標時期 |
| `next_action` | str / null |  |  |  | track 全体の次回アクション |
| `next_due` | date / null |  |  |  | next_action の期日 |

<a id="model-employerdoc"></a>

### EmployerDoc

前職・現職ログ: vault/profile/employers/{company_key}.md（全 track で check_company の除外対象）

| キー | 型 | 必須 | 既定値 | 制約 | 説明 |
|---|---|---|---|---|---|
| `company` | str | ✔ |  |  | 正式社名（例: 株式会社〇〇） |
| `company_key` | str | ✔ |  | `^[a-z0-9]+(?:-[a-z0-9]+)*$` | kebab-case の企業キー。フォルダ名／ファイル名と一致させる |
| `aliases` | list[str] |  | `[]` |  | 別名・略称・英語表記（check_company の照合に使う） |
| `date` | date | ✔ |  |  | 初回相談日 |
| `updated_at` | date | ✔ |  |  | 最終更新日 |
| `job_url` | str / null |  |  |  | 対象求人URL（主となる1件） |
| `job_title` | str / null |  |  |  | 対象求人の職種名 |
| `sources` | list[str] |  | `[]` |  | 参照した情報源（findy, openwork, corporate_site 等） |
| `evidence_level` | [EvidenceLevel](#enum-evidencelevel) / null |  |  |  | 調査の深さ |
| `verified_items` | list[str] |  | `[]` |  | 確認できた事項 |
| `unverified_items` | list[str] |  | `[]` |  | 未検証・今後確かめる事項 |
| `tags` | list[str] |  | `[]` |  | 技術スタック・業界・勤務形態などの検索用タグ |
| `salary_min` | int / null |  |  | ≥ 0 | 提示年収の下限（万円） |
| `salary_max` | int / null |  |  | ≥ 0 | 提示年収の上限（万円）。上限なしは未記入 |
| `salary_note` | str / null |  |  |  | 年収の補足（固定残業込み、手当別途 等） |
| `remote_type` | [RemoteType](#enum-remotetype) / null |  |  |  | 勤務形態の分類 |
| `office_days_per_week` | float / null |  |  | ≥ 0, ≤ 7 | 週あたりの出社日数（月1回なら 0.25）。不明なら未記入 |
| `remote_note` | str / null |  |  |  | 勤務形態の補足（勤務地、出社曜日、フレックス等） |
| `fit_score_min` | int / null |  |  | ≥ 0, ≤ 100 | 適合度スコアの下限（0〜100） |
| `fit_score_max` | int / null |  |  | ≥ 0, ≤ 100 | 適合度スコアの上限（0〜100） |
| `fit_summary` | str / null |  |  |  | 適合度の要約と、レンジの理由 |
| `status` | `employer` |  | `employer` |  | 常に employer |
| `blacklisted` | bool |  | `false` |  | 退職済みで二度と関わらない企業なら true |
| `blacklist_reason` | str / null |  |  |  | blacklisted の理由 |

<a id="model-archivedoc"></a>

### ArchiveDoc

見送り台帳: vault/tracks/{track}/archive.md（同一 track で除外対象。blacklisted は全 track で除外）

| キー | 型 | 必須 | 既定値 | 制約 | 説明 |
|---|---|---|---|---|---|
| `type` | `closed_archive` |  | `closed_archive` |  | 常に closed_archive |
| `track` | [Track](#enum-track) | ✔ |  |  | 配置先 track と一致させる |
| `updated_at` | date | ✔ |  |  | 最終更新日 |
| `companies` | list[[ArchivedCompany](#model-archivedcompany)] |  | `[]` |  | 圧縮した企業（本文に一覧表は書かない） |

<a id="model-archivedcompany"></a>

#### ArchivedCompany

見送り台帳の 1 社. 再相談のときに判断に効く情報だけを残す（その時点の年収・勤務形態などは持たない）.

| キー | 型 | 必須 | 既定値 | 制約 | 説明 |
|---|---|---|---|---|---|
| `name` | str | ✔ |  |  | 社名（企業ログ由来なら元の company） |
| `company_key` | str / null |  |  | `^[a-z0-9]+(?:-[a-z0-9]+)*$` | 元の企業フォルダのキー。企業ログ由来では必須（リクルーターログの company_key 参照をここで解決する） |
| `aliases` | list[str] |  | `[]` |  | 別名・略称（check_company の照合に使う） |
| `status` | [ArchivedStatus](#enum-archivedstatus) | ✔ |  |  | 見送りの種別（除外範囲は元の企業ステータス・スクリーニングと同じ） |
| `considered_at` | date | ✔ |  |  | 初回検討日（企業ログの date、スクリーニングはバッチの date） |
| `closed_at` | date | ✔ |  |  | 見送り日 |
| `reached` | [CompanyStatus](#enum-companystatus) / null |  |  |  | 見送り前に到達した段階（casual_interview 等） |
| `fit_score_min` | int / null |  |  | ≥ 0, ≤ 100 | 見送り時点の適合度スコアの下限 |
| `fit_score_max` | int / null |  |  | ≥ 0, ≤ 100 | 見送り時点の適合度スコアの上限 |
| `reason` | str | ✔ |  |  | 見送り理由の核心。条件の言葉で 1〜2 文（目安 120 字以内） |
| `reconsider_if` | str / null |  |  |  | 再検討してよい条件（例: 出社が週1以下になったら） |
| `recruiter` | str / null |  |  | `^[a-z0-9]+(?:-[a-z0-9]+)*(?:_[a-z0-9]+(?:-[a-z0-9]+)*)+$` | 紹介元リクルーターのキー |
| `source` | [ArchiveSource](#enum-archivesource) | ✔ |  |  | 圧縮元 |

<a id="model-techprojectdoc"></a>

### TechProjectDoc

技術ノート（プロジェクト）: vault/profile/tech/projects/{project_key}.md

| キー | 型 | 必須 | 既定値 | 制約 | 説明 |
|---|---|---|---|---|---|
| `project_key` | str | ✔ |  | `^[a-z0-9]+(?:-[a-z0-9]+)*$` | kebab-case のプロジェクトキー。ファイル名と一致させる |
| `title` | str | ✔ |  |  | プロジェクト名 |
| `project_type` | [TechProjectType](#enum-techprojecttype) / null |  |  |  | 個人開発・実務・OSS の別 |
| `status` | [TechProjectStatus](#enum-techprojectstatus) / null |  |  |  | 進行状態 |
| `started_at` | date / null |  |  |  | 開始日（月までしか分からなければ 1 日で書く） |
| `ended_at` | date / null |  |  |  | 終了日（進行中は未記入） |
| `tech_stack` | list[str] |  | `[]` |  | 使った言語・フレームワーク・サービス |
| `role` | str / null |  |  |  | 自分の役割・担当範囲 |
| `areas` | list[str] |  | `[]` |  | 関連する技術領域のキー（vault/profile/tech/areas/{key}.md） |
| `tags` | list[str] |  | `[]` |  | 検索用タグ |
| `visibility` | `internal` / null |  |  |  | 外部に出さない本音を含むなら internal |
| `updated_at` | date | ✔ |  |  | 最終更新日 |

<a id="model-techareadoc"></a>

### TechAreaDoc

技術ノート（領域）: vault/profile/tech/areas/{area_key}.md

| キー | 型 | 必須 | 既定値 | 制約 | 説明 |
|---|---|---|---|---|---|
| `area_key` | str | ✔ |  | `^[a-z0-9]+(?:-[a-z0-9]+)*$` | kebab-case の領域キー。ファイル名と一致させる |
| `title` | str | ✔ |  |  | 技術領域の名前 |
| `depth` | [TechDepth](#enum-techdepth) | ✔ |  |  | 現在の理解度（補足は本文に書く） |
| `last_used` | date / null |  |  |  | 最後に実際に使った時期（月までしか分からなければ 1 日で書く） |
| `projects` | list[str] |  | `[]` |  | この領域を使ったプロジェクトのキー（vault/profile/tech/projects/{key}.md） |
| `tags` | list[str] |  | `[]` |  | 検索用タグ |
| `visibility` | `internal` / null |  |  |  | 外部に出さない本音を含むなら internal |
| `updated_at` | date | ✔ |  |  | 最終更新日 |

<a id="model-materialdoc"></a>

### MaterialDoc

外部資料の要約: vault/tracks/{track}/companies/{company_key}/materials/{slug}.md または vault/recruiters/{recruiter_key}/materials/{slug}.md  links（入口）→ materials（永続する要約）→ data/（使い捨ての生データ）の中段。 所属する企業・リクルーターは配置フォルダから決まるので書かない。 material から辿られる link 側には fetched_at を書かない（日付の正本はこちら）。

| キー | 型 | 必須 | 既定値 | 制約 | 説明 |
|---|---|---|---|---|---|
| `title` | str | ✔ |  |  | 資料のタイトル |
| `source_url` | str / null |  |  |  | 元資料のURL（親 index.md の links[].url と揃える。手書きの資料なら省略可） |
| `fetched_at` | date | ✔ |  |  | 要約を書いた・見直した日（要約の鮮度） |
| `raw_data` | list[str] |  | `[]` |  | 生データの場所（data/ で始まるリポジトリルート相対パス）。保持期間を過ぎると消えるのは正常 |
| `raw_fetched_at` | date / null |  |  |  | 生データを取得した日（生データの鮮度） |

## 列挙値

<a id="enum-track"></a>

### Track

| 値 | ラベル |
|---|---|
| `domestic` | 国内（日本法人に雇用） |
| `overseas` | 海外（国外法人に雇用・契約） |

<a id="enum-statuscategory"></a>

### StatusCategory

| 値 | ラベル |
|---|---|
| `active` | 進行中（調査・検討・選考） |
| `closed` | 終了（承諾・辞退・不合格） |
| `excluded` | 除外（ブラックリスト） |

<a id="enum-companystatus"></a>

### CompanyStatus

| 値 | ラベル | 分類 (category) | 並び順 | check_company の除外範囲 | 意味 |
|---|---|---|---|---|---|
| `offer` | 内定・オファー | `active` | 0 | `none` | 内定・条件提示を受けた |
| `final_interview` | 最終面接 | `active` | 1 | `none` | 最終・役員面接の段階 |
| `second_interview` | 2次面接 | `active` | 2 | `none` | 2次面接の段階 |
| `first_interview` | 1次面接 | `active` | 3 | `none` | 1次面接（技術面接等）の段階 |
| `casual_interview` | カジュアル面談 | `active` | 4 | `none` | カジュアル面談の調整・実施段階 |
| `applied` | 応募済 | `active` | 5 | `none` | 応募し、書類選考の結果待ち |
| `considering` | 検討中 | `active` | 6 | `none` | 調査済みで、応募・面談するか検討中 |
| `researching` | 調査中 | `active` | 7 | `none` | 調査に着手したばかり・未検証 |
| `on_hold` | 保留 | `active` | 8 | `none` | 一時的に止めている（時期待ち等） |
| `low_priority` | 優先度低 | `active` | 9 | `none` | 見送りではないが優先度が低い |
| `accepted` | 内定承諾 | `closed` | 20 | `none` | 内定を承諾した |
| `declined` | 見送り・辞退 | `closed` | 21 | `same_track` | 自分から見送り・辞退した |
| `rejected` | 不合格 | `closed` | 22 | `same_track` | 企業側から不合格・お見送りとされた |
| `blacklisted` | ブラックリスト | `excluded` | 30 | `all_tracks` | 二度と関わらない企業 |

<a id="enum-archivedstatus"></a>

### ArchivedStatus

| 値 | ラベル |
|---|---|
| `declined` | 見送り・辞退 |
| `rejected` | 不合格 |
| `blacklisted` | ブラックリスト |
| `discarded` | スクリーニングで打ち切り |

<a id="enum-archivesource"></a>

### ArchiveSource

| 値 | ラベル |
|---|---|
| `company_log` | 企業ログから圧縮 |
| `screening` | スクリーニング集約ログから畳み込み |

<a id="enum-actiontype"></a>

### ActionType

| 値 | ラベル |
|---|---|
| `action_required` | 要対応（自分ボール） |
| `scheduled` | 確定済予定 |
| `waiting` | 結果・連絡待ち（相手ボール） |
| `none` | タスクなし |

<a id="enum-evidencelevel"></a>

### EvidenceLevel

| 値 | ラベル |
|---|---|
| `job_post_only` | 求人票のみ |
| `web_researched` | Web調査済 |
| `reviews_verified` | 口コミ確認済 |
| `interview_verified` | 面談で確認済 |

<a id="enum-remotetype"></a>

### RemoteType

| 値 | ラベル |
|---|---|
| `full_remote` | フルリモート |
| `mostly_remote` | リモート中心（出社は月数回程度） |
| `hybrid` | ハイブリッド（週1日以上の出社） |
| `onsite` | 出社（原則出社） |
| `unknown` | 不明・要確認 |

<a id="enum-interviewstage"></a>

### InterviewStage

| 値 | ラベル |
|---|---|
| `casual` | カジュアル面談 |
| `1st-interview` | 1次面接 |
| `2nd-interview` | 2次面接 |
| `final` | 最終面接 |
| `offer` | オファー面談 |
| `retro` | 振り返り |
| `career-consultation` | キャリア相談（エージェント） |
| `job-introduction` | 求人紹介（エージェント） |

<a id="enum-interviewresult"></a>

### InterviewResult

| 値 | ラベル |
|---|---|
| `pending` | 結果待ち |
| `passed` | 通過 |
| `rejected` | 不合格 |
| `declined` | 辞退 |
| `not_applicable` | 合否なし |

<a id="enum-recruiterstatus"></a>

### RecruiterStatus

| 値 | ラベル |
|---|---|
| `active` | やり取り中 |
| `trusted` | 信頼できるパートナー |
| `declined` | 見送り・連絡終了 |
| `blacklisted` | 要注意・NG |

<a id="enum-rating"></a>

### Rating

| 値 | ラベル |
|---|---|
| `S` | 最優良・パートナー |
| `A` | 優良 |
| `B` | 通常・検証中 |
| `C` | 微妙・ズレあり |
| `D` | 悪質・NG |

<a id="enum-matchingaccuracy"></a>

### MatchingAccuracy

| 値 | ラベル |
|---|---|
| `high` | 高い |
| `medium` | 普通 |
| `low` | 低い |
| `spam` | スパム（希望を無視） |

<a id="enum-platform"></a>

### Platform

| 値 | ラベル |
|---|---|
| `bizreach` | ビズリーチ |
| `linkedin` | LinkedIn |
| `findy` | Findy |
| `levtech_direct` | レバテックダイレクト |
| `forkwell` | Forkwell |
| `green` | Green |
| `openwork` | OpenWork |
| `youtrust` | YOUTRUST |
| `wellfound` | Wellfound |
| `direct` | 企業から直接 |
| `email` | メール |
| `other` | その他 |

<a id="enum-techdepth"></a>

### TechDepth

| 値 | ラベル |
|---|---|
| `aware` | 知っている（概要・用語を説明できる） |
| `tried` | 触った（チュートリアル・小さな検証レベル） |
| `practical` | 実用できる（実務・個人開発で動くものを作れる） |
| `design` | 設計判断まで説明できる（選定理由・トレードオフを語れる） |
| `teach` | 人に教えられる（レビュー・指導・発信ができる） |

<a id="enum-techprojecttype"></a>

### TechProjectType

| 値 | ラベル |
|---|---|
| `personal` | 個人開発 |
| `work` | 実務 |
| `oss` | OSS |

<a id="enum-techprojectstatus"></a>

### TechProjectStatus

| 値 | ラベル |
|---|---|
| `active` | 進行中 |
| `paused` | 休止 |
| `done` | 完了 |

<a id="enum-linkcategory"></a>

### LinkCategory

| 値 | ラベル |
|---|---|
| `corporate` | コーポレート・会社概要 |
| `entrance_book` | 採用・Entrance Book |
| `deck` | 会社説明資料・ピッチデック |
| `blog` | 技術ブログ・記事 |
| `review` | 口コミ・転職評判 |
| `interview` | インタビュー・登壇 |
| `news` | プレスリリース・ニュース |
| `sns` | SNS・公式アカウント |
| `other` | その他リソース |
