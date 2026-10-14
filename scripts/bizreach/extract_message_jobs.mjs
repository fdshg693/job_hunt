// scripts/bizreach/extract_message_jobs.mjs
// ビズリーチの個別メッセージ画面から添付求人のアコーディオンを展開し、添付求人情報を抽出する Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/bizreach/extract_message_jobs.mjs --raw

async page => {
  let targetUrl = null;
  try {
    if (typeof process !== 'undefined' && process && process.env) {
      targetUrl = process.env.BIZREACH_MESSAGE_URL || null;
    }
  } catch (_) {}

  if (targetUrl && !page.url().includes(targetUrl)) {
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  }

  const currentUrl = page.url();

  // 認証壁判定
  const isAuthWall = /auth\.id\.bizreach\.jp|\/login|\/signin/i.test(currentUrl);
  if (isAuthWall) {
    return {
      success: false,
      error: '認証が必要です（ログイン画面にリダイレクトされました）',
      url: currentUrl
    };
  }

  // メッセージスレッド画面待機
  try {
    await page.waitForSelector(
      'section[class*="ThreadDetailView"], div[class*="message-list"], button[class*="Accordion"], main',
      { timeout: 15000 }
    );
  } catch (_) {
    // タイムアウト時はそのまま続行
  }

  // 添付求人アコーディオンの開閉状態を判定し、閉じている場合は展開
  try {
    const triggerLocator = page.locator('button[class*="Accordion"][class*="trigger"]');
    const triggerCount = await triggerLocator.count();

    for (let i = 0; i < triggerCount; i++) {
      const trigger = triggerLocator.nth(i);
      const text = (await trigger.textContent() || '').trim();
      if (text.includes('添付求人')) {
        const ariaExpanded = await trigger.getAttribute('aria-expanded');
        const dataState = await trigger.getAttribute('data-state');
        if (ariaExpanded === 'false' || dataState === 'closed') {
          try {
            await trigger.click();
            await page.waitForTimeout(500);
          } catch (_) {}
        }
      }
    }
  } catch (_) {
    // アコーディオン操作エラー時は既存表示のまま抽出を試みる
  }

  // DOMからスレッド情報および添付求人情報を抽出
  const extraction = await page.evaluate(() => {
    const url = window.location.href;
    const pageTitle = document.title;

    // スレッドID抽出
    const threadMatch = url.match(/\/messages\/([a-zA-Z0-9_-]+)/);
    const threadId = threadMatch ? threadMatch[1] : null;

    // 送信者情報（会社名 / 担当者名）
    const senderEl = document.querySelector('header [class*="recruiter-company-name"], [class*="MessageHeader"] [class*="sender"]');
    const senderName = senderEl ? senderEl.textContent.trim() : '';

    // 求人リンク要素の収集
    const allJobLinks = Array.from(document.querySelectorAll('a[href*="/jobs/"]'));
    const attachedLinks = allJobLinks.filter(a => {
      const href = a.getAttribute('href') || '';
      if (!href) return false;
      // ナビゲーション等の共通求人リンクを除外
      if (href.includes('/jobs/search') || href.includes('/favorite/jobs') || href.includes('/jobs/applied')) {
        return false;
      }
      // /jobs/{id}/ 形式か判定
      return /\/jobs\/[a-zA-Z0-9_-]+/.test(href);
    });

    const seenJobIds = new Set();
    const jobs = [];

    for (const linkEl of attachedLinks) {
      const rawHref = linkEl.getAttribute('href') || '';
      const m = rawHref.match(/\/jobs\/([a-zA-Z0-9_-]+)/);
      if (!m) continue;
      const jobId = m[1];

      // 同一求人IDの重複排除
      if (seenJobIds.has(jobId)) continue;
      seenJobIds.add(jobId);

      const fullJobUrl = rawHref.startsWith('http')
        ? rawHref
        : `https://www.bizreach.jp/jobs/${jobId}/`;

      // カード内要素からメタデータを抽出
      const titleEl = linkEl.querySelector('[class*="job-title"], h3');
      const title = titleEl ? titleEl.textContent.trim() : '';

      const salaryEl = linkEl.querySelector('[class*="salary"]');
      const salary = salaryEl ? salaryEl.textContent.trim() : '';

      const catEl = linkEl.querySelector('[class*="job-category"]');
      const category = catEl ? catEl.textContent.trim() : '';

      const locEl = linkEl.querySelector('[class*="work-location"]');
      const location = locEl ? locEl.textContent.trim() : '';

      const compEl = linkEl.querySelector('[class*="company-name"]');
      const company = compEl ? compEl.textContent.trim() : '';

      const indEl = linkEl.querySelector('[class*="company-industry"]');
      const industry = indEl ? indEl.textContent.trim() : '';

      const imgEl = linkEl.querySelector('img');
      const imageUrl = imgEl ? (imgEl.getAttribute('src') || '') : '';

      jobs.push({
        jobId,
        jobUrl: fullJobUrl,
        title,
        salary,
        category,
        location,
        company,
        industry,
        imageUrl
      });
    }

    return {
      threadId,
      url,
      pageTitle,
      senderName,
      totalCount: jobs.length,
      jobs
    };
  });

  return {
    success: true,
    ...extraction
  };
}
