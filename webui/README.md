# Web UI（閲覧専用）

vault・求人データを人間が絞り込み・閲覧するための Web UI。FastAPI + Jinja2 + htmx 製で、127.0.0.1 でだけ待ち受ける。vault への書き込みはしない（書き込みに当たる操作は索引の作り直しだけ）。開発時の規約は [`.agents/rules/webui.md`](../.agents/rules/webui.md) を参照。

## 起動

```powershell
uv run python -m webui
```

起動後、<http://127.0.0.1:8765> を開く。別のポートで動かしたいときは `--port` を付ける。

```powershell
uv run python -m webui --port 8766
```

止めるときは、起動したターミナルで `Ctrl+C` を押す。

## 画面

| パス | 内容 |
|---|---|
| `/` | ダッシュボード（要対応・確定予定・連絡待ち） |
| `/companies` | 企業一覧（会社名検索、「進行中だけ」、fit_score 下限などで絞り込み）と詳細 |
| `/recruiters` | リクルーター一覧と詳細 |
| `/screening` | スクリーニング早期打ち切りログ |
| `/jobs` | 取得済み求人の一覧と詳細 |
| `/search` | 全文検索 |

非公開ファイル（`criteria.md`・`ratings.md`・`vault/profile/internal/`）は表示しない。

## トラブルシューティング: ポートが使用中で起動できない

次のエラーは、ポート 8765 を別のプロセスがすでに使っているときに出る。

```
ERROR:    [Errno 10048] error while attempting to bind on address ('127.0.0.1', 8765): [winerror 10048] only one usage of each socket address (protocol/network address/port) is normally permitted
```

前に起動した Web UI が、別のターミナルやバックグラウンドで動いたままになっていることが多い。その場合はブラウザで <http://127.0.0.1:8765> を開けばそのまま使える。コードを変更したので再起動したい、といったときは、以下の手順で古いプロセスを止めてから起動し直す。

### 1. ポートを使っているプロセスを確かめる

PowerShell:

```powershell
Get-NetTCPConnection -LocalPort 8765 -State Listen |
  ForEach-Object { Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)" } |
  Select-Object ProcessId, Name, CommandLine
```

コマンドラインが `...\.venv\Scripts\python.exe -m webui` なら、Web UI のプロセス。別のプログラムが表示された場合は止めずに、`--port` で別のポートを使う。

Git Bash の場合は、`netstat` の最後の列が PID。

```bash
netstat -ano | grep ':8765' | grep LISTENING
```

### 2. プロセスを止める

PowerShell（`<PID>` には手順 1 で確かめた `ProcessId` を入れる）:

```powershell
Stop-Process -Id <PID>
```

Git Bash:

```bash
taskkill //PID <PID> //F
```

ポートの確認と停止をまとめて行う場合（PowerShell）。止める前に、手順 1 で Web UI のプロセスかどうかを確かめておく。

```powershell
Get-NetTCPConnection -LocalPort 8765 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess }
```

### 3. 起動し直す

```powershell
uv run python -m webui
```
