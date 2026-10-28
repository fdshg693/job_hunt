<!-- 自動生成ファイル: .agents/rules/recruiter-log.md から scripts/dev/sync_agents.py で生成。直接編集せず .agents/rules/recruiter-log.md を編集して再同期すること -->

> **適用条件**: エージェント担当者・ヘッドハンター・リクルーターについて相談を受け調査・回答する際、または vault/recruiters/ 配下のリクルーター評価ログを作成・参照・更新する際に適用

# リクルーター・ヘッドハンター評価ログ (`vault/recruiters/`) 運用ルール

転職活動におけるエージェント担当者、ヘッドハンター、企業リクルーター（採用担当者）からの求人紹介・スカウトについて相談・回答する際、および人単位での評価・見極めを行う際は、[`vault/recruiters/`](../../vault/recruiters/) 配下に**1人1フォルダ**で担当者別ログを作成・蓄積します。

## 目的と位置づけ

- **人単位（エージェント／ヘッドハンター）での評価の蓄積**:
  - 求人や企業そのもののスペック（企業ログ）とは独立して、「誰がどの媒体でどんな提案をしてきたか」「ユーザーの希望や本音の足切り条件を理解しているか」「強引さや定型文スパムではないか」を客観的に評価する。
- **紹介案件の品質・マッチング精度の追跡**:
  - 同一のリクルーターから複数の求人が紹介された場合に、紹介案件一覧（企業ログへのリンク）を一元管理し、リクルーターのマッチング精度・目利き力を定量・定性的に把握する。
- **悪質・地雷エージェントの重複対応防止**:
  - 希望条件無視やSES/常駐案件・ブラック企業の押し付けを行う担当者を `status: blacklisted` / `declined` として記録し、無駄な面談や連絡の消耗を防ぐ。
- **関連スキル**: [`consult-company-job`](../skills/consult-company-job/SKILL.md)
- **関連ルール**: [企業ログルール](company-log.md), [面談詳細ログルール](interview-log.md), [track 運用ルール](tracks.md), [ユーザープロフィールルール](user-profile.md)

## ディレクトリ構成

```
vault/recruiters/{recruiter-key}/
├── index.md                     # リクルーター評価ログ
├── materials/                   # 外部資料要約Markdown（エージェント紹介資料・独自求人票要約等）
│   └── {slug}.md
└── {YYYY-MM-DD}_{stage}.md      # 事前面談・求人紹介面談の詳細ログ（interview-log.md）
```

- **track 横断**: 同一担当者が国内・海外の両方を扱うことがあるため、track 配下ではなく `vault/recruiters/` 直下に置き、フロントマター `tracks:` で扱う track を示す。
- **外部資料（`materials/`）**: 担当者や所属エージェントから提供された独自資料、会社案内、独自求人まとめ等の要約Markdownを配置する。**配置するのは Markdown のみ**とし、PDFや画像などの生バイナリは置かない。links → materials → data の流れ・日付・見直し手順は企業ログと同じ（[`docs/vault/materials.md`](../../docs/vault/materials.md)）。
- **ステータスはフロントマターの `status` のみで管理する**。ステータスによるフォルダ分け・`git mv` による移動は行わない。

| `status` | 意味 | 基準 |
|---|---|---|
| `active` | やり取り中・検討中 | 現在メッセージやり取り中、求人紹介を受けている、または面談調整中 |
| `trusted` | 信頼できるパートナー（高評価） | ユーザーの志向・Dealbreakerを深く理解し、高品質・高マッチ度な案件を継続提案してくれる（評価 S/A） |
| `declined` | 見送り・連絡終了 | 提案内容が合わなかった、やり取りを終了した、またはユーザー主導で連絡をフェードアウト・辞退した |
| `blacklisted` | 要注意・NG | 希望条件（年収・リモート等）の完全無視、定型文コピペの乱れ撃ち、強引な応募催促など、二度と関わりたくない（評価 D） |

- **新規作成は `status: active` が既定**。初回からあからさまな定型文スパムやDealbreaker無視と判明した場合は最初から `blacklisted` でよい。
- 評価の変化時は `status` / `rating` / `updated_at` を更新する。
- **検索**: 既存ログの存在確認は `vault/recruiters/{recruiter-key}/index.md`、または `rg` で `vault/recruiters/*/index.md` の `name:` / `agency:` を検索する。

## 命名規則

- **フォルダ名（`recruiter-key`）**: `{agency-or-platform}_{recruiter-name}`
- **命名規則**:
  - 半角英数字小文字ハイフン/アンダースコア区切り（例: `bizreach_yamada-taro`, `recruit_suzuki-ichiro`, `jac_john-smith`, `direct_mercari_tanaka-hanako`）。
  - 所属エージェント組織またはプラットフォーム名をプレフィックスとし、アンダースコア（`_`）で担当者名をつなぐ。
  - 氏名が不明・イニシャル表記のみの場合はプラットフォーム＋公開IDや識別子（例: `bizreach_hh-12345`, `linkedin_recruiter-abc`）。

## フロントマター仕様（`index.md`）

- キー・型・許容値の正は [`scripts/vault/schema/`](../../scripts/vault/schema/)。一覧は生成物 [`docs/vault/schema.md`](../../docs/vault/schema.md) の `RecruiterDoc` / `IntroducedCompany` を見る（このルールにフィールド表は書かない）。
- テンプレートは [recruiter_template.md](../skills/consult-company-job/references/recruiter_template.md)。作成・更新したら `uv run python scripts/vault/validate.py` を実行してエラー0にする。
- `introduced_companies` には企業ログがあれば `company_key` を書いて結合する。status・fit_score は企業ログ側を正とし、ここには書き写さない。企業ログが無い紹介（社名非公開・ログ化しなかった案件）は `note` に想定年収・所感を残す。
- `links` にはエージェント企業のコーポレートサイト、担当者の公開プロフィール（LinkedIn、SNS等）、受領した紹介資料等の外部リソースリンクを構造化して記載する（キーは `docs/vault/schema.md` の `ReferenceLink`）。要約は `uv run python scripts/vault/add_material.py <URL> -r <recruiter-key> -s` で同フォルダの `materials/{slug}.md` に作り、`material` で紐付ける（日付は資料側に書く。[`docs/vault/materials.md`](../../docs/vault/materials.md)）。
- `rating` / `matching_accuracy` / `dealbreaker_adherence` は紹介案件の質とやり取りから判断し、新しい紹介・やり取りのたびに見直す。

## 本文セクション構成

テンプレートは [recruiter_template.md](../skills/consult-company-job/references/recruiter_template.md)。

1. `# {name}（{agency}）評価ログ`
2. `## 1. 基本情報・接点経緯`: 接触媒体、スカウト種別（プラチナ/通常）、初回メッセージの文面分析（個別カスタマイズか定型コピペか）
3. `## 2. 評価サマリ・見極め分析`:
   - マッチング精度（希望条件・Dealbreakerの理解度）
   - 提案案件の質（地雷案件・SES・レガシー負債の有無、独自案件の有無）
   - コミュニケーション品質（レスポンス、強引さの有無、パートナーシップ志向かノルマ志向か）
4. `## 3. 紹介・提案求人一覧`: 紹介企業テーブル（日付、企業名、fit_score、ステータス、企業ログへの相対リンク、所感）
5. `## 4. やり取り履歴・面談ログ`: 日付ごとのメッセージ要約、同フォルダの面談ログへのリンク
6. `## 5. 今後の対応方針・ネクストアクション`: 返信方針、付き合いの継続有無、注意点

## リクルーターへの返信下書き

媒体（メール・LinkedIn・ビズリーチ等）を問わず、リクルーターへの返信下書きは次を守る。

- **相手が出した情報を起点にする**: 求人票・口コミ・Web 等で独自に調べた内容（求人票の原文、技術スタック、年収の掲載値など）は企業ログにメモとして残し、返信には持ち込まない。確かめたい点は、こちらの条件や一般的な質問として聞く（例: 調べた出社規定を引用せず「このポジションの出社方針は？ 私の上限は安定して週2日です」と聞く）。
- **相手の発言を引くときは文脈を確かめる**: どのメールの、どの求人についての発言かを確認し、別の求人や一般論として言われたことを今回の求人の話として持ち出さない。
- `visibility: internal` の情報は混ぜない（[user-profile.md](user-profile.md)）。

## 企業ログとの双方向連携

リクルーター経由で求人相談が行われた場合、**企業ログとリクルーターログの双方向リンク**を必ず形成する。

1. **企業ログ (`vault/tracks/{track}/companies/{company-key}/index.md`) 側の記述**:
   - フロントマターに `recruiter: "agency_recruiter-name"`（キーのみ。パスは書かない）を追加。
   - 本文の「1. 相談・リクエスト内容」に紹介元リクルーターを明記。
2. **リクルーターログ (`vault/recruiters/{recruiter-key}/index.md`) 側の記述**:
   - `introduced_companies` リストに対象企業を `company_key` 付きで追加。
   - 紹介企業の track が `tracks:` に無ければ追加する。
   - 紹介案件の適合度を踏まえ、リクルーター自身の `matching_accuracy` や `rating` を更新。
