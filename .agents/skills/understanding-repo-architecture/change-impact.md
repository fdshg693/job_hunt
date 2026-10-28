# 変更種別ごとの波及チェックリスト

該当する節の項目を作業の TODO に入れてから着手する。複数に当てはまるなら全部見る。最後に「検証コマンド」を流す。

## 目次

- 新規スクリプト（既存媒体）
- 新規媒体
- 新規スキル
- ルールの新規作成・変更
- vault スキーマの変更
- vault のパス・構成の変更
- 雛形（テンプレート）の変更
- 公開対象パスの追加
- Google API のスコープ変更
- ディレクトリの改名・移動
- 検証コマンド

## 新規スクリプト（既存媒体）

- [ ] 着手前に `docs/{site}/` を読む（[scripts-entrypoint.md](../../rules/scripts-entrypoint.md) §7）
- [ ] 共通 CLI 基盤・認証エンジン・crawler パイプラインに乗せる（同 §6・§8・§9）
- [ ] `docs/{site}/` の README とサイト構造ドキュメントを更新する
- [ ] docstring 1 行目を書き、`gen_script_catalog.py` でスクリプト一覧 `docs/scripts/catalog.md` を再生成する（[goal.md](../../rules/goal.md) には個別スクリプトを書かない。新しいカテゴリのディレクトリなら `gen_script_catalog.py` の `CATEGORIES` と goal.md のカテゴリ表に足す）
- [ ] 新しい場面を作るスクリプト（新しい情報源・新しい種類の取得）なら [using-job-hunt-scripts](../using-job-hunt-scripts/SKILL.md) の判断フローに足す（同階層 `README.md` の更新タイミング）
- [ ] 利用者向けの機能なら `README.md` の該当箇所も更新する
- [ ] `tests/` にオフラインのテストを足す（個人情報はダミー）

## 新規媒体

上の「新規スクリプト」に加えて:

- [ ] [new_site_scraper_guide.md](../../../docs/guides/new_site_scraper_guide.md) の手順に従う（テンプレート `scripts/templates/site_scraper_template.py`、認証設定）
- [ ] `docs/README.md` の媒体表・目次に足す
- [ ] `README.md` の対応サービス・ディレクトリ構成に足す
- [ ] 媒体登録状況を `vault/profile/accounts.md` に足す（非公開側）

## 新規スキル

- [ ] 既存スキルで代用できないか、ルールで済まないかを確かめる（[writing-skill](../writing-skill/writing.md) 手順1）
- [ ] `.agents/skills/{name}/` に作る（`.claude/skills/` には書かない）
- [ ] 他プロジェクトから持ち込むスキルは、このリポジトリに無い文書・スキル・パスへの参照を外す（リンク切れを残さない）
- [ ] 関連スキルの `requires_skills` と、本文の振り分け先を双方向に更新する
- [ ] [goal.md](../../rules/goal.md) の「整備済みスキル」に足す
- [ ] `.claude/` に入れたくないものは `scripts/dev/sync_agents.yaml` の `exclude` に足す（[layers.md](layers.md)）
- [ ] `sync_agents.py` で `.claude/` を再生成する

## ルールの新規作成・変更

- [ ] trigger を選ぶ。`always_on` / `model_decision` は Claude Code で常時読み込みになる（[layers.md](layers.md)「ルールの trigger とコンテキストコスト」）
- [ ] 他のルール・スキルと内容が重ならないか確かめ、重なるなら片方をリンクにする
- [ ] `README.md` の「その他のエージェント」向けの常時読み込み一覧に影響しないか確かめる
- [ ] `sync_agents.py` で `.claude/` を再生成する

## vault スキーマの変更

[vault-schema.md](../../rules/vault-schema.md) に従い、同じコミットで:

- [ ] `scripts/vault/schema/` を直す
- [ ] vault 全件を移行し、`templates/vault/` の雛形も合わせる
- [ ] `gen_schema_doc.py` で `docs/vault/schema.md` を再生成する
- [ ] テストを直す・足す
- [ ] 種別を足すなら、読む側（loader・`check_company.py`・`build_index.py`・`build_pipeline.py`・Web UI）も対応する
- [ ] ルールやスキルにフィールドの説明を書いていないか確かめる（スキーマ文書へリンクする）

## vault のパス・構成の変更

- [ ] `scripts/common/paths.py` と `scripts/vault/schema/` の `KIND_GLOBS`
- [ ] `vault/README.md` と `templates/vault/`
- [ ] ディレクトリ図を持つルール（[company-log.md](../../rules/company-log.md)、[interview-log.md](../../rules/interview-log.md)、[recruiter-log.md](../../rules/recruiter-log.md)、[tracks.md](../../rules/tracks.md)、[user-profile.md](../../rules/user-profile.md)）と [goal.md](../../rules/goal.md)
- [ ] パスを書いているスキルの本文（`rg` で旧パスを検索する）

## 雛形（テンプレート）の変更

- [ ] 同じ用途の雛形が別の場所に無いか確かめる（面談ログは `templates/interview/` が正。企業ログ・リクルーターログは `consult-company-job/references/`）
- [ ] 見出し構成をルール側に書き写していないか確かめる（ルールは雛形へリンクし、各節で押さえる内容だけを書く）
- [ ] `templates/vault/` を変えたら `validate.py --root templates` を通す

## 公開対象パスの追加

次の4か所を一致させる:

- [ ] `.github/workflows/sync-public.yml` のコピー対象
- [ ] `scripts/dev/check_public_leak.py` の `PUBLIC_DIRS` / `PUBLIC_FILES`
- [ ] `lefthook.yml` の `check-public-leak` の glob
- [ ] [goal.md](../../rules/goal.md) の「リポジトリ公開・パブリック同期規約」

## Google API のスコープ変更

- [ ] `scripts/google/client.py` だけを直す（[google-api.md](../../rules/google-api.md)）

## ディレクトリの改名・移動

- [ ] 旧パスを `rg` で全体検索し、`.agents/`・`docs/`・`README.md`・`vault/README.md`・`templates/` の参照を直す
- [ ] 公開対象パスに関わるなら「公開対象パスの追加」の4か所も直す

## 検証コマンド

pre-commit（`lefthook.yml`）と同じものに、手動実行が義務の ruff・pytest を足したもの。触った範囲に関係するものを流す。

```powershell
uv run python scripts/dev/sync_agents.py --check          # .agents と .claude の同期
uv run python scripts/vault/validate.py                   # vault のスキーマ適合
uv run python scripts/vault/validate.py --root templates  # 雛形のスキーマ適合
uv run python scripts/vault/gen_schema_doc.py --check     # スキーマ文書の一致
uv run python scripts/dev/gen_script_catalog.py --check   # スクリプト一覧の一致
uv run python scripts/dev/check_public_leak.py --denylist vault/profile/internal/public_denylist.txt  # 公開漏れ
uv run ruff check scripts/
uv run pytest
```

- 失敗したら生成物を手で直さず、正本を直して再生成する（`sync_agents.py`、`gen_schema_doc.py`、`gen_script_catalog.py`、`build_pipeline.py --track {track}`）。
