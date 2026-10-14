// scripts/findy/auth_guard.mjs
// Findy認証状態の検知および手動ログイン待機 Playwright スクリプト
// sharing-browser-with-user/references/scripted-automation.md §3 準拠
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/findy/auth_guard.mjs --raw

async page => {
  const t0 = Date.now();
  const currentUrl = page.url();

  const isAuthWallUrl = u =>
    /\/users\/sign_in|\/login|\/signin|\/users\/auth|accounts\.google\.com|github\.com\/login/i.test(u);

  // 認証壁状態の判定
  let onAuthWall = isAuthWallUrl(currentUrl);
  if (!onAuthWall && /^https:\/\/findy-code\.io\/?$/i.test(currentUrl)) {
    try {
      const signInLinkCount = await page.locator('a[href="/users/sign_in"]').count();
      if (signInLinkCount > 0) {
        onAuthWall = true;
      }
    } catch (_) {}
  }

  // 既にログイン完了している場合は即座に正常終了
  if (!onAuthWall) {
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
  // 述語関数で「認証画面から離脱し、ログイン後画面へ遷移した」ことを検知する
  try {
    await page.waitForURL(
      u => {
        const s = u.toString();
        return !isAuthWallUrl(s) && !/^https:\/\/findy-code\.io\/?$/i.test(s);
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
