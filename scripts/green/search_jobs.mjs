// scripts/green/search_jobs.mjs
// Green（https://www.green-japan.com/search）で画面上部サーチバー操作またはクエリ指定による求人検索を行う Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/green/search_jobs.mjs --raw

async page => {
  const result = {
    success: false,
    fetchedAt: new Date().toISOString(),
    url: '',
    keyword: '__KEYWORD__',
    minSalary: '__MIN_SALARY__',
    currentPage: 1,
    totalCount: 0,
    jobs: [],
    errors: [],
  };

  const BASE_URL = 'https://www.green-japan.com';
  const keyword = ('__KEYWORD__' || '').trim();
  const minSalaryStr = ('__MIN_SALARY__' || '').trim();
  const pageNum = parseInt('__PAGE__' || '1', 10) || 1;
  const limit = __LIMIT__;

  // 初期遷移URLの構築（パラメータがあれば付与）
  const queryParts = [];
  if (keyword) queryParts.push(`keyword=${encodeURIComponent(keyword)}`);
  if (minSalaryStr && !isNaN(parseInt(minSalaryStr, 10))) {
    queryParts.push(`salary_bottom_id=${encodeURIComponent(minSalaryStr)}`);
  }
  if (pageNum > 1) {
    queryParts.push(`page=${encodeURIComponent(String(pageNum))}`);
  }

  const queryStr = queryParts.join('&');
  const initialUrl = queryStr ? `${BASE_URL}/search?${queryStr}` : `${BASE_URL}/search`;
  result.url = initialUrl;

  try {
    await page.goto(initialUrl, { waitUntil: 'domcontentloaded', timeout: 35000 });
    await page.waitForTimeout(1500);

    const currentUrl = page.url();
    if (currentUrl.includes('/login') || currentUrl.includes('accounts.google.com')) {
      result.errors.push(`未ログイン状態または認証壁に到達しました（現在のURL: ${currentUrl}）`);
      return result;
    }

    // 画面上部サーチバーの直接操作（ユーザー要件: 指定は画面上部のサーチバーで行う）
    // ページ読み込み後にキーワード入力欄を操作して再検索または確定
    const searchInput = page.locator('input[placeholder="キーワード"], input[name="user_search[keyword]"]').first();
    if (keyword && (await searchInput.count()) > 0) {
      try {
        const currentVal = await searchInput.inputValue();
        if (currentVal !== keyword) {
          await searchInput.fill(keyword);
          await page.waitForTimeout(300);
          // Enter または 検索ボタン押下
          const searchBtn = page.locator('button[type="submit"], button[aria-label="求人を検索"]').first();
          if ((await searchBtn.count()) > 0 && !(await searchBtn.isDisabled())) {
            await searchBtn.click();
          } else {
            await searchInput.press('Enter');
          }
          await page.waitForTimeout(2000);
        }
      } catch (inputErr) {
        // サーチバー操作失敗時はURL遷移結果をそのまま利用
      }
    }

    result.url = page.url();

    // 検索結果の抽出（Next.js props 優先、DOM フォールバック）
    const extractedData = await page.evaluate(() => {
      const pp = window.__NEXT_DATA__?.props?.pageProps;
      const defaultData = pp?.defaultSearchJobOfferData;
      const totalCount = defaultData?.totalJobOfferCount ?? defaultData?.totalCount ?? 0;

      const jobs = [];

      // 1. Next.js の構造化データから取得
      if (defaultData?.jobOffers && Array.isArray(defaultData.jobOffers) && defaultData.jobOffers.length > 0) {
        for (const item of defaultData.jobOffers) {
          const comp = item.company || item.client || {};
          const id = String(item.id || '');
          const jobUrl = item.jobOfferUrl ? `https://www.green-japan.com${item.jobOfferUrl}` : `https://www.green-japan.com/job/${id}`;

          // 年収文字列
          let salary = item.salary || '';
          if (!salary && (item.minSalary || item.maxSalary)) {
            salary = `${item.minSalary ?? ''}万円〜${item.maxSalary ?? ''}万円`;
          }

          // タグ
          const tags = [];
          if (Array.isArray(item.tagNames)) tags.push(...item.tagNames);
          if (Array.isArray(item.skillNames)) tags.push(...item.skillNames);

          jobs.push({
            id: id,
            company: comp.name || comp.fullName || '企業名不明',
            companyId: comp.id ? String(comp.id) : '',
            companyTitle: comp.title || '',
            title: item.title || item.name || '',
            roleName: item.name || '',
            salary: salary,
            location: item.areaName || '',
            url: jobUrl,
            tags: tags,
            employeesNumber: item.employeesNumber || null,
            updatedAtTimestamp: item.jobOfferUpdatedAtTimestamp || null,
          });
        }
      }

      // 2. もし Next.js props が空だった場合の DOM フォールバック
      if (jobs.length === 0) {
        const cardLinks = Array.from(document.querySelectorAll('a[href*="/job/"]'));
        const seenIds = new Set();

        for (const card of cardLinks) {
          const href = card.href;
          const match = href.match(/\/job\/(\d+)/);
          if (!match) continue;
          const id = match[1];
          if (seenIds.has(id)) continue;
          seenIds.add(id);

          const lines = card.innerText.split('\n').map(s => s.trim()).filter(Boolean);
          let company = '';
          const pTags = Array.from(card.querySelectorAll('p'));
          if (pTags.length > 0) company = pTags[0].innerText.trim();
          else if (lines.length > 1) company = lines[0];

          let title = '';
          const titleEl = card.querySelector('.job-offer-name, h3, h4');
          if (titleEl) title = titleEl.innerText.trim();
          else if (lines.length > 2) title = lines[1];

          let salary = '';
          const salLine = lines.find(l => /^\d+万円(?:〜\d+万円)?/.test(l));
          if (salLine) salary = salLine;

          jobs.push({
            id: id,
            company: company || '企業名不明',
            companyId: '',
            companyTitle: '',
            title: title || '求人タイトル不明',
            roleName: '',
            salary: salary,
            location: '',
            url: href,
            tags: [],
            employeesNumber: null,
            updatedAtTimestamp: null,
          });
        }
      }

      return {
        totalCount: totalCount || jobs.length,
        jobs: jobs,
      };
    });

    result.totalCount = extractedData.totalCount;
    let jobList = extractedData.jobs;

    if (limit > 0 && jobList.length > limit) {
      jobList = jobList.slice(0, limit);
    }

    result.jobs = jobList;
    result.success = true;
  } catch (err) {
    result.errors.push(`求人検索例外: ${err.message || String(err)}`);
  }

  return result;
}
