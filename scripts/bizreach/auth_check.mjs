// scripts/bizreach/auth_check.mjs
// ビズリーチの現在の認証状態（ログイン済みか、認証画面にいるか）を瞬時にチェックする Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/bizreach/auth_check.mjs --raw

async page => {
  const currentUrl = page.url();

  // 認証壁URLのパターン（ログイン画面、OAuthリダイレクト、サインアップ等）
  const isAuthWallUrl = u =>
    /auth\.id\.bizreach\.jp|\/login|\/signin|\/members\/register|\/auth\/login-callback/i.test(u);

  let onAuthWall = isAuthWallUrl(currentUrl);

  // トップページ等にいる場合、ログインリンクがあるかチェック
  if (!onAuthWall && /^https:\/\/(?:www\.)?bizreach\.jp\/?$/i.test(currentUrl)) {
    try {
      const loginLinkCount = await page.locator('a[href*="/login"]').count();
      if (loginLinkCount > 0) {
        onAuthWall = true;
      }
    } catch (_) {
      // タイムアウト等の場合はURL判定を優先
    }
  }

  // ログイン済みを示す要素（マイページ、メッセージ、ユーザー名ボタン等）の存在確認
  let hasLoggedInNav = false;
  try {
    const navCount = await page
      .locator('nav a[href*="/mypage"], a[href*="/messages"], button:has-text("様")')
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
