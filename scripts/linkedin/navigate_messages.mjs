// scripts/linkedin/navigate_messages.mjs
// LinkedIn メッセージ（https://www.linkedin.com/messaging/）の会話一覧・スレッド本文を取得する Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/linkedin/navigate_messages.mjs --raw
// 注意: スレッドを開くと既読になる副作用があるため、本文取得は '__FETCH_THREADS__' が true の場合のみ行う。

async page => {
  const targetUrl = '__TARGET_URL__';
  const status = '__LI_STATUS__';
  const filter = '__LI_FILTER__';
  const fetchThreads = __FETCH_THREADS__;
  const limit = __LIMIT__;
  const sleep = ms => page.waitForTimeout(ms);

  const result = {
    success: false,
    fetchedAt: new Date().toISOString(),
    targetUrl,
    url: '',
    status,
    filter,
    totalCount: 0,
    messages: [],
    errors: [],
  };

  try {
    // ターゲットURLへ遷移（クエリパラメータでステータス・サブフィルタを直接指定）
    const current = page.url();
    if (current !== targetUrl) {
      await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await sleep(2500);
    }
    result.url = page.url();

    // リストコンテナまたはメッセージアイテムの出現を待機
    try {
      await Promise.race([
        page.waitForSelector('li.msg-conversation-listitem', { timeout: 10000 }),
        page.waitForSelector('ul.msg-conversations-container__conversations-list', { timeout: 10000 }),
        page.waitForSelector('.msg-conversations-container', { timeout: 10000 }),
      ]);
    } catch (_) {
      // 0件メッセージや遅延時のフォールバック
    }
    await sleep(1500);

    // ヘルパー関数: カードから一意キーを生成
    const makeKey = c => {
      if (c.threadId) return `tid:${c.threadId}`;
      if (c.threadUrl) return `url:${c.threadUrl}`;
      if (c.name && c.time) return `nt:${c.name}::${c.time}::${c.snippet.slice(0, 30)}`;
      if (c.name) return `n:${c.name}::${c.snippet.slice(0, 30)}`;
      if (c.snippet) return `s:${c.time}::${c.snippet.slice(0, 50)}`;
      if (c.id) return `id:${c.id}`;
      return null;
    };

    const mergeCard = (existing, incoming) => {
      return {
        id: incoming.id || existing.id,
        threadId: incoming.threadId || existing.threadId,
        threadUrl: incoming.threadUrl || existing.threadUrl,
        name: incoming.name || existing.name,
        time: incoming.time || existing.time,
        label: incoming.label || existing.label,
        snippet: incoming.snippet || existing.snippet,
        unread: incoming.unread !== undefined ? incoming.unread : existing.unread,
        active: incoming.active || existing.active,
        starred: incoming.starred || existing.starred,
      };
    };

    // 内部スクロールコンテナ（ul 自体）をスクロールしながら逐次カードを抽出・蓄積
    // LinkedInの会話リストは仮想DOM化されており、一気に下へ行くと上部がアンマウントされて情報が消えるため、
    // 段階的スクロール（下方向＋上方向の復路）を行い、出現したカードをすべて収集・マージする。
    const collectedCards = new Map();

    const collectFromDom = async () => {
      const batch = await page.evaluate(() => {
        const norm = s => (s || '').replace(/\s+/g, ' ').trim();
        return Array.from(document.querySelectorAll('li.msg-conversation-listitem')).map(li => {
          const linkEl = li.querySelector('a.msg-conversation-listitem__link, a[href*="/messaging/thread/"]');
          let href = linkEl?.getAttribute('href') || '';
          if (href && !href.startsWith('http')) {
            href = 'https://www.linkedin.com' + href;
          }
          let threadId = '';
          if (href) {
            const idm = href.match(/\/messaging\/thread\/([^/?#]+)/);
            if (idm) threadId = idm[1];
          }

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
          const id = li.getAttribute('id') || '';

          return { id, threadId, threadUrl: href, name, time, label: pill, snippet, unread, active, starred };
        });
      });

      for (const card of batch) {
        // 名前もスニペットもない空要素（プレースホルダー）はスキップ
        if (!card.name && !card.snippet) continue;
        const key = makeKey(card);
        if (!key) continue;
        if (collectedCards.has(key)) {
          collectedCards.set(key, mergeCard(collectedCards.get(key), card));
        } else {
          collectedCards.set(key, card);
        }
      }
    };

    // 初期表示のカードを収集
    await collectFromDom();

    // 段階的スクロール（下方向）
    let noChangeCount = 0;
    let lastSize = collectedCards.size;
    for (let step = 0; step < 60; step++) {
      if (limit > 0 && collectedCards.size >= limit) break;

      const scrollRes = await page.evaluate(() => {
        const ul = document.querySelector('ul.msg-conversations-container__conversations-list');
        if (!ul) return { atBottom: true };
        ul.scrollTop += 500;
        return {
          atBottom: Math.ceil(ul.scrollTop + ul.clientHeight) >= ul.scrollHeight - 5,
        };
      });

      await sleep(1000);
      await collectFromDom();

      if (collectedCards.size === lastSize && scrollRes.atBottom) {
        noChangeCount++;
        if (noChangeCount >= 3) break;
      } else {
        noChangeCount = 0;
      }
      lastSize = collectedCards.size;
    }

    // 復路スクロール（上方向）でアンマウントされていた上部カードの再補完
    for (let step = 0; step < 30; step++) {
      const scrollRes = await page.evaluate(() => {
        const ul = document.querySelector('ul.msg-conversations-container__conversations-list');
        if (!ul) return { atTop: true };
        ul.scrollTop -= 800;
        return { atTop: ul.scrollTop <= 0 };
      });

      await sleep(600);
      await collectFromDom();
      if (scrollRes.atTop) break;
    }

    const cards = Array.from(collectedCards.values());
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
      threadUrl: c.threadUrl || (c.active ? page.url() : ''),
      threadId: c.threadId || '',
      thread: [],
    }));

    // スレッド本文取得（既読副作用あり）
    if (fetchThreads && messages.length > 0) {
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
