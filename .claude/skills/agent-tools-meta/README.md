# agent-tools-meta スキルについて

人間のメンテナ向け。AI が実行時に読むのは [SKILL.md](SKILL.md) と参照ファイルで、このファイルは読まない。

## 目的

このリポジトリの業務（就活）ではなく、Claude Code / Google Antigravity というツールそのものの使い方を答えるためのスキル。使用頻度が低いので、もとは 7 本あったスキル（`claude-cli-docs`・`claude-code-docs`・`claude-cli-use`・`agy-cli-docs`・`antigravity-docs`・`antigravity-memory`・`antigravity-subagents`）を 1 本にまとめ、常時コンテキストに載る description を 1 つに減らした。

## 設計方針

- **SKILL.md は振り分け表だけ**: 質問の種類 → 参照ファイル。各ツールの本文は `claude/`・`antigravity/` に置き、必要な 1 ファイルだけ読ませる。
- **両ツール共通**: 正本は `.agents/skills/agent-tools-meta/`、`.claude/` へは `scripts/dev/sync_agents.py` で通常どおり同期する。Claude Code 専用のフロントマター（`!` コマンド注入・`allowed-tools`・`disable-model-invocation`）は使わない。旧 `claude-cli-use` の自動起動禁止は、SKILL.md の CAUTION と `claude/cli-use.md` 冒頭の文章で置き換えている。
- **パスはスキルのフォルダ基準**: 同じ中身が `.agents/` と `.claude/` の 2 か所にあるため、`${CLAUDE_SKILL_DIR}` もリポジトリ絶対パスも使わない。
- **取得物はコミットしない**: スクリプトは `Path(__file__)` 基準でスキル直下の `output/{claude,antigravity}/` に書き、`output/` は `.gitignore` 済み。`llms-full.txt`（約 6MB）を 2 か所・公開リポジトリに載せないため、また `.claude/` 側での再生成が同期差分にならないため。旧スキルがコミットしていた `help_result.yaml` のスナップショットも置かない（CLI があれば数秒で再生成できる）。

## ファイル構成

```text
agent-tools-meta/
├── SKILL.md                 # ルーター（CAUTION と振り分け表）
├── README.md                # このファイル
├── .gitignore               # output/ を無視
├── claude/
│   ├── cli-docs.md          # `claude --help` のスナップショット参照
│   ├── code-docs.md         # code.claude.com の llms.txt / llms-full.txt 参照
│   └── cli-use.md           # `claude -p` への委譲（明示依頼時のみ）
├── antigravity/
│   ├── cli-docs.md          # `agy --help` / `agy help <sub>` のスナップショット参照
│   ├── docs.md              # antigravity.google の llms.txt と <path>.md 参照
│   ├── docs_url_map.md      # Markdown 版ページの取得ルール（と廃止済みの旧表）
│   ├── memory.md            # GEMINI.md / AGENTS.md / Rules / Workflows（スナップショット）
│   └── subagents.md         # サブエージェント（スナップショット）
└── scripts/
    ├── generate_claude_help_yaml.py      # → output/claude/help_result.yaml（PyYAML）
    ├── download_claude_code_reference.py # → output/claude/llms.txt, llms-full.txt（requests）
    ├── extract_doc_section.py            # → output/claude/temp/<slug>.txt
    ├── generate_agy_help_yaml.py         # → output/antigravity/help_result.yaml（PyYAML）
    └── download_antigravity_reference.py # → output/antigravity/llms.txt（requests）
```

## 出典と更新方法

- `antigravity/memory.md`: 2026-08-30 取得。出典はファイル冒頭のコメント（`docs/rules-workflows`・`docs/ide/rules`・`docs/cli/gcli-migration` 等）
- `antigravity/subagents.md`: 2026-09-01 取得。出典はファイル冒頭のコメント（`docs/subagents`・`docs/cli/subagents`・`docs/cli/commands/agents`・`docs/sdk/subagents`）
- `antigravity/docs_url_map.md`: `<path>.md` ルールは 2026-08-30 確認
- スナップショット系（memory / subagents）は、`antigravity/docs.md` の手順で出典ページを取り直し、差分を反映して冒頭コメントの取得日を更新する
- CLI のヘルプ書式が変わってパースが崩れたら、`scripts/generate_*_help_yaml.py` のパーサーを直す（書式の説明は各スクリプトの docstring と `*/cli-docs.md` の補足）
- 参照ファイルを足したら SKILL.md の振り分け表と description のトリガー語を一緒に更新する
