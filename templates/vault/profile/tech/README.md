# 技術詳細ノート（`profile/tech/`）

履歴書（`resume.md`）・自己PR（`skills.md`）に書くには細かすぎる、技術の一次情報の置き場です。「今まさに何をやっているか」「各技術領域をどこまで理解しているか」「プロジェクトの細部」を書きます。

## 構成

| フォルダ | 1 ファイルの単位 | 書くこと |
|---|---|---|
| `projects/{key}.md` | 1 プロジェクト（個人開発・実務・OSS） | 時系列・具体。現在地、構成・設計判断、詰まった点、未解決、面接で話せるポイント |
| `areas/{key}.md` | 1 技術領域（例: Kubernetes、分散トレーシング） | 横断的な理解度。根拠、説明できること、説明できないこと・未経験、関連プロジェクト |

- キーは kebab-case で、ファイル名とフロントマターの `project_key` / `area_key` を一致させる。
- プロジェクトの `areas` と領域の `projects` でお互いをキー参照する。存在しないキーは `validate.py` が警告する。
- フロントマターのキーは [`docs/vault/schema.md`](../../../../docs/vault/schema.md) の `TechProjectDoc` / `TechAreaDoc`。理解度 `depth` の段階は同ファイルの `TechDepth` を見る。
- 雛形: [`projects/example-project.md`](projects/example-project.md)、[`areas/example-area.md`](areas/example-area.md)。コピーして使う。
- このフォルダ直下の README 以外に、`projects/` `areas/` の中へ README などスキーマ外のファイルを置かない（検証エラーになる）。

## 要約（`resume.md` / `skills.md`）との役割分担

- `resume.md` / `skills.md` は外部媒体への同期・PDF 出力の元になる**要約**、`tech/` は**一次情報**。同じ内容を両方に書かない。
- `tech/` は英語版同期・PDF 出力・媒体更新スクリプトの対象外。外部に出したい内容は、要約に起こしてから使う。
- 弱み・未経験の告白など外部に出せない本音を含むファイルには、フロントマターに `visibility: "internal"` を付ける。
