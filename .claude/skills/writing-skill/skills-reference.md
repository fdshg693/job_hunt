# Claudeで利用可能なスキル

> 参考文献: [Extend Claude with skills](https://code.claude.com/docs/en/skills) / [Commands](https://code.claude.com/docs/en/commands)

## 目次

- [概要](#概要)
- [配置場所](#配置場所)
- [Claude Codeでの組み込みスキル](#claude-codeでの組み込みbundledスキル)
- [カスタムスキルの書き方](#カスタムスキルの書き方)
- [誰が呼び出せるかの制御](#誰が呼び出せるかの制御)
- [スキルコンテンツのライフサイクル](#スキルコンテンツのライフサイクル)
- [発展: 動的コンテキスト注入・引数・置換変数](#発展動的コンテキスト注入引数置換変数)
- [Pull request context](#pull-request-context)
- [参考文献](#参考文献)

## 概要

スキルは `SKILL.md` というファイルにインストラクションを書いておき、Claudeの能力を拡張する仕組み。
同じ指示や手順を毎回チャットに貼り付けている、あるいはCLAUDE.mdの一部が「事実」ではなく「手順」に肥大化してきた、という場合にスキル化する。

- ユーザーが `/skill-name` で直接呼び出すことも、Claudeが会話の流れから自動的に読み込むこともできる
- Claude Code独自のスキル標準は [Agent Skills](https://agentskills.io) というオープン標準に準拠しており、他のAIツールとも互換性がある
- Claude Codeでは、標準に加えて「誰が呼び出せるかの制御」「サブエージェントでの実行 (`context: fork`)」「動的コンテキスト注入 (`!`command``)」が独自拡張として追加されている

### 3段階のロード（コスト最適化の仕組み）

**最初はフロントマターのメタデータ（`description`など）だけが会話コンテキストに読み込まれ、エージェントはスキルの存在を認識する。**
スキルが実際に呼び出された時にだけ、`SKILL.md`本体の全文が読み込まれる。さらに本体から参照される追加ファイル（`reference.md`など）は、Claudeがそれを必要とした時にだけ読み込まれる。
この3段階（フロントマター → 本体 → 参照ファイル）により、多数のスキルを常備していてもコスト・性能面で有利になる。

参考: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview#three-types-of-skill-content-three-levels-of-loading

## 配置場所

スキルの置き場所によって、誰が使えるかが変わる（Source: [skills.md#where-skills-live](https://code.claude.com/docs/en/skills)）。

| 種別       | パス                                     | 適用範囲               |
| :--------- | :--------------------------------------- | :--------------------- |
| Enterprise | managed settingsで指定                   | 組織内の全ユーザー     |
| Personal   | `~/.claude/skills/<skill-name>/SKILL.md` | 自分の全プロジェクト   |
| Project    | `.claude/skills/<skill-name>/SKILL.md`   | このプロジェクトのみ   |
| Plugin     | `<plugin>/skills/<skill-name>/SKILL.md`  | プラグインが有効な範囲 |

補足事項:

- 同名スキルが複数階層にある場合、Enterprise > Personal > Project の優先順位で上書きされる。同名の組み込み(bundled)スキルも、いずれかの階層に同名スキルがあれば上書きされる
- プラグインのスキルは `plugin-name:skill-name` という名前空間になるため他と衝突しない
- モノレポなどで `packages/frontend/.claude/skills/` のように、作業中のサブディレクトリ配下にネストしたスキルも自動的に読み込まれる。ルートと名前が衝突する場合は `/apps/web:deploy` のようにディレクトリ修飾名になる
- `<skill-name>` ディレクトリはシンボリックリンクでも良く、Claude Codeはリンク先の`SKILL.md`を読みに行く
- `.claude/skills/`配下の変更はセッション中でも即座に検知される（ライブ変更検知）。ただし、セッション開始時になかった新しいトップレベルのスキルディレクトリを追加した場合はセッションの再起動が必要
- `--add-dir`で追加したディレクトリの`.claude/skills/`は自動で読み込まれる（`permissions.additionalDirectories`設定では読み込まれない点に注意）

## Claude Codeでの組み込み(bundled)スキル

Claude Codeには標準でいくつかのスキルが同梱されており、`disableBundledSkills`設定で無効化しない限り常に利用可能（Source: [skills.md#bundled-skills](https://code.claude.com/docs/en/skills)）。
組み込みコマンドの多くはCLIに直接コーディングされた固定ロジックだが、**bundled skillsはプロンプトベース**で、Claudeに詳細な指示を与えてツールをオーケストレーションさせる点が異なる。

代表的なもの（詳細は[Commands](https://code.claude.com/docs/en/commands)参照）:

| コマンド                                             | 概要                                                                                                                                                                                                                                                                                                                                        |
| :--------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `/code-review [effort] [--fix] [--comment] [target]` | 現在のdiffを正しさ・簡潔性・効率性の観点でレビュー。v2.1.218以降デフォルトでバックグラウンドサブエージェントとして実行される。`ultra`でクラウド上のマルチエージェントレビュー(ultrareview)になり、`claude -p '/code-review ultra'`でCI/スクリプトから起動できる。ultrareviewはデフォルトで500ファイル/8,000行を超えるdiffを明示的に拒否する |
| `/simplify [target]`                                 | バグ探しはせず、再利用性・簡潔性・効率性の観点だけで変更後のコードをレビューし、修正まで適用する                                                                                                                                                                                                                                            |
| `/batch <instruction>`                               | 大規模な変更をリサーチ→5〜30個の独立した作業単位に分解→各単位をworktree付きのバックグラウンドサブエージェントで実装しPRを作成                                                                                                                                                                                                               |
| `/run`                                               | 変更後のアプリを実際に起動して動作を確認する                                                                                                                                                                                                                                                                                                |
| `/verify`                                            | テストや型チェックに頼らず、ビルド・起動して変更が意図通り動くか確認する                                                                                                                                                                                                                                                                    |
| `/run-skill-generator`                               | `/run`・`/verify`のために、プロジェクト固有の起動手順を`.claude/skills/run-<name>/`に記録する                                                                                                                                                                                                                                               |
| `/debug [description]`                               | デバッグログを有効化し、セッションログを読んで問題を調査する                                                                                                                                                                                                                                                                                |
| `/loop [interval] [prompt]`                          | プロンプトを繰り返し実行する。間隔省略でClaudeが自らペースを決める                                                                                                                                                                                                                                                                          |
| `/dataviz [request]`                                 | チャート・グラフ・ダッシュボードのデザインガイダンス                                                                                                                                                                                                                                                                                        |
| `/claude-api [migrate\|managed-agents-onboard]`      | Claude API（Python/TS/Java/Go/Ruby/C#/PHP/cURL）のリファレンスをロード。`anthropic`や`@anthropic-ai/sdk`のimportで自動発火もする                                                                                                                                                                                                            |
| `/fewer-permission-prompts`                          | 過去のトランスクリプトから許可済みコマンドを走査し、許可リストを`.claude/settings.json`に追加                                                                                                                                                                                                                                               |
| `/design-sync [hint]`                                | リポジトリのReactデザインシステムをClaude Designにアップロード                                                                                                                                                                                                                                                                              |

これらは通常のスキルと同じ扱いのため、プロジェクトの`.claude/skills/`に同名スキルを置けば組み込み版を上書きできる。

## カスタムスキルの書き方

`.claude/skills/{skill-name}/SKILL.md`（個人用なら`~/.claude/skills/`）に以下のフォーマットで記載する。

```markdown
---
name: スキルの名前
description: スキルの概要（Claudeが自動起動するかの判断に使う。用途を先頭に書くこと）
---

スキルの説明・指示本文
```

`description`のみ推奨（他は省略可）。省略した場合、Markdown本文の最初の段落が`description`として使われる。

### フロントマターの全フィールド一覧

Source: [skills.md#frontmatter-reference](https://code.claude.com/docs/en/skills)

| フィールド                 | 必須 | 説明                                                                                                                                                                   |
| :------------------------- | :--- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                     | 任意 | スキル一覧に表示される名前。省略時はディレクトリ名。呼び出しコマンド名とは基本的に別（後述）                                                                           |
| `description`              | 推奨 | スキルの内容と使用場面。Claudeの自動起動判断に使われる。`when_to_use`と合わせて1,536文字で切り詰められるため、重要なユースケースを先頭に書く                           |
| `when_to_use`              | 任意 | 起動トリガーとなるフレーズなどの補足情報。`description`と結合されリスト表示される                                                                                      |
| `argument-hint`            | 任意 | オートコンプリート時に表示される引数のヒント。例: `[issue-number]`                                                                                                     |
| `arguments`                | 任意 | `$name`置換用の名前付き位置引数。スペース区切り文字列またはYAMLリストで指定                                                                                            |
| `disable-model-invocation` | 任意 | `true`にするとClaudeによる自動起動を禁止し、ユーザーの`/name`呼び出しのみ許可。副作用のあるワークフロー(`/deploy`等)向け。デフォルト`false`                            |
| `user-invocable`           | 任意 | `false`にすると`/`メニューから隠れ、Claudeのみが呼び出せる。背景知識用スキル向け。デフォルト`true`                                                                     |
| `allowed-tools`            | 任意 | このスキルが有効な間、確認なしで使えるツール。スペース/カンマ区切り文字列 or YAMLリスト                                                                                |
| `disallowed-tools`         | 任意 | このスキルが有効な間、Claudeの利用可能なツールプールから除外するツール。次のメッセージで解除される                                                                     |
| `model`                    | 任意 | このスキル実行中に使うモデル。`/model`と同じ値、または`inherit`を指定可能。今回のターンのみ有効                                                                        |
| `effort`                   | 任意 | このスキル実行中のeffortレベル(`low`/`medium`/`high`/`xhigh`/`max`)。省略時はセッションの設定を継承                                                                    |
| `context`                  | 任意 | `fork`を指定するとフォークされたサブエージェントで実行される                                                                                                           |
| `agent`                    | 任意 | `context: fork`使用時に使うサブエージェントの種類(`Explore`, `Plan`, `general-purpose`, カスタムエージェント名)                                                        |
| `hooks`                    | 任意 | このスキルのライフサイクルに紐づくフック設定                                                                                                                           |
| `paths`                    | 任意 | このスキルが自動起動する対象ファイルを絞り込むglobパターン。カンマ区切り文字列またはYAMLリスト                                                                         |
| `shell`                    | 任意 | `` !`command` ``や` ```! `ブロックで使うシェル。`bash`(既定)または`powershell`                                                                                         |
| `metadata`                 | 任意 | 自由形式のメタデータ                                                                                                                                                   |
| `license`                  | 任意 | ライセンスを記載するフィールド                                                                                                                                         |
| `compatibility`            | 任意 | 互換性を記載するフィールド                                                                                                                                             |
| `background`               | 任意 | `context: fork`実行時にバックグラウンドで実行するかの真偽値。デフォルトは`true`（バックグラウンド実行）。明示的に`false`にすると、結果が返るまでそのターン内で待機する |

すべて任意項目だが、Claudeに自動判断させたい場合は`description`は書いておくべき。

### スキルのコマンド名の決まり方

`name`フィールドは基本的に「一覧に表示される名前」であり、`/`の後に打つコマンド名とは別ソースになる点に注意。

| 配置                                           | コマンド名の由来                                                     | 例                                                             |
| :--------------------------------------------- | :------------------------------------------------------------------- | :------------------------------------------------------------- |
| `~/.claude/skills/`または`.claude/skills/`配下 | ディレクトリ名                                                       | `.claude/skills/deploy-staging/SKILL.md` → `/deploy-staging`   |
| ネストした`.claude/skills/`（名前衝突時）      | 作業ディレクトリからの相対パス+ディレクトリ名                        | `apps/web/.claude/skills/deploy/SKILL.md` → `/apps/web:deploy` |
| `.claude/commands/`配下                        | 拡張子なしのファイル名                                               | `.claude/commands/deploy.md` → `/deploy`                       |
| プラグインの`skills/`サブディレクトリ          | ディレクトリ名（プラグイン名で名前空間化）                           | `my-plugin/skills/review/SKILL.md` → `/my-plugin:review`       |
| プラグインルートの`SKILL.md`                   | フロントマターの`name`（フォールバックでプラグインのディレクトリ名） | `name: review` → `/my-plugin:review`                           |

プラグインルート直下の`SKILL.md`だけが、`name`がそのままコマンド名になる唯一のケース。

## 誰が呼び出せるかの制御

| フロントマター                   | ユーザーが呼べる | Claudeが呼べる | コンテキストへのロードタイミング                                          |
| :------------------------------- | :--------------- | :------------- | :------------------------------------------------------------------------ |
| (デフォルト)                     | ○                | ○              | descriptionは常にコンテキストにあり、呼ばれた時に本体がロードされる       |
| `disable-model-invocation: true` | ○                | ×              | descriptionはコンテキストになし。ユーザーが呼んだ時のみ本体がロードされる |
| `user-invocable: false`          | ×                | ○              | descriptionは常にコンテキストにあり、呼ばれた時に本体がロードされる       |

- `disable-model-invocation: true`: `/commit`、`/deploy`など、副作用がある・タイミングを自分で制御したい処理向け
- `user-invocable: false`: `/`コマンドとしては無意味だがClaudeが知っておくべき背景知識向け

`Skill(name)`（完全一致）や`Skill(name *)`（プレフィックス一致）の permission ルールで、Claudeが呼び出せるスキルをホワイトリスト/ブラックリスト管理することも可能。

## スキルコンテンツのライフサイクル

スキルが呼び出されると、レンダリング済みの`SKILL.md`内容は1つのメッセージとして会話に入り、セッションの残り全体で保持され続ける（再読み込みはされない）。
そのため「タスク全体を通して守ってほしいこと」は一時的な手順ではなく、常設の指示として書く必要がある。

- 同じ内容のスキルを再度呼び出しても、内容が変わっていなければ「すでにロード済み」という短い注記が入るだけで、本体は再挿入されない（v2.1.202以降）
- Auto-compaction（自動要約）が起きても、直近に呼び出された各スキルは要約後に再アタッチされる（各スキル先頭5,000トークン、全体で合計25,000トークンの予算内）
- スキルの効果が薄れてきたと感じたら、`description`や指示文を強化するか、再度スキルを呼び出して内容を復元する

## 発展（動的コンテキスト注入・引数・置換変数）

### 引数の渡し方

- `$ARGUMENTS`をSKILL内に埋め込むと、SKILL実行時に渡された引数全体に置換される。埋め込みがない場合は末尾に`ARGUMENTS: <value>`として自動追記される
- `$ARGUMENTS[N]`または短縮形`$N`（0始まり）で、個別の引数にアクセスできる（例: `$0`が1つ目の引数）
- フロントマターの`arguments: [issue, branch]`のように名前付き引数を宣言すると、`$issue`・`$branch`のように名前で参照できる
- 複数語の引数はシェル風にクォートする（例: `/my-skill "hello world" second`）
- リテラルの`$`を数字などの前に書きたい場合は`\$1.00`のようにバックスラッシュでエスケープする
- v2.1.199以降、`/code-review /fix-issue 123`のように最大6つまでスキルをスタックして呼び出せ、末尾の引数はスタックした全スキルに渡される

### 動的コンテキストの注入（`!` コマンド埋め込み）

`` !`<command>` ``という記法で、スキル本体がClaudeに渡される**前に**シェルコマンドを実行し、その出力をプレースホルダーの位置に埋め込むことができる。Claudeはコマンドそのものではなく、実行結果（テキスト）だけを目にする。

```markdown
## Pull request context

- PR diff: !`gh pr diff`
- PR comments: !`gh pr view --comments`
```

仕組みと制約:

1. `` !`<command>` ``は元ファイルに対して**1回だけ**走査・実行される。コマンドの出力自体は再スキャンされないため、出力の中に新しいプレースホルダーを含めても展開されない
2. インライン記法は、行頭または直前が空白の場合のみ認識される。`` KEY=!`cmd` ``のように他の文字の直後に続く場合は展開されずリテラルのまま扱われる
3. 複数行のコマンドを実行したい場合は、` ```! `で囲んだフェンスコードブロックを使う

   ````markdown
   ## Environment

   ```!
   node --version
   npm --version
   ```
   ````

4. `shell`フロントマターで`bash`（既定）と`powershell`を切り替えられる（`powershell`利用には`CLAUDE_CODE_USE_POWERSHELL_TOOL=1`が必要）
5. `"disableSkillShellExecution": true`を設定すると、この動的実行自体を無効化できる（無効化時は`[shell command execution disabled by policy]`に置換される）。組み込み・managedスキルは対象外で、主にmanaged settingsでの利用を想定

### 利用可能な文字列置換変数一覧

Source: [skills.md#available-string-substitutions](https://code.claude.com/docs/en/skills)

| 変数                    | 説明                                                                                         |
| :---------------------- | :------------------------------------------------------------------------------------------- |
| `$ARGUMENTS`            | 呼び出し時に渡された引数全体                                                                 |
| `$ARGUMENTS[N]` / `$N`  | N番目（0始まり）の引数                                                                       |
| `$name`                 | フロントマター`arguments`で宣言した名前付き引数                                              |
| `${CLAUDE_SESSION_ID}`  | 現在のセッションID。ログ出力やセッション固有ファイルの命名に使える                           |
| `${CLAUDE_EFFORT}`      | 現在のeffortレベル(`low`/`medium`/`high`/`xhigh`/`max`)。ultracodeは`xhigh`として報告される  |
| `${CLAUDE_SKILL_DIR}`   | このスキルの`SKILL.md`が置かれているディレクトリ。同梱スクリプトの参照に使う                 |
| `${CLAUDE_PROJECT_DIR}` | プロジェクトルート。hooksやMCPサーバーに渡されるものと同じ値（v2.1.196以降でスキルにも対応） |

### 拡張思考を有効化する

`ultrathink`というキーワードをスキル本文中に含めることで、そのスキル実行時の拡張思考（deeper reasoning）をONにできる。

### サブエージェントでの実行（`context: fork`）

フロントマターに`context: fork`を指定すると、スキル本体がプロンプトとしてサブエージェントに渡され、隔離された環境で実行される（会話履歴にはアクセスできない）。`agent`フィールドで使用するサブエージェントの種類（`Explore`/`Plan`/`general-purpose`またはカスタム）を指定できる（省略時は`general-purpose`）。

`context: fork`のスキルはデフォルトでバックグラウンド実行される（結果を待たずに他の作業を継続できる）。フロントマターで`background: false`を指定すると、バックグラウンド実行せず、結果が返るまでそのターン内で待機する挙動に変更できる。

```yaml
---
name: deep-research
description: Research a topic thoroughly
context: fork
agent: Explore
---

Research $ARGUMENTS thoroughly:
1. Find relevant files using Glob and Grep
2. Read and analyze the code
3. Summarize findings with specific file references
```

`context: fork`は明確なタスク（手順）を書いたスキル向け。「このAPI規約を守って」のようなガイドラインだけを書くと、サブエージェントには実行可能なプロンプトがないまま渡ってしまい、意味のある出力が返らない点に注意。

### 補助ファイルの追加

スキルディレクトリには`SKILL.md`以外にテンプレート・サンプル出力・実行スクリプトなどを置ける。`SKILL.md`本体は簡潔に保ち、詳細なリファレンスは別ファイルに逃がして必要な時だけ読み込ませる。

```text
my-skill/
├── SKILL.md           # 必須。概要とナビゲーション
├── template.md        # Claudeが埋めるテンプレート
├── examples/
│   └── sample.md      # 期待する出力形式の例
└── scripts/
    └── validate.sh    # Claudeが実行できるスクリプト
```

`SKILL.md`は500行以内に収め、詳細は別ファイルに分離するのが推奨。

## 参考文献

- エージェントスキル全般の使い方: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview
- Claude Codeでの使い方（フロントマター・配置場所・動的コンテキストなど本記事の主な情報源）: https://code.claude.com/docs/en/skills
- コマンド一覧（組み込みコマンド・bundled skillsの区別含む）: https://code.claude.com/docs/en/commands
