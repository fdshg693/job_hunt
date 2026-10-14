// LinkedIn 認証状態チェック用スクリプト
async page => {
  const currentUrl = page.url();

  // 認証壁URLのパターン（ログイン画面、AuthWall、チェックポイント、SSO等）
  const isAuthWallUrl = u =>
    /linkedin\.com\/(?:authwall|login|checkpoint|uas\/login)|accounts\.google\.com/i.test(u);

  let onAuthWall = isAuthWallUrl(currentUrl);
  let authType = null;

  if (onAuthWall) {
    if (/checkpoint/i.test(currentUrl)) {
      authType = 'captcha';
    } else {
      authType = 'login';
    }
  }

  // ログイン済みを示す要素の存在確認
  let hasLoggedInNav = false;
  try {
    const navCount = await page
      .locator(
        'header a[href*="/jobs"], nav a[href*="/jobs"], button[aria-label*="Me"], a[href*="/messaging"], nav button:has-text("プロフィール")'
      )
      .count();
    if (navCount > 0) {
      hasLoggedInNav = true;
    }
  } catch (_) {}

  const loggedIn = !onAuthWall && (hasLoggedInNav || !isAuthWallUrl(currentUrl));

  const loc = await page
    .evaluate(() => ({
      host: location.host,
      pathname: location.pathname,
    }))
    .catch(() => ({ host: '', pathname: '' }));

  return {
    loggedIn: loggedIn && !onAuthWall,
    onAuthWall: onAuthWall || !loggedIn,
    authType,
    url: currentUrl,
    host: loc.host,
    pathname: loc.pathname,
  };
}
