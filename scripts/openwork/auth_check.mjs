// OpenWork 認証・CAPTCHA壁判定スクリプト
async page => {
  const currentUrl = page.url();
  const targetUrl = (typeof process !== 'undefined' && process.env && process.env.TARGET_URL) || 'https://www.openwork.jp/mypage/resume';



  const currentTitle = await page.title();

  // WAF (awselb) 403 対策: Chrome User-Agent をセットして遷移
  if (!currentUrl || currentUrl === 'about:blank' || currentUrl.includes('403') || currentTitle.includes('403')) {
    try {
      const client = await page.context().newCDPSession(page);
      await client.send('Network.setUserAgentOverride', {
        userAgent:
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        acceptLanguage: 'ja,en-US;q=0.9,en;q=0.8',
        platform: 'Win32',
      });
    } catch (_) {}
    const retryUrl = (currentUrl && currentUrl.startsWith('http') && !currentUrl.includes('403')) ? currentUrl : targetUrl;
    await page.goto(retryUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  }



  const title = await page.title();
  const url = page.url();

  // タイトル、URL、または本文から認証壁（画像認証・403・ログイン画面）を判定
  const authInfo = await page.evaluate(() => {
    const t = document.title || '';
    const u = window.location.href;

    const isForbidden = t.includes('403 Forbidden');
    const isCaptcha =
      t.includes('画像認証') ||
      !!document.querySelector('input[name*="captcha"]') ||
      (document.body && document.body.textContent.includes('通常と異なるアクセスが検出されました'));

    const isLoginPage =
      u.includes('login.php') ||
      t.includes('ログイン') ||
      !!document.querySelector('form[action*="login"]') ||
      !!document.querySelector('input[name="user_id"]');

    let authType = null;
    if (isCaptcha) {
      authType = 'captcha';
    } else if (isForbidden) {
      authType = 'forbidden';
    } else if (isLoginPage) {
      authType = 'login';
    }

    return {
      onAuthWall: !!authType,
      authType,
    };
  });

  return {
    success: true,
    url,
    title,
    onAuthWall: authInfo.onAuthWall,
    authType: authInfo.authType,
  };
}
