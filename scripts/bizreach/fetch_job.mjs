// scripts/bizreach/fetch_job.mjs
// ビズリーチの求人詳細画面（/jobs/{id}/）から求人詳細情報を構造化抽出する Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/bizreach/fetch_job.mjs --raw

async page => {
  const targetUrl = process.env.BIZREACH_JOB_URL;
  if (!targetUrl) {
    return { success: false, error: 'BIZREACH_JOB_URL environment variable is required' };
  }

  // 求人詳細ページへナビゲート
  if (page.url() !== targetUrl) {
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  }

  // 主要要素（h1タイトルまたはJobSection）の出現を待機
  try {
    await page.waitForSelector('h1, section[class*="JobSection"], main', { timeout: 15000 });
  } catch (_) {}

  const extraction = await page.evaluate(() => {
    // タイトル
    const h1El = document.querySelector('h1');
    const title = h1El ? h1El.textContent.trim() : '';

    // 想定年収
    const salaryEl =
      document.querySelector('h2[class*="color-accent-primary"]') ||
      document.querySelector('[class*="color-accent-primary"]') ||
      document.querySelector('[class*="salary"]');
    const salaryText = salaryEl ? salaryEl.textContent.trim() : '';

    // 企業名 & 企業URL
    const compEl =
      document.querySelector('h2[class*="company-name-label"]') ||
      document.querySelector('a[class*="company-link"]') ||
      document.querySelector('a[href*="/company/view/"]');
    const company = compEl ? compEl.textContent.trim() : '';
    const compHref = compEl && compEl.getAttribute('href') ? compEl.getAttribute('href') : '';
    const companyUrl = compHref.startsWith('http')
      ? compHref
      : compHref
      ? `https://www.bizreach.jp${compHref}`
      : '';

    // 特徴タグ（appeals / labels）
    const tagEls = Array.from(
      document.querySelectorAll(
        'div[aria-label="appeals"] div[class*="Label"], div[aria-label="appeals"] span, [class*="JobTag"]'
      )
    );
    const tags = tagEls
      .map(el => el.textContent.trim())
      .filter(t => t.length > 0 && !t.includes('\n'));

    // 各セクション (section[class*="JobSection"] または dl / div 群) の収集
    const sections = {};
    const sectionEls = Array.from(document.querySelectorAll('section[class*="JobSection"], section'));

    for (const sec of sectionEls) {
      const headerEl = sec.querySelector('h2, h3');
      if (!headerEl) continue;
      const headerText = headerEl.textContent.trim();
      if (!headerText) continue;

      // セクション内のテキスト・サブ項目を収集
      const clone = sec.cloneNode(true);
      // ヘッダーを除去して本文を抽出
      const cloneH = clone.querySelector('h2, h3');
      if (cloneH) cloneH.remove();

      // dl / dt / dd 構造があればパース
      const dlItems = {};
      const dls = Array.from(clone.querySelectorAll('dl'));
      for (const dl of dls) {
        const dts = Array.from(dl.querySelectorAll('dt'));
        const dds = Array.from(dl.querySelectorAll('dd'));
        for (let i = 0; i < dts.length; i++) {
          const dtText = dts[i] ? dts[i].textContent.trim() : '';
          const ddText = dds[i] ? dds[i].textContent.trim() : '';
          if (dtText && ddText) {
            dlItems[dtText] = ddText;
          }
        }
      }

      // サブ見出し（h3 / h4）がある場合のグループ化
      const subheadings = {};
      const subEls = Array.from(sec.querySelectorAll('h3, h4'));
      for (const sub of subEls) {
        const subTitle = sub.textContent.trim();
        let sibling = sub.nextElementSibling;
        let subContent = [];
        while (sibling && !['H2', 'H3', 'H4'].includes(sibling.tagName)) {
          const txt = sibling.textContent.trim();
          if (txt) subContent.push(txt);
          sibling = sibling.nextElementSibling;
        }
        if (subTitle && subContent.length > 0) {
          subheadings[subTitle] = subContent.join('\n\n');
        }
      }

      const fullText = clone.textContent.trim();
      sections[headerText] = {
        fullText,
        dlItems,
        subheadings
      };
    }

    // 勤務地
    let location = '';
    for (const [secName, secData] of Object.entries(sections)) {
      if (secData.dlItems['勤務地']) {
        location = secData.dlItems['勤務地'];
        break;
      }
    }
    if (!location) {
      const locEl = document.querySelector('div[aria-label="work-location"] p');
      if (locEl) location = locEl.textContent.trim();
    }

    return {
      title,
      company,
      companyUrl,
      salaryText,
      location,
      tags,
      sections
    };
  });

  return {
    success: true,
    url: page.url(),
    ...extraction
  };
}
