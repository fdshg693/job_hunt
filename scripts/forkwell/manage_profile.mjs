// scripts/forkwell/manage_profile.mjs
// Forkwell Jobs プロフィール（自己紹介、目指したいこと、スカウト設定等）の更新・管理 Playwright スクリプト
// Python側の execute_manage_action からテンプレート置換されて実行されます。

async page => {
  const ACTION = '__FORKWELL_ACTION__';
  const PAYLOAD = __FORKWELL_PAYLOAD__;
  const IS_DRY_RUN = __FORKWELL_DRY_RUN__;

  const BASE_URL = 'https://jobs.forkwell.com';

  const result = {
    success: false,
    action: ACTION,
    isDryRun: IS_DRY_RUN,
    timestamp: new Date().toISOString(),
    data: {},
    error: null,
  };

  try {
    // -------------------------------------------------------------
    // 1. 自己紹介 (Bio)
    // -------------------------------------------------------------
    if (ACTION === 'get-bio') {
      const currentUrl = page.url();
      if (!currentUrl.includes('/dashboard') || currentUrl.includes('/preferences') || currentUrl.includes('/skills')) {
        await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'domcontentloaded', timeout: 20000 });
      }
      await page.waitForTimeout(500);

      let bio = '';
      try {
        const bioRes = await page.evaluate(async () => {
          const res = await fetch('/api/v1/profile/bios', { headers: { 'Accept': 'application/json' } });
          return res.ok ? await res.json() : null;
        });
        if (bioRes && (bioRes.bio || bioRes.biography)) {
          bio = bioRes.bio || bioRes.biography;
        }
      } catch (_) {}

      if (!bio) {
        bio = await page.evaluate(() => {
          const cards = Array.from(document.querySelectorAll('.dashboard-card, .card'));
          const card = cards.find(c => c.textContent.includes('自己紹介'));
          if (!card) return '';
          const body = card.querySelector('.profile-markdown, .dashboard-card__body, .card-body') || card;
          return body.textContent.replace('自己紹介', '').replace('編集する', '').trim();
        });
      }

      result.success = true;
      result.data = { bio: bio };
      return result;
    }

    if (ACTION === 'update-bio') {
      const currentUrl = page.url();
      if (!currentUrl.includes('/dashboard') || currentUrl.includes('/preferences') || currentUrl.includes('/skills')) {
        await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'domcontentloaded', timeout: 20000 });
      }
      await page.waitForTimeout(500);

      // 現在の自己紹介を取得
      let previousBio = '';
      try {
        const bioRes = await page.evaluate(async () => {
          const res = await fetch('/api/v1/profile/bios', { headers: { 'Accept': 'application/json' } });
          return res.ok ? await res.json() : null;
        });
        if (bioRes && (bioRes.bio || bioRes.biography)) {
          previousBio = bioRes.bio || bioRes.biography;
        }
      } catch (_) {}

      const newBio = PAYLOAD.bio || '';

      if (IS_DRY_RUN) {
        result.success = true;
        result.data = {
          previousBio: previousBio,
          newBio: newBio,
          finalUrl: page.url(),
        };
        return result;
      }

      // 本番反映: まず API (PATCH /api/v1/profile/bios) を試みる
      let apiSuccess = false;
      try {
        const apiResult = await page.evaluate(async (text) => {
          const csrfMeta = document.querySelector('meta[name="csrf-token"]');
          const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';
          const res = await fetch('/api/v1/profile/bios', {
            method: 'PATCH',
            headers: {
              'Content-Type': 'application/json',
              'Accept': 'application/json',
              'X-CSRF-Token': csrfToken,
            },
            body: JSON.stringify({ bio: text }),
          });
          return { ok: res.ok, status: res.status };
        }, newBio);
        apiSuccess = apiResult.ok;
      } catch (_) {
        apiSuccess = false;
      }

      // API失敗時はUIフォールバック（画面上での編集・保存）
      if (!apiSuccess) {
        const editBtnSelector = 'button.dashboard-edit-button[data-gtm-click="dashboard_biography_edit"]';
        await page.waitForSelector(editBtnSelector, { timeout: 10000 });
        await page.click(editBtnSelector);
        await page.waitForTimeout(500);

        const textareaSelector = '.dashboard-card:has([data-gtm-click="dashboard_biography_save"]) textarea, .dashboard-card textarea';
        await page.waitForSelector(textareaSelector, { timeout: 10000 });
        await page.fill(textareaSelector, newBio);
        await page.waitForTimeout(300);

        const saveBtnSelector = 'button.dashboard-edit-button[data-gtm-click="dashboard_biography_save"]';
        await page.waitForSelector(saveBtnSelector, { timeout: 5000 });
        await page.click(saveBtnSelector);
        await page.waitForTimeout(1500);
      }

      // 更新後の値を取得
      let updatedBio = '';
      try {
        const bioRes = await page.evaluate(async () => {
          const res = await fetch('/api/v1/profile/bios', { headers: { 'Accept': 'application/json' } });
          return res.ok ? await res.json() : null;
        });
        if (bioRes && (bioRes.bio || bioRes.biography)) {
          updatedBio = bioRes.bio || bioRes.biography;
        }
      } catch (_) {}

      result.success = true;
      result.data = {
        previousBio: previousBio,
        newBio: newBio,
        updatedBio: updatedBio || newBio,
        method: apiSuccess ? 'api' : 'ui',
        finalUrl: page.url(),
      };
      return result;
    }

    // -------------------------------------------------------------
    // 2. やりたい・目指したいこと (Desired Role / Career Vision)
    // -------------------------------------------------------------
    if (ACTION === 'get-desired-role') {
      await page.goto(`${BASE_URL}/dashboard/preferences`, { waitUntil: 'domcontentloaded', timeout: 20000 });
      await page.waitForTimeout(500);

      const desiredRole = await page.evaluate(() => {
        const card = document.querySelector('#career-vision');
        if (!card) return '';
        const body = card.querySelector('.dashboard-card__body, .card-body') || card;
        return body.textContent.replace('やりたい・目指したいこと', '').replace('編集する', '').trim();
      });

      result.success = true;
      result.data = { desiredRole: desiredRole };
      return result;
    }

    if (ACTION === 'update-desired-role') {
      await page.goto(`${BASE_URL}/dashboard/preferences`, { waitUntil: 'domcontentloaded', timeout: 20000 });
      await page.waitForTimeout(500);

      // 現在の値
      const previousRole = await page.evaluate(() => {
        const card = document.querySelector('#career-vision');
        if (!card) return '';
        const body = card.querySelector('.dashboard-card__body, .card-body') || card;
        return body.textContent.replace('やりたい・目指したいこと', '').replace('編集する', '').trim();
      });

      const newRole = PAYLOAD.desiredRole || '';

      if (IS_DRY_RUN) {
        result.success = true;
        result.data = {
          previousRole: previousRole,
          newRole: newRole,
          finalUrl: page.url(),
        };
        return result;
      }

      // UI編集
      const editBtnSelector = '#career-vision button[data-gtm-click="dashboard_career_vision_edit"], #career-vision button.dashboard-edit-button';
      await page.waitForSelector(editBtnSelector, { timeout: 10000 });
      await page.click(editBtnSelector);
      await page.waitForTimeout(500);

      const textareaSelector = '#career-vision textarea, #career-vision input[type="text"]';
      await page.waitForSelector(textareaSelector, { timeout: 10000 });
      await page.fill(textareaSelector, newRole);
      await page.waitForTimeout(300);

      const saveBtnSelector = '#career-vision button[data-gtm-click="dashboard_career_vision_save"], #career-vision button.dashboard-edit-button';
      await page.waitForSelector(saveBtnSelector, { timeout: 5000 });
      await page.click(saveBtnSelector);
      await page.waitForTimeout(1500);

      // 保存後の値
      const updatedRole = await page.evaluate(() => {
        const card = document.querySelector('#career-vision');
        if (!card) return '';
        const body = card.querySelector('.dashboard-card__body, .card-body') || card;
        return body.textContent.replace('やりたい・目指したいこと', '').replace('編集する', '').trim();
      });

      result.success = true;
      result.data = {
        previousRole: previousRole,
        newRole: newRole,
        updatedRole: updatedRole || newRole,
        finalUrl: page.url(),
      };
      return result;
    }

    // -------------------------------------------------------------
    // 3. スカウト設定 (Scout Status)
    // -------------------------------------------------------------
    if (ACTION === 'get-scout') {
      const currentUrl = page.url();
      if (!currentUrl.includes('/dashboard') || currentUrl.includes('/preferences') || currentUrl.includes('/skills')) {
        await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'domcontentloaded', timeout: 20000 });
      }
      await page.waitForTimeout(500);

      const scoutInfo = await page.evaluate(() => {
        const btn = document.querySelector('.labeled-toggle-switch, [data-gtm-click*="scout"]');
        if (!btn) return { active: false, status: 'unknown' };
        const isActive = btn.classList.contains('labeled-toggle-switch--active') || btn.getAttribute('aria-pressed') === 'true';
        return {
          active: isActive,
          status: isActive ? 'on' : 'off',
        };
      });

      result.success = true;
      result.data = scoutInfo;
      return result;
    }

    if (ACTION === 'update-scout') {
      const currentUrl = page.url();
      if (!currentUrl.includes('/dashboard') || currentUrl.includes('/preferences') || currentUrl.includes('/skills')) {
        await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'domcontentloaded', timeout: 20000 });
      }
      await page.waitForTimeout(500);

      const currentStatus = await page.evaluate(() => {
        const btn = document.querySelector('.labeled-toggle-switch, [data-gtm-click*="scout"]');
        if (!btn) return 'unknown';
        const isActive = btn.classList.contains('labeled-toggle-switch--active') || btn.getAttribute('aria-pressed') === 'true';
        return isActive ? 'on' : 'off';
      });

      const targetStatus = (PAYLOAD.status || '').toLowerCase(); // 'on' or 'off'

      if (IS_DRY_RUN) {
        result.success = true;
        result.data = {
          previousStatus: currentStatus,
          targetStatus: targetStatus,
          alreadySet: currentStatus === targetStatus,
          finalUrl: page.url(),
        };
        return result;
      }

      if (currentStatus !== targetStatus && targetStatus !== '') {
        const scoutBtnSelector = '.labeled-toggle-switch, [data-gtm-click*="scout"]';
        await page.waitForSelector(scoutBtnSelector, { timeout: 10000 });
        await page.click(scoutBtnSelector);
        await page.waitForTimeout(1000);
      }

      const updatedStatus = await page.evaluate(() => {
        const btn = document.querySelector('.labeled-toggle-switch, [data-gtm-click*="scout"]');
        if (!btn) return 'unknown';
        const isActive = btn.classList.contains('labeled-toggle-switch--active') || btn.getAttribute('aria-pressed') === 'true';
        return isActive ? 'on' : 'off';
      });

      result.success = true;
      result.data = {
        previousStatus: currentStatus,
        targetStatus: targetStatus,
        updatedStatus: updatedStatus,
        finalUrl: page.url(),
      };
      return result;
    }

    // -------------------------------------------------------------
    // 4. 職歴一覧 (Career Summary)
    // -------------------------------------------------------------
    if (ACTION === 'get-career') {
      const currentUrl = page.url();
      if (!currentUrl.includes('/dashboard') || currentUrl.includes('/preferences') || currentUrl.includes('/skills')) {
        await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'domcontentloaded', timeout: 20000 });
      }
      await page.waitForTimeout(500);

      const careerData = await page.evaluate(() => {
        const companies = [];
        const timelineElements = Array.from(document.querySelectorAll('.vertical-timeline-element'));
        timelineElements.forEach((tlEl, idx) => {
          const companyNameBox = tlEl.querySelector('.vertical-timeline-element__company-name');
          if (!companyNameBox) return;

          const companyNameDiv = companyNameBox.querySelector('div:first-child');
          const periodDiv = companyNameBox.querySelector('div:last-child');
          const companyName = companyNameDiv ? companyNameDiv.textContent.trim() : `企業 #${idx + 1}`;
          const period = periodDiv ? periodDiv.textContent.trim() : '';

          const contentBox = tlEl.querySelector('.vertical-timeline-element__with-label-content');
          const projects = [];
          if (contentBox) {
            const projBlocks = Array.from(contentBox.querySelectorAll('.pt-3'));
            projBlocks.forEach((pb, pIdx) => {
              const pPeriodDiv = pb.querySelector('.period div:first-child');
              const roleBadge = pb.querySelector('.period span.badge, .period [class*="badge"]');
              const markdownEl = pb.querySelector('.profile-markdown');

              const pPeriod = pPeriodDiv ? pPeriodDiv.textContent.trim() : '';
              const pRole = roleBadge ? roleBadge.textContent.trim() : '';
              const desc = markdownEl ? markdownEl.textContent.trim() : '';

              if (pPeriod || pRole || desc) {
                projects.push({
                  index: pIdx,
                  period: pPeriod,
                  role: pRole,
                  description: desc,
                });
              }
            });
          }

          if (companyName) {
            companies.push({
              index: idx,
              companyName: companyName,
              period: period,
              projects: projects,
            });
          }
        });
        return { companies: companies };
      });

      result.success = true;
      result.data = careerData;
      return result;
    }

    throw new Error(`未対応のアクションです: ${ACTION}`);
  } catch (err) {
    result.success = false;
    result.error = err.message || String(err);
    return result;
  }
}
