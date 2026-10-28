// scripts/bizreach/search_jobs.mjs
// ビズリーチ求人検索画面から求人カード一覧および検索メタデータを抽出する Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/bizreach/search_jobs.mjs --raw

async page => {
  const targetUrl = process.env.BIZREACH_SEARCH_URL || 'https://www.bizreach.jp/jobs/search/';
  const limit = parseInt(process.env.SEARCH_LIMIT || '50', 10);

  // 指定URLへナビゲート（現在のURLと異なる場合）
  const currentUrl = page.url();
  if (currentUrl !== targetUrl) {
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  }

  // 求人一覧または該当なしメッセージの出現を待機
  try {
    await page.waitForSelector(
      'div[class*="JobListItemWithCompanyLink"], div[class*="JobSearchResult"], h3:has-text("件"), div:has-text("該当する求人は見つかりませんでした")',
      { timeout: 15000 }
    );
  } catch (_) {
    // タイムアウト時はそのまま抽出へ進む
  }

  // 構造化データの抽出
  const result = await page.evaluate(limitCount => {
    // 総件数の抽出
    let totalCount = 0;
    const countCandidates = Array.from(document.querySelectorAll('h3, h2, p, span'));
    for (const el of countCandidates) {
      const text = el.textContent ? el.textContent.trim() : '';
      const m = text.replace(/,/g, '').match(/^(\d+)\s*件$/) || text.replace(/,/g, '').match(/(\d+)\s*件/);
      if (m && (el.className.includes('JobSearch') || el.closest('section') || el.closest('main') || text.includes('件'))) {
        const num = parseInt(m[1], 10);
        if (num > 0 && (totalCount === 0 || num > totalCount)) {
          totalCount = num;
        }
      }
    }

    // 求人カード要素の探索
    let cardEls = Array.from(document.querySelectorAll('div[class*="JobListItemWithCompanyLink"][class*="card"]'));
    if (cardEls.length === 0) {
      // フォールバック: cardクラスと求人リンクを持つdiv
      cardEls = Array.from(document.querySelectorAll('div[class*="card"]')).filter(el =>
        el.querySelector('a[href*="/jobs/"]')
      );
    }

    const jobs = [];

    for (const card of cardEls) {
      if (jobs.length >= limitCount) {
        break;
      }

      // 求人リンク & ID
      const linkEl =
        card.querySelector('a[class*="background-link"]') ||
        card.querySelector('a[href*="/jobs/"]');
      const href = linkEl ? linkEl.getAttribute('href') || '' : '';
      const idMatch = href.match(/\/jobs\/([a-zA-Z0-9_-]+)/);
      const id = idMatch ? idMatch[1] : '';
      const fullUrl = href.startsWith('http')
        ? href
        : href
        ? `https://www.bizreach.jp${href}`
        : '';

      // 求人タイトル
      const titleEl =
        card.querySelector('h3[class*="job-title"]') ||
        card.querySelector('h3') ||
        card.querySelector('a[class*="title"]');
      const title = titleEl ? titleEl.textContent.trim() : '';

      // 想定年収
      const salaryEl =
        card.querySelector('p[class*="color-accent-primary"]') ||
        card.querySelector('span[class*="color-accent-primary"]') ||
        card.querySelector('[class*="salary"]');
      const salaryText = salaryEl ? salaryEl.textContent.trim() : '';

      // 企業名 & 企業URL
      const compLinkEl = card.querySelector('a[class*="company-link"]') || card.querySelector('a[href*="/company/view/"]');
      const compNameEl = compLinkEl
        ? compLinkEl.querySelector('p') || compLinkEl
        : card.querySelector('p[class*="company-name"]');
      const company = compNameEl ? compNameEl.textContent.trim() : '';
      const compHref = compLinkEl ? compLinkEl.getAttribute('href') || '' : '';
      const companyUrl = compHref.startsWith('http')
        ? compHref
        : compHref
        ? `https://www.bizreach.jp${compHref}`
        : '';

      // 勤務地
      const locEl =
        card.querySelector('div[aria-label="work-location"] p') ||
        card.querySelector('div[aria-label="work-location"]');
      const location = locEl ? locEl.textContent.trim() : '';

      // 特徴タグ（appeals）
      const appealEls = Array.from(
        card.querySelectorAll('div[aria-label="appeals"] div[class*="Label"], div[aria-label="appeals"] span')
      );
      const appeals = appealEls
        .map(el => el.textContent.trim())
        .filter(t => t.length > 0 && !t.includes('\n'));

      // 職種・業種カテゴリ
      let jobRole = '';
      let industry = '';
      const roleIcon = card.querySelector('span[class*="business-bag"]');
      if (roleIcon && roleIcon.parentElement) {
        jobRole = roleIcon.parentElement.textContent.replace(roleIcon.textContent || '', '').trim();
      }
      const buildingIcon = card.querySelector('span[class*="building"]');
      if (buildingIcon && buildingIcon.parentElement) {
        industry = buildingIcon.parentElement.textContent.replace(buildingIcon.textContent || '', '').trim();
      }

      // 求人概要スニペット
      const descEl =
        card.querySelector('p[class*="description"]') ||
        card.querySelector('div[class*="content"] p');
      const snippet = descEl ? descEl.textContent.trim().replace(/\s+/g, ' ') : '';

      if (id || title) {
        jobs.push({
          id,
          title,
          company,
          companyUrl,
          url: fullUrl,
          salaryText,
          location,
          appeals,
          jobRole,
          industry,
          snippet
        });
      }
    }

    return {
      totalCount: totalCount || jobs.length,
      cardCount: cardEls.length,
      jobs
    };
  }, limit);

  return {
    success: true,
    url: page.url(),
    ...result
  };
}
