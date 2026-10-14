// scripts/forkwell/auth_check.mjs
// Forkwellの現在の認証状態（ログイン済みか、認証画面にいるか）を瞬時にチェックする Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/forkwell/auth_check.mjs --raw

async page => {
  const currentUrl = page.url();

  // 認証壁URLのパターン（サインイン画面、OAuthリダイレクト、サインアップ等）
  const isAuthWallUrl = u =>
    /auth\.forkwell\.com|\/users\/sign_in|\/login|\/signin/i.test(u);

  let onAuthWall = isAuthWallUrl(currentUrl);

  // トップページ等にいる場合、ログインリンクがあるかチェック
  if (!onAuthWall && /^https:\/\/jobs\.forkwell\.com\/?$/i.test(currentUrl)) {
    try {
      const signInLinkCount = await page.locator('a[href*="/users/sign_in"]').count();
      if (signInLinkCount > 0) {
        onAuthWall = true;
      }
    } catch (_) {}
  }

  // ログイン済みを示す要素（ログアウトリンク、ダッシュボードリンク、スカウトボタン、メッセージリンク等）
  let hasLoggedInNav = false;
  try {
    const navCount = await page
      .locator('a[href*="/users/sign_out"], a[href*="/dashboard"], button:has-text("スカウト"), a[href*="/messages"], .dashboard-card')
      .count();
    if (navCount > 0) {
      hasLoggedInNav = true;
    }
  } catch (_) {}

  const loggedIn = !onAuthWall && (hasLoggedInNav || !isAuthWallUrl(currentUrl));

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
