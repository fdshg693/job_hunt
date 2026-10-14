// scripts/linkedin/navigate_messages.mjs
// LinkedIn メッセージ（https://www.linkedin.com/messaging/）の会話一覧・スレッド本文を取得する Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/linkedin/navigate_messages.mjs --raw
// 注意: スレッドを開くと既読になる副作用があるため、本文取得は '__FETCH_THREADS__' が true の場合のみ行う。

async page => {
  const result = {
    success: false,
    fetchedAt: new Date().toISOString(),
    url: 'https://www.linkedin.com/messaging/',
    filter: '__LI_FILTER__',
    totalCount: 0,
    messages: [],
    errors: [],
  };

  const filter = '__LI_FILTER__';
  const fetchThreads = __FETCH_THREADS__;
  const limit = __LIMIT__;
  const sleep = ms => page.waitForTimeout(ms);

  try {
    if (!page.url().includes('/messaging')) {
      await page.goto('https://www.linkedin.com/messaging/', { waitUntil: 'domcontentloaded', timeout: 25000 });
    }
    await page.waitForSelector('li.msg-conversation-listitem', { timeout: 20000 });
    await sleep(2000);

    // フィルタ（Focused / Jobs / Unread / Connections / InMail / Starred）
    if (filter && filter !== 'all') {
      try {
        const btn = page.getByRole('button', { name: filter, exact: true }).first();
        if (await btn.count() > 0) {
          await btn.click();
          await sleep(2000);
        } else {
          result.errors.push(`Filter button not found: ${filter}`);
        }
      } catch (e) {
        result.errors.push(`Filter click failed (${filter}): ${e.message}`);
      }
    }

    // 内部スクロールコンテナ（ul 自体）をスクロールして遅延読込
    const countItems = () => page.locator('li.msg-conversation-listitem').count();
    let prev = -1;
    let stale = 0;
    for (let i = 0; i < 40; i++) {
      const c = await countItems();
      if (limit > 0 && c >= limit) break;
      if (c === prev) {
        stale++;
        if (stale >= 2) break;
      } else {
        stale = 0;
      }
      prev = c;
      await page.evaluate(() => {
        const ul = document.querySelector('ul.msg-conversations-container__conversations-list');
        if (ul) ul.scrollTop = ul.scrollHeight;
      });
      await sleep(1500);
    }

    // 一覧の抽出
    const cards = await page.evaluate(() => {
      const norm = s => (s || '').replace(/\s+/g, ' ').trim();
      return Array.from(document.querySelectorAll('li.msg-conversation-listitem')).map(li => {
        const name = norm(li.querySelector('.msg-conversation-card__participant-names')?.innerText);
        const time = norm(li.querySelector('time')?.innerText);
        const snipEl = li.querySelector('.msg-conversation-card__message-snippet');
        const pill = norm(snipEl?.querySelector('.msg-conversation-card__pill')?.innerText);
        let snippet = '';
        if (snipEl) {
          const c = snipEl.cloneNode(true);
          c.querySelectorAll('.msg-conversation-card__pill, .msg-conversation-card__message-label-dot').forEach(x => x.remove());
          snippet = norm(c.innerText);
        }
        const unread = !!li.querySelector('.msg-conversation-card__message-snippet--unread, .msg-conversation-card__unread-count');
        const active = !!li.querySelector('.msg-conversations-container__convo-item-link--active');
        const starred = !!li.querySelector('.msg-conversation-card__star-icon--active, [class*="star-icon--"]');
        return { name, time, label: pill, snippet, unread, active, starred };
      });
    });

    const target = limit > 0 ? cards.slice(0, limit) : cards;
    const messages = target.map((c, idx) => ({
      index: idx,
      name: c.name,
      date: c.time,
      label: c.label,
      isInMail: /inmail/i.test(c.label),
      isSponsored: /sponsored/i.test(c.label),
      unread: c.unread,
      starred: c.starred,
      snippet: c.snippet,
      threadUrl: c.active ? page.url() : '',
      threadId: '',
      thread: [],
    }));

    // スレッド本文取得（既読副作用あり）
    if (fetchThreads) {
      const items = page.locator('li.msg-conversation-listitem');
      for (let i = 0; i < messages.length; i++) {
        try {
          const li = items.nth(i);
          await li.scrollIntoViewIfNeeded();
          await li.locator('.msg-conversation-listitem__link').first().click();
          await sleep(2500);
          const url = page.url();
          messages[i].threadUrl = url;
          const idm = url.match(/\/messaging\/thread\/([^/?#]+)/);
          if (idm) messages[i].threadId = idm[1];

          messages[i].thread = await page.evaluate(() => {
            const norm = s => (s || '').replace(/\u00a0/g, ' ').trim();
            const out = [];
            let sender = '';
            let day = '';
            const list = document.querySelector('ul.msg-s-message-list-content');
            if (!list) return out;
            for (const li of Array.from(list.children)) {
              const heading = li.querySelector('time.msg-s-message-list__time-heading');
              if (heading) day = norm(heading.innerText);
              const nameEl = li.querySelector('.msg-s-message-group__name');
              if (nameEl) sender = norm(nameEl.innerText);
              const bodyEls = li.querySelectorAll('.msg-s-event-listitem__body');
              if (!bodyEls.length) continue;
              const time = norm(li.querySelector('time.msg-s-message-group__timestamp')?.innerText);
              bodyEls.forEach(b => {
                const text = norm(b.innerText);
                if (text) out.push({ sender, day, time, text });
              });
            }
            return out;
          });
        } catch (e) {
          result.errors.push(`Thread fetch error for item ${i} (${messages[i].name}): ${e.message}`);
        }
        await sleep(1200 + Math.floor(Math.random() * 800));
      }
    }

    result.success = true;
    result.totalCount = messages.length;
    result.messages = messages;
    return result;
  } catch (globalErr) {
    result.errors.push(`Global error: ${globalErr.message}`);
    return result;
  }
}
