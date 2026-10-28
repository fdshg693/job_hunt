# understanding-repo-architecture スキルについて

人間のメンテナ向け。AI が実行時に読むのは [SKILL.md](SKILL.md) と参照ファイルで、このファイルは読まない。

## 目的

このリポジトリはルール・スキル・docs・スクリプト・vault・テンプレート・公開同期が互いを参照し合っており、1か所を変えると一覧や文書の更新漏れ（追随漏れ）が起きやすい。このスキルは、仕組みを改修する前に「どこが何の正本か」「変えたら何が波及するか」を AI に確認させるためのもの。発動は改修タスクに限り、vault への記録や既存スクリプトの実行では使わない（`description` と `role.md` の1行で制御）。

## 設計方針

- **規約を書き写さない**: 規約本文は `goal.md`・`role.md`・各ルール・`docs/` が正本。このスキルが持つのは地図（[layers.md](layers.md)）、思想の要点（[principles.md](principles.md)）、波及チェックリスト（[change-impact.md](change-impact.md)）だけ。複製するとこのスキル自体が追随漏れの発生源になる。
- **書き方は別スキル**: スキル・ルールの書式は `writing-skill`・`writing-rules` に任せ、役割を重ねない。
- **機械チェックは持たない**: 一覧と実体の突合などの決定論的な検査は、必要になったら別のスクリプトとして切り出す。

## ファイル構成

```text
understanding-repo-architecture/
├── SKILL.md          # ルーター。CAUTION と、何を変えるかによる参照先の振り分け
├── README.md         # このファイル
├── layers.md         # レイヤーごとの役割・正本・読み手・書いてはいけないこと
├── principles.md     # 横断的な設計思想の要点と正本へのリンク
└── change-impact.md  # 変更種別ごとの波及チェックリストと検証コマンド
```

## このスキル自体を更新するタイミング

- 新しいレイヤー（トップレベルのディレクトリ、新しい生成物）を足したとき → `layers.md`
- 新しい横断ルール・設計思想を正本（ルール等）に足したとき → `principles.md` にリンクを1行
- 変更時に一緒に直す箇所が増えたとき（新しい一覧・新しい pre-commit フック・公開対象の管理箇所） → `change-impact.md`
- `sync_agents.py` の trigger 変換仕様が変わったとき → `layers.md` の trigger 表
- `sync_agents.yaml` のスキーマが変わったとき → `layers.md` の `.agents/skills/` 行
