// scripts/green/auth_check.mjs
// Greenの現在の認証状態（ログイン済みか、認証画面にいるか）を瞬時にチェックする Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/green/auth_check.mjs --raw

async page => {
  const currentUrl = page.url();

  // 認証壁URLのパターン（サインイン画面、Google OAuth等）
  const isAuthWallUrl = u =>
    /green-japan\.com\/login|accounts\.google\.com/i.test(u);

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

  // ログイン済みを示す要素（ヘッダーメニュー、ログアウト、プロフィール編集リンク、メッセージ一覧等）
  let hasLoggedInNav = false;
  try {
    const navCount = await page
      .locator('a[href*="/profiles/edit"], a[href*="/messages"], a[href*="/client_users/interests"], a[href*="/favorites/received"], a[href*="/search"], button:has-text("ログアウト")')
      .count();
    if (navCount > 0) {
      hasLoggedInNav = true;
    }
  } catch (_) {}

  const loggedIn = !onAuthWall && (isLoginFlag || hasLoggedInNav || !isAuthWallUrl(currentUrl));

  const loc = await page
    .evaluate(() => ({
      host: location.host,
      pathname: location.pathname
    }))
    .catch(() => ({ host: '', pathname: '' }));

  return {
    loggedIn: loggedIn && !onAuthWall,
    onAuthWall: onAuthWall || !loggedIn,
    url: currentUrl,
    host: loc.host,
    pathname: loc.pathname
  };
}
