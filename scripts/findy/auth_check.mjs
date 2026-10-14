// scripts/findy/auth_check.mjs
// Findyの現在の認証状態（ログイン済みか、認証画面にいるか）を瞬時にチェックする Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/findy/auth_check.mjs --raw

async page => {
  const currentUrl = page.url();

  // 認証壁URLのパターン（サインイン画面、SSO、Authコールバック等）
  const isAuthWallUrl = u =>
    /\/users\/sign_in|\/login|\/signin|\/users\/auth|accounts\.google\.com|github\.com\/login/i.test(u);

  let onAuthWall = isAuthWallUrl(currentUrl);

  // トップページにいる場合、ログインリンクがあるかチェック
  if (!onAuthWall && /^https:\/\/findy-code\.io\/?$/i.test(currentUrl)) {
    try {
      const signInLinkCount = await page.locator('a[href="/users/sign_in"]').count();
      if (signInLinkCount > 0) {
        onAuthWall = true;
      }
    } catch (_) {
      // タイムアウト等の場合はURL判定を優先
    }
  }

  // ログイン済みを示す要素（ヘッダーナビのマイページやいいね等）の存在確認
  let hasLoggedInNav = false;
  try {
    const navCount = await page.locator('header a[href*="/likes"], header a[href*="/home"], nav a[href*="/likes"]').count();
    if (navCount > 0) {
      hasLoggedInNav = true;
    }
  } catch (_) {}

  const loggedIn = !onAuthWall && (hasLoggedInNav || !isAuthWallUrl(currentUrl));

  const loc = await page.evaluate(() => ({
    host: location.host,
    pathname: location.pathname
  })).catch(() => ({ host: '', pathname: '' }));

  return {
    loggedIn: loggedIn && !onAuthWall,
    onAuthWall: onAuthWall || !loggedIn,
    url: currentUrl,
    host: loc.host,
    pathname: loc.pathname
  };
}
