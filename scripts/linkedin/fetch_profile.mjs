// scripts/linkedin/fetch_profile.mjs
// LinkedIn プロフィール（Headline, About, Skills等）を取得する Playwright スクリプト

async page => {
  const slug = '__LINKEDIN_PROFILE_SLUG__';
  const profileUrl = `https://www.linkedin.com/in/${slug}/`;
  const skillsUrl = `https://www.linkedin.com/in/${slug}/details/skills/`;
  const summaryEditUrl = `https://www.linkedin.com/in/${slug}/edit/forms/summary/new/`;

  const sleep = ms => page.waitForTimeout(ms);

  // 1. プロフィールトップ画面へ遷移
  await page.goto(profileUrl, {
    waitUntil: 'domcontentloaded',
    timeout: 25000,
  });
  await sleep(3000);

  // トップカード情報（名前、ヘッドライン、所在地など）の取得
  const topCard = await page.evaluate(() => {
    const editLink = document.querySelector('a[href*="/edit/intro/"]');
    const container = editLink ? editLink.closest('section') : document.querySelector('section[aria-label="Primary content"]');
    if (!container) return { name: '', headline: '', location: '' };

    const name = container.querySelector('h1, h2')?.innerText.trim() || '';
    const textLines = container.innerText.split('\n').map(s => s.trim()).filter(Boolean);

    let headline = '';
    let location = '';
    for (let i = 1; i < textLines.length; i++) {
      const line = textLines[i];
      if (line.includes('Verify in') || line.includes('Open to work') || line.includes('Open to')) continue;
      if (!headline) {
        headline = line;
        continue;
      }
      if (!location) {
        if (line === '·' || line === 'Contact info') break;
        location = line;
        break;
      }
    }

    return { name, headline, location };
  });

  // 2. About（自己紹介）の取得
  // トップ画面のAboutセクションから取得を試みる
  let aboutText = await page.evaluate(() => {
    const sections = Array.from(document.querySelectorAll('section'));
    for (const sec of sections) {
      const heading = sec.querySelector('h2, .t-bold');
      if (heading && heading.innerText.trim().toLowerCase() === 'about') {
        const textEl = sec.querySelector('.inline-show-more-text');
        if (textEl) {
          return textEl.innerText.trim();
        }
        // 見出し以外のテキスト
        return sec.innerText.replace(/^About\s*/i, '').trim();
      }
    }
    return '';
  });

  // もしトップ画面からAboutが十分に取得できなかった場合、About編集画面を開いて取得
  if (!aboutText) {
    try {
      await page.goto(summaryEditUrl, {
        waitUntil: 'domcontentloaded',
        timeout: 20000,
      });
      await sleep(2500);
      aboutText = await page.evaluate(() => {
        const el = document.querySelector('div[role="textbox"][aria-label="About"], div[role="textbox"]');
        return el ? (el.innerText || el.textContent || '').trim() : '';
      });
    } catch (e) {
      // 失敗した場合は無視
    }
  }

  // 3. Skills 一覧の取得
  await page.goto(skillsUrl, {
    waitUntil: 'domcontentloaded',
    timeout: 25000,
  });
  await sleep(3000);

  const skills = await page.evaluate(() => {
    const results = [];
    const seenIds = new Set();

    // 各スキルの編集リンク: a[href*="/details/skills/edit/forms/"]
    const editLinks = Array.from(document.querySelectorAll('a[href*="/details/skills/edit/forms/"]'));

    for (const link of editLinks) {
      const href = link.getAttribute('href') || '';
      const m = href.match(/\/details\/skills\/edit\/forms\/(\d+)/);
      if (!m) continue;
      const id = m[1];
      if (seenIds.has(id)) continue;
      seenIds.add(id);

      // aria-label からスキル名を抽出 (例: "Edit Google Cloud Platform (GCP) skill")
      const aria = link.getAttribute('aria-label') || '';
      let name = '';
      const ariaMatch = aria.match(/Edit\s+(.+?)\s+skill/i);
      if (ariaMatch) {
        name = ariaMatch[1].trim();
      } else {
        // コンテナ内のテキストから探す
        const container = link.closest('li') || link.closest('.artdeco-list__item') || link.parentElement;
        if (container) {
          const lines = container.innerText.split('\n').map(s => s.trim()).filter(Boolean);
          name = lines[0] || '';
        }
      }

      results.push({
        id,
        name: name || `Skill #${id}`,
        editUrl: link.href || `https://www.linkedin.com/details/skills/edit/forms/${id}/`,
      });
    }

    return results;
  });

  return {
    success: true,
    profile: {
      name: topCard.name,
      headline: topCard.headline,
      location: topCard.location,
      about: aboutText,
      skillsCount: skills.length,
      skills,
    },
  };
}

