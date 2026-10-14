// scripts/levtech_direct/manage_profile_skill.mjs
// レバテックダイレクト 保有スキル画面（/mypage/profile/skill）DOM操作 Playwright スクリプト
// sharing-browser-with-user スキル準拠

async page => {
  const ACTION = '__LEVTECH_ACTION__';
  const PAYLOAD = __LEVTECH_PAYLOAD__;
  const IS_DRY_RUN = __LEVTECH_DRY_RUN__;

  const TARGET_URL = 'https://levtech-direct.jp/mypage/profile/skill';

  // 1. 現在のページURLを確認し、必要に応じて遷移
  if (!page.url().includes('/mypage/profile/skill')) {
    await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
  }

  // スキルセクションの読み込み待機
  await page.waitForSelector('[data-display-name="ExperienceSkillsSection_SectionFieldset"]', { timeout: 15000 });

  // 年数マッピング辞書 (ID -> 表示名)
  const EXPERIENCE_YEARS_MAP = {
    15: '半年未満',
    6: '半年以上',
    7: '1年以上',
    8: '1年半以上',
    9: '2年以上',
    10: '3年以上',
    11: '4年以上',
    12: '5年以上',
    13: '7年以上',
    14: '10年以上'
  };

  const EXPERIENCE_YEARS_NAME_TO_ID = Object.fromEntries(
    Object.entries(EXPERIENCE_YEARS_MAP).map(([id, name]) => [name, parseInt(id, 10)])
  );

  // 年数の表記ゆれ・数値をIDに変換するヘルパー
  function parseYearToId(val) {
    if (val === null || val === undefined || val === '') return null;
    if (typeof val === 'number') {
      if (val < 0.5) return 15;
      if (val < 1.0) return 6;
      if (val < 1.5) return 7;
      if (val < 2.0) return 8;
      if (val < 3.0) return 9;
      if (val < 4.0) return 10;
      if (val < 5.0) return 11;
      if (val < 7.0) return 12;
      if (val < 10.0) return 13;
      return 14;
    }
    const str = String(val).trim();
    if (EXPERIENCE_YEARS_NAME_TO_ID[str]) return EXPERIENCE_YEARS_NAME_TO_ID[str];
    if (EXPERIENCE_YEARS_MAP[str]) return parseInt(str, 10);

    const m = str.match(/([0-9]+(?:\.[0-9]+)?)/);
    if (m) {
      const num = parseFloat(m[1]);
      return parseYearToId(num);
    }
    if (str.includes('半年未満')) return 15;
    if (str.includes('半年')) return 6;
    return null;
  }

  // 補助関数: 現在の画面状態・データを取得する
  async function extractCurrentData() {
    // 1. __NEXT_DATA__ から取得
    let nextResume = null;
    let nextGlobalDef = null;
    try {
      const nextDataEl = await page.$('#__NEXT_DATA__');
      if (nextDataEl) {
        const text = await nextDataEl.textContent();
        const parsed = JSON.parse(text);
        nextResume = parsed?.props?.pageProps?.profilesResume || null;
        nextGlobalDef = parsed?.props?.pageProps?.globalDefinition || null;
      }
    } catch (_) {}

    // 定義マップの構築
    const gdef = nextGlobalDef || {};
    const skillMasterList = gdef.skills || gdef.mainSkills || [];
    const skillNameMap = Object.fromEntries(skillMasterList.map(s => [s.id, s.name]));
    const skillIdMap = Object.fromEntries(skillMasterList.map(s => [s.name.toLowerCase(), s.id]));

    const occList = gdef.occupations || [];
    const occNameMap = Object.fromEntries(occList.map(o => [o.id, o.name]));

    const procList = gdef.processes || [];
    const procNameMap = Object.fromEntries(procList.map(p => [p.id, p.name]));

    const mgmtList = gdef.managementScales || [];
    const mgmtNameMap = Object.fromEntries(mgmtList.map(m => [m.id, m.name]));

    // 2. DOMのフォームから現在の入力値を取得
    const domData = await page.evaluate(() => {
      const skillSection = document.querySelector('[data-display-name="ExperienceSkillsSection_SectionFieldset"]');
      const rows = [];
      if (skillSection) {
        const inputEls = Array.from(skillSection.querySelectorAll('input[placeholder="経験スキルを選択"]'));
        const selectEls = Array.from(skillSection.querySelectorAll('[data-display-name="ExperienceSkillsSection_Select"] select'));
        for (let i = 0; i < inputEls.length; i++) {
          const inp = inputEls[i];
          const sel = selectEls[i];
          rows.push({
            name: inp ? inp.value.trim() : '',
            experienceYearId: sel ? parseInt(sel.value, 10) || null : null,
            experienceYearText: sel && sel.selectedIndex >= 0 ? sel.options[sel.selectedIndex]?.text : ''
          });
        }
      }

      // 現在の職種
      const curOccEl = document.querySelector('select#currentOccupationsInput, select[name="currentOccupations.0"]');
      const curOccId = curOccEl ? parseInt(curOccEl.value, 10) || null : null;
      const curOccText = curOccEl && curOccEl.selectedIndex >= 0 ? curOccEl.options[curOccEl.selectedIndex]?.text : '';

      // マネジメント規模
      const mgmtEl = document.querySelector('select#managementScalesInput, select[name="managementScale"]');
      const mgmtId = mgmtEl ? parseInt(mgmtEl.value, 10) || null : null;
      const mgmtText = mgmtEl && mgmtEl.selectedIndex >= 0 ? mgmtEl.options[mgmtEl.selectedIndex]?.text : '';

      // 保存ボタン状態
      const submitBtn = document.querySelector('button[type="submit"][data-display-name="ProfileDetailLayout_Button"]');

      return {
        domSkills: rows,
        currentOccupation: { id: curOccId, name: curOccText },
        managementScale: { id: mgmtId, name: mgmtText },
        isSubmitDisabled: submitBtn ? submitBtn.disabled : true
      };
    });

    // スキルリストの正規化（DOMの入力値をベースにしつつIDを補完）
    const enrichedSkills = domData.domSkills.map(row => {
      const matchedId = skillIdMap[row.name.toLowerCase()] || null;
      const yearName = EXPERIENCE_YEARS_MAP[row.experienceYearId] || row.experienceYearText || '';
      return {
        id: matchedId,
        name: row.name,
        experienceYearId: row.experienceYearId,
        experienceYears: yearName
      };
    });

    // 経験職種
    const occupations = (nextResume?.occupations || []).map(o => ({
      id: o.id,
      name: occNameMap[o.id] || `職種ID: ${o.id}`,
      experienceYearId: o.experienceYearId,
      experienceYears: EXPERIENCE_YEARS_MAP[o.experienceYearId] || ''
    }));

    // 経験担当工程
    const processes = (nextResume?.processes || []).map(p => ({
      id: p.id,
      name: procNameMap[p.id] || `工程ID: ${p.id}`,
      experienceYearId: p.experienceYearId,
      experienceYears: EXPERIENCE_YEARS_MAP[p.experienceYearId] || ''
    }));

    return {
      skills: enrichedSkills,
      currentOccupation: {
        id: domData.currentOccupation.id || (nextResume?.currentOccupations?.[0] || null),
        name: domData.currentOccupation.name || (occNameMap[nextResume?.currentOccupations?.[0]] || '')
      },
      managementScale: {
        id: domData.managementScale.id || (nextResume?.managementScale || null),
        name: domData.managementScale.name || (mgmtNameMap[nextResume?.managementScale] || '')
      },
      occupations,
      processes,
      rawResume: nextResume,
      isSubmitDisabled: domData.isSubmitDisabled
    };
  }

  // --- アクション分岐 ---

  if (ACTION === 'fetch') {
    const data = await extractCurrentData();
    return {
      success: true,
      action: 'fetch',
      data
    };
  }

  if (ACTION === 'update') {
    const p = PAYLOAD || {};
    let modifiedCount = 0;

    // スキルセクション
    const skillSection = page.locator('[data-display-name="ExperienceSkillsSection_SectionFieldset"]');
    const addSkillBtn = skillSection.locator('button[data-display-name="MultipleConditionField_AddConditionButton"]');

    // 1. スキルの更新・追加・削除
    if (Array.isArray(p.skills)) {
      const targetSkills = p.skills.map(s => {
        if (typeof s === 'string') {
          return { name: s, yearId: 9 }; // デフォルト2年以上
        }
        const yearId = parseYearToId(s.experienceYears || s.experienceYearId || s.years) || 9;
        return {
          name: s.name || s.skillName || '',
          yearId
        };
      }).filter(s => Boolean(s.name.trim()));

      let curInputs = skillSection.locator('input[placeholder="経験スキルを選択"]');
      let curCount = await curInputs.count();

      // 目標より多い場合は末尾から行を削除
      while (curCount > targetSkills.length && curCount > 0) {
        const removeBtns = skillSection.locator('button[data-display-name="MultipleConditionField_RemoveConditionButton"]');
        const count = await removeBtns.count();
        if (count === 0) break;
        await removeBtns.last().click();
        await page.waitForTimeout(300);
        curCount = await skillSection.locator('input[placeholder="経験スキルを選択"]').count();
        modifiedCount++;
      }

      // 目標より少ない場合は「追加する」ボタンを押して行を増やす
      while (curCount < targetSkills.length) {
        if (await addSkillBtn.isVisible() && !await addSkillBtn.isDisabled()) {
          await addSkillBtn.click();
          await page.waitForTimeout(300);
          curCount = await skillSection.locator('input[placeholder="経験スキルを選択"]').count();
          modifiedCount++;
        } else {
          break;
        }
      }

      // 各行に目標のスキル名と年数をセット
      const rowInputs = skillSection.locator('input[placeholder="経験スキルを選択"]');
      const rowSelects = skillSection.locator('[data-display-name="ExperienceSkillsSection_Select"] select');
      const totalRows = await rowInputs.count();

      for (let i = 0; i < Math.min(totalRows, targetSkills.length); i++) {
        const target = targetSkills[i];
        const inputLoc = rowInputs.nth(i);
        const selectLoc = rowSelects.nth(i);

        const currentVal = (await inputLoc.inputValue()).trim();
        if (currentVal.toLowerCase() !== target.name.toLowerCase()) {
          await inputLoc.click();
          await inputLoc.fill(target.name);
          await page.waitForTimeout(400);

          // オートコンプリートの候補（Listbox）が表示されたら一致するものを探す
          const options = page.locator('[role="listbox"] [role="option"], ul.MuiAutocomplete-listbox li');
          const optCount = await options.count().catch(() => 0);
          let matched = false;
          for (let j = 0; j < optCount; j++) {
            const optText = (await options.nth(j).innerText()).trim();
            if (optText.toLowerCase() === target.name.toLowerCase()) {
              await options.nth(j).click();
              matched = true;
              break;
            }
          }
          if (!matched) {
            if (optCount > 0) {
              await options.first().click();
            } else {
              await inputLoc.press('Enter');
            }
          }
          await page.waitForTimeout(300);
          modifiedCount++;
        }

        // 経験年数のセット
        if (target.yearId) {
          const curYearVal = await selectLoc.inputValue();
          if (curYearVal !== String(target.yearId)) {
            await selectLoc.selectOption(String(target.yearId));
            await page.waitForTimeout(200);
            modifiedCount++;
          }
        }
      }
    }

    // 2. 現在の職種 (currentOccupation)
    if (p.currentOccupation !== undefined && p.currentOccupation !== null) {
      const curOccEl = page.locator('select#currentOccupationsInput, select[name="currentOccupations.0"]');
      if (await curOccEl.isVisible()) {
        const targetOccId = String(p.currentOccupation);
        const curOccVal = await curOccEl.inputValue();
        if (curOccVal !== targetOccId) {
          await curOccEl.selectOption(targetOccId);
          await page.waitForTimeout(200);
          modifiedCount++;
        }
      }
    }

    // 3. マネジメント規模 (managementScale)
    if (p.managementScale !== undefined && p.managementScale !== null) {
      const mgmtEl = page.locator('select#managementScalesInput, select[name="managementScale"]');
      if (await mgmtEl.isVisible()) {
        const targetMgmtId = String(p.managementScale);
        const curMgmtVal = await mgmtEl.inputValue();
        if (curMgmtVal !== targetMgmtId) {
          await mgmtEl.selectOption(targetMgmtId);
          await page.waitForTimeout(200);
          modifiedCount++;
        }
      }
    }

    // 保存ボタンの状態確認
    const submitBtn = page.locator('button[type="submit"][data-display-name="ProfileDetailLayout_Button"]');
    const isSubmitDisabled = await submitBtn.isDisabled();

    // ドライラン判定
    if (IS_DRY_RUN) {
      const previewData = await extractCurrentData();
      return {
        success: true,
        action: 'update',
        isDryRun: true,
        modifiedCount,
        isSubmitDisabled,
        data: previewData
      };
    }

    // 保存ボタンが非活性（変更なし）の場合
    if (isSubmitDisabled) {
      const currentData = await extractCurrentData();
      return {
        success: true,
        action: 'update',
        isDryRun: false,
        modifiedCount: 0,
        message: '変更がありませんでした。',
        data: currentData
      };
    }

    // 保存実行
    await submitBtn.click();
    await page.waitForTimeout(1000);

    // バリデーションエラー確認
    const errors = await page.evaluate(() => {
      const errNodes = Array.from(document.querySelectorAll('.Mui-error, [role="alert"]'));
      return errNodes
        .map(e => e.innerText?.trim())
        .filter(t => t && !t.includes('保存') && !t.includes('完了') && !t.includes('更新'));
    });

    if (errors.length > 0) {
      throw new Error(`保存処理バリデーションエラー: ${errors.join(' / ')}`);
    }

    // トーストまたはボタンの再disabled待機
    await page.waitForTimeout(1500);

    const finalData = await extractCurrentData();
    return {
      success: true,
      action: 'update',
      isDryRun: false,
      modifiedCount,
      data: finalData
    };
  }

  throw new Error(`未知のアクションです: ${ACTION}`);
}
