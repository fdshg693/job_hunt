# 市場調査 (research/market/)

職種・技術スタック別の海外需要・給与水準のレポートを置く。国に閉じた情報は [`../countries/`](../countries/) へ、媒体の評価は [`../platforms.md`](../platforms.md) へ。

- **ファイル名**: `{YYYY-MM-DD}_{topic}.md`（例: `2027-01-10_backend-go-remote-salary.md`）
- **フロントマター**:

```yaml
---
date: "YYYY-MM-DD"
topic: "Go バックエンドのリモート求人の給与水準"
regions: ["ca", "au", "remote-global"]
roles: ["backend", "fullstack", "ai-engineer"]
answers: ["Q-07"]         # questions.md の問い ID
sources:
  - url: "https://..."
    checked_at: "YYYY-MM-DD"
---
```

- **本文**: 調査の問い → 収集データ（求人件数・給与レンジ・要求スキル・ビザ/リモート条件の傾向）→ 自分のプロフィール（`vault/profile/`）との照合 → 結論と次の調査。
- 求人票の生データは `data/{site}/` のスナップショットを参照し、ここには集計・考察だけを書く。
