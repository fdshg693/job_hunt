// scripts/green/navigate_favorites.mjs
// Green（https://www.green-japan.com/favorites/received）から気になる求人・企業一覧を取得する Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/green/navigate_favorites.mjs --raw

async page => {
  const result = {
    success: false,
    fetchedAt: new Date().toISOString(),
    url: 'https://www.green-japan.com/favorites/received',
    tab: '__GREEN_TAB__',
    totalCount: 0,
    favorites: [],
    errors: [],
  };

  const BASE_URL = 'https://www.green-japan.com';
  const targetTab = ('__GREEN_TAB__' || 'received').toLowerCase();
  const limit = __LIMIT__;

  const TAB_PATH_MAP = {
    received: '/favorites/received',
    sent: '/favorites/sent',
    matched: '/favorites/matched',
    uninterested: '/favorites/uninterested',
  };

  const targetPath = TAB_PATH_MAP[targetTab] || '/favorites/received';
  const targetUrl = `${BASE_URL}${targetPath}`;
  result.url = targetUrl;

  try {
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(2000);

    // 未ログイン判定（URLが/loginに飛ばされた場合など）
    const currentUrl = page.url();
    if (currentUrl.includes('/login') || currentUrl.includes('accounts.google.com')) {
      result.errors.push(`未ログイン状態です（現在のURL: ${currentUrl}）`);
      return result;
    }

    // 求人カード一覧の抽出
    const extractedData = await page.evaluate(() => {
      // 件数表示の取得（例: "1求人" など）
      let headerCount = null;
      const countElements = Array.from(document.querySelectorAll('*')).filter(el => {
        const text = (el.innerText || '').trim();
        return /^\d+\s*求人$/.test(text);
      });
      if (countElements.length > 0) {
        const m = countElements[0].innerText.match(/(\d+)\s*求人/);
        if (m) headerCount = parseInt(m[1], 10);
      }

      const cardLinks = Array.from(document.querySelectorAll('a[href*="/job/"]'));
      const items = [];

      for (const card of cardLinks) {
        const href = card.href;
        const match = href.match(/\/company\/(\d+)\/job\/(\d+)/);
        const companyId = match ? match[1] : '';
        const jobId = match ? match[2] : '';

        // 行テキスト
        const lines = card.innerText.split('\n').map(s => s.trim()).filter(Boolean);

        // 企業名（会社ロゴ・企業情報部分の段落テキスト）
        let company = '';
        const pTags = Array.from(card.querySelectorAll('p'));
        if (pTags.length > 0) {
          company = pTags[0].innerText.trim();
        } else if (lines.length > 1) {
          company = lines[1];
        }

        // 求人職種・タイトル（.job-offer-name クラス優先）
        let jobTitle = '';
        const titleEl = card.querySelector('.job-offer-name');
        if (titleEl) {
          jobTitle = titleEl.innerText.trim();
        } else {
          // 年収行の前にあるものを候補とする
          const salaryIdx = lines.findIndex(l => /^\d+万円/.test(l));
          if (salaryIdx > 0) {
            jobTitle = lines[salaryIdx - 1];
          }
        }

        // 年収
        let salary = '';
        const salaryLine = lines.find(l => /^\d+万円(?:〜\d+万円)?/.test(l));
        if (salaryLine) {
          salary = salaryLine;
        }

        // 勤務地
        let location = '';
        const prefectures = [
          '東京都', '神奈川県', '埼玉県', '千葉県', '茨城県', '栃木県', '群馬県',
          '大阪府', '京都府', '兵庫県', '奈良県', '滋賀県', '和歌山県',
          '愛知県', '静岡県', '岐阜県', '三重県', '北海道', '福岡県', '沖縄県',
          '全国', 'フルリモート', 'リモート'
        ];
        for (const line of lines) {
          if (prefectures.some(p => line.includes(p)) && !line.includes('万円')) {
            location = line;
            break;
          }
        }

        // 受信日時 / 送信日時
        let eventDate = '';
        const dateLine = lines.find(l => /\d{4}[\/\.-]\d{1,2}[\/\.-]\d{1,2}(?:\s*(?:受信|送信))?/.test(l));
        if (dateLine) {
          eventDate = dateLine;
        }

        // 特徴タグ（例: "カジュアル面接歓迎", "リモート勤務可" 等）
        const tags = lines.filter(l =>
          ['カジュアル面接歓迎', 'リモート勤務可', '未経験歓迎', '副業OK', '自社製品・サービス'].some(t => l.includes(t))
        );

        // レビュー・求職者の声（あれば）
        let reviewSnippet = null;
        const voiceIdx = lines.indexOf('求職者の声');
        if (voiceIdx !== -1 && lines.length > voiceIdx + 1) {
          reviewSnippet = lines.slice(voiceIdx).join(' ');
        }

        // 画像URL
        const img = card.querySelector('img');
        const imageUrl = img ? (img.src || img.getAttribute('src') || '') : '';

        // 親コンテナのアクションボタン
        const parentContainer = card.parentElement;
        const actionButtons = parentContainer
          ? Array.from(parentContainer.querySelectorAll('button')).map(b => b.innerText.trim())
          : [];

        items.push({
          companyId,
          jobId,
          company,
          jobTitle,
          salary,
          location,
          eventDate,
          tags,
          reviewSnippet,
          url: href,
          imageUrl,
          actionButtons,
          rawLines: lines,
        });
      }

      return {
        headerCount,
        items,
      };
    });

    result.totalCount = extractedData.headerCount !== null ? extractedData.headerCount : extractedData.items.length;
    let favorites = extractedData.items;

    if (limit > 0 && favorites.length > limit) {
      favorites = favorites.slice(0, limit);
    }

    result.favorites = favorites;
    result.success = true;

  } catch (err) {
    result.errors.push(err.message);
  }

  return result;
}
