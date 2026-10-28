// scripts/linkedin/fetch_single_thread.mjs
// 指定されたスレッドURLを開いて参加者情報・メッセージ履歴・添付リンクを取得する

async page => {
  const targetUrl = process.env.TARGET_URL || 'https://www.linkedin.com/messaging/thread/2-OTU4NTFlOWQtMWY5NS00YTFhLWFmMjMtMTRiYThiMjliMWM2XzEwMA==/';
  const sleep = ms => page.waitForTimeout(ms);

  const result = {
    success: false,
    url: targetUrl,
    actualUrl: '',
    title: '',
    participant: {
      name: '',
      headline: '',
      profileUrl: '',
    },
    messages: [],
    links: [],
    errors: [],
  };

  try {
    console.log(`Navigating to ${targetUrl}...`);
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await sleep(3500);

    result.actualUrl = page.url();
    result.title = await page.title();

    // 認証壁チェック
    if (result.actualUrl.includes('/login') || result.actualUrl.includes('/checkpoint/')) {
      result.errors.push(`Hit authentication wall or checkpoint: ${result.actualUrl}`);
      return result;
    }

    // スレッドコンテナまたはメッセージリストの待機
    try {
      await Promise.race([
        page.waitForSelector('ul.msg-s-message-list-content', { timeout: 15000 }),
        page.waitForSelector('.msg-thread', { timeout: 15000 }),
        page.waitForSelector('.msg-convo-wrapper', { timeout: 15000 }),
      ]);
    } catch (e) {
      result.errors.push(`Timeout waiting for thread selector: ${e.message}`);
    }
    await sleep(2000);

    // 参加者情報の取得
    const participantInfo = await page.evaluate(() => {
      const norm = s => (s || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
      
      // スレッド上部のヘッダーやプロフィールリンクを探す
      const header = document.querySelector('.msg-title-bar, .msg-entity-lockup, .msg-thread__topcard, header.msg-title-bar');
      let name = '';
      let headline = '';
      let profileUrl = '';

      if (header) {
        const nameEl = header.querySelector('h2, .msg-entity-lockup__entity-title, a[href*="/in/"]');
        if (nameEl) name = norm(nameEl.innerText);
        const subEl = header.querySelector('.msg-entity-lockup__entity-subtitle, .msg-entity-lockup__entity-headline, p');
        if (subEl) headline = norm(subEl.innerText);
        const linkEl = header.querySelector('a[href*="/in/"]');
        if (linkEl) profileUrl = linkEl.href;
      }

      // トップカード（プロフィール要約カード）がある場合
      const topcard = document.querySelector('.msg-thread__topcard, .artdeco-entity-lockup');
      if (topcard) {
        if (!name) {
          const tName = topcard.querySelector('.artdeco-entity-lockup__title, h2, a[href*="/in/"]');
          if (tName) name = norm(tName.innerText);
        }
        if (!headline) {
          const tSub = topcard.querySelector('.artdeco-entity-lockup__subtitle, .artdeco-entity-lockup__caption');
          if (tSub) headline = norm(tSub.innerText);
        }
        if (!profileUrl) {
          const tLink = topcard.querySelector('a[href*="/in/"]');
          if (tLink) profileUrl = tLink.href;
        }
      }

      // フォールバック: ページ全体の .msg-thread 内の /in/ リンク
      if (!profileUrl) {
        const inLink = document.querySelector('.msg-thread a[href*="/in/"], .msg-conversations-container__convo-item a[href*="/in/"]');
        if (inLink) {
          profileUrl = inLink.href;
          if (!name) name = norm(inLink.innerText);
        }
      }

      return { name, headline, profileUrl };
    });

    result.participant = participantInfo;

    // メッセージ履歴の取得
    const threadData = await page.evaluate(() => {
      const norm = s => (s || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
      const out = [];
      const links = [];

      const list = document.querySelector('ul.msg-s-message-list-content, .msg-s-message-list-container');
      if (!list) return { out, links };

      let currentDay = '';
      let currentSender = '';

      // list内の全要素またはメッセージグループを走査
      const items = Array.from(list.querySelectorAll('li.msg-s-message-list__event, li.msg-s-message-group, div.msg-s-event-listitem'));
      
      for (const item of items) {
        const heading = item.querySelector('time.msg-s-message-list__time-heading');
        if (heading) {
          currentDay = norm(heading.innerText);
        }

        const nameEl = item.querySelector('.msg-s-message-group__name, .msg-s-message-group__profile-link');
        if (nameEl) {
          currentSender = norm(nameEl.innerText);
        }

        const timeEl = item.querySelector('time.msg-s-message-group__timestamp, time');
        const timeStr = timeEl ? norm(timeEl.innerText) : '';

        const bodyEls = item.querySelectorAll('.msg-s-event-listitem__body, .msg-s-event-listitem__message-bubble');
        if (bodyEls.length > 0) {
          for (const b of bodyEls) {
            const text = norm(b.innerText);
            // 内部リンク（求人やURL）も収集
            const aTags = Array.from(b.querySelectorAll('a'));
            for (const a of aTags) {
              if (a.href) links.push({ text: norm(a.innerText), href: a.href });
            }
            if (text) {
              out.push({
                sender: currentSender,
                day: currentDay,
                time: timeStr,
                text: text,
              });
            }
          }
        }
      }

      return { out, links };
    });

    result.messages = threadData.out;
    result.links = threadData.links;
    result.success = result.messages.length > 0 || !!result.participant.name;

    return result;
  } catch (err) {
    result.errors.push(`Exception: ${err.message}`);
    return result;
  }
};
