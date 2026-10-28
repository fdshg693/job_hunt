<!-- 自動生成ファイル: .agents/rules/tracks.md から scripts/dev/sync_agents.py で生成。直接編集せず .agents/rules/tracks.md を編集して再同期すること -->

> **適用条件**: 企業・求人・リクルーターの相談を受けてログを作成・参照する際、または vault/tracks/ 配下を操作する際に適用

# 転職活動 track 運用ルール

転職活動は「track」単位で分け、`vault/tracks/{track}/` 配下に企業ログ・条件・選考状況を置く。国内転職と海外転職で企業・条件・パイプラインを混在させないための仕組み。

- 関連ルール: [企業ログルール](company-log.md), [面談詳細ログルール](interview-log.md), [リクルーター評価ログルール](recruiter-log.md), [ユーザープロフィールルール](user-profile.md)

## track の定義と振り分け基準

| track | 対象 | 例 |
|---|---|---|
| `domestic` | 日本法人に雇用される就業。**外資系企業の日本法人を含む** | 国内SaaS企業、外資系企業の日本法人、日本法人採用の外資ポジション |
| `overseas` | 日本国外の法人に雇用・契約される就業。**現地就労・リロケーション・海外企業へのフルリモート勤務を含む** | 海外企業の現地採用、リロケーション付き採用、海外法人とのリモート雇用・業務委託契約 |

- 判定基準は「勤務地」ではなく「**雇用・契約主体がどの国の法人か**」。日本在住のまま海外法人にフルリモートで雇用される場合は `overseas`、外資系でも日本法人に雇用されるなら `domestic`。
- 求人票から雇用主体が判別できない場合は、ユーザーに確認するか、確認事項として `unverified_items` に記載した上で暫定 track に置く。
- 相談開始時に track を判定し、`check_company.py --track {track}` で重複・除外判定を行う（[company-log.md](company-log.md)）。

## track 配下のファイルの役割

```
vault/tracks/{track}/
├── README.md      # track の期間・目標・定義
├── strategy.md    # track 固有の希望条件（年収・出社/勤務地・雇用形態・企業フェーズ・英語環境の位置づけ・track 固有NG）
├── criteria.md    # track の足切りルール（visibility: internal、外部露出厳禁）
├── ratings.md     # 企業格付け・ベンチマーク・ブラックリスト（visibility: internal、外部露出厳禁）
├── pipeline.md    # 選考ダッシュボード（一覧はマーカー間を build_pipeline.py で自動生成）
├── companies/{company-key}/  # 1社1フォルダ（index.md ＋ 面談ログ）
├── screening/     # スクリーニング早期打ち切りの集約ログ
└── archive.md     # 見送り台帳（終了企業・古いスクリーニングを 1 社数行に圧縮。company-log.md）
```

- track 固有ファイルが未作成の track（例: `overseas` の `ratings.md`）は、必要になった時点で `domestic` の同名ファイルの構成に倣って作る。
- `pipeline.md` の `<!-- pipeline:begin -->` 〜 `<!-- pipeline:end -->` 区間は自動生成のため手で編集しない。企業ログの `status` を更新したら `uv run python scripts/vault/validate.py` で検証し、`uv run python scripts/vault/build_pipeline.py --track {track}` で再生成する。ステータスの値・分類・並び順は [`docs/vault/schema.md`](../../docs/vault/schema.md) の `CompanyStatus`（正は `scripts/vault/schema/`）。マーカー外（活動フェーズ・次回アクション等）は手書きで維持する。
- マーカー外の更新漏れ（フロントマター `next_due` 切れ・企業ログより古い `updated_at`）は `scripts/vault/find_chores.py` が `pipeline-stale` として検出する。手書きチェックリストと企業ログの食い違いは [`sweep-chores`](../skills/sweep-chores/SKILL.md) スキルで AI が読んで直す。

## track をまたぐ情報の扱い

- **企業ログ**は必ずいずれか1つの track の `companies/` に置き、フロントマター `track` と一致させる。同一企業が両 track に現れる場合は track ごとに別フォルダを作り、本文で相互リンクする。
- **除外判定**は同一 track 内のみ有効。別 track の辞退・不合格・打ち切りは `[OTHER TRACK]` として参考提示に留める。ただし `blacklisted`（企業）と `employer`（前職・現職）は全 track で除外。
- **人の共通情報**（経歴・スキル・技術志向・キャリア観）は track に置かず `vault/profile/` に置く。track の条件で共通情報を縛らないよう、迷う記述は track 側（`strategy.md` / `criteria.md`）に置く。
- **リクルーター**は track 横断で `vault/recruiters/` に置き、フロントマター `tracks:` で扱う track を示す（[recruiter-log.md](recruiter-log.md)）。
- **媒体アカウント**（登録・連携状況）は track 横断で `vault/profile/accounts.md` に置く。
