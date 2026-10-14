// scripts/common/js/universal_auth.mjs
// サイト横断 共通認証状態判定・待機 Playwright スクリプト
// sharing-browser-with-user/references/scripted-automation.md 準拠

async page => {
  const t0 = Date.now();
  const action = process.env.AUTH_ACTION || 'check';
  const timeoutMs = parseInt(process.env.TIMEOUT_MS || '600000', 10);
  const wallRegexStr = process.env.AUTH_WALL_REGEX || '';
  const wallRegex = wallRegexStr ? new RegExp(wallRegexStr, 'i') : null;
  const checkCaptcha = process.env.CHECK_CAPTCHA === '1';

  let loggedInSelectors = [];
  try {
    if (process.env.LOGGED_IN_SELECTORS) {
      loggedInSelectors = JSON.parse(process.env.LOGGED_IN_SELECTORS);
    }
  } catch (_) {
    if (process.env.LOGGED_IN_SELECTORS) {
      loggedInSelectors = process.env.LOGGED_IN_SELECTORS.split(',').map(s => s.trim()).filter(Boolean);
    }
  }

  const checkState = async () => {
    const currentUrl = page.url();
    let onAuthWall = wallRegex ? wallRegex.test(currentUrl) : false;
    let authType = onAuthWall ? 'login' : null;

    // CAPTCHA・WAF 判定
    if (checkCaptcha) {
      try {
        const title = (await page.title()) || '';
        const isForbidden = title.includes('403 Forbidden');
        const isCaptchaTitle = title.includes('画像認証');

        const domInfo = await page.evaluate(() => {
          const hasCaptchaInput = !!document.querySelector('input[name*="captcha"]');
          const hasCaptchaText = !!(
            document.body &&
            document.body.textContent.includes('通常と異なるアクセスが検出されました')
          );
          const hasLoginInput = !!document.querySelector('input[name="user_id"], form[action*="login"]');
          return { hasCaptchaInput, hasCaptchaText, hasLoginInput };
        }).catch(() => ({ hasCaptchaInput: false, hasCaptchaText: false, hasLoginInput: false }));

        if (isCaptchaTitle || domInfo.hasCaptchaInput || domInfo.hasCaptchaText) {
          onAuthWall = true;
          authType = 'captcha';
        } else if (isForbidden) {
          onAuthWall = true;
          authType = 'forbidden';
        } else if (domInfo.hasLoginInput) {
          onAuthWall = true;
          authType = 'login';
        }
      } catch (_) {}
    }

    // ログイン済みを示す要素の存在確認
    let hasLoggedInNav = false;
    for (const sel of loggedInSelectors) {
      try {
        const cnt = await page.locator(sel).count();
        if (cnt > 0) {
          hasLoggedInNav = true;
          break;
        }
      } catch (_) {}
    }

    const loggedIn = !onAuthWall && (hasLoggedInNav || (!wallRegex || !wallRegex.test(currentUrl)));

    let host = '';
    let pathname = '';
    try {
      const loc = await page.evaluate(() => ({
        host: location.host,
        pathname: location.pathname,
      }));
      host = loc.host;
      pathname = loc.pathname;
    } catch (_) {}

    return {
      loggedIn: loggedIn && !onAuthWall,
      onAuthWall: onAuthWall || !loggedIn,
      authType,
      url: currentUrl,
      host,
      pathname,
    };
  };

  // 1. チェックアクション
  if (action === 'check') {
    return await checkState();
  }

  // 2. ガード（待機）アクション
  let state = await checkState();
  if (!state.onAuthWall && state.loggedIn) {
    return {
      loggedIn: true,
      cleared: true,
      onAuthWall: false,
      waitedMs: 0,
      url: state.url,
    };
  }

  // 待機開始直前にウィンドウ前面化を試行
  try {
    await page.bringToFront();
  } catch (_) {}

  while (Date.now() - t0 < timeoutMs) {
    try {
      await page.waitForTimeout(1500);
    } catch (_) {
      break;
    }

    try {
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

      state = await checkState();
      if (!state.onAuthWall && state.loggedIn) {
        return {
          loggedIn: true,
          cleared: true,
          onAuthWall: false,
          waitedMs: Date.now() - t0,
          url: state.url,
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
