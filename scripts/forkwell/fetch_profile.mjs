// scripts/forkwell/fetch_profile.mjs
// Forkwell Jobs のダッシュボード（/dashboard, /dashboard/preferences, /dashboard/skills）から
// プロフィール情報（キャリア、職歴、プロジェクト、希望条件、スキル、語学、資格等）を高精度に構造化抽出する Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/forkwell/fetch_profile.mjs --raw

async page => {
  const result = {
    success: false,
    fetchedAt: new Date().toISOString(),
    userInfo: {},
    career: {},
    preferences: {},
    skills: {},
    errors: [],
  };

  const BASE_URL = 'https://jobs.forkwell.com';

  const cleanText = (str) => {
    if (!str) return '';
    return str
      .replace(/編集する/g, '')
      .replace(/詳しく見る/g, '')
      .replace(/すべて表示/g, '')
      .replace(/資格を追加する/g, '')
      .replace(/学歴を追加する/g, '')
      .replace(/職歴を追加/g, '')
      .replace(/プロジェクト・職務を追加/g, '')
      .replace(/\s+/g, ' ')
      .trim();
  };

  // 1. /dashboard（キャリア＆ワークス）
  try {
    const currentUrl = page.url();
    if (!currentUrl.includes('/dashboard') || currentUrl.includes('/preferences') || currentUrl.includes('/skills')) {
      await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'domcontentloaded', timeout: 20000 });
    }
    await page.waitForTimeout(1000);

    const dashboardData = await page.evaluate(async () => {
      const data = {
        meta: {},
        basic: {},
        bio: '',
        scoutStatus: '',
        jobIntent: '',
        companies: [],
        educations: [],
        otherExperiences: '',
        workConditions: '',
        rawCards: {},
      };

      // グローバルオブジェクト
      if (window.Forkwell) {
        data.meta.forkwell = window.Forkwell;
      }

      // CSRFトークン
      const csrfMeta = document.querySelector('meta[name="csrf-token"]');
      if (csrfMeta) {
        data.meta.csrfToken = csrfMeta.getAttribute('content');
      }

      // ユーザー名
      const userEl = document.querySelector('.user-menu, .header-user-name, [data-toggle="dropdown"], .navbar-text');
      if (userEl) {
        data.basic.name = userEl.textContent.trim();
      }

      // スカウト設定状態
      const scoutBtn = document.querySelector('.labeled-toggle-switch, [data-gtm-click*="scout"]');
      if (scoutBtn) {
        data.scoutStatus = scoutBtn.textContent.trim().replace(/\s+/g, ' ');
      }

      // 転職意欲
      const intentCard = Array.from(document.querySelectorAll('.dashboard-card, .card, div')).find(c => {
        return c.textContent.includes('転職意欲') && c.textContent.length < 500;
      });
      if (intentCard) {
        data.jobIntent = intentCard.textContent.replace('転職意欲', '').trim().replace(/\s+/g, ' ');
      }

      // 自己紹介（API経由）
      try {
        const bioRes = await fetch('/api/v1/profile/bios', {
          headers: { 'Accept': 'application/json' }
        });
        if (bioRes.ok) {
          const bioJson = await bioRes.json();
          data.bio = bioJson.bio || bioJson.biography || '';
        }
      } catch (_) {}

      // フォールバック: DOMから自己紹介取得
      if (!data.bio) {
        const bioCard = Array.from(document.querySelectorAll('.dashboard-card, .card')).find(c => {
          const title = c.querySelector('.dashboard-card__header-title, .card-title, h2, h3');
          return title && title.textContent.includes('自己紹介');
        });
        if (bioCard) {
          data.bio = bioCard.textContent.replace(/自己紹介/g, '').replace(/編集する/g, '').trim();
        }
      }

      // カード群の収集
      const cards = Array.from(document.querySelectorAll('.dashboard-card, .card'));
      for (const card of cards) {
        const header = card.querySelector('.dashboard-card__header-title, .card-title, h2, h3');
        const headerText = header ? header.textContent.trim() : '';
        const cardText = card.textContent.trim().replace(/\s+/g, ' ');

        if (headerText) {
          data.rawCards[headerText] = cardText;
        }

        if (headerText.includes('学歴')) {
          // 学歴詳細の抽出
          const bodyEl = card.querySelector('.dashboard-card__body') || card;
          const cleanedEdu = bodyEl.textContent.replace(/学歴/g, '').replace(/学歴を追加する/g, '').replace(/を追加する/g, '').trim().replace(/\s+/g, ' ');
          if (cleanedEdu) data.educations.push(cleanedEdu);
        } else if (headerText.includes('その他の経験')) {
          const bodyEl = card.querySelector('.dashboard-card__body') || card;
          data.otherExperiences = bodyEl.textContent.replace(/その他の経験/g, '').replace(/編集する/g, '').trim().replace(/\s+/g, ' ');
        } else if (headerText.includes('国内就労条件') || headerText.includes('就労条件')) {
          const bodyEl = card.querySelector('.dashboard-card__body') || card;
          data.workConditions = bodyEl.textContent.replace(/国内就労条件/g, '').replace(/就労条件/g, '').replace(/編集する/g, '').trim().replace(/\s+/g, ' ');
        }
      }

      // 職歴タイムラインの抽出
      const timelineElements = Array.from(document.querySelectorAll('.vertical-timeline-element'));
      for (const tlEl of timelineElements) {
        const companyNameBox = tlEl.querySelector('.vertical-timeline-element__company-name');
        if (!companyNameBox) continue;

        const companyNameDiv = companyNameBox.querySelector('div:first-child');
        const periodDiv = companyNameBox.querySelector('div:last-child');
        const companyName = companyNameDiv ? companyNameDiv.textContent.trim() : '';
        const period = periodDiv ? periodDiv.textContent.trim() : '';

        // 各プロジェクトブロック
        const contentBox = tlEl.querySelector('.vertical-timeline-element__with-label-content');
        const projects = [];
        if (contentBox) {
          // プロジェクト枠（.pt-3）
          const projBlocks = Array.from(contentBox.querySelectorAll('.pt-3'));
          for (const pb of projBlocks) {
            const periodDiv = pb.querySelector('.period div:first-child');
            const roleBadge = pb.querySelector('.period span.badge, .period [class*="badge"]');
            const markdownEl = pb.querySelector('.profile-markdown');
            const tags = Array.from(pb.querySelectorAll('.tag, .badge:not(.bg-primary)'))
              .map(t => t.textContent.trim()).filter(Boolean);

            const periodText = periodDiv ? periodDiv.textContent.trim() : '';
            const roleText = roleBadge ? roleBadge.textContent.trim() : '';
            const descText = markdownEl ? markdownEl.textContent.trim() : '';

            if (periodText || roleText || descText) {
              projects.push({
                period: periodText,
                role: roleText,
                description: descText,
                tags,
              });
            }
          }
        }

        if (companyName) {
          data.companies.push({
            companyName,
            period,
            projects,
            rawText: tlEl.textContent.trim().replace(/\s+/g, ' '),
          });
        }
      }

      return data;
    });

    result.userInfo = dashboardData.basic || {};
    result.userInfo.meta = dashboardData.meta || {};
    result.career = {
      bio: dashboardData.bio,
      scoutStatus: cleanText(dashboardData.scoutStatus),
      jobIntent: cleanText(dashboardData.jobIntent),
      companies: dashboardData.companies,
      educations: dashboardData.educations,
      otherExperiences: cleanText(dashboardData.otherExperiences),
      workConditions: cleanText(dashboardData.workConditions),
      rawCards: dashboardData.rawCards,
    };
  } catch (err) {
    result.errors.push(`Dashboard fetch failed: ${err.message}`);
  }

  // 2. /dashboard/preferences（やりたいこと・希望）
  try {
    await page.goto(`${BASE_URL}/dashboard/preferences`, { waitUntil: 'domcontentloaded', timeout: 20000 });
    await page.waitForTimeout(1000);

    const preferencesData = await page.evaluate(() => {
      const prefs = {
        desiredRole: '',
        desiredSkills: [],
        conditions: '',
        otherPreferences: '',
        salary: '',
        rawCards: {},
      };

      const cards = Array.from(document.querySelectorAll('.dashboard-card, .card'));
      for (const card of cards) {
        const header = card.querySelector('.dashboard-card__header-title, .card-title, h2, h3');
        const headerText = header ? header.textContent.trim() : '';
        const bodyEl = card.querySelector('.dashboard-card__body') || card;
        const bodyText = bodyEl.textContent.trim().replace(/\s+/g, ' ');

        if (headerText) {
          prefs.rawCards[headerText] = bodyText;
        }

        if (headerText.includes('やりたい') || headerText.includes('目指したい')) {
          prefs.desiredRole = bodyText.replace(/やりたい・目指したいこと/g, '').replace(/編集する/g, '').trim();
        } else if (headerText.includes('希望技術')) {
          const tags = Array.from(card.querySelectorAll('.tag, .badge, [class*="skill"], [class*="tag"]'))
            .map(t => t.textContent.trim()).filter(Boolean);
          if (tags.length > 0) {
            prefs.desiredSkills = tags;
          } else {
            const cleaned = bodyText.replace(/^希望技術\s*(?:編集する)?\s*/, '');
            prefs.desiredSkills = cleaned.split(',').map(s => s.trim()).filter(Boolean);
          }
        } else if (headerText.includes('希望条件')) {
          prefs.conditions = bodyText.replace(/希望条件/g, '').replace(/編集する/g, '').trim();
        } else if (headerText.includes('その他の希望')) {
          prefs.otherPreferences = bodyText.replace(/その他の希望条件/g, '').replace(/編集する/g, '').replace(/すべて表示/g, '').trim();
        } else if (headerText.includes('年収')) {
          prefs.salary = bodyText.replace(/年収/g, '').replace(/編集する/g, '').trim();
        }
      }

      return prefs;
    });

    result.preferences = {
      desiredRole: cleanText(preferencesData.desiredRole),
      desiredSkills: preferencesData.desiredSkills,
      conditions: cleanText(preferencesData.conditions),
      otherPreferences: cleanText(preferencesData.otherPreferences),
      salary: cleanText(preferencesData.salary),
      rawCards: preferencesData.rawCards,
    };
  } catch (err) {
    result.errors.push(`Preferences fetch failed: ${err.message}`);
  }

  // 3. /dashboard/skills（スキル）
  try {
    await page.goto(`${BASE_URL}/dashboard/skills`, { waitUntil: 'domcontentloaded', timeout: 20000 });
    await page.waitForTimeout(1000);

    const skillsData = await page.evaluate(() => {
      const skills = {
        experiencedSkills: {
          level3: [],
          level2: [],
          level1: [],
          raw: '',
        },
        certifications: [],
        languages: [],
        rawCards: {},
      };

      const cards = Array.from(document.querySelectorAll('.dashboard-card, .card'));
      for (const card of cards) {
        const header = card.querySelector('.dashboard-card__header-title, .card-title, h2, h3');
        const headerText = header ? header.textContent.trim() : '';
        const bodyEl = card.querySelector('.dashboard-card__body') || card;
        const bodyText = bodyEl.textContent.trim().replace(/\s+/g, ' ');

        if (headerText) {
          skills.rawCards[headerText] = bodyText;
        }

        if (headerText.includes('経験技術')) {
          skills.experiencedSkills.raw = bodyText;

          // 各レベルごとのブロック（div.d-flex:has(strong.text-nowrap)）
          const levelRows = Array.from(card.querySelectorAll('.d-flex[style*="gap: 20px"], .d-flex'));
          for (const row of levelRows) {
            const strong = row.querySelector('strong.text-nowrap');
            if (!strong) continue;
            const lvText = strong.textContent.trim();
            const tagContainer = row.querySelector('.d-flex.flex-wrap');
            if (!tagContainer) continue;

            const tags = Array.from(tagContainer.querySelectorAll('span, a, div'))
              .map(t => t.textContent.trim())
              .filter(t => t && t !== '該当なし');

            if (lvText.includes('3')) {
              skills.experiencedSkills.level3 = tags;
            } else if (lvText.includes('2')) {
              skills.experiencedSkills.level2 = tags;
            } else if (lvText.includes('1')) {
              skills.experiencedSkills.level1 = tags;
            }
          }
        } else if (headerText.includes('資格')) {
          // テキストから資格名と取得年月を正規表現で抽出
          const cleaned = bodyText.replace(/資格/g, '').replace(/を追加する/g, '').trim();
          const regex = /(.+?)(\d{4}年\d{1,2}月)/g;
          let m;
          const certs = [];
          while ((m = regex.exec(cleaned)) !== null) {
            const cName = m[1].replace(/を追加する/g, '').replace(/資格/g, '').trim();
            certs.push(`${cName} (${m[2]})`);
          }
          skills.certifications = certs.length > 0 ? certs : (cleaned ? [cleaned] : []);
        } else if (headerText.includes('語学')) {
          const langBlocks = Array.from(card.querySelectorAll('.dashboard-card__body > .mb-2'));
          if (langBlocks.length > 0) {
            skills.languages = langBlocks.map(b => b.textContent.replace(/\s+/g, '').trim()).filter(Boolean);
          } else {
            const cleaned = bodyText.replace(/語学力/g, '').replace(/編集する/g, '').trim();
            if (cleaned) skills.languages = [cleaned];
          }
        }
      }

      return skills;
    });

    result.skills = {
      experiencedSkills: skillsData.experiencedSkills,
      certifications: skillsData.certifications.map(cleanText).filter(Boolean),
      languages: skillsData.languages.map(cleanText).filter(Boolean),
      rawCards: skillsData.rawCards,
    };
  } catch (err) {
    result.errors.push(`Skills fetch failed: ${err.message}`);
  }

  result.success = (result.career && (!!result.career.bio || (result.career.companies && result.career.companies.length > 0))) ||
                   (result.preferences && Object.keys(result.preferences.rawCards || {}).length > 0) ||
                   (result.skills && Object.keys(result.skills.rawCards || {}).length > 0);

  return result;
}
