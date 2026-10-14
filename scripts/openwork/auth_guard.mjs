// scripts/openwork/auth_guard.mjs
// OpenWork画像認証・CAPTCHA解除の手動待機 Playwright スクリプト
// sharing-browser-with-user/references/scripted-automation.md §3 準拠

async page => {
  const t0 = Date.now();
  const timeoutMs = 600000; // 最大10分

  const checkOnWall = async () => {
    try {
      const title = await page.title();
      const url = page.url();
      if (title.includes('画像認証') || title.includes('403 Forbidden') || title.includes('ログイン') || url.includes('login.php')) {
        return true;
      }
      return await page.evaluate(() => {
        const hasCaptchaInput = !!document.querySelector('input[name*="captcha"]');
        const hasCaptchaText = document.body && document.body.textContent.includes('通常と異なるアクセスが検出されました');
        const hasLoginInput = !!document.querySelector('input[name="user_id"]');
        return hasCaptchaInput || hasCaptchaText || hasLoginInput;
      });
    } catch (_) {
      return false;
    }
  };

  let onWall = await checkOnWall();
  if (!onWall) {
    return {
      loggedIn: true,
      cleared: true,
      waitedMs: 0,
      url: page.url(),
    };
  }

  // 待機ループ（最大 timeoutMs）
  while (Date.now() - t0 < timeoutMs) {
    try {
      await page.waitForTimeout(2000);
    } catch (_) {
      break;
    }
    try {
      // ユーザーがブラウザを閉じたかのチェック
      if (page.isClosed()) {
        return {
          loggedIn: false,
          cleared: false,
          windowClosed: true,
          waitedMs: Date.now() - t0,
          url: '',
          error: 'window_closed',
        };
      }

      onWall = await checkOnWall();
      if (!onWall) {
        return {
          loggedIn: true,
          cleared: true,
          waitedMs: Date.now() - t0,
          url: page.url(),
        };
      }
    } catch (e) {
      const errorStr = String(e && e.message ? e.message : e);
      if (/has been closed|Target page, context or browser has been closed/i.test(errorStr)) {
        return {
          loggedIn: false,
          cleared: false,
          windowClosed: true,
          waitedMs: Date.now() - t0,
          url: '',
          error: 'window_closed',
        };
      }
    }
  }

  return {
    loggedIn: false,
    cleared: false,
    timedOut: true,
    waitedMs: Date.now() - t0,
    url: page.url(),
    error: 'timed_out',
  };
}
