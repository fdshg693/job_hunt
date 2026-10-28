// scripts/openwork/navigate_messages.mjs
// OpenWork メッセージ・応募管理画面（/job_apply_list）からのスカウト・メッセージ一覧抽出 Playwright スクリプト

async page => {
  // WAF (awselb) 403 対策: CDP による Chrome User-Agent 設定
  try {
    const client = await page.context().newCDPSession(page);
    await client.send('Network.setUserAgentOverride', {
      userAgent:
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
      acceptLanguage: 'ja,en-US;q=0.9,en;q=0.8',
      platform: 'Win32',
    });
  } catch (_) {}

  const targetUrl = 'https://www.openwork.jp/job_apply_list';
  const currentUrl = page.url();

  if (!currentUrl.includes('/job_apply_list')) {
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  }

  // リストのロード待機
  try {
    await page.waitForSelector('.messageList_link, #mainColumn', { timeout: 10000 });
  } catch (_) {}

  const result = await page.evaluate(() => {
    const cleanLine = str =>
      (str || '')
        .replace(/[\r\n\t]+/g, ' ')
        .replace(/[ ]+/g, ' ')
        .trim();

    // タブ情報の取得
    const totalCountText = document.querySelector('.messageList_count, .count')?.innerText || '';
    const mCount = totalCountText.match(/(\d+)\s*件/);
    const totalCount = mCount ? parseInt(mCount[1], 10) : 0;

    // メッセージアイテムの取得
    const items = Array.from(document.querySelectorAll('.messageList_link, a[href*="/job_apply/"]'));
    const messages = [];

    for (const el of items) {
      const href = el.href;
      const rawText = el.innerText || '';
      const lines = rawText.split('\n').map(l => l.trim()).filter(l => l.length > 0);

      // 未読判定
      const isUnread = rawText.includes('未読') || el.classList.contains('isUnread');

      // スカウト種別
      const isScout = rawText.includes('スカウト');
      const scoutType = isScout ? 'スカウト' : 'メッセージ';

      // 会社名、期限、件名、日付の推定抽出
      let company = '';
      let deadline = '';
      let subject = '';
      let date = '';
      let snippet = '';

      // 会社名要素
      const compEl = el.querySelector('.messageList_companyName, strong, h3');
      if (compEl) {
        company = cleanLine(compEl.innerText);
      } else if (lines.length > 0) {
        company = lines[0];
      }

      // 日付要素（例: 2026年10月04日）
      for (const line of lines) {
        const dMatch = line.match(/\d{4}年\d{1,2}月\d{1,2}日/);
        if (dMatch) {
          date = dMatch[0];
          break;
        }
      }

      // 返信期限（例: 返信期限残り27日）
      for (const line of lines) {
        if (line.includes('返信期限')) {
          deadline = line;
          break;
        }
      }

      // 件名（会社名や日付、未読、返信期限以外の主要テキスト）
      const candidateLines = lines.filter(
        l =>
          l !== company &&
          l !== date &&
          l !== deadline &&
          l !== '未読' &&
          l !== '既読' &&
          l !== 'スカウト' &&
          l !== 'スカウト非公開求人' &&
          !l.includes('スカウト辞退')
      );

      if (candidateLines.length > 0) {
        subject = candidateLines[0];
        if (candidateLines.length > 1) {
          snippet = candidateLines.slice(1).join(' / ');
        }
      } else {
        subject = '（件名なし）';
      }

      messages.push({
        url: href,
        company,
        subject,
        date,
        deadline,
        isUnread,
        scoutType,
        snippet,
        rawText: cleanLine(rawText)
      });
    }

    return {
      success: true,
      url: window.location.href,
      totalCount: messages.length,
      messages
    };
  });

  return result;
}

