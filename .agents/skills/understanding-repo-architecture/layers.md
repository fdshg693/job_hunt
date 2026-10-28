# レイヤーごとの役割・正本・読み手

各レイヤーが何の正本で、誰が読み、何を書いてはいけないか。詳細な規約はリンク先が正。

## 目次

- レイヤー一覧
- ルールの trigger とコンテキストコスト
- スキルの分類
- 置き場所に迷ったとき

## レイヤー一覧

| レイヤー | 役割 | 正本 / 生成物 | 主な読み手 | 書いてはいけないこと |
| --- | --- | --- | --- | --- |
| `.agents/rules/` | 常時・条件付きで守る規約（「何を守るか」） | 正本。`.claude/rules/` は `scripts/dev/sync_agents.py` の生成物 | AI（実行時） | 手順の詳細（→スキル）、フィールド表（→`docs/vault/schema.md` へリンク） |
| `.agents/skills/` | タスク単位の手順（「どう進めるか」） | 正本。`.claude/skills/` は生成物（同期除外は `scripts/dev/sync_agents.yaml` の `exclude`） | `SKILL.md`=AI / `README.md`=メンテナ | 規約の再定義（→ルールへリンク）、個人情報 |
| `.agents/agents/` | サブエージェント定義 | 正本。`.claude/agents/` は生成物（ツール名を変換） | AI | 個人情報 |
| `docs/` | 媒体のサイト構造・CLI 仕様・手順の詳細 | 正本。ただし `docs/vault/schema.md` は `scripts/vault/gen_schema_doc.py`、`docs/scripts/catalog.md` は `scripts/dev/gen_script_catalog.py`（各スクリプトの docstring 1 行目が正）の生成物 | AI（実装前）/ 人間 | 個人情報、生成物の手編集 |
| `scripts/` | CLI。媒体別 `scripts/{site}/`、共通基盤 `common/`、vault の道具 `vault/`、プロフィール出力 `profile/`、開発用 `dev/` | 正本。vault スキーマの正は `scripts/vault/schema/`、パスの正は `scripts/common/paths.py` | AI / 人間 | パス・ステータス値・スコープのハードコード、個人の値の直書き |
| `vault/` | 個人データの SSOT（非公開） | 正本。`pipeline.md` のマーカー内は `scripts/vault/build_pipeline.py` の生成物 | AI / 人間 | `visibility: internal` の外部露出、ステータス変更でのファイル移動 |
| `data/` | 媒体から取得したスナップショット・キャッシュ（非公開） | 派生。`data/vault_index.sqlite` は `scripts/vault/build_index.py` の派生キャッシュ | スクリプト / AI | 正本扱い（プロフィールの正は `vault/profile/`） |
| `templates/` | 公開用の空の雛形（`templates/vault/` は vault と同構成、`templates/interview/`） | 正本（公開対象）。`validate.py --root templates` で検証 | 新規ユーザー / AI | 個人情報 |
| `tests/` | オフラインのモックテスト（ダミーは `tests/fixtures/`） | 正本 | 開発者 | 個人情報 |
| `webui/` | 人間用の閲覧専用 UI | 正本。データは索引と `loader.load_doc()` 経由のみ | 人間 | vault への書き込み、独自パース、ラベル・値リストの直書き |
| `ai/tools/` | スキルから使う補助 CLI | 正本（公開対象） | AI | 個人情報 |
| `ai/plans/` | 実装前のプラン（非公開） | 一時的な正本。完了したら削除 | AI | 独立した Implementation Plan の二重作成 |
| ルート文書 | `README.md`（全体像）/ `QUICKSTART.md`（公開版の初期化）/ `vault/README.md`（vault の地図） | 正本 | 人間 | 機能一覧の正本化（機能カテゴリ・スキル一覧の正は [goal.md](../../rules/goal.md)、スクリプト一覧は `docs/scripts/catalog.md`） |

規約の正本: [role.md](../../rules/role.md)（`.agents` と `.claude` の関係）、[vault-schema.md](../../rules/vault-schema.md)、[webui.md](../../rules/webui.md)、[user-profile.md](../../rules/user-profile.md)（`internal` の範囲）、[tracks.md](../../rules/tracks.md)（pipeline のマーカー）。

## ルールの trigger とコンテキストコスト

`.agents/rules/` は Antigravity 形式の `trigger` を持ち、`sync_agents.py` が Claude Code 形式に変換する。

| trigger | Antigravity | Claude Code（変換後） |
| --- | --- | --- |
| `always_on` | 常時読み込み | 常時読み込み |
| `glob` | 該当パスを触ったとき | `paths:` で該当パスを触ったとき |
| `model_decision` | モデルが必要と判断したとき | **常時読み込み**（本文冒頭に「適用条件」が挿入される） |

- `always_on` と `model_decision` のルールに書いた分は、Claude Code では毎回のコンテキストに乗る。手順や長い表はスキルか `docs/` に出し、ルールには「何を守るか」と正本へのリンクだけを書く。
- 特定のパスに閉じた規約なら `glob` を選ぶ。

## スキルの分類

| 分類 | 例 | 慣習 |
| --- | --- | --- |
| ドメイン手順 | `consult-company-job`, `read-job-mail`, `schedule-interview`, `sweep-chores`, `using-job-hunt-scripts`（場面→スクリプトの振り分け） | フロントマター `meta:` と `requires_skills` で相互依存を宣言。冒頭の CAUTION に守るべき境界を置き、他スキルへの振り分けを明記 |
| ブラウザ・Web | `sharing-browser-with-user`, `using-playwright-cli` | 他プロジェクト由来の汎用スキル。前提・同梱ファイルはフロントマターのコメント |
| 書き方・設計のメタスキル | `writing-skill`, `writing-rules`, このスキル | 読むだけ。副作用なし |
| ツール自体のメタスキル | `agent-tools-meta` | Claude Code / Antigravity 共通で `.claude/` へも同期する。`SKILL.md` は振り分け表だけで、本文はツール別の参照ファイル。取得キャッシュ（`output/`）は gitignore |

一覧の正は [goal.md](../../rules/goal.md) の「整備済みスキル」。スキルを足したら、そこにも足す。

## 置き場所に迷ったとき

| 書きたいもの | 置き場所 |
| --- | --- |
| 常に（または特定パスで）守らせたい短い約束 | `.agents/rules/` |
| 特定のタスクを進める手順・判断フロー | `.agents/skills/{name}/SKILL.md`（設計意図は同階層の `README.md`） |
| 媒体のサイト構造・セレクタ・CLI の仕様 | `docs/{site}/` |
| フロントマターのキー・型・値 | `scripts/vault/schema/`（文書は生成する） |
| 個人の経歴・希望・選考状況 | `vault/`（振り分けは [user-profile.md](../../rules/user-profile.md)） |
| 新規ユーザー向けの空の雛形 | `templates/` |
| 着手前の計画・調査メモ | `ai/plans/{name}/` |
