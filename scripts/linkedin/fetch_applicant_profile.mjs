// scripts/linkedin/fetch_applicant_profile.mjs
// LinkedIn 申請者（他ユーザー）のプロフィール詳細ページから概要情報を取得する Playwright スクリプト
// 対象URL: https://www.linkedin.com/in/{slug}/

async page => {
  const targetUrl = '__PROFILE_URL__';
  const sleep = ms => page.waitForTimeout(ms);

  const result = {
    success: false,
    url: targetUrl,
    name: '',
    headline: '',
    location: '',
    currentCompany: '',
    currentRole: '',
    about: '',
    experiences: [],
    skills: [],
    error: '',
  };

  try {
    if (!targetUrl || !targetUrl.includes('/in/')) {
      result.error = '有効なプロフィールURLが指定されていません';
      return result;
    }

    await page.goto(targetUrl, {
      waitUntil: 'domcontentloaded',
      timeout: 25000,
    });
    await sleep(2500);

    const data = await page.evaluate(() => {
      const norm = s => (s || '').replace(/\s+/g, ' ').trim();

      // 1. トップカード情報
      const topSection = document.querySelector('section[data-member-id]') ||
                         document.querySelector('main section:first-of-type') ||
                         document.querySelector('section.artdeco-card');
      
      let name = '';
      let headline = '';
      let location = '';
      let currentCompany = '';

      if (topSection) {
        const h1 = topSection.querySelector('h1');
        if (h1) name = norm(h1.innerText);

        // Headline
        const headlineEl = topSection.querySelector('.text-body-medium, div[data-generated-suggestion-target]');
        if (headlineEl) {
          headline = norm(headlineEl.innerText);
        }

        // Location
        const locEl = topSection.querySelector('.text-body-small.inline.t-black--light, span[class*="location"]');
        if (locEl) {
          location = norm(locEl.innerText);
        }

        // 現職企業名（トップカード右上の企業リンク等）
        const companyEl = topSection.querySelector('button[aria-label*="Current company"], a[href*="/company/"] span, [aria-label*="現在の勤務先"]');
        if (companyEl) {
          currentCompany = norm(companyEl.innerText);
        }
      }

      // フォールバック（タイトルタグ等）
      if (!name) {
        const titleMatch = document.title.match(/^(.*?)\s*[-|]\s*LinkedIn/i);
        if (titleMatch) name = norm(titleMatch[1]);
      }

      // 2. About（自己紹介）
      let about = '';
      const allSections = Array.from(document.querySelectorAll('section'));
      for (const sec of allSections) {
        const secText = (sec.querySelector('h2')?.innerText || '').toLowerCase();
        if (secText.includes('about') || secText.includes('自己紹介') || secText.includes('概要')) {
          const textEl = sec.querySelector('.inline-show-more-text');
          if (textEl) {
            about = norm(textEl.innerText);
          } else {
            // 見出し以外
            const clone = sec.cloneNode(true);
            clone.querySelectorAll('h2, button').forEach(e => e.remove());
            about = norm(clone.innerText);
          }
          break;
        }
      }

      // 3. Experience（職歴・直近の役職）
      const experiences = [];
      for (const sec of allSections) {
        const secText = (sec.querySelector('h2')?.innerText || '').toLowerCase();
        if (secText.includes('experience') || secText.includes('職歴')) {
          const items = Array.from(sec.querySelectorAll('li.artdeco-list__item, li.pvs-list__pvs-item, ul > li'));
          for (const it of items.slice(0, 3)) { // 直近3件
            const lines = it.innerText.split('\n').map(s => norm(s)).filter(Boolean);
            if (lines.length >= 2) {
              const roleTitle = lines[0];
              const compName = lines[1];
              const period = lines[2] || '';
              experiences.push({
                role: roleTitle,
                company: compName,
                period,
              });
            }
          }
          break;
        }
      }

      // 4. Skills（スキル一覧セクションから抜粋）
      const skills = [];
      for (const sec of allSections) {
        const secText = (sec.querySelector('h2')?.innerText || '').toLowerCase();
        if (secText.includes('skills') || secText.includes('スキル')) {
          const sItems = Array.from(sec.querySelectorAll('li, span[aria-hidden="true"]'));
          for (const s of sItems) {
            const st = norm(s.innerText);
            if (st && st.length < 40 && !st.includes('Skills') && !skills.includes(st)) {
              skills.push(st);
            }
            if (skills.length >= 8) break;
          }
          break;
        }
      }

      return {
        name,
        headline,
        location,
        currentCompany,
        about,
        experiences,
        skills,
      };
    });

    result.success = true;
    result.name = data.name;
    result.headline = data.headline;
    result.location = data.location;
    result.currentCompany = data.currentCompany;
    if (data.experiences.length > 0 && !result.currentCompany) {
      result.currentCompany = data.experiences[0].company;
      result.currentRole = data.experiences[0].role;
    }
    result.about = data.about;
    result.experiences = data.experiences;
    result.skills = data.skills;

    return result;
  } catch (err) {
    result.error = `Profile fetch failed: ${err.message}`;
    return result;
  }
};
