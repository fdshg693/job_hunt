// scripts/green/navigate_messages.mjs
// Green（https://www.green-japan.com/messages/v2）からメッセージ・スカウト一覧およびスレッド本文を取得する Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/green/navigate_messages.mjs --raw

async page => {
  const result = {
    success: false,
    fetchedAt: new Date().toISOString(),
    url: 'https://www.green-japan.com/messages/v2',
    tab: '__GREEN_TAB__',
    totalCount: 0,
    messages: [],
    threadDetail: null,
    errors: [],
  };

  const BASE_URL = 'https://www.green-japan.com';
  const targetTab = ('__GREEN_TAB__' || 'all').toLowerCase();
  const fetchDetails = __FETCH_DETAILS__;
  const limit = __LIMIT__;
  const specificThreadId = '__THREAD_ID__';

  // ヘルパー: 単一スレッド詳細のDOM抽出
  async function extractThreadDetail(p) {
    return await p.evaluate(() => {
      // 添付求人リンク
      const jobLinks = Array.from(document.querySelectorAll('a'))
        .filter(a => a.href.includes('/job/') && a.href.includes('/company/'))
        .map(a => {
          const text = a.innerText.trim();
          return {
            url: a.href,
            rawText: text,
          };
        });

      // メッセージ本文バブル
      // Greenの本文エリアは長いテキストのコンテナ
      const messageContainers = Array.from(document.querySelectorAll('div, p'))
        .filter(el => {
          const t = el.innerText || '';
          return t.length > 40 && el.children.length === 0;
        })
        .map(el => {
          const text = el.innerText.trim();
          // 近傍の日時テキストを探す
          let dateStr = null;
          let parent = el.parentElement;
          for (let i = 0; i < 4 && parent; i++) {
            const timeCandidate = Array.from(parent.querySelectorAll('*')).find(c => {
              const ct = (c.innerText || '').trim();
              return /^\d{4}[\/\.-]\d{1,2}[\/\.-]\d{1,2}\s+\d{1,2}:\d{2}$/.test(ct);
            });
            if (timeCandidate) {
              dateStr = timeCandidate.innerText.trim();
              break;
            }
            parent = parent.parentElement;
          }

          return {
            body: text,
            sentAt: dateStr,
          };
        });

      // 重複するメッセージ本文を除去（親と子の重複等）
      const uniqueMessages = [];
      const seen = new Set();
      for (const m of messageContainers) {
        if (!seen.has(m.body)) {
          seen.add(m.body);
          uniqueMessages.push(m);
        }
      }

      return {
        threadUrl: location.href,
        attachedJob: jobLinks[0] || null,
        messages: uniqueMessages,
      };
    });
  }

  try {
    // 1. 特定スレッドIDの直接取得
    if (specificThreadId && specificThreadId !== 'null' && specificThreadId !== '') {
      const threadUrl = `${BASE_URL}/messages/v2/${specificThreadId}`;
      await page.goto(threadUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForTimeout(2000);

      const detail = await extractThreadDetail(page);
      result.success = true;
      result.threadDetail = {
        threadId: String(specificThreadId),
        ...detail,
      };
      return result;
    }

    // 2. タブごとの一覧取得
    const tabsToFetch = [];
    if (targetTab === 'agent') {
      tabsToFetch.push({ type: 'agent', path: '/messages/v2/agent', label: 'エージェントから' });
    } else if (targetTab === 'company') {
      tabsToFetch.push({ type: 'company', path: '/messages/v2', label: '企業から' });
    } else {
      // all
      tabsToFetch.push({ type: 'company', path: '/messages/v2', label: '企業から' });
      tabsToFetch.push({ type: 'agent', path: '/messages/v2/agent', label: 'エージェントから' });
    }

    const allMessages = [];

    for (const tabInfo of tabsToFetch) {
      const tabUrl = `${BASE_URL}${tabInfo.path}`;
      try {
        await page.goto(tabUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
        await page.waitForTimeout(2000);
      } catch (e) {
        result.errors.push(`Tab navigation failed for ${tabInfo.label}: ${e.message}`);
        continue;
      }

      // スレッド一覧リンクの抽出
      const threads = await page.evaluate(type => {
        const links = Array.from(document.querySelectorAll('a[href*="threadId="]'));
        return links.map(link => {
          const href = link.href;
          const match = href.match(/threadId=(\d+)/);
          const threadId = match ? match[1] : '';

          const lines = link.innerText.split('\n').map(s => s.trim()).filter(Boolean);

          let scoutType = '';
          let company = '';
          let subject = '';
          let jobTitle = '';
          let salary = '';
          let senderName = '';

          if (type === 'agent') {
            // エージェント: [担当者名, 会社名, キャッチコピー/メッセージ抜粋]
            if (lines.length >= 1) senderName = lines[0];
            if (lines.length >= 2) company = lines[1];
            if (lines.length >= 3) subject = lines[2];
          } else {
            // 企業: [スカウト(バッジ), 会社名, キャッチコピー, 求人名, 年収]
            let idx = 0;
            if (lines[idx] === 'スカウト') {
              scoutType = 'スカウト';
              idx++;
            }
            if (lines.length > idx) company = lines[idx++];
            if (lines.length > idx) subject = lines[idx++];
            if (lines.length > idx) jobTitle = lines[idx++];
            if (lines.length > idx) salary = lines[idx++];
          }

          // 画像URL
          const img = link.querySelector('img');
          const imageUrl = img ? img.src || img.getAttribute('src') || '' : '';

          return {
            threadId,
            type,
            threadUrl: `https://www.green-japan.com/messages/v2/${threadId}`,
            company,
            senderName,
            subject,
            jobTitle,
            salary,
            scoutType,
            imageUrl,
            rawLines: lines,
          };
        });
      }, tabInfo.type);

      // 上限処理
      for (const t of threads) {
        if (limit > 0 && allMessages.length >= limit) {
          break;
        }
        allMessages.push(t);
      }

      if (limit > 0 && allMessages.length >= limit) {
        break;
      }
    }

    // 3. 詳細取得フラグがある場合、各メッセージのスレッド詳細を取得
    if (fetchDetails) {
      for (const msg of allMessages) {
        if (!msg.threadId) continue;
        try {
          const threadUrl = `${BASE_URL}/messages/v2/${msg.threadId}`;
          await page.goto(threadUrl, { waitUntil: 'domcontentloaded', timeout: 25000 });
          await page.waitForTimeout(1500);

          const detail = await extractThreadDetail(page);
          msg.attachedJob = detail.attachedJob;
          msg.messages = detail.messages;
        } catch (e) {
          msg.error = `Detail fetch failed: ${e.message}`;
        }
      }
    }

    result.success = true;
    result.totalCount = allMessages.length;
    result.messages = allMessages;

  } catch (err) {
    result.errors.push(err.message);
  }

  return result;
}
