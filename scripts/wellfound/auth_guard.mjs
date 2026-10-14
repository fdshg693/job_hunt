// scripts/wellfound/auth_guard.mjs
// Wellfound 認証状態の検知および手動ログイン待機 Playwright スクリプト
// sharing-browser-with-user/references/scripted-automation.md §3 準拠
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/wellfound/auth_guard.mjs --raw

async page => {
  const t0 = Date.now();
  const currentUrl = page.url();

  const isAuthWallUrl = u =>
    /wellfound\.com\/(?:login|join)|accounts\.google\.com/i.test(u);

  let onAuthWall = isAuthWallUrl(currentUrl);

  // 既にログイン完了しているかチェック（アバター、ボタン等）
  let hasLoggedInNav = false;
  try {
    const navCount = await page
      .locator('img[alt*="Avatar for"], button:has-text("Open to offers"), a[href*="/profile/edit"]')
      .count();
    if (navCount > 0) {
      hasLoggedInNav = true;
    }
  } catch (_) {}

  if (!onAuthWall && hasLoggedInNav) {
    return {
      loggedIn: true,
      onAuthWall: false,
      waitedMs: 0,
      url: currentUrl
    };
  }

  // 待機開始直前にユーザーの注意を促すため前面化
  try {
    await page.bringToFront();
  } catch (_) {}

  // タイムアウト付き待機（最大10分 = 600,000ms）
  try {
    await page.waitForURL(
      u => {
        const s = u.toString();
        return !isAuthWallUrl(s);
      },
      { timeout: 600000 }
    );

    // 念のため画面要素も確認
    await page.waitForTimeout(2000);

    return {
      loggedIn: true,
      onAuthWall: false,
      waitedMs: Date.now() - t0,
      url: page.url()
    };
  } catch (e) {
    const errorStr = String(e && e.message ? e.message : e);
    const closed = /has been closed|Target page, context or browser has been closed/i.test(errorStr);
    return {
      loggedIn: false,
      onAuthWall: true,
      timedOut: !closed,
      windowClosed: closed,
      waitedMs: Date.now() - t0,
      url: page.url(),
      error: closed ? 'window_closed' : 'timed_out'
    };
  }
}
