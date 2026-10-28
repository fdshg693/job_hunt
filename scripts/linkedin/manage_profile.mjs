// scripts/linkedin/manage_profile.mjs
// LinkedIn の Headline（肩書き）および About（自己紹介文）を更新する Playwright スクリプト

async page => {
  const action = '__LINKEDIN_ACTION__';
  const payload = __LINKEDIN_PAYLOAD__;
  const slug = '__LINKEDIN_PROFILE_SLUG__';
  const INTRO_EDIT_URL = `https://www.linkedin.com/in/${slug}/edit/intro/`;
  const SUMMARY_EDIT_URL = `https://www.linkedin.com/in/${slug}/edit/forms/summary/new/`;

  const sleep = ms => page.waitForTimeout(ms);

  if (action === 'update') {
    const updatedFields = [];

    // 1. Headline の更新
    if (payload.headline !== undefined && payload.headline !== null) {
      await page.goto(INTRO_EDIT_URL, {
        waitUntil: 'domcontentloaded',
        timeout: 25000,
      });
      await sleep(3000);

      // Headline は TipTap / ProseMirror の contenteditable
      // または通常の input/textarea の可能性も考慮
      const headlineLocator = page.locator('.tiptap.ProseMirror, div[contenteditable="true"]').first();
      await headlineLocator.waitFor({ state: 'visible', timeout: 15000 });
      await headlineLocator.click();
      await sleep(300);

      // 全選択して消去
      await page.keyboard.press('ControlOrMeta+a');
      await page.keyboard.press('Backspace');
      await sleep(200);

      // 新しいテキストを挿入
      if (payload.headline.trim()) {
        await page.keyboard.insertText(payload.headline.trim());
      }
      await sleep(500);

      // Save ボタンをクリック
      const saveBtn = page.locator('button').filter({ hasText: /^Save$|^保存$/i }).first();
      await saveBtn.waitFor({ state: 'visible', timeout: 10000 });
      await saveBtn.scrollIntoViewIfNeeded();
      await saveBtn.click();
      await sleep(3000);

      updatedFields.push('headline');
    }

    // 2. About の更新
    if (payload.about !== undefined && payload.about !== null) {
      await page.goto(SUMMARY_EDIT_URL, {
        waitUntil: 'domcontentloaded',
        timeout: 25000,
      });
      await sleep(3000);

      // About の contenteditable (div[role="textbox"][aria-label="About"])
      const aboutLocator = page.locator('div[role="textbox"][aria-label="About"], div[role="textbox"], .tiptap.ProseMirror, textarea').first();
      await aboutLocator.waitFor({ state: 'visible', timeout: 15000 });
      await aboutLocator.click();
      await sleep(300);

      // 全選択して消去
      await page.keyboard.press('ControlOrMeta+a');
      await page.keyboard.press('Backspace');
      await sleep(200);

      // 新しいテキストを挿入
      if (payload.about.trim()) {
        await page.keyboard.insertText(payload.about.trim());
      }
      await sleep(500);

      // Save ボタンをクリック
      const saveBtn = page.locator('button').filter({ hasText: /^Save$|^保存$/i }).first();
      await saveBtn.waitFor({ state: 'visible', timeout: 10000 });
      await saveBtn.scrollIntoViewIfNeeded();
      await saveBtn.click();
      await sleep(3000);

      updatedFields.push('about');
    }

    return {
      success: true,
      updatedFields,
      message: `LinkedIn プロフィール (${updatedFields.join(', ')}) を更新しました。`,
    };
  }

  return { success: false, error: `未知のアクション: ${action}` };
}
