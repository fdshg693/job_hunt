# テンプレート一覧と管理ルール

就活・選考活動で利用する各種テンプレートの置き場です。
個人情報は含めず、再利用可能な汎用テンプレートとして管理します（パブリックリポジトリにも同期されます）。

## ディレクトリ構成

- [`vault/`](vault/): リポジトリ初期化用・公開リポジトリ用の `vault/` 全体雛形構造
  - [`vault/automation/routines.yaml`](vault/automation/routines.yaml): 定期実行ルーチン（今日やることブリーフ）の定義例。`vault/automation/` にコピーして使う（[docs/automation/README.md](../docs/automation/README.md)）
- [`interview/`](interview/): 面談・面接記録用のテンプレート
  - [`casual.md`](interview/casual.md): カジュアル面談用メモ（事前論点、リアルタイム質疑メモ、所感、アクション）
  - [`interview.md`](interview/interview.md): 本選考面接用メモ（1次・2次・最終面接、訴求ポイント、深掘り回答ログ）
  - [`recruiter.md`](interview/recruiter.md): エージェント・リクルーター面談用メモ（条件すり合わせ、求人紹介、評価所感）

## 今後テンプレートを追加する場合のカテゴリ指針

今後テンプレートを増やす際は、以下のカテゴリフォルダを切って配置してください。

- `templates/message/`: スカウト返信、面談日程調整、内定受諾・辞退などの定型文
- `templates/research/`: 企業調査ノート、決算・事業分析シート
- `templates/review/`: 転職活動の週次・月次振り返りシート
