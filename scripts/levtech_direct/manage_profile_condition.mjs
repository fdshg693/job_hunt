// scripts/levtech_direct/manage_profile_condition.mjs
// レバテックダイレクト 希望条件画面（/mypage/profile/condition）DOM操作 Playwright スクリプト
// sharing-browser-with-user スキル準拠

async page => {
  const ACTION = '__LEVTECH_ACTION__';
  const PAYLOAD = __LEVTECH_PAYLOAD__;
  const IS_DRY_RUN = __LEVTECH_DRY_RUN__;

  const TARGET_URL = 'https://levtech-direct.jp/mypage/profile/condition';

  // 1. 現在のページURLを確認し、必要に応じて遷移
  if (!page.url().includes('/mypage/profile/condition')) {
    await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
  }

  // フォーム読み込み待機
  await page.waitForSelector('form', { timeout: 15000 });

  // 補助関数: DOMから現在の入力値・状態を取得する
  async function extractCurrentData() {
    // 1. __NEXT_DATA__ から取得
    let nextCondition = null;
    let globalDefinition = null;
    try {
      const nextDataEl = await page.$('#__NEXT_DATA__');
      if (nextDataEl) {
        const text = await nextDataEl.textContent();
        const parsed = JSON.parse(text);
        nextCondition = parsed?.props?.pageProps?.condition || null;
        globalDefinition = parsed?.props?.pageProps?.globalDefinition || null;
      }
    } catch (_) {}

    // 2. DOMのフォームから現在の入力値を取得
    const domData = await page.evaluate(() => {
      const val = sel => {
        const el = document.querySelector(sel);
        return el ? el.value : '';
      };
      const checked = sel => {
        const el = document.querySelector(sel);
        return el ? el.checked : false;
      };

      // 年収
      const annualIncome = val('input[name="annualIncome"]');

      // 転職希望時期
      const jobChangePeriodEl = document.querySelector('input[name="jobChangePeriod"]:checked');
      const jobChangePeriod = jobChangePeriodEl ? jobChangePeriodEl.value : '';

      // 企業フェーズ・条件
      const businessFormEl = document.querySelector('input[name="jobConditions.businessForm"]:checked');
      const remoteWorkEl = document.querySelector('input[name="jobConditions.remoteWork"]:checked');
      const projectScaleEl = document.querySelector('input[name="jobConditions.projectScale"]:checked');

      // 業務内容への意欲
      const businessKeys = [
        'newBusinessStartUp', 'servicePlanningProposal', 'requirementDefinitionPlanning',
        'pmDirection', 'technologySelectionPromotion', 'architectureDesign',
        'codeQualityStandard', 'developmentFlowEfficiency', 'coding',
        'refactoring', 'performanceTuning', 'bugInvestigation', 'memberTraining'
      ];
      const businesses = {};
      for (const k of businessKeys) {
        const r = document.querySelector(`input[name="businesses.${k}"]:checked`);
        businesses[k] = r ? r.value : '';
      }

      // 技術領域への意欲
      const techDomainKeys = [
        'serverApplication', 'frontApplication', 'smartPhoneApplication',
        'infraMiddleware', 'embeddedControlSystem', 'aiDataAnalysis', 'technologyInvestigation'
      ];
      const technologyDomains = {};
      for (const k of techDomainKeys) {
        const r = document.querySelector(`input[name="technologyDomains.${k}"]:checked`);
        technologyDomains[k] = r ? r.value : '';
      }

      // 雇用形態
      const employmentStatusEls = Array.from(document.querySelectorAll('[data-display-name="DesiredEmploymentStatusSection_Checkbox"] input[type="checkbox"]'));
      const desiredEmploymentStatuses = [];
      const statusLabels = ['regular_employee', 'dispatch_employee', 'contract_employee', 'freelance'];
      employmentStatusEls.forEach((el, idx) => {
        if (el.checked) {
          const valOrKey = el.value !== 'on' ? el.value : (statusLabels[idx] || '');
          if (valOrKey) desiredEmploymentStatuses.push(valOrKey);
        }
      });

      // 稼働頻度
      const minWorkFrequency = val('select[name="minWorkFrequency"]');
      const maxWorkFrequency = val('select[name="maxWorkFrequency"]');

      // こだわり条件
      const workStyleEls = Array.from(document.querySelectorAll('[data-display-name="WorkStyleSection_Checkbox"] input[type="checkbox"]:checked'));
      const workStyles = workStyleEls.map(el => parseInt(el.value, 10)).filter(n => !isNaN(n));

      // 必ず満たしたい条件
      const requiredEls = Array.from(document.querySelectorAll('[data-display-name="RequiredAndOtherConditionSection_Checkbox"] input[type="checkbox"]:checked'));
      const requiredConditions = requiredEls.map(el => el.value);

      // その他希望条件
      const other = val('textarea[name="other"]');

      // 希望職種 (Select要素群)
      const occSelects = Array.from(document.querySelectorAll('[data-display-name="DesiredOccupationField_Select"] select'));
      const occupations = occSelects.map(s => parseInt(s.value, 10)).filter(n => !isNaN(n) && n > 0);

      // 希望スキル (Input要素群)
      const skillInputs = Array.from(document.querySelectorAll('[data-display-name="Autocomplete_AutocompleteInput"] input'));
      const skillNames = skillInputs.map(i => i.value.trim()).filter(Boolean);

      // 希望勤務地 (Select要素群)
      const placeSelects = Array.from(document.querySelectorAll('[data-display-name="DesiredWorkPlacesField_Select"] select'));
      const workPlaces = placeSelects.map(s => s.value).filter(Boolean);

      return {
        annualIncome,
        jobChangePeriod,
        jobConditions: {
          businessForm: businessFormEl ? businessFormEl.value : '',
          remoteWork: remoteWorkEl ? remoteWorkEl.value : '',
          projectScale: projectScaleEl ? projectScaleEl.value : ''
        },
        businesses,
        technologyDomains,
        desiredEmploymentStatuses,
        minWorkFrequency,
        maxWorkFrequency,
        workStyles,
        requiredConditions,
        other,
        occupations,
        skillNames,
        workPlaces
      };
    });

    // 定義マップ
    const gdef = globalDefinition || {};
    const occMap = Object.fromEntries((gdef.occupations || []).map(o => [o.id, o.name]));
    const skillNameMap = Object.fromEntries((gdef.mainSkills || []).map(s => [s.id, s.name]));
    const skillIdMap = Object.fromEntries((gdef.mainSkills || []).map(s => [s.name.toLowerCase(), s.id]));
    const placeMap = Object.fromEntries((gdef.workPlaces || []).map(p => [p.id, p.name]));
    const workStyleMap = Object.fromEntries((gdef.workStyles || []).map(w => [w.id, w.name]));
    const jobChangePeriodMap = Object.fromEntries((gdef.jobChangePeriods || []).map(j => [j.id, j.name]));
    const empStatusMap = Object.fromEntries((gdef.desiredEmploymentStatuses || []).map(e => [e.key, e.name]));
    const reqConditionMap = Object.fromEntries((gdef.employeeRequiredConditions || []).map(r => [r.key, r.name]));

    // スキルIDの補完
    const skills = [];
    for (const name of domData.skillNames) {
      const id = skillIdMap[name.toLowerCase()];
      skills.push({
        id: id || null,
        name
      });
    }

    // 職種表示名補完
    const occupations = domData.occupations.map(id => ({
      id,
      name: occMap[id] || `職種ID: ${id}`
    }));

    // 勤務地表示名補完
    const workPlaces = domData.workPlaces.map(id => ({
      id,
      name: placeMap[id] || id
    }));

    // こだわり条件表示名補完
    const workStyles = domData.workStyles.map(id => ({
      id,
      name: workStyleMap[id] || `条件ID: ${id}`
    }));

    // 雇用形態表示名補完
    const desiredEmploymentStatuses = domData.desiredEmploymentStatuses.map(key => ({
      key,
      name: empStatusMap[key] || key
    }));

    // 必須条件表示名補完
    const requiredConditions = domData.requiredConditions.map(key => ({
      key,
      name: reqConditionMap[key] || key
    }));

    return {
      annualIncome: domData.annualIncome ? parseInt(domData.annualIncome, 10) : (nextCondition?.annualIncome || null),
      jobChangePeriod: domData.jobChangePeriod ? parseInt(domData.jobChangePeriod, 10) : (nextCondition?.jobChangePeriod || null),
      jobChangePeriodLabel: jobChangePeriodMap[domData.jobChangePeriod] || '',
      jobConditions: domData.jobConditions,
      businesses: domData.businesses,
      technologyDomains: domData.technologyDomains,
      workPlaces,
      occupations,
      skills,
      desiredEmploymentStatuses,
      minWorkFrequency: domData.minWorkFrequency,
      maxWorkFrequency: domData.maxWorkFrequency,
      workStyles,
      requiredConditions,
      other: domData.other,
      globalDefinition: {
        occupations: gdef.occupations || [],
        mainSkills: gdef.mainSkills || [],
        workPlaces: gdef.workPlaces || [],
        workStyles: gdef.workStyles || [],
        jobChangePeriods: gdef.jobChangePeriods || [],
        desiredEmploymentStatuses: gdef.desiredEmploymentStatuses || [],
        employeeRequiredConditions: gdef.employeeRequiredConditions || []
      }
    };
  }

  // -------------------------------------------------------------
  // ACTION: fetch
  // -------------------------------------------------------------
  if (ACTION === 'fetch') {
    const data = await extractCurrentData();
    return {
      success: true,
      action: 'fetch',
      data
    };
  }

  // -------------------------------------------------------------
  // ACTION: update
  // -------------------------------------------------------------
  if (ACTION === 'update') {
    const initialData = await extractCurrentData();
    const p = PAYLOAD || {};
    let modifiedCount = 0;

    // ヘルパー: テキスト入力設定
    async function setInput(locator, value) {
      if (value === undefined || value === null) return;
      const count = await locator.count();
      if (count === 0) return;
      const cur = await locator.inputValue();
      const strVal = String(value);
      if (cur !== strVal) {
        await locator.fill(strVal);
        await locator.dispatchEvent('change');
        await locator.dispatchEvent('input');
        modifiedCount++;
      }
    }

    // ヘルパー: セレクトボックス設定
    async function setSelect(locator, value) {
      if (value === undefined || value === null) return;
      const count = await locator.count();
      if (count === 0) return;
      const cur = await locator.inputValue();
      const strVal = String(value);
      if (cur !== strVal) {
        await locator.selectOption(strVal);
        await locator.dispatchEvent('change');
        modifiedCount++;
      }
    }

    // ヘルパー: ラジオボタン設定
    async function setRadio(name, value) {
      if (value === undefined || value === null || value === '') return;
      const loc = page.locator(`input[name="${name}"][value="${value}"]`);
      if (await loc.count() > 0) {
        const isChecked = await loc.isChecked();
        if (!isChecked) {
          await loc.check({ force: true, timeout: 5000 });
          modifiedCount++;
        }
      }
    }

    // 1. 希望年収 (annualIncome)
    if (p.annualIncome !== undefined && p.annualIncome !== null) {
      await setInput(page.locator('input[name="annualIncome"]'), p.annualIncome);
    }

    // 2. 転職希望時期 (jobChangePeriod)
    if (p.jobChangePeriod !== undefined && p.jobChangePeriod !== null) {
      await setRadio('jobChangePeriod', String(p.jobChangePeriod));
    }

    // 3. 企業フェーズ・条件 (jobConditions)
    if (p.jobConditions) {
      if (p.jobConditions.businessForm) await setRadio('jobConditions.businessForm', p.jobConditions.businessForm);
      if (p.jobConditions.remoteWork) await setRadio('jobConditions.remoteWork', p.jobConditions.remoteWork);
      if (p.jobConditions.projectScale) await setRadio('jobConditions.projectScale', p.jobConditions.projectScale);
    }

    // 4. 業務内容への意欲 (businesses)
    if (p.businesses && typeof p.businesses === 'object') {
      for (const [key, val] of Object.entries(p.businesses)) {
        if (val) await setRadio(`businesses.${key}`, val);
      }
    }

    // 5. 技術領域への意欲 (technologyDomains)
    if (p.technologyDomains && typeof p.technologyDomains === 'object') {
      for (const [key, val] of Object.entries(p.technologyDomains)) {
        if (val) await setRadio(`technologyDomains.${key}`, val);
      }
    }

    // 6. 希望勤務地 (workPlaces)
    if (Array.isArray(p.workPlaces)) {
      const targetPlaces = p.workPlaces.map(String);
      const placeSection = page.locator('[data-display-name="DesiredWorkPlaceSection_DesiredWorkPlacesField"]');
      const addPlaceBtn = placeSection.locator('[data-display-name="MultipleConditionField_AddConditionButton"]');
      
      // 現在のセレクト群を取得
      let curCount = await placeSection.locator('[data-display-name="DesiredWorkPlacesField_Select"] select').count();
      
      // 目標行数より多い場合は末尾から削除
      while (curCount > targetPlaces.length && curCount > 1) {
        const removeBtns = placeSection.locator('[data-display-name="MultipleConditionField_RemoveConditionButton"]');
        await removeBtns.last().click();
        await page.waitForTimeout(300);
        curCount = await placeSection.locator('[data-display-name="DesiredWorkPlacesField_Select"] select').count();
        modifiedCount++;
      }

      // 目標行数より少ない場合は追加
      while (curCount < targetPlaces.length) {
        if (await addPlaceBtn.isVisible() && !await addPlaceBtn.isDisabled()) {
          await addPlaceBtn.click();
          await page.waitForTimeout(300);
          curCount = await placeSection.locator('[data-display-name="DesiredWorkPlacesField_Select"] select').count();
          modifiedCount++;
        } else {
          break;
        }
      }

      // 各行の値をセット
      const selects = placeSection.locator('[data-display-name="DesiredWorkPlacesField_Select"] select');
      const total = await selects.count();
      for (let i = 0; i < Math.min(total, targetPlaces.length); i++) {
        await setSelect(selects.nth(i), targetPlaces[i]);
      }
    }

    // 7. 希望職種 (occupations)
    if (Array.isArray(p.occupations)) {
      const targetOccs = p.occupations.map(String);
      const occSection = page.locator('[data-display-name="DesiredOccupationSection_DesiredOccupationField"]');
      const addOccBtn = occSection.locator('[data-display-name="MultipleConditionField_AddConditionButton"]');
      
      let curCount = await occSection.locator('[data-display-name="DesiredOccupationField_Select"] select').count();
      
      while (curCount > targetOccs.length && curCount > 1) {
        const removeBtns = occSection.locator('[data-display-name="MultipleConditionField_RemoveConditionButton"]');
        await removeBtns.last().click();
        await page.waitForTimeout(300);
        curCount = await occSection.locator('[data-display-name="DesiredOccupationField_Select"] select').count();
        modifiedCount++;
      }

      while (curCount < targetOccs.length) {
        if (await addOccBtn.isVisible() && !await addOccBtn.isDisabled()) {
          await addOccBtn.click();
          await page.waitForTimeout(300);
          curCount = await occSection.locator('[data-display-name="DesiredOccupationField_Select"] select').count();
          modifiedCount++;
        } else {
          break;
        }
      }

      const selects = occSection.locator('[data-display-name="DesiredOccupationField_Select"] select');
      const total = await selects.count();
      for (let i = 0; i < Math.min(total, targetOccs.length); i++) {
        await setSelect(selects.nth(i), targetOccs[i]);
      }
    }

    // 8. 希望スキル (skills)
    if (Array.isArray(p.skills)) {
      const targetSkills = p.skills.map(String);
      const skillSection = page.locator('[data-display-name="DesiredSkillSection_DesiredSkillField"]');
      const addSkillBtn = skillSection.locator('[data-display-name="MultipleConditionField_AddConditionButton"]');

      let curCount = await skillSection.locator('[data-display-name="Autocomplete_AutocompleteInput"] input').count();

      // 目標より多い場合は末尾から削除
      while (curCount > targetSkills.length && curCount > 1) {
        const removeBtns = skillSection.locator('[data-display-name="MultipleConditionField_RemoveConditionButton"]');
        await removeBtns.last().click();
        await page.waitForTimeout(300);
        curCount = await skillSection.locator('[data-display-name="Autocomplete_AutocompleteInput"] input').count();
        modifiedCount++;
      }

      // 目標より少ない場合は追加
      while (curCount < targetSkills.length) {
        if (await addSkillBtn.isVisible() && !await addSkillBtn.isDisabled()) {
          await addSkillBtn.click();
          await page.waitForTimeout(300);
          curCount = await skillSection.locator('[data-display-name="Autocomplete_AutocompleteInput"] input').count();
          modifiedCount++;
        } else {
          break;
        }
      }

      // 各行の値をセット
      const inputs = skillSection.locator('[data-display-name="Autocomplete_AutocompleteInput"] input');
      const total = await inputs.count();
      for (let i = 0; i < Math.min(total, targetSkills.length); i++) {
        const targetSkill = targetSkills[i];
        const inputLoc = inputs.nth(i);
        const curVal = await inputLoc.inputValue();
        if (curVal.toLowerCase() !== targetSkill.toLowerCase()) {
          await inputLoc.click();
          await inputLoc.fill(targetSkill);
          await page.waitForTimeout(400);

          // オートコンプリートの候補（Listbox）が表示されたら先頭を選択
          const optionLoc = page.locator('[role="listbox"] [role="option"], ul.MuiAutocomplete-listbox li').first();
          if (await optionLoc.isVisible({ timeout: 1500 }).catch(() => false)) {
            await optionLoc.click();
          } else {
            // ドロップダウンが出ない場合はEnter
            await inputLoc.press('Enter');
          }
          await page.waitForTimeout(300);
          modifiedCount++;
        }
      }
    }

    // 9. 雇用形態 (desiredEmploymentStatuses)
    if (Array.isArray(p.desiredEmploymentStatuses)) {
      const targetStatuses = new Set(p.desiredEmploymentStatuses);
      const checkboxes = await page.locator('[data-display-name="DesiredEmploymentStatusSection_Checkbox"] input[type="checkbox"]').all();
      const statusLabels = ['regular_employee', 'dispatch_employee', 'contract_employee', 'freelance'];
      for (let idx = 0; idx < checkboxes.length; idx++) {
        const cb = checkboxes[idx];
        const key = statusLabels[idx];
        const shouldBeChecked = targetStatuses.has(key) || targetStatuses.has(cb);
        const isChecked = await cb.isChecked();
        if (isChecked !== shouldBeChecked) {
          if (shouldBeChecked) await cb.check({ force: true, timeout: 5000 });
          else await cb.uncheck({ force: true, timeout: 5000 });
          modifiedCount++;
        }
      }
    }

    // 10. 稼働頻度
    if (p.minWorkFrequency !== undefined) {
      await setSelect(page.locator('select[name="minWorkFrequency"]'), p.minWorkFrequency);
    }
    if (p.maxWorkFrequency !== undefined) {
      await setSelect(page.locator('select[name="maxWorkFrequency"]'), p.maxWorkFrequency);
    }

    // 11. こだわり条件 (workStyles)
    if (Array.isArray(p.workStyles)) {
      const targetStyles = new Set(p.workStyles.map(n => parseInt(n, 10)));
      const checkboxes = await page.locator('[data-display-name="WorkStyleSection_Checkbox"] input[type="checkbox"]').all();
      for (const cb of checkboxes) {
        const val = parseInt(await cb.getAttribute('value'), 10);
        const shouldBeChecked = targetStyles.has(val);
        const isChecked = await cb.isChecked();
        if (isChecked !== shouldBeChecked) {
          if (shouldBeChecked) await cb.check({ force: true, timeout: 5000 });
          else await cb.uncheck({ force: true, timeout: 5000 });
          modifiedCount++;
        }
      }
    }

    // 12. 必ず満たしたい条件 (requiredConditions)
    if (Array.isArray(p.requiredConditions)) {
      const targetReqs = new Set(p.requiredConditions);
      const checkboxes = await page.locator('[data-display-name="RequiredAndOtherConditionSection_Checkbox"] input[type="checkbox"]').all();
      for (const cb of checkboxes) {
        const val = await cb.getAttribute('value');
        const shouldBeChecked = targetReqs.has(val);
        const isChecked = await cb.isChecked();
        if (isChecked !== shouldBeChecked) {
          if (shouldBeChecked) await cb.check({ force: true, timeout: 5000 });
          else await cb.uncheck({ force: true, timeout: 5000 });
          modifiedCount++;
        }
      }
    }

    // 13. その他希望条件 (other)
    if (p.other !== undefined && p.other !== null) {
      await setInput(page.locator('textarea[name="other"]'), p.other);
    }

    // 変更後のデータ抽出
    const updatedData = await extractCurrentData();

    // 送信ボタンの状態確認
    const submitBtn = page.locator('button[type="submit"][data-display-name="ProfileDetailLayout_Button"]');
    const isSubmitDisabled = await submitBtn.isDisabled();

    if (IS_DRY_RUN) {
      return {
        success: true,
        action: 'update',
        isDryRun: true,
        modifiedCount,
        canSubmit: !isSubmitDisabled,
        data: updatedData
      };
    }

    // 実際の保存実行
    if (isSubmitDisabled) {
      return {
        success: true,
        action: 'update',
        isDryRun: false,
        noChanges: true,
        message: '変更項目がなかったため保存処理をスキップしました。',
        data: updatedData
      };
    }

    // 保存ボタンクリック
    try {
      await Promise.all([
        submitBtn.click(),
        page.waitForResponse(
          res => res.url().includes('/api/') || res.url().includes('/condition'),
          { timeout: 8000 }
        )
      ]);
    } catch (_) {
      // タイムアウトしても後続チェックを行う
    }

    // バリデーションエラー確認
    const errors = await page.evaluate(() => {
      const errNodes = Array.from(document.querySelectorAll('.Mui-error, [role="alert"]'));
      return errNodes
        .map(e => e.innerText?.trim())
        .filter(t => t && !t.includes('保存'));
    });

    if (errors.length > 0) {
      throw new Error(`保存処理バリデーションエラー: ${errors.join(' / ')}`);
    }

    // 最新状態を再取得
    const finalData = await extractCurrentData();

    return {
      success: true,
      action: 'update',
      isDryRun: false,
      data: finalData
    };
  }

  throw new Error(`未知のアクションです: ${ACTION}`);
}
