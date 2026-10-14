---
name: using-playwright-cli
description: Drives a browser from the shell with `playwright-cli` (`npx playwright cli`), grounded in a local snapshot of the skill microsoft/playwright itself ships. Use when asked to open / navigate / click / fill / snapshot a page, take screenshots or PDFs, mock requests, record a trace or video, manage browser sessions, cookies or storage state, or run and debug Playwright tests from the command line; also when asked what `playwright-cli install --skills` installs.
allowed-tools: Bash(python ${CLAUDE_SKILL_DIR}/*.py *) Bash(playwright-cli:*) Bash(npx:*) Bash(npm:*)
# 同梱ファイル:
#   - download_playwright_cli_skill.py: upstream スナップショット取得（!`` で起動時に実行）
#   - output/playwright-cli/: upstream の playwright-cli スキル本体（生成物。手で編集しない）
#   - references/: 自前の運用手順（upstream ではなくこのリポジトリの実測が根拠）
#   - README.md: メンテナ向け。取得対象の増やし方、設計意図
# 暗黙の前提:
#   - `gh` が PATH にあること（公開リポジトリなので未認証でも動くが、レート制限回避のため `gh auth login` 済みが望ましい）
#   - Python 3.9+ が PATH にあること（標準ライブラリのみ使用）
#   - `playwright-cli` 本体は別途必要（未導入なら本文の Installation 節に従う）
# 設計メモ:
#   - この SKILL.md は薄いルーター。実体は output/playwright-cli/ 配下に一段深く置く。
#     将来 playwright-component-testing / playwright-trace など他のバンドルスキルを
#     同じスキルに足すときに、この階層のまま output/<skill-name>/ を増やせばよい
# 依存スキル: なし
---

!`python "${CLAUDE_SKILL_DIR}/download_playwright_cli_skill.py"`

# playwright-cli でブラウザを操作する

記憶ではなく `${CLAUDE_SKILL_DIR}/output/`（microsoft/playwright `main` が同梱しているスキルのスナップショット）を根拠にする。
上のコマンドで取得済み。エラーが出ていた場合は原因（`gh` 未インストール等）を伝えてから続行する。

## まずこれを読む

[output/playwright-cli/playwright-cli-skill.md](output/playwright-cli/playwright-cli-skill.md)
— `playwright-cli install --skills` が配る skill 本体（upstream の `SKILL.md`。ここでは別名で保存している）。
コマンド一覧、snapshot と ref による要素指定、セッション、`--raw` / `--json`、インストール手順はすべてここにある。
**この本文を読んでから実行する。** コマンド名やオプションを記憶で補わない。

## 個別トピック

本文の末尾から張られている参照先。必要になったものだけ Read する（`output/` をまとめて流さない）。
全体の索引は [output/summary.md](output/summary.md)。

| やりたいこと | 見る場所 |
|---|---|
| Playwright テストの実行・デバッグ | `output/playwright-cli/references/playwright-tests.md` |
| テスト生成（plan / generate / heal） | `output/playwright-cli/references/test-generation.md` |
| リクエストのモック（route / unroute） | `output/playwright-cli/references/request-mocking.md` |
| 任意の Playwright コード実行（`run-code`） | `output/playwright-cli/references/running-code.md` |
| セッション管理（複数ブラウザ、attach / detach） | `output/playwright-cli/references/session-management.md` |
| storage state・cookie・localStorage | `output/playwright-cli/references/storage-state.md` |
| trace の取得と閲覧 | `output/playwright-cli/references/tracing.md` |
| 動画録画・チャプター・アクション表示 | `output/playwright-cli/references/video-recording.md` |
| 要素の id / class / data-* など属性の取得 | `output/playwright-cli/references/element-attributes.md` |
| PR に画像・動画を添付する（`gh --attach`） | `output/playwright-cli/references/pr-attachments.md` |

## 自前のリファレンス（`references/`）

upstream のスナップショットではなく、このリポジトリでの実測にもとづく運用手順。

| やりたいこと | 見る場所 |
|---|---|
| 長いブラウザ手順を、少しずつ書いては実行して育てる（スクリプト ⇄ CLI の往復） | [references/script-cli-roundtrip.md](references/script-cli-roundtrip.md) |
| 初見・大きいページを、snapshot の生出力をコンテキストに流さずに調べる（`pwq` ラッパー） | [references/context-saving-explore.md](references/context-saving-explore.md) |
| 初見のサイトに何があるかを、ブラウザを開く前に機械的に掴む（`robots.txt` / `sitemap.xml` / リンクグラフ） | [references/site-recon.md](references/site-recon.md) |
| 探索の往復ごと一区間を安いAIに任せ、報告と回収スクリプトだけ受け取る（`pwdo` 委譲） | [references/delegating-browser-tasks.md](references/delegating-browser-tasks.md) |

## 実行時の注意

- Windows 環境（このリポジトリの前提）。URL に `&` を含むときのエスケープは本文の「URLs with `&` on Windows」に従う
- 上流の `packages/playwright-core/src/tools/skills/playwright-cli/` がこのローカルクローンにもあるが、
  ローカルは古い／実験で改変されうる（`.claude/rules/ROLE.md`）。判断の根拠は常に `output/` を使い、
  差があれば差として報告する
- 答えるときは `output/` 内の相対パスと上流 URL
  （`https://github.com/microsoft/playwright/blob/main/<元パス>`、元パスは `output/_meta.json`）を示す

## スナップショットの更新

既定では 7 日以内に取得済みならスキップされる。強制再取得:

```bash
python "${CLAUDE_SKILL_DIR}/download_playwright_cli_skill.py" --force
```

同梱スキルは Playwright のリリースごとに更新される。バージョン差が問題になりそうなときは `--force` してから答える。
