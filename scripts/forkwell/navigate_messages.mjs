// scripts/forkwell/navigate_messages.mjs
// Forkwell Jobs（https://jobs.forkwell.com/inbox）からスカウトおよびメッセージを取得する Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/forkwell/navigate_messages.mjs --raw

async page => {
  const result = {
    success: false,
    fetchedAt: new Date().toISOString(),
    url: 'https://jobs.forkwell.com/inbox',
    tab: '__FORKWELL_TAB__',
    totalCount: 0,
    messages: [],
    errors: [],
  };

  const BASE_URL = 'https://jobs.forkwell.com';
  const targetTab = ('__FORKWELL_TAB__' || 'active').toLowerCase();
  const fetchDetails = __FETCH_DETAILS__;
  const limit = __LIMIT__;

  try {
    const currentUrl = page.url();
    if (!currentUrl.includes('/inbox')) {
      await page.goto(`${BASE_URL}/inbox`, { waitUntil: 'domcontentloaded', timeout: 25000 });
    }
    await page.waitForTimeout(1500);

    const tabsToProcess = [];
    if (targetTab === 'all') {
      tabsToProcess.push({ key: 'active', label: 'スカウト・やりとり' });
      tabsToProcess.push({ key: 'archive', label: 'アーカイブ' });
    } else if (targetTab === 'archive' || targetTab === 'archived') {
      tabsToProcess.push({ key: 'archive', label: 'アーカイブ' });
    } else {
      // active
      tabsToProcess.push({ key: 'active', label: 'スカウト・やりとり' });
    }

    const allExtractedMessages = [];

    for (const tabInfo of tabsToProcess) {
      // タブ切り替え
      try {
        const tabEl = page.locator(`li.nav-item:has-text("${tabInfo.label}")`).first();
        if (await tabEl.count() > 0) {
          await tabEl.click();
          await page.waitForTimeout(1200);
        }
      } catch (e) {
        result.errors.push(`Tab switch failed for ${tabInfo.label}: ${e.message}`);
      }

      // カード要素の取得
      const cardLocators = page.locator('.list-group-item.list-group-item-action');
      const cardCount = await cardLocators.count();

      const itemsToFetch = (limit > 0 && targetTab !== 'all')
        ? Math.min(cardCount, limit)
        : (limit > 0 && targetTab === 'all' && allExtractedMessages.length >= limit)
          ? 0
          : (limit > 0)
            ? Math.min(cardCount, limit - allExtractedMessages.length)
            : cardCount;

      for (let i = 0; i < itemsToFetch; i++) {
        try {
          const card = cardLocators.nth(i);

          // カード基本情報
          const cardData = await card.evaluate((el) => {
            const img = el.querySelector('img');
            const companyName = img ? img.getAttribute('alt') || '' : '';
            const companyIcon = img ? img.getAttribute('src') || '' : '';

            // タイトル・件名
            const titleEl = el.querySelector('.card-content-space-top.small') || el.querySelector('.d-flex.align-items-center.card-content-space-top');
            const subject = titleEl ? titleEl.innerText.trim() : '';

            // 日時・期限テキスト
            const dateEl = el.querySelector('.text-muted, time');
            const statusText = dateEl ? dateEl.innerText.trim() : '';

            // バッジ群
            const badgeEls = Array.from(el.querySelectorAll('.badge, [class*="badge"]'));
            const badges = badgeEls.map(b => b.innerText.trim()).filter(Boolean);

            return {
              company: companyName,
              companyIcon,
              subject,
              statusText,
              badges,
            };
          });

          // 日時・期限のパース
          let deadline = null;
          let dateStr = null;
          let isExpired = false;

          const st = cardData.statusText || '';
          if (st.includes('有効期限切れ')) {
            isExpired = true;
          }
          const deadlineMatch = st.match(/有効期限\s*([\d]{4}\/[\d]{1,2}\/[\d]{1,2})/);
          if (deadlineMatch) {
            deadline = deadlineMatch[1];
          }
          const dateMatch = st.match(/最終更新日\s*([\d]{4}\/[\d]{1,2}\/[\d]{1,2})/);
          if (dateMatch) {
            dateStr = dateMatch[1];
          }

          const primaryBadge = cardData.badges[0] || 'スカウト';
          const msgObj = {
            id: '',
            type: '',
            tab: tabInfo.key,
            tabLabel: tabInfo.label,
            company: cardData.company,
            companyIcon: cardData.companyIcon,
            companyUrl: '',
            subject: cardData.subject,
            statusText: cardData.statusText,
            date: dateStr,
            deadline: deadline,
            isExpired: isExpired,
            scoutType: primaryBadge,
            badges: cardData.badges,
            threadUrl: '',
            jobUrl: '',
            jobTitle: '',
            jobSalary: '',
            jobRole: '',
            body: '',
            snippet: '',
          };

          // 詳細取得（カードをクリックして右ペインを解析）
          if (fetchDetails) {
            try {
              await card.click();
              await page.waitForTimeout(1000);

              const currentUrlAfterClick = page.url();
              msgObj.threadUrl = currentUrlAfterClick;

              // id と type の抽出（URLクラスを使わず正規表現で安全に抽出）
              const idMatch = currentUrlAfterClick.match(/[?&]id=([^&#]+)/);
              if (idMatch) msgObj.id = idMatch[1];
              const typeMatch = currentUrlAfterClick.match(/[?&]type=([^&#]+)/);
              if (typeMatch) msgObj.type = typeMatch[1];

              // 右ペインの詳細情報取得
              const detailData = await page.evaluate(() => {
                // スカウト本文カード（.message__inbox_scout_body）または右カラム全体
                const scoutBody = document.querySelector('.message__inbox_scout_body') ||
                                  document.querySelector('.message__body') ||
                                  document.querySelector('.row > div:last-child');
                if (!scoutBody) return null;

                // 企業リンク
                const compLink = scoutBody.querySelector('a[href^="/"]:not([href*="/jobs/"])') ||
                                 document.querySelector('.row > div:last-child h2 a');
                const compUrl = compLink ? (compLink.href.startsWith('http') ? compLink.href : window.location.origin + compLink.getAttribute('href')) : '';

                // 求人リンク
                const allJobLinks = Array.from(document.querySelectorAll('.row > div:last-child a[href*="/jobs/"]'))
                  .filter(a => !a.href.includes('/jobs/search') && !a.href.includes('/dashboard'));
                const jobLink = allJobLinks[0];
                const jobUrl = jobLink ? jobLink.href : '';

                // 求人カードのテキスト
                const jobCardEl = document.querySelector('.scout-content-job, [class*="scout-content-job"]');
                let jobTitle = '';
                let jobSalary = '';
                let jobRole = '';

                if (jobCardEl) {
                  const jobLines = jobCardEl.innerText.split('\n').map(s => s.trim()).filter(Boolean);
                  if (jobLines.length > 0) jobTitle = jobLines[0];
                  for (const line of jobLines) {
                    if (line.includes('円')) jobSalary = line;
                    if (line.includes('エンジニア') || line.includes('PM') || line.includes('リーダー')) jobRole = line;
                  }
                }

                // 本文テキスト
                const bodyText = scoutBody.innerText || '';
                // 企業からのメッセージ部分などを抜粋
                const snippetLines = bodyText.split('\n')
                  .map(s => s.trim())
                  .filter(s => s && !s.includes('さんへ') && !s.includes('スカウトが届きました') && !s.includes('株式会社') && !s.includes('戻る'));
                const snippet = snippetLines.slice(0, 5).join(' ').slice(0, 250);

                return {
                  compUrl,
                  jobUrl,
                  jobTitle,
                  jobSalary,
                  jobRole,
                  body: bodyText,
                  snippet,
                };
              });

              if (detailData) {
                if (detailData.compUrl) msgObj.companyUrl = detailData.compUrl;
                if (detailData.jobUrl) msgObj.jobUrl = detailData.jobUrl;
                if (detailData.jobTitle) msgObj.jobTitle = detailData.jobTitle;
                if (detailData.jobSalary) msgObj.jobSalary = detailData.jobSalary;
                if (detailData.jobRole) msgObj.jobRole = detailData.jobRole;
                if (detailData.body) msgObj.body = detailData.body;
                if (detailData.snippet) msgObj.snippet = detailData.snippet;
              }
            } catch (err) {
              result.errors.push(`Detail fetch error for item ${i} in ${tabInfo.label}: ${err.message}`);
            }
          }

          allExtractedMessages.push(msgObj);
        } catch (cardErr) {
          result.errors.push(`Card extract error index ${i} in ${tabInfo.label}: ${cardErr.message}`);
        }
      }
    }

    result.success = true;
    result.totalCount = allExtractedMessages.length;
    result.messages = allExtractedMessages;
    return result;

  } catch (globalErr) {
    result.errors.push(`Global error: ${globalErr.message}`);
    return result;
  }
}
