// scripts/linkedin/manage_skills.mjs
// LinkedIn のスキル（Skills）一覧取得・追加・削除を実行する Playwright スクリプト

async page => {
  const action = '__LINKEDIN_ACTION__';
  const payload = __LINKEDIN_PAYLOAD__;
  const slug = '__LINKEDIN_PROFILE_SLUG__';
  const BASE_SKILLS_URL = `https://www.linkedin.com/in/${slug}/details/skills/`;
  const NEW_SKILL_URL = `https://www.linkedin.com/in/${slug}/skills/edit/forms/new/`;

  const sleep = ms => page.waitForTimeout(ms);

  // --- 1. LIST アクション ---
  if (action === 'list') {
    await page.goto(BASE_SKILLS_URL, {
      waitUntil: 'domcontentloaded',
      timeout: 25000,
    });
    await sleep(3000);

    const skills = await page.evaluate(() => {
      const results = [];
      const seenIds = new Set();
      const editLinks = Array.from(document.querySelectorAll('a[href*="/details/skills/edit/forms/"]'));

      for (const link of editLinks) {
        const href = link.getAttribute('href') || '';
        const m = href.match(/\/details\/skills\/edit\/forms\/(\d+)/);
        if (!m) continue;
        const id = m[1];
        if (seenIds.has(id)) continue;
        seenIds.add(id);

        const aria = link.getAttribute('aria-label') || '';
        let name = '';
        const ariaMatch = aria.match(/Edit\s+(.+?)\s+skill/i);
        if (ariaMatch) {
          name = ariaMatch[1].trim();
        } else {
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
      count: skills.length,
      skills,
    };
  }

  // --- 2. ADD アクション ---
  if (action === 'add') {
    const skillName = (payload.name || '').trim();
    if (!skillName) {
      return { success: false, error: '追加するスキル名（name）が指定されていません。' };
    }

    await page.goto(NEW_SKILL_URL, {
      waitUntil: 'domcontentloaded',
      timeout: 25000,
    });
    await sleep(3000);

    // スキル名入力欄を探す
    const inputLocator = page.locator('input[placeholder*="Skill"], input[aria-label*="Skill"]').first();
    await inputLocator.waitFor({ state: 'visible', timeout: 15000 });
    await inputLocator.click();
    await inputLocator.fill(skillName);
    await sleep(1000);

    // ドロップダウン候補が表示される場合、最初の完全一致または先頭候補をクリック
    const dropdownItem = page.locator('div[role="listbox"] div[role="option"], ul[role="listbox"] li, .basic-typeahead__selectable-list li').first();
    const hasDropdown = await dropdownItem.isVisible({ timeout: 2000 }).catch(() => false);
    if (hasDropdown) {
      await dropdownItem.click();
      await sleep(500);
    } else {
      // Enter キーで確定
      await page.keyboard.press('Enter');
      await sleep(500);
    }

    // Save ボタンをクリック
    const saveBtn = page.locator('button').filter({ hasText: /^Save$|^保存$/i }).first();
    await saveBtn.waitFor({ state: 'visible', timeout: 10000 });
    await saveBtn.scrollIntoViewIfNeeded();
    await saveBtn.click();
    await sleep(3000);

    return {
      success: true,
      name: skillName,
      message: `スキル「${skillName}」を追加しました。`,
    };
  }

  // --- 3. DELETE アクション ---
  if (action === 'delete') {
    const targetId = payload.id;
    if (!targetId) {
      return { success: false, error: '削除対象のスキルID（id）が指定されていません。' };
    }

    const editUrl = `https://www.linkedin.com/in/${slug}/details/skills/edit/forms/${targetId}/`;
    await page.goto(editUrl, {
      waitUntil: 'domcontentloaded',
      timeout: 25000,
    });
    await sleep(3000);

    // 「Delete skill」ボタンを探してクリック
    const deleteBtn = page.locator('button').filter({ hasText: /^Delete skill$|^スキルを削除$/i }).first();
    await deleteBtn.waitFor({ state: 'visible', timeout: 15000 });
    await deleteBtn.scrollIntoViewIfNeeded();
    await deleteBtn.click();
    await sleep(1000);

    // 確認ダイアログが出た場合、モーダル内の確定「Delete」ボタンをクリック
    const confirmDeleteBtn = page.locator('button').filter({ hasText: /^Delete$|^削除$/i }).last();
    const hasConfirm = await confirmDeleteBtn.isVisible({ timeout: 3000 }).catch(() => false);
    if (hasConfirm) {
      await confirmDeleteBtn.click();
      await sleep(2500);
    }

    return {
      success: true,
      id: targetId,
      message: `スキル (ID: ${targetId}) を削除しました。`,
    };
  }

  return { success: false, error: `未知のアクション: ${action}` };
}
