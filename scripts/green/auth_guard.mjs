// scripts/green/auth_guard.mjs
// Green認証状態の検知および手動ログイン待機 Playwright スクリプト
// sharing-browser-with-user/references/scripted-automation.md §3 準拠
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/green/auth_guard.mjs --raw

async page => {
  const t0 = Date.now();
  const currentUrl = page.url();

  const isAuthWallUrl = u =>
    /green-japan\.com\/login|accounts\.google\.com/i.test(u);

  // 認証壁状態の判定
  let onAuthWall = isAuthWallUrl(currentUrl);

  // Next.js の __NEXT_DATA__ から isLogin フラグをチェック
  let isLoginFlag = false;
  try {
    isLoginFlag = await page.evaluate(() => {
      try {
        return !!(window.__NEXT_DATA__?.props?.pageProps?.userData?.isLogin);
      } catch (_) {
        return false;
      }
    });
  } catch (_) {}

  // 既にログイン完了している場合は即座に正常終了
  if (!onAuthWall && (isLoginFlag || !isAuthWallUrl(currentUrl))) {
    return {
      loggedIn: true,
      onAuthWall: false,
      waitedMs: 0,
      url: currentUrl
    };
  }

  // 待機開始直前にユーザーの注意を促すため前面化（1回のみ）
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
