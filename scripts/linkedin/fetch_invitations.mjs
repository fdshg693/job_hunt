// scripts/linkedin/fetch_invitations.mjs
// LinkedIn 受信招待（つながり申請）一覧を取得する Playwright スクリプト
// 対象URL: https://www.linkedin.com/mynetwork/invitation-manager/received/
// 注意: 承諾（Accept）や拒否（Ignore）の自動操作は行わず、読み取り・情報抽出のみを実行する。

async page => {
  const result = {
    success: false,
    fetchedAt: new Date().toISOString(),
    url: 'https://www.linkedin.com/mynetwork/invitation-manager/received/',
    totalCount: 0,
    invitations: [],
    emptyState: false,
    errors: [],
  };

  const limit = __LIMIT__;
  const sleep = ms => page.waitForTimeout(ms);

  try {
    const targetUrl = 'https://www.linkedin.com/mynetwork/invitation-manager/received/';
    if (!page.url().includes('/mynetwork/invitation-manager/received')) {
      await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 25000 });
    }

    // 招待一覧アイテムまたは空状態要素の出現を待機
    const rowSelector = 'div[role="listitem"][componentkey^="urn:li:invitation:"], div[componentkey^="invitation_manager_row_urn:li:invitation:"]';
    try {
      await page.waitForFunction(
        sel => {
          const rows = document.querySelectorAll(sel);
          if (rows.length > 0) return true;
          const bodyText = document.body ? document.body.innerText : '';
          return (
            bodyText.includes('No pending invitations') ||
            bodyText.includes('招待はありません') ||
            bodyText.includes('保留中の招待はありません')
          );
        },
        rowSelector,
        { timeout: 15000 }
      );
    } catch (_) {
      // タイムアウトしてもページ遷移自体が成功していれば続行
    }
    await sleep(2000);

    // スクロールによる遅延読込処理
    const countItems = () => page.locator(rowSelector).count();
    let prev = -1;
    let stale = 0;
    for (let i = 0; i < 30; i++) {
      const c = await countItems();
      if (c === 0) break; // 空状態の場合はスクロール不要
      if (limit > 0 && c >= limit) break;
      if (c === prev) {
        stale++;
        if (stale >= 2) break;
      } else {
        stale = 0;
      }
      prev = c;

      await page.evaluate(() => {
        // LazyColumn または window をスクロール
        const lazyCol = document.querySelector('div[data-component-type="LazyColumn"], div[data-testid="lazy-column"]');
        if (lazyCol) {
          lazyCol.scrollTop = lazyCol.scrollHeight;
        }
        window.scrollBy(0, 1000);
      });
      await sleep(1500);
    }

    // 添付メッセージがある場合、展開ボタン（Show more / 続きを読む）を安全にクリック
    // 注意: 絶対に Accept / Ignore ボタンを押下しないよう、セレクタを厳格に限定
    try {
      const expandButtons = page.locator('span[data-testid="expandable-text-box"] button[data-testid="expandable-text-button"], button[data-testid="expandable-text-button"]');
      const btnCount = await expandButtons.count();
      for (let i = 0; i < btnCount; i++) {
        try {
          const btn = expandButtons.nth(i);
          const btnText = (await btn.innerText() || '').trim().toLowerCase();
          if (btnText.includes('more') || btnText.includes('続きを読む') || btnText.includes('…')) {
            await btn.scrollIntoViewIfNeeded();
            await btn.click({ timeout: 2000 });
            await sleep(300);
          }
        } catch (_) {
          // 個別の展開失敗は無視して続行
        }
      }
    } catch (e) {
      result.errors.push(`Expand messages failed: ${e.message}`);
    }

    // 招待一覧アイテムの抽出
    const rawItems = await page.evaluate(sel => {
      const norm = s => (s || '').replace(/\s+/g, ' ').trim();
      const normalizeProfileUrl = rawUrl => {
        if (!rawUrl) return '';
        try {
          const u = new URL(rawUrl, window.location.origin);
          const m = u.pathname.match(/\/in\/([^/?#]+)/);
          if (m) {
            return `${u.origin}/in/${m[1]}/`;
          }
          return u.origin + u.pathname;
        } catch (_) {
          return rawUrl.split('?')[0];
        }
      };

      const rows = Array.from(document.querySelectorAll(sel));
      return rows.map(row => {
        // 招待ID / URN
        const cKey = row.getAttribute('componentkey') || '';
        const urnMatch = cKey.match(/urn:li:invitation:(\d+)/);
        const invitationId = urnMatch ? urnMatch[1] : '';
        const urn = urnMatch ? urnMatch[0] : cKey;

        // 申請者リンク・氏名
        const profileLinkEl = row.querySelector('a[href*="/in/"]');
        let profileUrl = '';
        let slug = '';
        if (profileLinkEl) {
          const href = profileLinkEl.getAttribute('href') || '';
          profileUrl = normalizeProfileUrl(href);
          const sm = profileUrl.match(/\/in\/([^/?#]+)/);
          if (sm) slug = sm[1];
        }

        let name = '';
        const strongEl = row.querySelector('a[href*="/in/"] strong');
        if (strongEl) {
          const strongClone = strongEl.cloneNode(true);
          strongClone.querySelectorAll('svg, [role="img"], span.gflii6').forEach(el => el.remove());
          name = norm(strongClone.innerText);
        }
        if (!name && profileLinkEl) {
          const linkClone = profileLinkEl.cloneNode(true);
          linkClone.querySelectorAll('svg, [role="img"]').forEach(el => el.remove());
          name = norm(linkClone.innerText);
        }
        if (!name) {
          const acceptBtn = row.querySelector('button[aria-label*="Accept"]');
          const acceptLabel = acceptBtn?.getAttribute('aria-label') || '';
          const mName = acceptLabel.match(/Accept\s+(.*?)(?:’s|'s)?\s+invitation/i);
          if (mName) name = norm(mName[1]);
        }

        // アバター画像
        const avatarEl = row.querySelector('img[alt*="profile picture"], figure img');
        const avatarUrl = avatarEl?.getAttribute('src') || '';

        // 企業ロゴ
        const logoEl = row.querySelector('img[src*="company-logo"]');
        const companyLogoUrl = logoEl?.getAttribute('src') || '';

        // 段落要素（p）を走査して Headline, 共通コネクション, 添付メッセージ, 返信URL を高精度に分離
        let headline = '';
        let mutualConnections = '';
        let mutualCount = 0;
        let message = '';
        let replyUrl = '';

        const pEls = Array.from(row.querySelectorAll('p'));
        for (const p of pEls) {
          const pText = norm(p.innerText);
          if (!pText) continue;

          // 1. 氏名・リクエスト行 (wants to connect / さんの招待)
          if (p.querySelector('a[href*="/in/"]') || /wants to connect|さんの招待/i.test(pText)) {
            continue;
          }

          // 2. 添付メッセージ (expandable-text-box)
          const msgBox = p.querySelector('span[data-testid="expandable-text-box"]');
          if (msgBox) {
            const clone = msgBox.cloneNode(true);
            clone.querySelectorAll('button').forEach(b => b.remove());
            message = norm(clone.innerText);
            continue;
          }

          // 3. 返信リンク (Reply to ...)
          const replyLink = p.querySelector('a[href*="/messaging/compose/"]');
          if (replyLink) {
            replyUrl = replyLink.getAttribute('href') || '';
            continue;
          }

          // 4. 共通コネクション
          if (/mutual connection|共通のつながり/i.test(pText)) {
            mutualConnections = pText;
            const cntMatch = pText.match(/(\d+)/);
            if (cntMatch) mutualCount = parseInt(cntMatch[1], 10);
            continue;
          }

          // 5. Headline / 肩書き（まだ見つかっていない場合）
          if (!headline) {
            headline = pText;
          }
        }

        // フォールバック: 添付メッセージが p の外にある場合
        if (!message) {
          const msgBox = row.querySelector('span[data-testid="expandable-text-box"]');
          if (msgBox) {
            const clone = msgBox.cloneNode(true);
            clone.querySelectorAll('button').forEach(b => b.remove());
            message = norm(clone.innerText);
          }
        }

        // フォールバック: 返信リンク
        if (!replyUrl) {
          const replyLinkEl = row.querySelector('a[href*="/messaging/compose/"]');
          if (replyLinkEl) replyUrl = replyLinkEl.getAttribute('href') || '';
        }

        // 受信時期
        let receivedTime = '';
        const timeEl = row.querySelector('time, span[class*="time"]');
        if (timeEl) receivedTime = norm(timeEl.innerText);

        return {
          invitationId,
          urn,
          name,
          slug,
          profileUrl,
          avatarUrl,
          headline,
          companyLogoUrl,
          mutualConnections,
          mutualCount,
          hasMessage: Boolean(message),
          message,
          replyUrl,
          receivedTime,
        };
      });
    }, rowSelector);

    // 重複除去（同一invitationIdまたはprofileUrl）
    const seen = new Set();
    const uniqueItems = [];
    for (const item of rawItems) {
      const key = item.invitationId || item.profileUrl || item.name;
      if (key && !seen.has(key)) {
        seen.add(key);
        uniqueItems.push(item);
      }
    }

    const finalInvitations = limit > 0 ? uniqueItems.slice(0, limit) : uniqueItems;

    result.success = true;
    result.totalCount = finalInvitations.length;
    result.invitations = finalInvitations;
    result.emptyState = finalInvitations.length === 0;

    return result;
  } catch (globalErr) {
    result.errors.push(`Global error: ${globalErr.message}`);
    return result;
  }
};
