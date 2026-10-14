// LinkedIn 認証状態の検知および手動ログイン待機 Playwright スクリプト
async page => {
  const t0 = Date.now();
  const currentUrl = page.url();

  const isAuthWallUrl = u =>
    /linkedin\.com\/(?:authwall|login|checkpoint|uas\/login)|accounts\.google\.com/i.test(u);

  let onAuthWall = isAuthWallUrl(currentUrl);

  // 既にログイン完了している場合は即座に正常終了
  if (!onAuthWall) {
    return {
      loggedIn: true,
      onAuthWall: false,
      waitedMs: 0,
      url: currentUrl,
    };
  }

  // 前面化
  try {
    await page.bringToFront();
  } catch (_) {}

  // 待機（最大10分）
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
      url: page.url(),
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
      error: closed ? 'window_closed' : 'timed_out',
    };
  }
}
