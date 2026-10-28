// scripts/bizreach/navigate_messages.mjs
// ビズリーチのメッセージ画面へナビゲートし、メッセージ・スカウト一覧を構造化抽出する Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/bizreach/navigate_messages.mjs --raw

async page => {
  const defaultUrl = 'https://www.bizreach.jp/messages/';
  const maxLimit = 60;

  // メッセージ画面（/messages/）に未到達の場合は遷移
  const currentUrl = page.url();
  if (!currentUrl.includes('/messages/')) {
    await page.goto(defaultUrl, { waitUntil: 'domcontentloaded' });
  }

  // メッセージ一覧の主要コンテナまたは要素の出現を待機
  try {
    await page.waitForSelector(
      'section[class*="ThreadList"], region[aria-label*="thread-list"], a[href^="/messages/"]',
      { timeout: 15000 }
    );
  } catch (_) {
    // タイムアウト時はそのままフォールバック
  }

  // スクロールコンテナの探索とオンデマンド読み込み
  // 初回表示は10件程度のため、指定件数に達するまで末尾スクロールを試行
  try {
    const scrollContainerSelector = 'section[class*="ThreadList"][class*="wrapper"]';
    const containerExists = (await page.locator(scrollContainerSelector).count()) > 0;

    if (containerExists) {
      let prevCount = 0;
      let scrollAttempts = 0;
      const maxAttempts = Math.min(10, Math.ceil(maxLimit / 10) + 1);

      while (scrollAttempts < maxAttempts) {
        const currentCount = await page.locator('a[href^="/messages/"]:not([href="/messages/"])').count();
        if (currentCount >= maxLimit || (scrollAttempts > 0 && currentCount === prevCount)) {
          break;
        }
        prevCount = currentCount;

        await page.evaluate(sel => {
          const el = document.querySelector(sel);
          if (el) {
            el.scrollTop = el.scrollHeight;
          }
        }, scrollContainerSelector);

        await page.waitForTimeout(800);
        scrollAttempts++;
      }
    }
  } catch (_) {
    // スクロール失敗時は現在レンダリングされている件数で続行
  }

  const finalUrl = page.url();
  const pageTitle = await page.title();

  // 構造化データの抽出
  const extraction = await page.evaluate(limit => {
    const threadLinks = Array.from(
      document.querySelectorAll('a[href^="/messages/"]:not([href="/messages/"])')
    );

    const seenUrls = new Set();
    const messages = [];

    for (const linkEl of threadLinks) {
      if (messages.length >= limit) {
        break;
      }

      const rawHref = linkEl.getAttribute('href') || '';
      const cleanPath = rawHref.split('?')[0];
      if (!cleanPath || seenUrls.has(cleanPath)) {
        continue;
      }
      seenUrls.add(cleanPath);

      const fullUrl = cleanPath.startsWith('http')
        ? cleanPath
        : `https://www.bizreach.jp${cleanPath}`;

      // カードコンテナ（親要素）
      const container = linkEl.closest('li') || linkEl.parentElement || linkEl;

      // 送信者情報（会社名 / 担当者）
      const senderEl = container.querySelector('p[class*="recruiter-company-name"]');
      const senderFull = senderEl ? senderEl.textContent.trim() : '';
      let company = senderFull;
      let recruiter = null;
      if (senderFull.includes('/')) {
        const parts = senderFull.split('/').map(s => s.trim());
        company = parts[0] || '不明';
        recruiter = parts.slice(1).join(' / ') || null;
      } else if (!company) {
        company = '（送信者非公開/なし）';
      }

      // 本文冒頭 / 件名
      const sentenceEl = container.querySelector('p[class*="opening-sentence"]');
      const fullSnippet = sentenceEl ? sentenceEl.textContent.trim() : '';

      // 件名推定（【...】で囲まれた部分があればタイトルとし、残りを本文とする）
      let title = null;
      let snippet = fullSnippet;
      const titleMatch = fullSnippet.match(/^(【[^】]+】)(.*)/s);
      if (titleMatch) {
        title = titleMatch[1].trim();
        snippet = (titleMatch[2] || '').trim();
      } else if (fullSnippet.length > 0) {
        // 先頭行または一定文字数をタイトルとして利用
        const firstLine = fullSnippet.split('\n')[0].trim();
        if (firstLine.length <= 40) {
          title = firstLine;
          snippet = fullSnippet.slice(firstLine.length).trim();
        } else {
          title = fullSnippet.slice(0, 40) + '...';
        }
      }
      if (!snippet && fullSnippet) {
        snippet = fullSnippet;
      }

      // 長すぎるスニペットは安全に切り詰め（200文字）
      if (snippet && snippet.length > 200) {
        snippet = snippet.slice(0, 200) + '...';
      }

      // 受信日時
      const timeEl = container.querySelector('p[class*="timestamp"]');
      const receivedDate = timeEl ? timeEl.textContent.trim() : null;

      // 未読状態
      const unreadEl = container.querySelector('[data-testid="unread-badge"], [class*="unread"], [class*="Badge"]');
      const isUnread = !!unreadEl;
      let unreadCount = 0;
      if (unreadEl) {
        const countText = unreadEl.textContent.trim();
        const parsedCount = parseInt(countText, 10);
        unreadCount = isNaN(parsedCount) ? 1 : parsedCount;
      }

      // ラベル・バッジ（求人あり, 非公開求人, プラチナスカウト 等）
      const badges = [];
      const badgeEls = container.querySelectorAll('[class*="Label-module"], [class*="label"], [class*="tag"]');
      for (const b of Array.from(badgeEls)) {
        const text = b.textContent.trim();
        if (text && !badges.includes(text) && text !== '未読' && text.length < 30) {
          badges.push(text);
        }
      }

      // スレッドID抽出
      const idMatch = cleanPath.match(/\/messages\/([^\/]+)/);
      const threadId = idMatch ? idMatch[1] : null;

      messages.push({
        threadId,
        company,
        recruiter,
        title: title || '（件名なし）',
        snippet: snippet || '',
        receivedDate,
        isUnread,
        unreadCount,
        badges,
        url: fullUrl
      });
    }

    // 0件メッセージや空状態の検知
    const emptyEl = document.querySelector('region[aria-label*="thread-list"] p, [class*="empty"], [class*="no-item"]');
    let emptyMessage = null;
    if (messages.length === 0 && emptyEl) {
      emptyMessage = emptyEl.textContent.trim();
    }

    return {
      totalCount: messages.length,
      messages,
      emptyMessage
    };
  }, maxLimit);

  return {
    success: finalUrl.includes('/messages'),
    url: finalUrl,
    title: pageTitle,
    totalCount: extraction.totalCount,
    messages: extraction.messages,
    emptyMessage: extraction.emptyMessage
  };
}
