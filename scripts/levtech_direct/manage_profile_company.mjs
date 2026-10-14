// scripts/levtech_direct/manage_profile_company.mjs
// レバテックダイレクト 経歴企業画面（/mypage/profile/company）DOM操作 Playwright スクリプト
// sharing-browser-with-user スキル準拠

async page => {
  const ACTION = '__LEVTECH_ACTION__';
  const PAYLOAD = __LEVTECH_PAYLOAD__;
  const IS_DRY_RUN = __LEVTECH_DRY_RUN__;

  const TARGET_URL = 'https://levtech-direct.jp/mypage/profile/company';

  // 1. 現在のページURLを確認し、必要に応じて遷移
  if (!page.url().includes('/mypage/profile/company')) {
    await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
  }

  // アプリ誘導モーダル/Drawerがあれば閉じる
  try {
    const webBtn = await page.$('button[data-display-name="DrawerContainer_Button"]:has-text("Webで続ける")');
    if (webBtn) await webBtn.click();
  } catch (_) {}

  // 画面の主要要素の読み込み待機
  await page.waitForSelector('select#workingStateInput', { timeout: 15000 });

  // 定義マッピング辞書
  const WORKING_STATES_MAP = {
    1: '正社員で就業中',
    6: 'フリーランスで参画中',
    7: '正社員で就業中かつフリーランスで参画中',
    2: '離職中（直近3ヶ月間で退職 or 終了）',
    3: '離職中（直近半年間で退職 or 終了）',
    4: '離職中（直近1年間で退職 or 終了）',
    5: '離職中（直近1年以上前に退職 or 終了）'
  };

  const BUSINESS_STATUSES_MAP = {
    'business_company': '事業会社',
    'client_resident': '客先常駐',
    'in_company_contract': '社内受託'
  };

  const EMPLOYMENT_STATUSES_MAP = {
    1: '正社員',
    2: '契約社員',
    3: '派遣社員',
    4: '業務委託',
    8: '副業',
    5: 'アルバイト',
    6: 'FCオーナー',
    7: '取締役'
  };

  const PROJECT_SCALES_MAP = {
    1: '4人以下',
    2: '5~10人',
    3: '11~20人',
    4: '21~49人',
    5: '50~99人',
    6: '100人以上'
  };

  const JOB_POSITIONS_MAP = {
    1: 'リードエンジニア',
    2: 'リードデザイナー',
    3: 'チームリーダー',
    4: 'マネージャー',
    5: 'エンジニア',
    6: 'デザイナー',
    7: 'ディレクター',
    8: 'その他'
  };

  const PROCESSES_MAP = {
    1: '要件定義',
    2: '仕様設計',
    4: 'DB設計',
    12: 'インフラ構築',
    5: 'コーディング',
    7: 'レビュー',
    8: 'テスト・QA',
    10: '保守運用',
    3: '施策・企画',
    9: 'マネジメント'
  };

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

    // 2. DOMのフォームから現在の入力値を取得
    const domData = await page.evaluate(() => {
      const workingStateEl = document.querySelector('select#workingStateInput');
      const businessStatusEl = document.querySelector('select#businessStatusInput');
      const companyCountEl = document.querySelector('select#companyCountInput');

      const workingStateId = workingStateEl ? workingStateEl.value : '';
      const businessStatusKey = businessStatusEl ? businessStatusEl.value : '';
      const companyCountId = companyCountEl ? companyCountEl.value : '';

      // カード一覧の走査
      const cardContainer = document.querySelector('[data-display-name="ExperiencedCompanyGroupSection_SectionFieldset"]');
      const cards = [];

      if (cardContainer) {
        // カード要素を探索 (カード内の各ブロック)
        const cardElements = Array.from(cardContainer.querySelectorAll('[data-display-name="CompanyCard_StyledIconButton"]'));
        // 2つのボタン（編集・削除）ごとに1企業
        const companyCount = Math.floor(cardElements.length / 2);

        // 各カードのラッパー要素を取得
        for (let i = 0; i < companyCount; i++) {
          const editBtn = cardElements[i * 2];
          // 親のカードコンテナ
          let cardEl = editBtn.parentElement;
          for (let k = 0; k < 6 && cardEl; k++) {
            if (cardEl.parentElement === cardContainer || cardEl.classList.contains('MuiPaper-root') || cardEl.tagName === 'DIV') {
              break;
            }
            cardEl = cardEl.parentElement;
          }

          const rawText = cardEl ? cardEl.textContent.trim().replace(/\s+/g, ' ') : '';
          cards.push({
            index: i,
            rawText
          });
        }
      }

      return {
        workingStateId,
        businessStatusKey,
        companyCountId,
        cards
      };
    });

    // 3. カードテキストおよび __NEXT_DATA__ からの企業詳細構造化
    const companies = [];
    const nextCompanies = nextResume?.companies || [];

    if (nextCompanies.length > 0) {
      // __NEXT_DATA__ に企業データがある場合はそれをベースに整形
      for (const nc of nextCompanies) {
        companies.push({
          id: nc.id,
          companyName: nc.companyName || nc.name || '',
          isBlocked: Boolean(nc.isBlocked),
          enrollments: (nc.enrollmentStatuses || nc.enrollments || []).map(en => ({
            employmentStatusId: en.employmentStatusId,
            employmentStatusName: EMPLOYMENT_STATUSES_MAP[en.employmentStatusId] || '',
            startYear: en.startYear,
            startMonth: en.startMonth,
            endYear: en.endYear,
            endMonth: en.endMonth,
            isCurrent: Boolean(en.isCurrent)
          })),
          projects: (nc.projects || []).map(pj => ({
            id: pj.id,
            name: pj.name || pj.projectName || '',
            startYear: pj.startYear,
            startMonth: pj.startMonth,
            endYear: pj.endYear,
            endMonth: pj.endMonth,
            isCurrent: Boolean(pj.isCurrent),
            scaleId: pj.projectScaleId,
            scaleName: PROJECT_SCALES_MAP[pj.projectScaleId] || '',
            jobPositions: (pj.jobPositions || []).map(jp => jp.name || JOB_POSITIONS_MAP[jp.id] || ''),
            processes: (pj.processes || []).map(pc => pc.name || PROCESSES_MAP[pc.id] || ''),
            description: pj.projectDescription || pj.description || ''
          }))
        });
      }
    } else if (domData.cards.length > 0) {
      // DOMのカードテキストからパース
      for (const card of domData.cards) {
        const text = card.rawText;
        // 例: 株式会社ヘッドウォータース正社員/2025年08月 ～ 現在ブロック企業として登録しました業務効率化ワークフロー...
        // 企業名抽出 (先頭から「正社員」「契約社員」等の雇用形態手前まで)
        let compName = '';
        const empMatch = text.match(/^(.*?)(正社員|契約社員|派遣社員|業務委託|副業|アルバイト|FCオーナー|取締役)/);
        if (empMatch) {
          compName = empMatch[1].trim();
        } else {
          compName = text.split('/')[0].trim();
        }

        const isBlocked = text.includes('ブロック企業');

        // 在籍情報
        const periodMatch = text.match(/(正社員|契約社員|派遣社員|業務委託|副業|アルバイト|FCオーナー|取締役)\/(\d{4}年\d{2}月)\s*～\s*(現在|\d{4}年\d{2}月)/);
        const enrollments = [];
        if (periodMatch) {
          enrollments.push({
            employmentStatusName: periodMatch[1],
            periodText: `${periodMatch[2]} ～ ${periodMatch[3]}`,
            isCurrent: periodMatch[3] === '現在'
          });
        }

        // プロジェクト
        const projects = [];
        // プロジェクト名、業務期間、開発規模、ポジション、担当工程、詳細を簡易抽出
        const projMatch = text.match(/登録しました(.*?)(?:業務期間(.*?))?(?:開発規模(.*?))?(?:ポジション(.*?))?(?:担当工程(.*?))?(?:詳細(.*?))?登録情報/);
        if (projMatch) {
          projects.push({
            name: (projMatch[1] || '').trim(),
            period: (projMatch[2] || '').trim(),
            scale: (projMatch[3] || '').trim(),
            position: (projMatch[4] || '').trim(),
            process: (projMatch[5] || '').trim(),
            description: (projMatch[6] || '').trim()
          });
        }

        companies.push({
          index: card.index,
          companyName: compName,
          isBlocked,
          enrollments,
          projects,
          rawText: text
        });
      }
    }

    const workingStateIdNum = parseInt(domData.workingStateId, 10);
    const companyCountIdNum = parseInt(domData.companyCountId, 10);

    return {
      workingState: {
        id: isNaN(workingStateIdNum) ? null : workingStateIdNum,
        name: WORKING_STATES_MAP[workingStateIdNum] || ''
      },
      currentBusinessStatus: {
        key: domData.businessStatusKey || null,
        name: BUSINESS_STATUSES_MAP[domData.businessStatusKey] || ''
      },
      experiencedCompanyCount: {
        id: isNaN(companyCountIdNum) ? null : companyCountIdNum,
        countText: isNaN(companyCountIdNum) ? '' : `${companyCountIdNum}社${companyCountIdNum >= 10 ? '以上' : ''}`
      },
      companies,
      totalCompanies: companies.length
    };
  }

  // ACTION: fetch
  if (ACTION === 'fetch') {
    const data = await extractCurrentData();
    return {
      success: true,
      action: 'fetch',
      data
    };
  }

  // ACTION: update
  if (ACTION === 'update') {
    const p = PAYLOAD || {};
    let modifiedCount = 0;

    // 1. 就業状況の更新
    if (p.workingStateId !== undefined && p.workingStateId !== null) {
      const stateSelect = page.locator('select#workingStateInput');
      const targetVal = String(p.workingStateId);
      const curVal = await stateSelect.inputValue();
      if (curVal !== targetVal) {
        await stateSelect.selectOption(targetVal);
        await page.waitForTimeout(200);
        modifiedCount++;
      }
    }

    // 2. 現在の業務形態の更新
    if (p.currentBusinessStatus !== undefined && p.currentBusinessStatus !== null) {
      const busSelect = page.locator('select#businessStatusInput');
      const targetVal = String(p.currentBusinessStatus);
      const curVal = await busSelect.inputValue();
      if (curVal !== targetVal) {
        await busSelect.selectOption(targetVal);
        await page.waitForTimeout(200);
        modifiedCount++;
      }
    }

    // 3. 経験企業数の更新
    if (p.experiencedCompanyCountId !== undefined && p.experiencedCompanyCountId !== null) {
      const countSelect = page.locator('select#companyCountInput');
      const targetVal = String(p.experiencedCompanyCountId);
      const curVal = await countSelect.inputValue();
      if (curVal !== targetVal) {
        await countSelect.selectOption(targetVal);
        await page.waitForTimeout(200);
        modifiedCount++;
      }
    }

    // 4. 企業の削除処理 (removeCompany)
    if (p.removeCompany !== undefined && p.removeCompany !== null) {
      const removeTarget = p.removeCompany;
      const cardContainer = page.locator('[data-display-name="ExperiencedCompanyGroupSection_SectionFieldset"]');
      const iconBtns = cardContainer.locator('button[data-display-name="CompanyCard_StyledIconButton"]');
      const btnCount = await iconBtns.count();
      const numCompanies = Math.floor(btnCount / 2);

      let deleteIdx = -1;
      if (typeof removeTarget === 'number') {
        deleteIdx = removeTarget;
      } else {
        // 名前一致で検索
        for (let i = 0; i < numCompanies; i++) {
          const editBtn = iconBtns.nth(i * 2);
          const cardText = await editBtn.locator('xpath=ancestor::*[contains(@class, "MuiPaper-root") or parent::fieldset]').innerText().catch(() => '');
          if (cardText.includes(String(removeTarget))) {
            deleteIdx = i;
            break;
          }
        }
      }

      if (deleteIdx >= 0 && deleteIdx < numCompanies) {
        // 削除ボタン (2番目のボタン) をクリック
        const deleteBtn = iconBtns.nth(deleteIdx * 2 + 1);
        await deleteBtn.click();
        await page.waitForTimeout(500);

        // 削除確認モーダルで「削除する」をクリック
        const confirmDialog = page.locator('[role="dialog"]');
        const confirmBtn = confirmDialog.locator('button:has-text("削除する")');
        await confirmBtn.waitFor({ state: 'visible', timeout: 3000 });
        await confirmBtn.click();
        await page.waitForTimeout(800);
        modifiedCount++;
      }
    }

    // 補助関数: モーダルで企業情報を入力して保存
    async function fillCompanyModal(companyData) {
      const modal = page.locator('[data-display-name="ExperiencedCompanyGroupSection_UpdateExperiencedCompanyModal"]');
      await modal.waitFor({ state: 'visible', timeout: 5000 });

      // 企業名入力 (Autocomplete)
      const compName = companyData.companyName || companyData.name || '';
      if (compName) {
        const compInput = modal.locator('[data-display-name="ExperienceCompanySelector_Autocomplete"] input');
        await compInput.click();
        await compInput.fill(compName);
        await page.waitForTimeout(400);

        const options = page.locator('[role="listbox"] [role="option"], ul.MuiAutocomplete-listbox li');
        const optCount = await options.count().catch(() => 0);
        if (optCount > 0) {
          await options.first().click();
        } else {
          await compInput.press('Enter');
        }
        await page.waitForTimeout(300);
      }

      // ブロック企業チェック
      if (companyData.isBlocked !== undefined) {
        const blockCheckbox = modal.locator('[data-display-name="CompanyNameForm_Checkbox"] input[type="checkbox"]');
        const isChecked = await blockCheckbox.isChecked();
        if (Boolean(companyData.isBlocked) !== isChecked) {
          await blockCheckbox.click();
          await page.waitForTimeout(200);
        }
      }

      // 在籍状況 (雇用形態・期間)
      const enroll = (companyData.enrollments && companyData.enrollments[0]) || companyData;
      if (enroll) {
        // 雇用形態
        const empId = enroll.employmentStatusId || enroll.employmentStatus || 1;
        const empSelect = modal.locator('[data-display-name="EmploymentStatusField_Select"] select');
        await empSelect.selectOption(String(empId));
        await page.waitForTimeout(200);

        // 在籍期間
        const enrollSection = modal.locator('[data-display-name="WorkStateField_EnrollmentPeriodField"]');
        const enrollSelects = enrollSection.locator('[data-display-name="PeriodForm_NumberSelect"] select');

        if (enroll.startYear) await enrollSelects.nth(0).selectOption(String(enroll.startYear));
        if (enroll.startMonth) await enrollSelects.nth(1).selectOption(String(enroll.startMonth));

        const enrollCurrentCheckbox = enrollSection.locator('[data-display-name="PeriodForm_Checkbox"] input[type="checkbox"]');
        const isCurrent = Boolean(enroll.isCurrent || enroll.endYear === null || enroll.endYear === '現在');

        if (isCurrent) {
          if (!await enrollCurrentCheckbox.isChecked()) {
            await enrollCurrentCheckbox.check();
          }
        } else {
          if (await enrollCurrentCheckbox.isChecked()) {
            await enrollCurrentCheckbox.uncheck();
          }
          if (enroll.endYear) await enrollSelects.nth(2).selectOption(String(enroll.endYear));
          if (enroll.endMonth) await enrollSelects.nth(3).selectOption(String(enroll.endMonth));
        }
        await page.waitForTimeout(200);
      }

      // プロジェクト情報
      const projects = companyData.projects || [];
      const proj = projects[0] || companyData.project;
      if (proj) {
        const projSection = modal.locator('[data-display-name="ProjectsSection_ProjectForm"]').first();

        // プロジェクト名
        const pName = proj.name || proj.projectName || '';
        if (pName) {
          const projNameInput = projSection.locator('[data-display-name="ProjectNameField_Input"] input');
          await projNameInput.fill(pName);
        }

        // 業務期間
        const projPeriodSection = projSection.locator('[data-display-name="ProjectPeriodField_PeriodForm"]');
        const projSelects = projPeriodSection.locator('[data-display-name="PeriodForm_NumberSelect"] select');

        if (proj.startYear) await projSelects.nth(0).selectOption(String(proj.startYear));
        if (proj.startMonth) await projSelects.nth(1).selectOption(String(proj.startMonth));

        const projCurrentCheckbox = projPeriodSection.locator('[data-display-name="PeriodForm_Checkbox"] input[type="checkbox"]');
        const isProjCurrent = Boolean(proj.isCurrent || proj.endYear === null || proj.endYear === '現在');

        if (isProjCurrent) {
          if (!await projCurrentCheckbox.isChecked()) {
            await projCurrentCheckbox.check();
          }
        } else {
          if (await projCurrentCheckbox.isChecked()) {
            await projCurrentCheckbox.uncheck();
          }
          if (proj.endYear) await projSelects.nth(2).selectOption(String(proj.endYear));
          if (proj.endMonth) await projSelects.nth(3).selectOption(String(proj.endMonth));
        }

        // 開発規模
        if (proj.scaleId || proj.projectScaleId) {
          const scaleSelect = projSection.locator('[data-display-name="ProjectScaleField_Select"] select');
          await scaleSelect.selectOption(String(proj.scaleId || proj.projectScaleId));
        }

        // ポジション
        if (proj.positionId || proj.jobPositionId) {
          const posSelect = projSection.locator('[data-display-name="JobPositionField_Select"] select');
          await posSelect.selectOption(String(proj.positionId || proj.jobPositionId));
        }

        // 担当工程
        if (proj.processId) {
          const procSelect = projSection.locator('[data-display-name="ProcessField_Select"] select');
          await procSelect.selectOption(String(proj.processId));
        }

        // 詳細 (name属性指定)
        const pDesc = proj.description || proj.projectDescription || '';
        if (pDesc) {
          const descTextarea = projSection.locator('textarea[name*="projectDescription"]');
          await descTextarea.fill(pDesc);
        }
      }

      await page.waitForTimeout(300);

      // モーダルの「入力を完了する」をクリック
      const submitBtn = modal.locator('button[data-display-name="FormModal_Button"]');
      const isSubmitDisabled = await submitBtn.isDisabled();
      if (isSubmitDisabled) {
        throw new Error('モーダル内の必須項目が不足しているため、「入力を完了する」ボタンが非活性です。');
      }
      await submitBtn.click();
      await page.waitForTimeout(800);
      modifiedCount++;
    }

    // 5. 企業の新規追加 (addCompany)
    if (p.addCompany && typeof p.addCompany === 'object') {
      const addBtn = page.locator('button[data-display-name="ExperiencedCompanyGroupSection_ProfileItemAddButton"]');
      await addBtn.click();
      await page.waitForTimeout(800);
      await fillCompanyModal(p.addCompany);
    }

    // 6. 企業一括同期/置換 (companies リスト)
    if (Array.isArray(p.companies) && p.companies.length > 0) {
      // 既存カードの全削除
      const cardContainer = page.locator('[data-display-name="ExperiencedCompanyGroupSection_SectionFieldset"]');
      let iconBtns = cardContainer.locator('button[data-display-name="CompanyCard_StyledIconButton"]');
      let btnCount = await iconBtns.count();

      while (btnCount >= 2) {
        // 最初のカードの削除ボタンをクリック
        const deleteBtn = iconBtns.nth(1);
        await deleteBtn.click();
        await page.waitForTimeout(500);

        const confirmDialog = page.locator('[role="dialog"]');
        const confirmBtn = confirmDialog.locator('button:has-text("削除する")');
        await confirmBtn.waitFor({ state: 'visible', timeout: 3000 });
        await confirmBtn.click();
        await page.waitForTimeout(800);

        iconBtns = cardContainer.locator('button[data-display-name="CompanyCard_StyledIconButton"]');
        btnCount = await iconBtns.count();
        modifiedCount++;
      }

      // 各企業を順番に追加
      for (const comp of p.companies) {
        const addBtn = page.locator('button[data-display-name="ExperiencedCompanyGroupSection_ProfileItemAddButton"]');
        await addBtn.click();
        await page.waitForTimeout(800);
        await fillCompanyModal(comp);
      }
    }

    // 7. 保存ボタンのクリック（ドライランでない場合）
    let saved = false;
    const saveBtn = page.locator('button[type="submit"][data-display-name="ProfileDetailLayout_Button"]');
    const isSaveDisabled = await saveBtn.isDisabled().catch(() => true);

    if (!IS_DRY_RUN && !isSaveDisabled) {
      await saveBtn.click();
      await page.waitForTimeout(2000);
      // 保存完了後のトースト表示やボタン非活性化待機
      await page.waitForLoadState('domcontentloaded');
      saved = true;
    }

    // 最新状態の再取得
    const finalData = await extractCurrentData();

    return {
      success: true,
      action: 'update',
      dryRun: Boolean(IS_DRY_RUN),
      modifiedCount,
      saved,
      data: finalData
    };
  }

  return {
    success: false,
    error: `未知のActionです: ${ACTION}`
  };
}
