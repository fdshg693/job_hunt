---
trigger: always_on
---

# Playwright ブラウザ操作・ユーザー共有に関する制約

## エージェントから可視ブラウザを開いてユーザーに操作させることは不可

Antigravity IDE のコマンド実行環境は、Windows の分離された仮想デスクトップ（`Desk: exebox-...`）上でプロセスを実行するサンドボックス構造になっている。

そのため、エージェント側が `run_command` 等から `playwright-cli open --headed` や可視ブラウザを起動しても、ウィンドウはユーザーのメイン画面（`WinSta0\Default`）ではなく隔離された仮想デスクトップに描画され、**ユーザーの画面には一切表示されず操作できない**。

## 運用ルールと対処方針

1. **エージェントからの headed 起動ハンドオフの禁止**:
   - エージェント自身が headed ブラウザを起動して「このウィンドウでログインしてください」とユーザーに渡すフローは機能しないため行ってはならない。

2. **ユーザーによる手動操作・ログインが必要な場合の手順**:
   以下のいずれかの方法で対応する。
   - **方式 A（推奨: ユーザー自身の外部ターミナルで起動）**:
     ユーザーに普段の外部ターミナル（PowerShell や Windows Terminal など）で以下のコマンドを実行してもらい、ログイン後に「終わった」と合図をもらう。
     ```powershell
     playwright-cli -s=<site> open <url> --headed --profile="$env:LOCALAPPDATA\claude-browser-profiles\<profile-name>"
     ```
   - **方式 B（リモートデバッグ接続）**:
     ユーザーの通常 Chrome で `chrome://inspect/#remote-debugging` を有効にしてもらい、エージェント側から `playwright-cli -s=<site> attach --cdp=chrome` で接続する。

3. **エージェントによる自動化・スクリプト実行**:
   - 一度プロファイルにログイン状態が永続化されれば、以降のエージェントによる操作・スクリプト実行は `--headed` を付けず通常（headless）で実行する。
