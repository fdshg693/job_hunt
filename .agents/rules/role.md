---
trigger: always_on
---

常に.agents\rulesが最新になるように心がけること

`.agents/plans` 配下のファイル（概要ファイル `00-overview.md`、ステップファイル `01-*.md` 等、ラフプラン含む）を作成・編集・参照・実行する際は、必ず事前に `.agents/plans/README.md` を読むこと。

WEBページ画面調査には、必ず `sharing-browser-with-user` スキルを使うこと

scripts作成・改修時は、必ず事前に `docs/{site}/` を参照してサイト構造・仕様を理解した上で着手し、実装完了時には判明・変更された仕様を `docs/{site}/` に反映して最新化すること。