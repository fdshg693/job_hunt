---
paths:
- vault/**/*.md
- templates/vault/**/*.md
- scripts/vault/**/*.py
---

<!-- 自動生成ファイル: .agents/rules/vault-schema.md から scripts/dev/sync_agents.py で生成。直接編集せず .agents/rules/vault-schema.md を編集して再同期すること -->

# vault フロントマタースキーマ規約

- キー・型・許容値の正は `scripts/vault/schema/`。一覧は生成物 `docs/vault/schema.md` を見る（手で編集しない）
- vault のファイルを作成・更新したら `uv run python scripts/vault/validate.py` を実行し、エラー0にする（`--summary` で一覧、`--strict` で警告も失敗扱い）
- スキーマを変える時は、同じコミットで vault 全件の移行・`gen_schema_doc.py` の再生成・テストまで行う
- ドキュメント種別と配置パスの対応は `scripts/vault/schema/__init__.py` の `DocKind` / `KIND_GLOBS`（企業ログ・面談ログ・リクルーター・スクリーニング集約ログ・見送り台帳 `archive.md`（`ArchiveDoc`）・pipeline・前職/現職・技術ノート `vault/profile/tech/{projects,areas}/`（`TechProjectDoc` / `TechAreaDoc`））。種別を足すときは読む側（loader の `Vault`・`check_company.py`・`build_index.py`・`build_pipeline.py`・Web UI）も同じ変更で対応する
- vault を読むコードは `scripts/vault/loader.py` の `load_vault()` を使い、独自にフロントマターをパースしない。ステータスの分類・並び順・ラベル・除外範囲はスキーマ（`COMPANY_STATUS_META` 等）から引き、値のリストをコードに書き写さない
- `data/vault_index.sqlite` は vault と `data/*/jobs` から作る派生キャッシュ。直接書き込まず、`uv run python scripts/vault/build_index.py` で作り直す（読む側は `ensure_index()` を呼べば正本の変更時だけ自動で作り直される）
