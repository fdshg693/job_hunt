// scripts/levtech_direct/auth_check.mjs
// レバテックダイレクトの現在の認証状態（ログイン済みか、認証画面にいるか）を瞬時にチェックする Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/levtech_direct/auth_check.mjs --raw

async page => {
  const currentUrl = page.url();

  // 認証壁URLのパターン（サインイン画面、auth.levtech.jpリダイレクト等）
  const isAuthWallUrl = u =>
    /auth\.levtech\.jp|\/signin|\/login/i.test(u);

  let onAuthWall = isAuthWallUrl(currentUrl);

  // トップページ等にいる場合、サインインリンクがあるかチェック
  if (!onAuthWall && /^https:\/\/levtech-direct\.jp\/?$/i.test(currentUrl)) {
    try {
      const signInLinkCount = await page.locator('a[href*="/signin"]').count();
      if (signInLinkCount > 0) {
        onAuthWall = true;
      }
    } catch (_) {}
  }

  // ログイン済みを示す要素（マイページリンク、メッセージリンク、プロフィールリンク等）
  let hasLoggedInNav = false;
  try {
    const navCount = await page
      .locator('a[href*="/mypage"], a[href*="/mypage/message"], a[href*="/mypage/profile"]')
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
