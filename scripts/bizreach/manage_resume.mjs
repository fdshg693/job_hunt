// scripts/bizreach/manage_resume.mjs
// ビズリーチ WEB履歴書（フリーフォーマット・職務経歴CRUD）の管理・自動化を実行する Playwright スクリプト

async page => {
  const action = '__BIZREACH_ACTION__';
  const payload = __BIZREACH_PAYLOAD__;
  const isDryRun = __BIZREACH_DRY_RUN__;

  const sleep = ms => page.waitForTimeout(ms);

  const cleanMultiline = str =>
    (str || '')
      .replace(/\r?\n/g, '\n')
      .split('\n')
      .map(line => line.trimEnd())
      .join('\n')
      .trim();

  // ダイアログが出た場合は自動で承認
  page.on('dialog', async dialog => {
    try {
      await dialog.accept();
    } catch (_) {}
  });

  try {
    // ==========================================
    // 1. フリーフォーマット取得 (get-freetext)
    // ==========================================
    if (action === 'get-freetext') {
      await page.goto('https://www.bizreach.jp/resume/freetext/', {
        waitUntil: 'domcontentloaded',
        timeout: 30000,
      });
      try {
        await page.waitForSelector('h2, div[class*="FreeTextView"]', { timeout: 15000 });
      } catch (_) {}

      const freetext = await page.evaluate(() => {
        const secEl = document.querySelector('div[class*="FreeTextView"][class*="section"], div[class*="FreeTextView"]');
        if (secEl) {
          return (secEl.innerText || secEl.textContent || '').replace(/\r?\n/g, '\n').trim();
        }
        const h2El = Array.from(document.querySelectorAll('h2')).find(h => (h.textContent || '').includes('フリーフォーマット'));
        if (h2El && h2El.parentElement) {
          const clone = h2El.parentElement.cloneNode(true);
          const h2InClone = clone.querySelector('h2');
          if (h2InClone) h2InClone.remove();
          clone.querySelectorAll('button').forEach(b => b.remove());
          return (clone.innerText || clone.textContent || '').replace(/\r?\n/g, '\n').trim();
        }
        return '';
      });

      return {
        success: true,
        action: 'get-freetext',
        freetext: cleanMultiline(freetext),
      };
    }

    // ==========================================
    // 2. フリーフォーマット更新 (update-freetext)
    // ==========================================
    if (action === 'update-freetext') {
      const newText = payload.text !== undefined ? payload.text : payload.content;
      if (typeof newText !== 'string') {
        return {
          success: false,
          error: '更新テキスト（payload.text）が指定されていません。',
        };
      }

      await page.goto('https://www.bizreach.jp/resume/freetext/edit/', {
        waitUntil: 'domcontentloaded',
        timeout: 30000,
      });

      const textareaSelector = 'textarea.mantine-Textarea-input, main textarea, textarea';
      try {
        await page.waitForSelector(textareaSelector, { timeout: 15000 });
      } catch (e) {
        return {
          success: false,
          error: `テキストエリアが見つかりません: ${e.message}`,
          currentUrl: page.url(),
        };
      }

      const currentText = await page.$eval(textareaSelector, el => el.value || '');

      if (isDryRun) {
        return {
          success: true,
          dryRun: true,
          action: 'update-freetext',
          previousText: cleanMultiline(currentText),
          newText: cleanMultiline(newText),
          lengthDiff: newText.length - currentText.length,
        };
      }

      const textarea = page.locator(textareaSelector).first();
      await textarea.fill(newText);
      await sleep(500);

      const saveButtonSelector = 'button[type="submit"]:has-text("保存"), button:has-text("保存")';
      const saveButton = page.locator(saveButtonSelector).first();
      const isSaveVisible = await saveButton.isVisible().catch(() => false);
      if (!isSaveVisible) {
        return {
          success: false,
          error: '保存ボタンが見つかりません。',
        };
      }

      await Promise.all([
        page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 20000 }).catch(() => null),
        saveButton.click(),
      ]);

      await sleep(2000);
      const finalUrl = page.url();

      let savedText = '';
      if (finalUrl.includes('/resume/freetext/') && !finalUrl.includes('/edit/')) {
        const secEl = await page.$('div[class*="FreeTextView"][class*="section"], div[class*="FreeTextView"]');
        if (secEl) {
          savedText = await secEl.innerText().catch(() => '');
        }
      }

      return {
        success: true,
        dryRun: false,
        action: 'update-freetext',
        previousText: cleanMultiline(currentText),
        newText: cleanMultiline(newText),
        savedText: cleanMultiline(savedText),
        finalUrl,
      };
    }

    // ==========================================
    // 3. フォーム構造確認 (get-career-form)
    // ==========================================
    if (action === 'get-career-form') {
      await page.goto('https://www.bizreach.jp/resume/company/detailEdit/', {
        waitUntil: 'domcontentloaded',
        timeout: 30000,
      });
      try {
        await page.waitForSelector('main, form, input, textarea', { timeout: 15000 });
      } catch (_) {}
      await sleep(1000);

      const formData = await page.evaluate(() => {
        const textareas = Array.from(document.querySelectorAll('textarea')).map((ta, idx) => ({
          index: idx,
          placeholder: ta.getAttribute('placeholder') || '',
          value: ta.value || '',
          name: ta.getAttribute('name') || '',
        }));

        const inputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type])')).map((inp, idx) => ({
          index: idx,
          placeholder: inp.getAttribute('placeholder') || '',
          value: inp.value || '',
          name: inp.getAttribute('name') || '',
        }));

        return {
          textareasCount: textareas.length,
          inputsCount: inputs.length,
          textareas,
          inputs: inputs.slice(0, 20),
        };
      });

      return {
        success: true,
        action: 'get-career-form',
        formData,
      };
    }

    // =========================================================================
    // 職務経歴CRUD共通ヘルパー
    // =========================================================================

    // 詳細編集画面への遷移とレンダリング待機
    async function ensureDetailEditPage() {
      const currentUrl = page.url();
      if (!currentUrl.includes('/resume/company/detailEdit/')) {
        await page.goto('https://www.bizreach.jp/resume/company/detailEdit/', {
          waitUntil: 'domcontentloaded',
          timeout: 30000,
        });
      }
      try {
        await page.waitForSelector('div[class*="CompanyEdit"][class*="root"]', { timeout: 15000 });
      } catch (_) {}
      await sleep(800);
    }

    // フォーム全体のデータ構造をパース
    async function parseCareerData() {
      return await page.evaluate(() => {
        const companyRoots = Array.from(document.querySelectorAll('div[class*="CompanyEdit"][class*="root"]'));
        return companyRoots.map((cRoot, cIdx) => {
          const compNameInp = cRoot.querySelector('input.mantine-Autocomplete-input');
          const companyName = compNameInp ? compNameInp.value || '' : '';

          const deptInp = cRoot.querySelector('input[data-path="departmentName"]');
          const departmentName = deptInp ? deptInp.value || '' : '';

          const periodTr = Array.from(cRoot.querySelectorAll('tr')).find(tr => {
            const th = tr.querySelector('th');
            return th && (th.textContent || '').includes('在籍期間');
          });
          let startYear = '', startMonth = '', endYear = '', endMonth = '', isCurrent = false;
          if (periodTr) {
            const syInp = periodTr.querySelector('input[data-path="startYear"]');
            const smInp = periodTr.querySelector('input[data-path="startMonth"]');
            const eyInp = periodTr.querySelector('input[data-path="endYear"]');
            const emInp = periodTr.querySelector('input[data-path="endMonth"]');
            const chk = periodTr.querySelector('input[type="checkbox"]');

            startYear = syInp ? syInp.value || '' : '';
            startMonth = smInp ? smInp.value || '' : '';
            endYear = eyInp ? eyInp.value || '' : '';
            endMonth = emInp ? emInp.value || '' : '';
            isCurrent = chk ? chk.checked : false;
          }

          const projTrs = Array.from(cRoot.querySelectorAll('tr')).filter(tr => {
            const th = tr.querySelector('th');
            return th && (th.textContent || '').includes('役職・プロジェクト');
          });
          const projects = projTrs.map((pTr, pIdx) => {
            const titleInp = pTr.querySelector('input[data-path="name"]');
            const title = titleInp ? titleInp.value || '' : '';

            const psyInp = pTr.querySelector('input[data-path="startYear"]');
            const psmInp = pTr.querySelector('input[data-path="startMonth"]');
            const peyInp = pTr.querySelector('input[data-path="endYear"]');
            const pemInp = pTr.querySelector('input[data-path="endMonth"]');
            const chk = pTr.querySelector('input[type="checkbox"]');

            const pStartYear = psyInp ? psyInp.value || '' : '';
            const pStartMonth = psmInp ? psmInp.value || '' : '';
            const pEndYear = peyInp ? peyInp.value || '' : '';
            const pEndMonth = pemInp ? pemInp.value || '' : '';
            const pIsCurrent = chk ? chk.checked : false;

            const ta = pTr.querySelector('textarea[data-path*="descriptions"], textarea');
            const description = ta ? ta.value || '' : '';

            const delBtn = pTr.querySelector('button');
            const hasDelBtn = delBtn ? (delBtn.textContent || '').includes('役職・プロジェクトを削除') : false;

            return {
              projectIndex: pIdx,
              title,
              startYear: pStartYear,
              startMonth: pStartMonth,
              endYear: pEndYear,
              endMonth: pEndMonth,
              isCurrent: pIsCurrent,
              description,
              canDelete: hasDelBtn,
            };
          });

          const hasDelCompBtn = Array.from(cRoot.querySelectorAll('button')).some(b => (b.textContent || '').includes('企業を削除'));

          return {
            companyIndex: cIdx,
            companyName,
            departmentName,
            startYear,
            startMonth,
            endYear,
            endMonth,
            isCurrent,
            projects,
            canDelete: hasDelCompBtn,
          };
        });
      });
    }

    // Mantine Selectの選択
    async function selectMantineOption(selectLocator, value) {
      if (value === undefined || value === null) return;
      const targetStr = String(value).trim();
      if (!targetStr) return;

      const isSelectVisible = await selectLocator.isVisible({ timeout: 5000 }).catch(() => false);
      if (!isSelectVisible) return;

      await selectLocator.scrollIntoViewIfNeeded().catch(() => {});
      const currentVal = await selectLocator.inputValue().catch(() => '');
      if (currentVal === targetStr) {
        return;
      }

      await selectLocator.click();
      await sleep(350);

      // 表示されている listbox または options コンテナから option を特定
      const listbox = page.locator('div[role="listbox"]:visible, div.mantine-Select-options:visible').last();
      let optionLocator = listbox.locator('div[role="option"]').filter({
        hasText: new RegExp(`^\\s*${targetStr}\\s*$`),
      }).first();

      let isFound = (await optionLocator.count().catch(() => 0)) > 0;
      if (!isFound) {
        // 全体の option から検索
        optionLocator = page.locator('div[role="option"]').filter({
          hasText: new RegExp(`^\\s*${targetStr}\\s*$`),
        }).first();
        isFound = (await optionLocator.count().catch(() => 0)) > 0;
      }

      if (isFound) {
        await optionLocator.scrollIntoViewIfNeeded().catch(() => {});
        await sleep(100);
        await optionLocator.click({ force: true });
        await sleep(250);
      } else {
        await page.keyboard.press('Escape');
        await sleep(150);
      }
    }

    // 期間入力共通フロー（開始年月選択 -> チェック解除 -> 終了年月選択）
    async function fillPeriod(containerLocator, { startYear, startMonth, endYear, endMonth, isCurrent }, isCompany = false) {
      // 1. 開始年月
      if (startYear) await selectMantineOption(containerLocator.locator('input[data-path="startYear"]').first(), startYear);
      if (startMonth) await selectMantineOption(containerLocator.locator('input[data-path="startMonth"]').first(), startMonth);

      // 2. チェックボックス（在職中 / 継続中）
      // endYear / endMonth が明示されている場合は継続中フラグを確実にオフにする
      let targetCurrent = isCurrent;
      if (targetCurrent === undefined || targetCurrent === null) {
        if (endYear || endMonth) {
          targetCurrent = false;
        }
      }

      const chk = containerLocator.locator('input[type="checkbox"]').first();
      if (targetCurrent !== undefined && targetCurrent !== null) {
        const isChecked = await chk.isChecked();
        if (isChecked !== !!targetCurrent) {
          const labelText = isCompany ? '在職中' : '継続中';
          const label = containerLocator.locator(`label:has-text("${labelText}")`).first();
          if (await label.isVisible().catch(() => false)) {
            await label.click();
          } else {
            await chk.click({ force: true });
          }
          await sleep(300);
        }
      }

      // 3. 終了年月（targetCurrent が false または endYear 指定時）
      if (!targetCurrent) {
        if (endYear) await selectMantineOption(containerLocator.locator('input[data-path="endYear"]').first(), endYear);
        if (endMonth) await selectMantineOption(containerLocator.locator('input[data-path="endMonth"]').first(), endMonth);
      }
    }

    // 企業インデックス解決
    function resolveCompanyIndex(companies, pl) {
      if (pl.companyIndex !== undefined && pl.companyIndex !== null) {
        const idx = Number(pl.companyIndex);
        if (idx >= 0 && idx < companies.length) return idx;
        throw new Error(`企業インデックス ${pl.companyIndex} は範囲外です（登録社数: ${companies.length}）`);
      }
      if (pl.companyName) {
        const q = String(pl.companyName).trim();
        const exactIdx = companies.findIndex(c => c.companyName === q);
        if (exactIdx !== -1) return exactIdx;
        const partialIdx = companies.findIndex(c => c.companyName.includes(q) || q.includes(c.companyName));
        if (partialIdx !== -1) return partialIdx;
        throw new Error(`企業名「${q}」に合致する企業が見つかりません。登録社: ${companies.map(c => c.companyName).join(', ')}`);
      }
      throw new Error('companyIndex または companyName を指定してください。');
    }

    // プロジェクトインデックス解決
    function resolveProjectIndex(projects, pl) {
      if (pl.projectIndex !== undefined && pl.projectIndex !== null) {
        const idx = Number(pl.projectIndex);
        if (idx >= 0 && idx < projects.length) return idx;
        throw new Error(`プロジェクトインデックス ${pl.projectIndex} は範囲外です（全 ${projects.length} 件）`);
      }
      const qTitle = pl.projectTitle || pl.title;
      if (qTitle) {
        const q = String(qTitle).trim();
        const exactIdx = projects.findIndex(p => p.title === q);
        if (exactIdx !== -1) return exactIdx;
        const partialIdx = projects.findIndex(p => p.title.includes(q) || q.includes(p.title));
        if (partialIdx !== -1) return partialIdx;
        throw new Error(`プロジェクト「${q}」に合致するプロジェクトが見つかりません。登録PJ: ${projects.map(p => p.title).join(', ')}`);
      }
      throw new Error('projectIndex または projectTitle を指定してください。');
    }

    // フォーム保存または離脱（dry-run）処理
    async function finishOperation(isDryRun) {
      if (isDryRun) {
        return { saved: false, dryRun: true };
      }

      const saveBtn = page.locator('button[type="submit"]:has-text("保存"), button:has-text("保存")').first();
      await saveBtn.scrollIntoViewIfNeeded().catch(() => {});
      await saveBtn.click();

      try {
        await page.waitForURL('**/resume/company/', { timeout: 20000 });
        return { saved: true, dryRun: false, finalUrl: page.url() };
      } catch (err) {
        const errors = await page.evaluate(() => {
          const errEls = Array.from(document.querySelectorAll('[class*="error"], [role="alert"], [aria-invalid="true"]'));
          return errEls.map(el => (el.textContent || '').trim()).filter(Boolean);
        });
        return {
          saved: false,
          dryRun: false,
          error: errors.length > 0 ? `バリデーションエラー: ${errors.join('; ')}` : `保存後の遷移タイムアウト: ${err.message}`,
          validationErrors: errors,
        };
      }
    }

    // ==========================================
    // 4. 職務経歴データ取得 (get-career)
    // ==========================================
    if (action === 'get-career') {
      await ensureDetailEditPage();
      const companies = await parseCareerData();
      return {
        success: true,
        action: 'get-career',
        companiesCount: companies.length,
        companies,
      };
    }

    // ==========================================
    // 5. 企業追加 (add-company)
    // ==========================================
    if (action === 'add-company') {
      const compName = payload.companyName || payload.name;
      const deptName = payload.departmentName || payload.role;
      const startYear = payload.startYear;
      const startMonth = payload.startMonth;
      const endYear = payload.endYear || null;
      const endMonth = payload.endMonth || null;
      const isCurrent = payload.isCurrent !== undefined ? payload.isCurrent : !endYear;

      if (!compName) return { success: false, error: '企業名 (companyName) は必須です。' };
      if (!deptName) return { success: false, error: '部署・役職名 (departmentName) は必須です。' };
      if (!startYear || !startMonth) return { success: false, error: '入社年月 (startYear, startMonth) は必須です。' };

      await ensureDetailEditPage();
      const initialCompanies = await parseCareerData();

      // 「企業を追加」ボタンをクリック
      const addCompBtn = page.locator('button:has-text("企業を追加")').last();
      await addCompBtn.scrollIntoViewIfNeeded();
      await addCompBtn.click();
      await sleep(600);

      // 追加された末尾の企業ブロックを取得
      const compBlocks = page.locator('div[class*="CompanyEdit"][class*="root"]');
      const newCompBlock = compBlocks.last();
      await newCompBlock.scrollIntoViewIfNeeded();

      // 企業名入力
      const compNameInput = newCompBlock.locator('input.mantine-Autocomplete-input').first();
      await compNameInput.fill(compName);
      await sleep(200);
      await page.keyboard.press('Escape');

      // 部署・役職名入力
      const deptInput = newCompBlock.locator('input[data-path="departmentName"]').first();
      await deptInput.fill(deptName);
      await sleep(150);

      // 在籍期間
      const periodTr = newCompBlock.locator('tr:has(th:has-text("在籍期間"))').first();
      await fillPeriod(periodTr, { startYear, startMonth, endYear, endMonth, isCurrent }, true);

      // 初期プロジェクト（payload.initialProject）が存在する場合に入力
      const initProj = payload.initialProject;
      if (initProj && (initProj.title || initProj.name)) {
        const addProjBtn = newCompBlock.locator('button:has-text("役職・プロジェクトを追加")').first();
        if (await addProjBtn.isVisible().catch(() => false)) {
          await addProjBtn.click();
          await sleep(500);

          const projTr = newCompBlock.locator('tr:has(th:has-text("役職・プロジェクト"))').last();
          await projTr.scrollIntoViewIfNeeded();

          const pTitleInp = projTr.locator('input[data-path="name"]').first();
          await pTitleInp.fill(initProj.title || initProj.name || '');

          const pIsCur = initProj.isCurrent !== undefined ? initProj.isCurrent : !initProj.endYear;
          await fillPeriod(projTr, {
            startYear: initProj.startYear,
            startMonth: initProj.startMonth,
            endYear: initProj.endYear,
            endMonth: initProj.endMonth,
            isCurrent: pIsCur,
          }, false);

          if (initProj.description) {
            const ta = projTr.locator('textarea[data-path*="descriptions"], textarea').first();
            await ta.fill(initProj.description);
          }
        }
      }

      const updatedCompanies = await parseCareerData();
      const finishRes = await finishOperation(isDryRun);

      return {
        success: finishRes.saved || isDryRun,
        action: 'add-company',
        dryRun: isDryRun,
        addedCompany: {
          companyName: compName,
          departmentName: deptName,
          startYear,
          startMonth,
          endYear,
          endMonth,
          isCurrent,
          initialProject: initProj || null,
        },
        previousCompaniesCount: initialCompanies.length,
        newCompaniesCount: updatedCompanies.length,
        finalUrl: finishRes.finalUrl || null,
        error: finishRes.error || null,
      };
    }

    // ==========================================
    // 6. 企業更新 (update-company)
    // ==========================================
    if (action === 'update-company') {
      await ensureDetailEditPage();
      const currentCompanies = await parseCareerData();
      const compIdx = resolveCompanyIndex(currentCompanies, payload);

      const compBlock = page.locator('div[class*="CompanyEdit"][class*="root"]').nth(compIdx);
      await compBlock.scrollIntoViewIfNeeded();
      const beforeComp = currentCompanies[compIdx];

      // 企業名の変更
      const newName = payload.newCompanyName || payload.new_name || (payload.companyName && payload.companyIndex !== undefined ? payload.companyName : null);
      if (newName) {
        const compNameInp = compBlock.locator('input.mantine-Autocomplete-input').first();
        await compNameInp.fill(newName);
        await sleep(200);
        await page.keyboard.press('Escape');
      }

      // 部署・役職名の変更
      const newDept = payload.departmentName || payload.role;
      if (newDept) {
        const deptInput = compBlock.locator('input[data-path="departmentName"]').first();
        await deptInput.fill(newDept);
        await sleep(150);
      }

      // 在籍期間の変更
      const periodTr = compBlock.locator('tr:has(th:has-text("在籍期間"))').first();
      await fillPeriod(periodTr, {
        startYear: payload.startYear,
        startMonth: payload.startMonth,
        endYear: payload.endYear,
        endMonth: payload.endMonth,
        isCurrent: payload.isCurrent,
      }, true);

      const updatedCompanies = await parseCareerData();
      const finishRes = await finishOperation(isDryRun);

      return {
        success: finishRes.saved || isDryRun,
        action: 'update-company',
        dryRun: isDryRun,
        companyIndex: compIdx,
        before: beforeComp,
        after: updatedCompanies[compIdx] || null,
        finalUrl: finishRes.finalUrl || null,
        error: finishRes.error || null,
      };
    }

    // ==========================================
    // 7. 企業削除 (delete-company)
    // ==========================================
    if (action === 'delete-company') {
      await ensureDetailEditPage();
      const currentCompanies = await parseCareerData();
      const compIdx = resolveCompanyIndex(currentCompanies, payload);

      const targetComp = currentCompanies[compIdx];
      if (currentCompanies.length <= 1) {
        return {
          success: false,
          error: '登録企業が1社のみのため、ビズリーチの仕様上企業を削除できません。',
        };
      }

      const delBtn = page.locator('button:has-text("企業を削除")').nth(compIdx);
      if (!(await delBtn.isVisible({ timeout: 5000 }).catch(() => false))) {
        return { success: false, error: `インデックス ${compIdx} の「企業を削除」ボタンが見つかりません。` };
      }

      await delBtn.scrollIntoViewIfNeeded();
      await delBtn.click();
      await sleep(500);

      const updatedCompanies = await parseCareerData();
      const finishRes = await finishOperation(isDryRun);

      return {
        success: finishRes.saved || isDryRun,
        action: 'delete-company',
        dryRun: isDryRun,
        deletedCompany: targetComp,
        previousCompaniesCount: currentCompanies.length,
        newCompaniesCount: updatedCompanies.length,
        finalUrl: finishRes.finalUrl || null,
        error: finishRes.error || null,
      };
    }

    // ==========================================
    // 8. プロジェクト追加 (add-project)
    // ==========================================
    if (action === 'add-project') {
      const pTitle = payload.title || payload.name;
      const pStartYear = payload.startYear;
      const pStartMonth = payload.startMonth;
      const pEndYear = payload.endYear || null;
      const pEndMonth = payload.endMonth || null;
      const pIsCurrent = payload.isCurrent !== undefined ? payload.isCurrent : !pEndYear;
      const pDesc = payload.description || '';

      if (!pTitle) return { success: false, error: 'プロジェクト名 (title) は必須です。' };
      if (!pStartYear || !pStartMonth) return { success: false, error: 'プロジェクト開始年月 (startYear, startMonth) は必須です。' };

      await ensureDetailEditPage();
      const currentCompanies = await parseCareerData();
      const compIdx = resolveCompanyIndex(currentCompanies, payload);

      const compBlock = page.locator('div[class*="CompanyEdit"][class*="root"]').nth(compIdx);
      await compBlock.scrollIntoViewIfNeeded();
      const addProjBtn = compBlock.locator('button:has-text("役職・プロジェクトを追加")').first();
      if (!(await addProjBtn.isVisible().catch(() => false))) {
        return { success: false, error: '「役職・プロジェクトを追加」ボタンが見つかりません。' };
      }

      await addProjBtn.scrollIntoViewIfNeeded();
      await addProjBtn.click();
      await sleep(500);

      // 追加された末尾のプロジェクト行を取得
      const projTrs = compBlock.locator('tr:has(th:has-text("役職・プロジェクト"))');
      const newProjTr = projTrs.last();
      await newProjTr.scrollIntoViewIfNeeded();

      // タイトル入力
      const titleInp = newProjTr.locator('input[data-path="name"]').first();
      await titleInp.fill(pTitle);
      await sleep(150);

      // 期間入力
      await fillPeriod(newProjTr, {
        startYear: pStartYear,
        startMonth: pStartMonth,
        endYear: pEndYear,
        endMonth: pEndMonth,
        isCurrent: pIsCurrent,
      }, false);

      // 業務内容入力
      if (pDesc) {
        const ta = newProjTr.locator('textarea[data-path*="descriptions"], textarea').first();
        await ta.fill(pDesc);
        await sleep(150);
      }

      const updatedCompanies = await parseCareerData();
      const finishRes = await finishOperation(isDryRun);

      return {
        success: finishRes.saved || isDryRun,
        action: 'add-project',
        dryRun: isDryRun,
        companyIndex: compIdx,
        companyName: currentCompanies[compIdx].companyName,
        addedProject: {
          title: pTitle,
          startYear: pStartYear,
          startMonth: pStartMonth,
          endYear: pEndYear,
          endMonth: pEndMonth,
          isCurrent: pIsCurrent,
          description: pDesc,
        },
        previousProjectsCount: currentCompanies[compIdx].projects.length,
        newProjectsCount: updatedCompanies[compIdx] ? updatedCompanies[compIdx].projects.length : 0,
        finalUrl: finishRes.finalUrl || null,
        error: finishRes.error || null,
      };
    }

    // ==========================================
    // 9. プロジェクト更新 (update-project)
    // ==========================================
    if (action === 'update-project') {
      await ensureDetailEditPage();
      const currentCompanies = await parseCareerData();
      const compIdx = resolveCompanyIndex(currentCompanies, payload);
      const projIdx = resolveProjectIndex(currentCompanies[compIdx].projects, payload);

      const compBlock = page.locator('div[class*="CompanyEdit"][class*="root"]').nth(compIdx);
      await compBlock.scrollIntoViewIfNeeded();
      const projTr = compBlock.locator('tr:has(th:has-text("役職・プロジェクト"))').nth(projIdx);
      await projTr.scrollIntoViewIfNeeded();
      const beforeProj = currentCompanies[compIdx].projects[projIdx];

      // タイトル更新
      const newTitle = payload.newTitle || payload.title;
      if (newTitle) {
        const titleInp = projTr.locator('input[data-path="name"]').first();
        await titleInp.fill(newTitle);
        await sleep(150);
      }

      // 期間更新
      await fillPeriod(projTr, {
        startYear: payload.startYear,
        startMonth: payload.startMonth,
        endYear: payload.endYear,
        endMonth: payload.endMonth,
        isCurrent: payload.isCurrent,
      }, false);

      // 業務内容更新
      if (payload.description !== undefined && payload.description !== null) {
        const ta = projTr.locator('textarea[data-path*="descriptions"], textarea').first();
        await ta.fill(payload.description);
        await sleep(150);
      }

      const updatedCompanies = await parseCareerData();
      const finishRes = await finishOperation(isDryRun);

      return {
        success: finishRes.saved || isDryRun,
        action: 'update-project',
        dryRun: isDryRun,
        companyIndex: compIdx,
        projectIndex: projIdx,
        before: beforeProj,
        after: updatedCompanies[compIdx] ? updatedCompanies[compIdx].projects[projIdx] || null : null,
        finalUrl: finishRes.finalUrl || null,
        error: finishRes.error || null,
      };
    }

    // ==========================================
    // 10. プロジェクト削除 (delete-project)
    // ==========================================
    if (action === 'delete-project') {
      await ensureDetailEditPage();
      const currentCompanies = await parseCareerData();
      const compIdx = resolveCompanyIndex(currentCompanies, payload);
      const projIdx = resolveProjectIndex(currentCompanies[compIdx].projects, payload);

      const targetComp = currentCompanies[compIdx];
      const targetProj = targetComp.projects[projIdx];

      if (targetComp.projects.length <= 1) {
        return {
          success: false,
          error: `企業「${targetComp.companyName}」のプロジェクトが1件のみのため、ビズリーチの仕様上削除できません。`,
        };
      }

      const compBlock = page.locator('div[class*="CompanyEdit"][class*="root"]').nth(compIdx);
      await compBlock.scrollIntoViewIfNeeded();
      const projTr = compBlock.locator('tr:has(th:has-text("役職・プロジェクト"))').nth(projIdx);
      await projTr.scrollIntoViewIfNeeded();
      const delBtn = projTr.locator('button:has-text("役職・プロジェクトを削除")').first();

      if (!(await delBtn.isVisible().catch(() => false))) {
        return {
          success: false,
          error: '対象プロジェクト行に「役職・プロジェクトを削除」ボタンが見つかりません。',
        };
      }

      await delBtn.scrollIntoViewIfNeeded();
      await delBtn.click();
      await sleep(400);

      const updatedCompanies = await parseCareerData();
      const finishRes = await finishOperation(isDryRun);

      return {
        success: finishRes.saved || isDryRun,
        action: 'delete-project',
        dryRun: isDryRun,
        companyIndex: compIdx,
        deletedProject: targetProj,
        previousProjectsCount: targetComp.projects.length,
        newProjectsCount: updatedCompanies[compIdx] ? updatedCompanies[compIdx].projects.length : 0,
        finalUrl: finishRes.finalUrl || null,
        error: finishRes.error || null,
      };
    }

    return {
      success: false,
      error: `未知のアクションです: ${action}`,
    };
  } catch (err) {
    return {
      success: false,
      error: `スクリプト実行時例外: ${err.message}`,
      stack: err.stack,
    };
  }
}
