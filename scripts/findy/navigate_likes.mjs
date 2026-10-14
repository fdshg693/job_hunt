// scripts/findy/navigate_likes.mjs
// 現在地からFindyの「いいね」一覧画面へナビゲートし、受け取った求人一覧のサマリを取得する Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/findy/navigate_likes.mjs --raw

async page => {
  const targetUrl = 'https://findy-code.io/likes';

  // いいね画面（/likes）に未到達の場合は遷移
  if (!page.url().includes('/likes')) {
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded' });
  }

  // いいね一覧の主要コンポーネントまたはカードのレンダリングを待機
  try {
    await page.waitForSelector(
      'h2, a[href*="/companies/"][href*="/jobs/"], [class*="empty"]',
      { timeout: 15000 }
    );
  } catch (_) {
    // コンテンツなしや読み込み遅延時はフォールバック
  }

  // 画面のメタ情報を収集
  const currentUrl = page.url();
  const pageTitle = await page.title();

  // 求人カード情報の構造化抽出
  // 重複を防止するため、求人詳細URL（/companies/{cid}/jobs/{jid}）を一意のキーとして集約
  const extraction = await page.evaluate(() => {
    const jobLinks = Array.from(
      document.querySelectorAll('a[href*="/companies/"][href*="/jobs/"]')
    );

    const seenUrls = new Set();
    const jobs = [];

    for (const linkEl of jobLinks) {
      const rawHref = linkEl.getAttribute('href') || '';
      // 余分なクエリパラメータを除去した正規パスを取得
      const cleanPath = rawHref.split('?')[0];
      if (!cleanPath || seenUrls.has(cleanPath)) {
        continue;
      }
      seenUrls.add(cleanPath);

      const fullUrl = cleanPath.startsWith('http')
        ? cleanPath
        : `https://findy-code.io${cleanPath}`;

      // カードコンテナを親階層から探索
      let card = linkEl.closest('[class*="job-description-card"]');
      if (!card) {
        // カードクラスが見つからない場合は祖先を探索
        let parent = linkEl.parentElement;
        while (parent && parent !== document.body) {
          if (parent.querySelector('[class*="company"]') && parent.textContent.includes('いいね')) {
            card = parent;
            break;
          }
          parent = parent.parentElement;
        }
      }
      const container = card || linkEl.parentElement;

      // 求人タイトル（リンク自身のテキスト、または見出し要素）
      const titleEl = container ? container.querySelector('h3, [class*="title"]') : null;
      let title = titleEl ? titleEl.textContent.trim() : linkEl.textContent.trim();
      // タイトルが空の場合はリンクテキストから
      if (!title) {
        title = linkEl.textContent.trim() || '（求人タイトルなし）';
      }

      // 企業名
      let company = '（企業名非公開/なし）';
      if (container) {
        const compEl = container.querySelector(
          '[class*="company-name"], [class*="companyName"], [class*="company_name"], a[href*="/companies/"]:not([href*="/jobs/"])'
        );
        if (compEl && compEl.textContent.trim()) {
          company = compEl.textContent.trim();
        }
      }

      // 想定年収
      let salary = null;
      if (container) {
        const salEl = container.querySelector('[class*="salary"]');
        if (salEl) {
          salary = salEl.textContent.trim();
        } else {
          const salMatch = container.textContent.match(/([0-9０-９]+万円\s*[〜～-]\s*[0-9０-９]+万円)/);
          if (salMatch) salary = salMatch[1];
        }
      }

      // いいね有効期限
      let deadline = null;
      if (container) {
        const deadlineMatch = container.textContent.match(/いいねの有効期限[:：]?\s*([0-9\/\-]+)/);
        if (deadlineMatch) {
          deadline = deadlineMatch[1];
        }
      }

      // 技術タグ・特徴
      const tags = [];
      if (container) {
        const tagEls = container.querySelectorAll(
          '[class*="tag"], [class*="skill"], [class*="badge"]'
        );
        for (const t of Array.from(tagEls)) {
          const text = t.textContent.trim();
          if (text && text.length > 0 && text.length < 30 && !tags.includes(text) && !text.startsWith('+')) {
            tags.push(text);
          }
        }
      }

      jobs.push({
        company,
        title,
        url: fullUrl,
        salary,
        deadline,
        tags: tags.slice(0, 10)
      });
    }

    // 0件メッセージや空状態の検知
    const emptyEl = document.querySelector('[class*="empty"], [class*="no-item"]');
    const emptyMessage = emptyEl ? emptyEl.textContent.trim() : null;

    return {
      totalCount: jobs.length,
      jobs,
      emptyMessage
    };
  });

  return {
    success: currentUrl.includes('/likes'),
    url: currentUrl,
    title: pageTitle,
    totalCount: extraction.totalCount,
    jobs: extraction.jobs,
    emptyMessage: extraction.emptyMessage
  };
}
