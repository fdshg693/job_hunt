// scripts/linkedin/manage_experience.mjs
// LinkedIn 職歴（Experience）画面における一覧取得・追加・更新・削除を実行する Playwright スクリプト
// 環境変数 LINKEDIN_ACTION, LINKEDIN_PAYLOAD, LINKEDIN_PROFILE_SLUG を参照して実行します。

async page => {
  const action = '__LINKEDIN_ACTION__';
  const payload = __LINKEDIN_PAYLOAD__;
  const slug = '__LINKEDIN_PROFILE_SLUG__';
  const BASE_EXPERIENCE_URL = `https://www.linkedin.com/in/${slug}/details/experience/`;
  const NEW_EXPERIENCE_URL = `https://www.linkedin.com/in/${slug}/details/experience/edit/forms/new/`;

  // 補助関数: 指定ミリ秒待機
  const sleep = ms => page.waitForTimeout(ms);

  // --- 1. LIST アクション ---
  if (action === 'list') {
    await page.goto(BASE_EXPERIENCE_URL, {
      waitUntil: 'domcontentloaded',
      timeout: 25000,
    });

    // 職歴要素の読み込み待機
    await page.waitForTimeout(3000);

    const experiences = await page.evaluate(() => {
      const results = [];
      const seenIds = new Set();

      // 各編集リンクから職歴アイテムを特定
      const editLinks = Array.from(document.querySelectorAll('a[href*="/details/experience/edit/forms/"]'));

      for (const link of editLinks) {
        const href = link.getAttribute('href') || '';
        const m = href.match(/\/details\/experience\/edit\/forms\/(\d+)/);
        if (!m) continue;
        const id = m[1];
        if (seenIds.has(id)) continue;
        seenIds.add(id);

        const container = link.closest('li') || link.closest('.artdeco-list__item') || link.parentElement;
        const text = container ? (container.innerText || '') : '';
        const lines = text
          .split('\n')
          .map(s => s.trim())
          .filter(Boolean);

        // 基本情報の抽出
        let title = '';
        let company = '';
        let employmentType = '';
        let duration = '';
        let location = '';
        let remoteType = '';
        let description = '';

        if (lines.length > 0) {
          title = lines[0];
        }
        if (lines.length > 1) {
          const compLine = lines[1];
          const parts = compLine.split('·').map(s => s.trim());
          company = parts[0] || '';
          if (parts.length > 1) {
            employmentType = parts[1];
          }
        }
        if (lines.length > 2) {
          duration = lines[2];
        }
        if (lines.length > 3) {
          const locLine = lines[3];
          const parts = locLine.split('·').map(s => s.trim());
          location = parts[0] || '';
          if (parts.length > 1) {
            remoteType = parts[1];
          }
        }
        if (lines.length > 4) {
          description = lines.slice(4).join('\n');
        }

        results.push({
          id,
          title,
          company,
          employmentType,
          duration,
          location,
          remoteType,
          description,
          rawLines: lines,
          editUrl: link.href || `https://www.linkedin.com/details/experience/edit/forms/${id}/`,
        });
      }
      return results;
    });

    return {
      success: true,
      count: experiences.length,
      experiences,
    };
  }

  // --- 2. ADD アクション ---
  if (action === 'add') {
    await page.goto(NEW_EXPERIENCE_URL, {
      waitUntil: 'domcontentloaded',
      timeout: 25000,
    });

    // フォームの主要入力欄が表示されるのを待機
    const titleInput = page.locator('input[placeholder*="Role title"], input[placeholder*="Example: Senior Product Manager"]').first();
    await titleInput.waitFor({ state: 'visible', timeout: 15000 });

    // 1. Job Title
    if (payload.title) {
      await titleInput.click();
      await titleInput.fill(payload.title);
      await sleep(300);
    }

    // 2. Organization / Company
    if (payload.company) {
      const compInput = page.locator('input[placeholder*="Organization name"], input[placeholder*="Example: Microsoft"]').first();
      await compInput.click();
      await compInput.fill(payload.company);
      await sleep(500);
      await page.keyboard.press('Escape');
      await sleep(300);
    }

    // 3. Employment Type
    if (payload.employmentType) {
      const empSelect = page.locator('label:has-text("Employment type") + select, select:has(option[value="1"])').first();
      if ((await empSelect.count()) > 0) {
        await empSelect.selectOption(String(payload.employmentType));
        await sleep(300);
      }
    }

    // 4. Location
    if (payload.location) {
      const locInput = page.locator('input[placeholder*="City, region, or Remote"], input[placeholder*="City or region"]').first();
      if ((await locInput.count()) > 0) {
        await locInput.click();
        await locInput.fill(payload.location);
        await sleep(500);
        await page.keyboard.press('Escape');
        await sleep(300);
      }
    }

    // 5. Location Type
    if (payload.locationType) {
      const locTypeSelect = page.locator('label:has-text("Location type") + select, select:has(option[value*="LocationType"])').first();
      if ((await locTypeSelect.count()) > 0) {
        await locTypeSelect.selectOption(String(payload.locationType));
        await sleep(300);
      }
    }

    // 6. I currently work here
    const isCurrent = payload.isCurrentlyWorking !== false; // デフォルトは在職中(true)
    const curCheckbox = page.locator('input[type="checkbox"]').first();
    const isChecked = await curCheckbox.isChecked();

    if (isCurrent && !isChecked) {
      await curCheckbox.click();
      await sleep(300);
    } else if (!isCurrent && isChecked) {
      await curCheckbox.click();
      await sleep(500);
    }

    // 7. Start date
    if (payload.startMonth) {
      const startMonthSelect = page.locator('label:has-text("Start month") + select, select:has(option[value="1"])').first();
      if ((await startMonthSelect.count()) > 0) {
        await startMonthSelect.selectOption(String(payload.startMonth));
        await sleep(200);
      }
    }
    if (payload.startYear) {
      const startYearSelect = page.locator('label:has-text("Start year") + select, select:has(option[value="2026"]), select:has(option[value="2025"])').first();
      if ((await startYearSelect.count()) > 0) {
        await startYearSelect.selectOption(String(payload.startYear));
        await sleep(200);
      }
    }

    // 8. End date (在職中でない場合)
    if (!isCurrent) {
      if (payload.endMonth) {
        const endMonthSelect = page.locator('label:has-text("End month") + select').first();
        if ((await endMonthSelect.count()) > 0) {
          await endMonthSelect.selectOption(String(payload.endMonth));
          await sleep(200);
        }
      }
      if (payload.endYear) {
        const endYearSelect = page.locator('label:has-text("End year") + select').first();
        if ((await endYearSelect.count()) > 0) {
          await endYearSelect.selectOption(String(payload.endYear));
          await sleep(200);
        }
      }
    }

    // 9. Description (Highlights)
    if (payload.description) {
      const descBox = page.locator('div[aria-label*="Description"], div.ProseMirror').first();
      if ((await descBox.count()) > 0) {
        await descBox.scrollIntoViewIfNeeded();
        await descBox.click();
        await sleep(300);
        await page.keyboard.press('Control+a');
        await sleep(200);
        await page.keyboard.press('Backspace');
        await sleep(200);
        await page.keyboard.insertText(payload.description);
        await sleep(300);
      }
    }

    // 10. Save ボタンクリック
    const saveBtn = page.locator('button:has-text("Save")').first();
    await saveBtn.scrollIntoViewIfNeeded();
    await saveBtn.click();

    // 保存完了待機
    await page.waitForTimeout(3000);

    // 新規作成されたIDを一覧から特定
    await page.goto(BASE_EXPERIENCE_URL, {
      waitUntil: 'domcontentloaded',
      timeout: 25000,
    });
    await page.waitForTimeout(2000);

    const afterExperiences = await page.evaluate(() => {
      const links = Array.from(document.querySelectorAll('a[href*="/details/experience/edit/forms/"]'));
      const ids = [];
      for (const l of links) {
        const m = (l.getAttribute('href') || '').match(/\/details\/experience\/edit\/forms\/(\d+)/);
        if (m && !ids.includes(m[1])) {
          ids.push(m[1]);
        }
      }
      return ids;
    });

    return {
      success: true,
      message: '職歴を新規作成しました。',
      allIds: afterExperiences,
      createdId: afterExperiences.length > 0 ? afterExperiences[0] : null,
    };
  }

  // --- 3. UPDATE アクション ---
  if (action === 'update') {
    const targetId = payload.id;
    if (!targetId) {
      return { success: false, error: '更新対象の職歴ID（id）が指定されていません。' };
    }

    const editUrl = `https://www.linkedin.com/in/${slug}/details/experience/edit/forms/${targetId}/`;
    await page.goto(editUrl, {
      waitUntil: 'domcontentloaded',
      timeout: 25000,
    });

    const titleInput = page.locator('input[placeholder*="Role title"], input[placeholder*="Example: Senior Product Manager"]').first();
    await titleInput.waitFor({ state: 'visible', timeout: 15000 });

    if (payload.title !== undefined) {
      await titleInput.click();
      await titleInput.fill(payload.title);
      await sleep(300);
    }

    if (payload.company !== undefined) {
      const compInput = page.locator('input[placeholder*="Organization name"], input[placeholder*="Example: Microsoft"]').first();
      await compInput.click();
      await compInput.fill(payload.company);
      await sleep(500);
      await page.keyboard.press('Escape');
      await sleep(300);
    }

    if (payload.employmentType !== undefined) {
      const empSelect = page.locator('label:has-text("Employment type") + select, select:has(option[value="1"])').first();
      if ((await empSelect.count()) > 0) {
        await empSelect.selectOption(String(payload.employmentType));
        await sleep(300);
      }
    }

    if (payload.location !== undefined) {
      const locInput = page.locator('input[placeholder*="City, region, or Remote"], input[placeholder*="City or region"]').first();
      if ((await locInput.count()) > 0) {
        await locInput.click();
        await locInput.fill(payload.location);
        await sleep(500);
        await page.keyboard.press('Escape');
        await sleep(300);
      }
    }

    if (payload.locationType !== undefined) {
      const locTypeSelect = page.locator('label:has-text("Location type") + select, select:has(option[value*="LocationType"])').first();
      if ((await locTypeSelect.count()) > 0) {
        await locTypeSelect.selectOption(String(payload.locationType));
        await sleep(300);
      }
    }

    if (payload.isCurrentlyWorking !== undefined) {
      const curCheckbox = page.locator('input[type="checkbox"]').first();
      const isChecked = await curCheckbox.isChecked();
      if (payload.isCurrentlyWorking && !isChecked) {
        await curCheckbox.click();
        await sleep(300);
      } else if (!payload.isCurrentlyWorking && isChecked) {
        await curCheckbox.click();
        await sleep(500);
      }
    }

    if (payload.startMonth !== undefined) {
      const startMonthSelect = page.locator('label:has-text("Start month") + select, select:has(option[value="1"])').first();
      if ((await startMonthSelect.count()) > 0) {
        await startMonthSelect.selectOption(String(payload.startMonth));
        await sleep(200);
      }
    }
    if (payload.startYear !== undefined) {
      const startYearSelect = page.locator('label:has-text("Start year") + select, select:has(option[value="2026"]), select:has(option[value="2025"])').first();
      if ((await startYearSelect.count()) > 0) {
        await startYearSelect.selectOption(String(payload.startYear));
        await sleep(200);
      }
    }

    if (payload.endMonth !== undefined) {
      const endMonthSelect = page.locator('label:has-text("End month") + select').first();
      if ((await endMonthSelect.count()) > 0) {
        await endMonthSelect.selectOption(String(payload.endMonth));
        await sleep(200);
      }
    }
    if (payload.endYear !== undefined) {
      const endYearSelect = page.locator('label:has-text("End year") + select').first();
      if ((await endYearSelect.count()) > 0) {
        await endYearSelect.selectOption(String(payload.endYear));
        await sleep(200);
      }
    }

    if (payload.description !== undefined) {
      const descBox = page.locator('div[aria-label*="Description"], div.ProseMirror').first();
      if ((await descBox.count()) > 0) {
        await descBox.scrollIntoViewIfNeeded();
        await descBox.click();
        await sleep(300);
        await page.keyboard.press('Control+a');
        await sleep(200);
        await page.keyboard.press('Backspace');
        await sleep(200);
        await page.keyboard.insertText(payload.description);
        await sleep(300);
      }
    }

    const saveBtn = page.locator('button:has-text("Save")').first();
    await saveBtn.scrollIntoViewIfNeeded();
    await saveBtn.click();
    await page.waitForTimeout(3000);

    return {
      success: true,
      id: targetId,
      message: `職歴 (ID: ${targetId}) を更新しました。`,
    };
  }

  // --- 4. DELETE アクション ---
  if (action === 'delete') {
    const targetId = payload.id;
    if (!targetId) {
      return { success: false, error: '削除対象の職歴ID（id）が指定されていません。' };
    }

    const editUrl = `https://www.linkedin.com/in/${slug}/details/experience/edit/forms/${targetId}/`;
    await page.goto(editUrl, {
      waitUntil: 'domcontentloaded',
      timeout: 25000,
    });

    // 1. 初回の削除ボタンを探索してクリック
    const deleteBtn = page.locator('button:has-text("Delete")').first();
    await deleteBtn.waitFor({ state: 'visible', timeout: 15000 });
    await deleteBtn.scrollIntoViewIfNeeded();
    await deleteBtn.click();
    await sleep(1000);

    // 2. 確認モーダル内の確定「Delete」ボタン（No thanksと並ぶ2つ目のDelete）をクリック
    const confirmDeleteBtn = page.locator('button:has-text("Delete")').last();
    await confirmDeleteBtn.waitFor({ state: 'visible', timeout: 10000 });
    await confirmDeleteBtn.click();

    await page.waitForTimeout(3000);

    return {
      success: true,
      id: targetId,
      message: `職歴 (ID: ${targetId}) を削除しました。`,
    };
  }

  return { success: false, error: `未知のアクション: ${action}` };
}
