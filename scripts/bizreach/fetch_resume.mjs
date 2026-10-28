// scripts/bizreach/fetch_resume.mjs
// ビズリーチ職務経歴書（基本情報・職務経歴・フリーフォーマット）データ抽出 Playwright スクリプト

async page => {
  const cleanLine = str =>
    (str || '')
      .replace(/[\r\n\t]+/g, ' ')
      .replace(/[ ]+/g, ' ')
      .trim();

  const cleanMultiline = str =>
    (str || '')
      .replace(/\r?\n/g, '\n')
      .split('\n')
      .map(line => line.trimEnd())
      .join('\n')
      .trim();

  // 1. 基本情報画面 (/resume/view/) の抽出
  await page.goto('https://www.bizreach.jp/resume/view/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  try {
    await page.waitForSelector('h2, table', { timeout: 15000 });
  } catch (_) {}

  const basicInfo = await page.evaluate(() => {
    const data = {};
    const tables = document.querySelectorAll('table');
    tables.forEach(t => {
      t.querySelectorAll('tr').forEach(tr => {
        const th = tr.querySelector('th');
        const td = tr.querySelector('td');
        if (th && td) {
          const key = (th.textContent || '').replace(/[\r\n\t]+/g, ' ').replace(/[ ]+/g, ' ').trim();
          const clone = td.cloneNode(true);
          // 装飾ボタン・バッジ等の除去
          clone.querySelectorAll('button, [class*="badge"], [class*="Badge"]').forEach(el => el.remove());
          let val = (clone.textContent || '')
            .replace(/[\r\n\t]+/g, ' ')
            .replace(/[ ]+/g, ' ')
            .trim()
            .replace(/\s*非公開$/, '')
            .trim();
          if (key) {
            data[key] = val;
          }
        }
      });
    });
    return data;
  });

  // 2. 職務経歴画面 (/resume/company/) の抽出
  await page.goto('https://www.bizreach.jp/resume/company/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  try {
    await page.waitForSelector('table tr th', { timeout: 10000 });
  } catch (_) {
    try {
      await page.waitForSelector('div[class*="CompanyExperienceView"]', { timeout: 10000 });
    } catch (_) {}
  }
  // わずかなレンダリング完了待機
  await page.waitForTimeout(1000);

  const career = await page.evaluate(() => {
    // 経験職種・業種の取得
    const experiencedJobCategories = [];
    const experiencedIndustries = [];

    const parseCategoryRows = (td, targetList) => {
      const rows = td.querySelectorAll('div[class*="Stack"][class*="row"], div[class*="row"]');
      if (rows.length > 0) {
        rows.forEach(r => {
          const pEls = r.querySelectorAll('p');
          if (pEls.length >= 2) {
            targetList.push({
              name: (pEls[0].textContent || '').trim(),
              years: (pEls[1].textContent || '').trim(),
            });
          } else if (pEls.length === 1) {
            targetList.push({
              name: (pEls[0].textContent || '').trim(),
              years: '',
            });
          }
        });
      } else {
        const pEls = Array.from(td.querySelectorAll('p'));
        for (let i = 0; i < pEls.length; i += 2) {
          targetList.push({
            name: (pEls[i].textContent || '').trim(),
            years: pEls[i + 1] ? (pEls[i + 1].textContent || '').trim() : '',
          });
        }
      }
    };

    const tables = document.querySelectorAll('table');
    tables.forEach(t => {
      t.querySelectorAll('tr').forEach(tr => {
        const th = tr.querySelector('th');
        const td = tr.querySelector('td');
        if (!th || !td) return;
        const thText = (th.textContent || '').trim();

        if (thText.includes('経験職種')) {
          parseCategoryRows(td, experiencedJobCategories);
        } else if (thText.includes('経験業種')) {
          parseCategoryRows(td, experiencedIndustries);
        }
      });
    });

    // 各社職務経歴ブロックの取得
    const companyBlocks = Array.from(
      document.querySelectorAll(
        'div[class*="CompanyExperienceView"][class*="company-experience"], div[class*="company-experience"]'
      )
    );

    const companies = companyBlocks.map(block => {
      const compHeaderEl = block.querySelector(
        'div[class*="CompanyExperienceView"][class*="company"], div[class*="company"]'
      );
      const periodEl = block.querySelector(
        'div[class*="CompanyExperienceView"][class*="period"], div[class*="period"]'
      );

      let companyName = '';
      let role = '';
      let period = '';

      if (periodEl) {
        period = (periodEl.textContent || '').trim();
      }

      if (compHeaderEl) {
        // periodを除いた社名・役職のpタグを取得
        const pEl = compHeaderEl.querySelector('p[class*="bold"], p');
        const rawTitle = pEl ? (pEl.textContent || '').trim() : '';
        if (rawTitle.includes('/')) {
          const parts = rawTitle.split('/');
          companyName = parts[0].trim();
          role = parts.slice(1).join('/').trim();
        } else {
          companyName = rawTitle;
        }
      }

      // プロジェクト群の取得
      const projects = [];
      const projectBlocks = Array.from(
        block.querySelectorAll('div[class*="Stack"][class*="column"][class*="space-4"]')
      );

      projectBlocks.forEach(pEl => {
        const titleRow = pEl.querySelector('div[class*="Stack"][class*="row"]');
        const titleEl = titleRow ? titleRow.querySelector('p[class*="bold"], p') : pEl.querySelector('p[class*="bold"]');
        const pPeriodEl = titleRow ? titleRow.querySelector('div[class*="period"], [class*="period"]') : null;

        // 本文コンテナ: space-16のStack内にあるpタグ
        const bodyContainer = pEl.querySelector('div[class*="space-16"], [class*="space-16"]');
        const bodyEl = bodyContainer ? bodyContainer.querySelector('p') : null;

        const title = titleEl ? (titleEl.textContent || '').trim() : '';
        const pPeriod = pPeriodEl ? (pPeriodEl.textContent || '').trim() : '';
        let description = '';

        if (bodyEl) {
          description = (bodyEl.innerText || bodyEl.textContent || '').replace(/\r?\n/g, '\n').trim();
        }

        if (title || description) {
          projects.push({
            title,
            period: pPeriod,
            description,
          });
        }
      });

      return {
        companyName,
        role,
        period,
        projects,
      };
    });

    return {
      experiencedJobCategories,
      experiencedIndustries,
      companies,
    };
  });

  // 3. フリーフォーマット画面 (/resume/freetext/) の抽出
  await page.goto('https://www.bizreach.jp/resume/freetext/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  try {
    await page.waitForSelector('h2', { timeout: 15000 });
  } catch (_) {}

  const freetext = await page.evaluate(() => {
    const secEl = document.querySelector('div[class*="FreeTextView"][class*="section"], div[class*="FreeTextView"]');
    if (secEl) {
      return (secEl.innerText || secEl.textContent || '').replace(/\r?\n/g, '\n').trim();
    }
    const h2El = Array.from(document.querySelectorAll('h2')).find(h => (h.textContent || '').includes('フリーフォーマット'));
    if (h2El && h2El.parentElement) {
      const clone = h2El.parentElement.cloneNode(true);
      const h2InClone = clone.querySelector('h2');
      if (h2InClone) h2InClone.remove();
      clone.querySelectorAll('button').forEach(b => b.remove());
      return (clone.innerText || clone.textContent || '').replace(/\r?\n/g, '\n').trim();
    }
    return '';
  });

  return {
    success: true,
    url: 'https://www.bizreach.jp/resume/company/',
    basicInfo,
    career,
    freetext: cleanMultiline(freetext),
  };
}
