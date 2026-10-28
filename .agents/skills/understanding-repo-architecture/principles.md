# 横断的な設計思想

仕組みを足す・変えるときに崩してはいけない考え方。要点だけを書き、本文は正本を読む。

| 思想 | 要点 | 正本 |
| --- | --- | --- |
| SSOT と生成物 | 正本は1か所。他は生成・派生させ、生成物は手で直さず再生成する。新しい一覧・文書を作るときも、まず「既存のどこかから生成できないか」「リンクで済まないか」を考える | [role.md](../../rules/role.md), [vault-schema.md](../../rules/vault-schema.md), [goal.md](../../rules/goal.md) |
| スキーマは1か所 | フロントマターのキー・型・値は `scripts/vault/schema/`。ルールにフィールド表を書かない。読む側は `load_vault()` を使い、値リストを書き写さない | [vault-schema.md](../../rules/vault-schema.md) |
| パスは1か所 | vault・data のパスは `scripts/common/paths.py` の定数・ヘルパーから引く | [user-profile.md](../../rules/user-profile.md) |
| ステータスはフロントマターだけ | 状態でフォルダを分けない・移動しない。終わった企業は見送り台帳に圧縮する | [company-log.md](../../rules/company-log.md) |
| `visibility: internal` の隔離 | 足切り・格付け・本音メモは判断支援にだけ使い、外部向け文章・公開パス・英語版に出さない | [user-profile.md](../../rules/user-profile.md) |
| 公開同期 | 公開リポジトリへはホワイトリストのパスだけを単一コミットで force push。禁止語ガードをローカル（pre-commit）と CI の二重で掛ける | [goal.md](../../rules/goal.md)「リポジトリ公開」, `.github/workflows/sync-public.yml`, `scripts/dev/check_public_leak.py` |
| 機械フィルタを過信しない | スクリプトの判定は事前フィルタ。最終判断は AI がプロファイルと照らして行い、調査を飛ばしたら理由を残す。スクリプトを作るときも「候補と根拠を出す」までに留める | [goal.md](../../rules/goal.md) 末尾 |
| スクリプトの出力規約 | stdout は作成・該当したパスだけ、人向けサマリは `--summary`、ログは stderr、結果は `data/` に永続化。共通 CLI 基盤・認証エンジン・crawler パイプラインを使う | [scripts-entrypoint.md](../../rules/scripts-entrypoint.md), [job-data-format.md](../../rules/job-data-format.md) |
| docs とコードはワンセット | 実装前に `docs/{site}/` を読み、判明・変更した仕様は同じ作業で `docs/{site}/` に反映する | [role.md](../../rules/role.md), [scripts-entrypoint.md](../../rules/scripts-entrypoint.md) §7 |
| AI と人間の役割分担 | AI は CLI で検索・取得・記録し、人間は Web UI で閲覧する。Web UI は書き込まない | [goal.md](../../rules/goal.md), [webui.md](../../rules/webui.md) |
| 文書の読み手を分ける | `SKILL.md` は AI の実行時、`README.md` はメンテナ向け。チェックリストや基準は1ファイルに一本化し、他からは参照する | [writing-skill](../writing-skill/bestpractices.md) |
| 機械で守れる境界は機械で守る | 守り続けたい境界（同期・スキーマ・公開漏れ）は pre-commit に載せる。新しい境界を足したら検証も足す | `lefthook.yml` |
