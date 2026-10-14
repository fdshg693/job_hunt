// scripts/youtrust/auth_check.mjs
// YOUTRUSTの現在の認証状態（ログイン済みか、認証画面にいるか）を瞬時にチェックする Playwright スクリプト

async page => {
  const currentUrl = page.url();

  // 認証壁URLのパターン（サインイン画面、Google OAuth等）
  const isAuthWallUrl = u =>
    /youtrust\.jp\/sign_in|accounts\.google\.com/i.test(u);

  let onAuthWall = isAuthWallUrl(currentUrl);

  // ログイン済みを示す要素（ヘッダーメニュー、設定、チャット、プロフィール等）
  let hasLoggedInNav = false;
  try {
    const navCount = await page
      .locator('header a[href*="/friend_connections"], header a[href*="/chat_rooms"], header a[href*="/users/"], a[href*="/settings/profile"], button:has-text("保存")')
      .count();
    if (navCount > 0) {
      hasLoggedInNav = true;
    }
  } catch (_) {}

  // APIによる確認（セッション情報）
  let apiOk = false;
  try {
    apiOk = await page.evaluate(async () => {
      try {
        const res = await fetch('/api/session_user', {
          headers: { Accept: 'application/json' },
          credentials: 'include',
        });
        if (!res.ok) return false;
        const data = await res.json();
        return !!(data && data.id);
      } catch (_) {
        return false;
      }
    });
  } catch (_) {}

  const loggedIn = !onAuthWall && (hasLoggedInNav || apiOk);

  return {
    loggedIn: loggedIn && !onAuthWall,
    onAuthWall: onAuthWall || !loggedIn,
    url: currentUrl,
  };
}
