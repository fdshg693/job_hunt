// scripts/wellfound/auth_check.mjs
// Wellfound の現在の認証状態（ログイン済みか、認証画面にいるか）をチェックする Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/wellfound/auth_check.mjs --raw

async page => {
  const currentUrl = page.url();

  // 認証壁URLのパターン（サインイン画面、Google OAuth等）
  const isAuthWallUrl = u =>
    /wellfound\.com\/(?:login|join)|accounts\.google\.com/i.test(u);

  let onAuthWall = isAuthWallUrl(currentUrl);

  // ログイン済みを示す要素（アバター画像、Open to offersボタン、プロフィール編集リンク、求人リンク等）
  let hasLoggedInNav = false;
  try {
    const navCount = await page
      .locator('img[alt*="Avatar for"], button:has-text("Open to offers"), a[href*="/profile/edit"], a[href*="/jobs"]')
      .count();
    if (navCount > 0) {
      hasLoggedInNav = true;
    }
  } catch (_) {}

  // Next.js の __NEXT_DATA__ から currentUser または Candidate をチェック
  let hasUserInStore = false;
  try {
    hasUserInStore = await page.evaluate(() => {
      try {
        const apollo = window.__NEXT_DATA__?.props?.pageProps?.apolloState?.data;
        if (!apollo) return false;
        return Object.keys(apollo).some(k => k.startsWith('User:') || k.startsWith('Candidate:'));
      } catch (_) {
        return false;
      }
    });
  } catch (_) {}

  const loggedIn = !onAuthWall && (hasLoggedInNav || hasUserInStore);

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
