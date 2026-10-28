<#
.SYNOPSIS
  ユーザーをブラウザ窓に呼ぶための OS 通知（ベストエフォート）。

.DESCRIPTION
  sharing-browser-with-user スキルの「スクリプトが認証壁に当たり、手動ログインを待ちに入る」
  瞬間にだけ撃つ。トーストが出せなければビープに落ち、それも駄目なら黙って終わる。
  **どの経路でも exit 0。** 通知の失敗で自動化本体を止めないため（references/scripted-automation.md）。

  必ず Windows PowerShell 5.1（powershell.exe）で実行すること。
  pwsh 7 には WinRT の型射影が無く、ToastNotificationManager が見つからずに失敗する。

.EXAMPLE
  powershell.exe -NoProfile -File notify-user.ps1 -Title "ログインをお願いします" -Body "github の窓で認証を完了してください"
#>
param(
  [string]$Title = 'ログインをお願いします',
  [string]$Body  = 'ブラウザの窓で認証を完了してください',
  [switch]$NoBeep
)

$ErrorActionPreference = 'Stop'

# スタートメニューの Windows PowerShell ショートカットの AppUserModelID を借用する。
# 専用 AUMID を登録すると環境を汚すので行わない（実測メモ C-2）。
$AppId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'

function Show-Toast {
  param([string]$Title, [string]$Body)

  [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
  [void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime]

  $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
    [Windows.UI.Notifications.ToastTemplateType]::ToastText02)

  $texts = $template.GetElementsByTagName('text')
  $texts.Item(0).AppendChild($template.CreateTextNode($Title)) | Out-Null
  $texts.Item(1).AppendChild($template.CreateTextNode($Body))  | Out-Null

  $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
  # Show() は即座に戻る（応答を待たない）。ここでブロックする手段は使わない。
  [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($AppId).Show($toast)
}

try {
  Show-Toast -Title $Title -Body $Body
  Write-Output 'notify: toast'
} catch {
  # 集中モード・WinRT 不在（pwsh で実行された等）・AUMID 解決失敗のいずれでもここに来る。
  Write-Output "notify: toast failed ($($_.Exception.Message))"
  if (-not $NoBeep) {
    try {
      [console]::beep(880, 300)
      Write-Output 'notify: beep'
    } catch {
      Write-Output 'notify: silent'
    }
  }
}

exit 0
