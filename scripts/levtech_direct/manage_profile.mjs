// scripts/levtech_direct/manage_profile.mjs
// レバテックダイレクト 統合プロファイル管理 Playwright スクリプト
// 基本情報(basic)、経歴企業(company)、職務経歴(resume)、希望条件(condition)、保有スキル(skill)のDOM操作を統合
// sharing-browser-with-user スキル準拠

async page => {
  const SECTION = '__LEVTECH_SECTION__'; // 'basic' | 'company' | 'resume' | 'condition' | 'skill'
  const ACTION = '__LEVTECH_ACTION__';   // 'fetch' | 'update'
  const PAYLOAD = __LEVTECH_PAYLOAD__;
  const IS_DRY_RUN = __LEVTECH_DRY_RUN__;

  const SECTION_URLS = {
    basic: 'https://levtech-direct.jp/mypage/profile/basic',
    company: 'https://levtech-direct.jp/mypage/profile/company',
    resume: 'https://levtech-direct.jp/mypage/profile/resume',
    condition: 'https://levtech-direct.jp/mypage/profile/condition',
    skill: 'https://levtech-direct.jp/mypage/profile/skill'
  };

  const targetUrl = SECTION_URLS[SECTION];
  if (!targetUrl) {
    throw new Error(`未知のセクションです: ${SECTION}`);
  }

  // 1. URL遷移
  if (!page.url().includes(new URL(targetUrl).pathname)) {
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  }

  // アプリ誘導モーダル/Drawerがあれば閉じる
  try {
    const webBtn = await page.$('button[data-display-name="DrawerContainer_Button"]:has-text("Webで続ける")');
    if (webBtn) await webBtn.click();
  } catch (_) {}

  // ---------------------------------------------------------------------------
  // 1. BASIC (基本情報)
  // ---------------------------------------------------------------------------
  if (SECTION === 'basic') {
    await page.waitForSelector('form', { timeout: 15000 });

    const PREFECTURE_MAP = {
      1: '東京都', 2: '神奈川県', 3: '千葉県', 4: '埼玉県', 5: '茨城県', 6: '群馬県', 7: '栃木県',
      8: '北海道', 9: '青森県', 10: '岩手県', 11: '宮城県', 12: '秋田県', 13: '山形県', 14: '福島県',
      15: '新潟県', 16: '富山県', 17: '石川県', 18: '福井県', 19: '山梨県', 20: '長野県', 21: '愛知県',
      22: '岐阜県', 23: '静岡県', 24: '三重県', 25: '大阪府', 26: '兵庫県', 27: '京都府', 28: '滋賀県',
      29: '奈良県', 30: '和歌山県', 31: '鳥取県', 32: '島根県', 33: '岡山県', 34: '広島県', 35: '山口県',
      36: '徳島県', 37: '香川県', 38: '愛媛県', 39: '高知県', 40: '福岡県', 41: '佐賀県', 42: '長崎県',
      43: '熊本県', 44: '大分県', 45: '宮崎県', 46: '鹿児島県', 47: '沖縄県', 48: '海外'
    };

    const PREFECTURE_NAME_TO_ID = Object.fromEntries(
      Object.entries(PREFECTURE_MAP).map(([id, name]) => [name, parseInt(id, 10)])
    );

    const SCHOOL_CATEGORY_MAP = {
      1: '大学', 2: '大学院', 3: '短大', 4: '専門学校', 5: 'その他'
    };

    const SCHOOL_CATEGORY_NAME_TO_ID = Object.fromEntries(
      Object.entries(SCHOOL_CATEGORY_MAP).map(([id, name]) => [name, parseInt(id, 10)])
    );

    const GENDER_MAP = { 1: '男性', 2: '女性', 3: '無回答' };
    const NATIVE_LANGUAGE_MAP = {
      1: '日本語', 2: '英語', 3: 'フランス語', 4: 'ドイツ語', 5: 'ロシア語',
      6: '中国語', 7: '韓国語', 8: 'イタリア語', 9: 'ポルトガル語', 10: 'スペイン語'
    };

    async function extractBasicData() {
      let nextBasics = null;
      try {
        const nextDataEl = await page.$('#__NEXT_DATA__');
        if (nextDataEl) {
          const text = await nextDataEl.textContent();
          const parsed = JSON.parse(text);
          nextBasics = parsed?.props?.pageProps?.profilesBasics || null;
        }
      } catch (_) {}

      const domData = await page.evaluate(() => {
        const val = sel => {
          const el = document.querySelector(sel);
          return el ? el.value : '';
        };
        const checked = sel => {
          const el = document.querySelector(sel);
          return el ? el.checked : false;
        };

        const genderEl = document.querySelector('input[name="base.gender"]:checked');
        const marriedEl = document.querySelector('input[name="base.isMarried"]:checked');

        const postalCode = val('div#address input[placeholder="1234567"]');
        const prefectureId = val('div#address select');
        const address = val('div#address input[placeholder="以降の住所を入力"]');

        const schoolCategorySelects = document.querySelectorAll('#schoolCategoryDetail select');
        const schoolCategoryId = schoolCategorySelects.length > 0 ? schoolCategorySelects[0].value : '';
        const schoolName = val('div#schoolCategoryDetail input[placeholder="学校名を入力"]');
        const facultyDepartment = val('div#schoolCategoryDetail input[placeholder="学部/学科/専攻を入力"]');
        const gradYear = schoolCategorySelects.length > 1 ? schoolCategorySelects[1].value : '';
        const gradMonth = schoolCategorySelects.length > 2 ? schoolCategorySelects[2].value : '';
        const educationalOther = val('textarea[name="educational.other"]');

        const phoneNumber = val('div#phoneNumber input[type="tel"]');
        const isAcceptedCallByHeadhunter = checked('div#phoneNumber input[type="checkbox"]');

        const langSelects = document.querySelectorAll('#languages select');
        const lang1Id = langSelects.length > 0 ? langSelects[0].value : '';
        const lang1Level = langSelects.length > 1 ? langSelects[1].value : '';

        const schoolAttendanceExperience = val('div#schoolAttendanceExperience select');
        const schoolAttendancePeriod = val('div#schoolAttendancePeriod select');

        return {
          lastName: val('input[name="base.lastName"]'),
          firstName: val('input[name="base.firstName"]'),
          kanaLastName: val('input[name="base.kanaLastName"]'),
          kanaFirstName: val('input[name="base.kanaFirstName"]'),
          birthdayYear: val('select[name="base.birthday.year"]'),
          birthdayMonth: val('select[name="base.birthday.month"]'),
          birthdayDay: val('select[name="base.birthday.day"]'),
          gender: genderEl ? genderEl.value : '',
          phoneNumber,
          isAcceptedCallByHeadhunter,
          postalCode,
          prefectureId,
          address,
          isMarried: marriedEl ? marriedEl.value : '',
          currentAnnualIncome: val('input[name="base.currentAnnualIncome"]'),
          schoolCategoryId,
          schoolName,
          facultyDepartment,
          graduationYear: gradYear,
          graduationMonth: gradMonth,
          educationalOther,
          nativeLanguageId: val('select[name="base.nativeLanguageId"]'),
          otherLanguage1Id: lang1Id,
          otherLanguage1Level: lang1Level,
          toeic: val('input[name="base.toeic"]'),
          toefl: val('input[name="base.toefl"]'),
          certification: val('textarea#certificationInput'),
          schoolAttendanceExperience,
          schoolAttendancePeriod,
        };
      });

      const base = nextBasics?.base || {};
      const edu = nextBasics?.educational || {};

      const prefId = domData.prefectureId || String(base.prefectureId || '');
      const schoolCatId = domData.schoolCategoryId || String(edu.schoolCategoryId || '');
      const genderVal = domData.gender || String(base.gender || '');
      const nativeLangId = domData.nativeLanguageId || String(base.nativeLanguageId || '');

      let bYear = domData.birthdayYear;
      let bMonth = domData.birthdayMonth;
      let bDay = domData.birthdayDay;
      if ((!bYear || !bMonth || !bDay) && base.birthday) {
        const parts = base.birthday.split('-');
        if (parts.length === 3) {
          bYear = bYear || parts[0];
          bMonth = bMonth || String(parseInt(parts[1], 10));
          bDay = bDay || String(parseInt(parts[2], 10));
        }
      }

      return {
        displayId: base.displayId || '',
        lastName: domData.lastName || base.lastName || '',
        firstName: domData.firstName || base.firstName || '',
        kanaLastName: domData.kanaLastName || base.kanaLastName || '',
        kanaFirstName: domData.kanaFirstName || base.kanaFirstName || '',
        birthday: bYear && bMonth && bDay ? `${bYear}-${String(bMonth).padStart(2, '0')}-${String(bDay).padStart(2, '0')}` : (base.birthday || ''),
        birthdayYear: bYear ? parseInt(bYear, 10) : null,
        birthdayMonth: bMonth ? parseInt(bMonth, 10) : null,
        birthdayDay: bDay ? parseInt(bDay, 10) : null,
        gender: genderVal ? parseInt(genderVal, 10) : null,
        genderLabel: GENDER_MAP[genderVal] || '',
        phoneNumber: domData.phoneNumber || base.phoneNumber || '',
        isAcceptedCallByHeadhunter: domData.isAcceptedCallByHeadhunter,
        postalCode: domData.postalCode || base.postalCode || '',
        prefectureId: prefId ? parseInt(prefId, 10) : null,
        prefectureName: PREFECTURE_MAP[prefId] || '',
        address: domData.address || base.address || '',
        isMarried: domData.isMarried !== '' ? domData.isMarried === '1' : (base.isMarried !== '' ? base.isMarried === 1 : null),
        currentAnnualIncome: domData.currentAnnualIncome ? parseInt(domData.currentAnnualIncome, 10) : (base.currentAnnualIncome || null),
        education: {
          schoolCategoryId: schoolCatId ? parseInt(schoolCatId, 10) : null,
          schoolCategoryName: SCHOOL_CATEGORY_MAP[schoolCatId] || '',
          schoolName: domData.schoolName || edu.schoolName || '',
          facultyDepartment: domData.facultyDepartment || edu.facultyDepartment || '',
          graduationYear: domData.graduationYear ? parseInt(domData.graduationYear, 10) : null,
          graduationMonth: domData.graduationMonth ? parseInt(domData.graduationMonth, 10) : null,
          graduationDate: domData.graduationYear && domData.graduationMonth ? `${domData.graduationYear}-${String(domData.graduationMonth).padStart(2, '0')}` : (edu.graduationDate || ''),
          other: domData.educationalOther || edu.other || ''
        },
        language: {
          nativeLanguageId: nativeLangId ? parseInt(nativeLangId, 10) : null,
          nativeLanguageName: NATIVE_LANGUAGE_MAP[nativeLangId] || '',
          toeic: domData.toeic ? parseInt(domData.toeic, 10) : (base.toeic ? parseInt(base.toeic, 10) : null),
          toefl: domData.toefl ? parseInt(domData.toefl, 10) : (base.toefl ? parseInt(base.toefl, 10) : null),
        },
        certification: domData.certification || base.certification || '',
        schoolAttendance: {
          experience: domData.schoolAttendanceExperience || base.schoolAttendanceExperience || '',
          period: domData.schoolAttendancePeriod || base.schoolAttendancePeriod || ''
        }
      };
    }

    if (ACTION === 'fetch') {
      const data = await extractBasicData();
      return { success: true, section: 'basic', action: 'fetch', url: page.url(), data };
    }

    if (ACTION === 'update') {
      const p = PAYLOAD || {};
      let modifiedCount = 0;

      async function setInput(locator, value) {
        if (value === undefined || value === null) return;
        if (await locator.count() > 0) {
          await locator.fill(String(value));
          await locator.blur();
          modifiedCount++;
        }
      }

      async function setSelect(locator, value) {
        if (value === undefined || value === null || value === '') return;
        if (await locator.count() > 0) {
          const valStr = String(value);
          try {
            await locator.selectOption(valStr);
          } catch (_) {
            try {
              await locator.selectOption({ label: valStr });
            } catch (_) {}
          }
          await locator.blur();
          modifiedCount++;
        }
      }

      await setInput(page.locator('input[name="base.lastName"]'), p.lastName);
      await setInput(page.locator('input[name="base.firstName"]'), p.firstName);
      await setInput(page.locator('input[name="base.kanaLastName"]'), p.kanaLastName);
      await setInput(page.locator('input[name="base.kanaFirstName"]'), p.kanaFirstName);

      if (p.birthday) {
        const parts = String(p.birthday).split('-');
        if (parts.length === 3) {
          p.birthdayYear = parseInt(parts[0], 10);
          p.birthdayMonth = parseInt(parts[1], 10);
          p.birthdayDay = parseInt(parts[2], 10);
        }
      }
      await setSelect(page.locator('select[name="base.birthday.year"]'), p.birthdayYear);
      await setSelect(page.locator('select[name="base.birthday.month"]'), p.birthdayMonth);
      await setSelect(page.locator('select[name="base.birthday.day"]'), p.birthdayDay);

      if (p.gender !== undefined && p.gender !== null) {
        const loc = page.locator(`input[name="base.gender"][value="${p.gender}"]`);
        if (await loc.count() > 0) {
          await loc.check();
          modifiedCount++;
        }
      }

      await setInput(page.locator('div#phoneNumber input[type="tel"]'), p.phoneNumber);

      if (p.isAcceptedCallByHeadhunter !== undefined && p.isAcceptedCallByHeadhunter !== null) {
        const loc = page.locator('div#phoneNumber input[type="checkbox"]');
        if (await loc.count() > 0) {
          const isChecked = await loc.isChecked();
          if (isChecked !== Boolean(p.isAcceptedCallByHeadhunter)) {
            await loc.setChecked(Boolean(p.isAcceptedCallByHeadhunter));
            modifiedCount++;
          }
        }
      }

      await setInput(page.locator('div#address input[placeholder="1234567"]'), p.postalCode);
      let prefValue = p.prefectureId;
      if (typeof prefValue === 'string' && PREFECTURE_NAME_TO_ID[prefValue]) {
        prefValue = PREFECTURE_NAME_TO_ID[prefValue];
      }
      await setSelect(page.locator('div#address select'), prefValue);
      await setInput(page.locator('div#address input[placeholder="以降の住所を入力"]'), p.address);

      if (p.isMarried !== undefined && p.isMarried !== null) {
        const val = p.isMarried === true || p.isMarried === 1 || p.isMarried === '1' ? '1' : '0';
        const loc = page.locator(`input[name="base.isMarried"][value="${val}"]`);
        if (await loc.count() > 0) {
          await loc.check();
          modifiedCount++;
        }
      }

      await setInput(page.locator('input[name="base.currentAnnualIncome"]'), p.currentAnnualIncome);

      const edu = p.education || p;
      let schoolCatVal = edu.schoolCategoryId;
      if (typeof schoolCatVal === 'string' && SCHOOL_CATEGORY_NAME_TO_ID[schoolCatVal]) {
        schoolCatVal = SCHOOL_CATEGORY_NAME_TO_ID[schoolCatVal];
      }
      await setSelect(page.locator('#schoolCategoryDetail select').nth(0), schoolCatVal);
      await setInput(page.locator('div#schoolCategoryDetail input[placeholder="学校名を入力"]'), edu.schoolName);
      await setInput(page.locator('div#schoolCategoryDetail input[placeholder="学部/学科/専攻を入力"]'), edu.facultyDepartment);
      await setSelect(page.locator('#schoolCategoryDetail select').nth(1), edu.graduationYear);
      await setSelect(page.locator('#schoolCategoryDetail select').nth(2), edu.graduationMonth);
      await setInput(page.locator('textarea[name="educational.other"]'), edu.educationalOther || edu.other);

      const lang = p.language || p;
      await setSelect(page.locator('select[name="base.nativeLanguageId"]'), lang.nativeLanguageId);
      await setInput(page.locator('input[name="base.toeic"]'), lang.toeic);
      await setInput(page.locator('input[name="base.toefl"]'), lang.toefl);
      await setInput(page.locator('textarea#certificationInput'), p.certification);

      const school = p.schoolAttendance || p;
      await setSelect(page.locator('div#schoolAttendanceExperience select'), school.schoolAttendanceExperience || school.experience);
      await setSelect(page.locator('div#schoolAttendancePeriod select'), school.schoolAttendancePeriod || school.period);

      const updatedData = await extractBasicData();
      const submitBtn = page.locator('button[type="submit"][data-display-name="ProfileDetailLayout_Button"]');
      const isSubmitDisabled = await submitBtn.isDisabled();

      if (IS_DRY_RUN) {
        return {
          success: true,
          section: 'basic',
          action: 'update',
          isDryRun: true,
          modifiedCount,
          canSubmit: !isSubmitDisabled,
          data: updatedData
        };
      }

      if (isSubmitDisabled) {
        return {
          success: true,
          section: 'basic',
          action: 'update',
          isDryRun: false,
          noChanges: true,
          message: '変更項目がなかったため保存処理をスキップしました。',
          data: updatedData
        };
      }

      await submitBtn.click();
      try {
        await Promise.race([
          page.waitForSelector('.MuiAlert-root, [role="alert"]', { timeout: 8000 }),
          page.waitForFunction(btn => btn.disabled, await submitBtn.elementHandle(), { timeout: 8000 })
        ]);
      } catch (_) {}

      const errors = await page.evaluate(() => {
        const errNodes = Array.from(document.querySelectorAll('.Mui-error, [role="alert"]'));
        return errNodes.map(e => e.innerText?.trim()).filter(t => t && !t.includes('保存'));
      });
      if (errors.length > 0) {
        throw new Error(`保存処理バリデーションエラー: ${errors.join(' / ')}`);
      }

      const finalData = await extractBasicData();
      return { success: true, section: 'basic', action: 'update', isDryRun: false, data: finalData };
    }
  }

  // ---------------------------------------------------------------------------
  // 2. COMPANY (経歴企業)
  // ---------------------------------------------------------------------------
  if (SECTION === 'company') {
    await page.waitForSelector('select#workingStateInput', { timeout: 15000 });

    const WORKING_STATES_MAP = {
      1: '正社員で就業中', 6: 'フリーランスで参画中', 7: '正社員で就業中かつフリーランスで参画中',
      2: '離職中（直近3ヶ月間で退職 or 終了）', 3: '離職中（直近半年間で退職 or 終了）',
      4: '離職中（直近1年間で退職 or 終了）', 5: '離職中（直近1年以上前に退職 or 終了）'
    };
    const BUSINESS_STATUSES_MAP = {
      'business_company': '事業会社', 'client_resident': '客先常駐', 'in_company_contract': '社内受託'
    };
    const EMPLOYMENT_STATUSES_MAP = {
      1: '正社員', 2: '契約社員', 3: '派遣社員', 4: '業務委託', 8: '副業', 5: 'アルバイト', 6: 'FCオーナー', 7: '取締役'
    };
    const PROJECT_SCALES_MAP = {
      1: '4人以下', 2: '5~10人', 3: '11~20人', 4: '21~49人', 5: '50~99人', 6: '100人以上'
    };
    const JOB_POSITIONS_MAP = {
      1: 'リードエンジニア', 2: 'リードデザイナー', 3: 'チームリーダー', 4: 'マネージャー',
      5: 'エンジニア', 6: 'デザイナー', 7: 'ディレクター', 8: 'その他'
    };
    const PROCESSES_MAP = {
      1: '要件定義', 2: '仕様設計', 4: 'DB設計', 12: 'インフラ構築', 5: 'コーディング',
      7: 'レビュー', 8: 'テスト・QA', 10: '保守運用', 3: '施策・企画', 9: 'マネジメント'
    };

    async function extractCompanyData() {
      let nextResume = null;
      try {
        const nextDataEl = await page.$('#__NEXT_DATA__');
        if (nextDataEl) {
          const text = await nextDataEl.textContent();
          const parsed = JSON.parse(text);
          nextResume = parsed?.props?.pageProps?.profilesResume || null;
        }
      } catch (_) {}

      const domData = await page.evaluate(() => {
        const workingStateEl = document.querySelector('select#workingStateInput');
        const businessStatusEl = document.querySelector('select#businessStatusInput');
        const companyCountEl = document.querySelector('select#companyCountInput');

        const cardContainer = document.querySelector('[data-display-name="ExperiencedCompanyGroupSection_SectionFieldset"]');
        const cards = [];
        if (cardContainer) {
          const cardElements = Array.from(cardContainer.querySelectorAll('[data-display-name="CompanyCard_StyledIconButton"]'));
          const companyCount = Math.floor(cardElements.length / 2);
          for (let i = 0; i < companyCount; i++) {
            const editBtn = cardElements[i * 2];
            let cardEl = editBtn.parentElement;
            for (let k = 0; k < 6 && cardEl; k++) {
              if (cardEl.parentElement === cardContainer || cardEl.classList.contains('MuiPaper-root') || cardEl.tagName === 'DIV') break;
              cardEl = cardEl.parentElement;
            }
            cards.push({ index: i, rawText: cardEl ? cardEl.textContent.trim().replace(/\s+/g, ' ') : '' });
          }
        }

        return {
          workingStateId: workingStateEl ? workingStateEl.value : '',
          businessStatusKey: businessStatusEl ? businessStatusEl.value : '',
          companyCountId: companyCountEl ? companyCountEl.value : '',
          cards
        };
      });

      const companies = [];
      const nextCompanies = nextResume?.companies || [];
      if (nextCompanies.length > 0) {
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
        for (const card of domData.cards) {
          const text = card.rawText;
          let compName = '';
          const empMatch = text.match(/^(.*?)(正社員|契約社員|派遣社員|業務委託|副業|アルバイト|FCオーナー|取締役)/);
          compName = empMatch ? empMatch[1].trim() : text.split('/')[0].trim();
          const isBlocked = text.includes('ブロック企業');

          const periodMatch = text.match(/(正社員|契約社員|派遣社員|業務委託|副業|アルバイト|FCオーナー|取締役)\/(\d{4}年\d{2}月)\s*～\s*(現在|\d{4}年\d{2}月)/);
          const enrollments = [];
          if (periodMatch) {
            enrollments.push({
              employmentStatusName: periodMatch[1],
              periodText: `${periodMatch[2]} ～ ${periodMatch[3]}`,
              isCurrent: periodMatch[3] === '現在'
            });
          }

          companies.push({ index: card.index, companyName: compName, isBlocked, enrollments, rawText: text });
        }
      }

      const workingStateIdNum = parseInt(domData.workingStateId, 10);
      const companyCountIdNum = parseInt(domData.companyCountId, 10);

      return {
        workingState: { id: isNaN(workingStateIdNum) ? null : workingStateIdNum, name: WORKING_STATES_MAP[workingStateIdNum] || '' },
        currentBusinessStatus: { key: domData.businessStatusKey || null, name: BUSINESS_STATUSES_MAP[domData.businessStatusKey] || '' },
        experiencedCompanyCount: { id: isNaN(companyCountIdNum) ? null : companyCountIdNum, countText: isNaN(companyCountIdNum) ? '' : `${companyCountIdNum}社${companyCountIdNum >= 10 ? '以上' : ''}` },
        companies,
        totalCompanies: companies.length
      };
    }

    if (ACTION === 'fetch') {
      const data = await extractCompanyData();
      return { success: true, section: 'company', action: 'fetch', data };
    }

    if (ACTION === 'update') {
      const p = PAYLOAD || {};
      let modifiedCount = 0;

      if (p.workingStateId !== undefined && p.workingStateId !== null) {
        const stateSelect = page.locator('select#workingStateInput');
        const targetVal = String(p.workingStateId);
        if (await stateSelect.inputValue() !== targetVal) {
          await stateSelect.selectOption(targetVal);
          await page.waitForTimeout(200);
          modifiedCount++;
        }
      }

      if (p.currentBusinessStatus !== undefined && p.currentBusinessStatus !== null) {
        const busSelect = page.locator('select#businessStatusInput');
        const targetVal = String(p.currentBusinessStatus);
        if (await busSelect.inputValue() !== targetVal) {
          await busSelect.selectOption(targetVal);
          await page.waitForTimeout(200);
          modifiedCount++;
        }
      }

      if (p.experiencedCompanyCountId !== undefined && p.experiencedCompanyCountId !== null) {
        const countSelect = page.locator('select#companyCountInput');
        const targetVal = String(p.experiencedCompanyCountId);
        if (await countSelect.inputValue() !== targetVal) {
          await countSelect.selectOption(targetVal);
          await page.waitForTimeout(200);
          modifiedCount++;
        }
      }

      if (p.removeCompany !== undefined && p.removeCompany !== null) {
        const removeTarget = p.removeCompany;
        const cardContainer = page.locator('[data-display-name="ExperiencedCompanyGroupSection_SectionFieldset"]');
        const iconBtns = cardContainer.locator('button[data-display-name="CompanyCard_StyledIconButton"]');
        const numCompanies = Math.floor(await iconBtns.count() / 2);

        let deleteIdx = -1;
        if (typeof removeTarget === 'number') {
          deleteIdx = removeTarget;
        } else {
          for (let i = 0; i < numCompanies; i++) {
            const cardText = await iconBtns.nth(i * 2).locator('xpath=ancestor::*[contains(@class, "MuiPaper-root") or parent::fieldset]').innerText().catch(() => '');
            if (cardText.includes(String(removeTarget))) {
              deleteIdx = i;
              break;
            }
          }
        }

        if (deleteIdx >= 0 && deleteIdx < numCompanies) {
          await iconBtns.nth(deleteIdx * 2 + 1).click();
          await page.waitForTimeout(500);
          const confirmBtn = page.locator('[role="dialog"] button:has-text("削除する")');
          await confirmBtn.waitFor({ state: 'visible', timeout: 3000 });
          await confirmBtn.click();
          await page.waitForTimeout(800);
          modifiedCount++;
        }
      }

      async function fillCompanyModal(companyData) {
        const modal = page.locator('[data-display-name="ExperiencedCompanyGroupSection_UpdateExperiencedCompanyModal"]');
        await modal.waitFor({ state: 'visible', timeout: 5000 });

        const compName = companyData.companyName || companyData.name || '';
        if (compName) {
          const compInput = modal.locator('[data-display-name="ExperienceCompanySelector_Autocomplete"] input');
          await compInput.click();
          await compInput.fill(compName);
          await page.waitForTimeout(400);

          const options = page.locator('[role="listbox"] [role="option"], ul.MuiAutocomplete-listbox li');
          if (await options.count().catch(() => 0) > 0) {
            await options.first().click();
          } else {
            await compInput.press('Enter');
          }
          await page.waitForTimeout(300);
        }

        if (companyData.isBlocked !== undefined) {
          const blockCheckbox = modal.locator('[data-display-name="CompanyNameForm_Checkbox"] input[type="checkbox"]');
          if (Boolean(companyData.isBlocked) !== await blockCheckbox.isChecked()) {
            await blockCheckbox.click();
            await page.waitForTimeout(200);
          }
        }

        const enroll = (companyData.enrollments && companyData.enrollments[0]) || companyData;
        if (enroll) {
          const empId = enroll.employmentStatusId || enroll.employmentStatus || 1;
          await modal.locator('[data-display-name="EmploymentStatusField_Select"] select').selectOption(String(empId));
          await page.waitForTimeout(200);

          const enrollSection = modal.locator('[data-display-name="WorkStateField_EnrollmentPeriodField"]');
          const enrollSelects = enrollSection.locator('[data-display-name="PeriodForm_NumberSelect"] select');
          if (enroll.startYear) await enrollSelects.nth(0).selectOption(String(enroll.startYear));
          if (enroll.startMonth) await enrollSelects.nth(1).selectOption(String(enroll.startMonth));

          const enrollCurrentCheckbox = enrollSection.locator('[data-display-name="PeriodForm_Checkbox"] input[type="checkbox"]');
          const isCurrent = Boolean(enroll.isCurrent || enroll.endYear === null || enroll.endYear === '現在');
          if (isCurrent) {
            if (!await enrollCurrentCheckbox.isChecked()) await enrollCurrentCheckbox.check();
          } else {
            if (await enrollCurrentCheckbox.isChecked()) await enrollCurrentCheckbox.uncheck();
            if (enroll.endYear) await enrollSelects.nth(2).selectOption(String(enroll.endYear));
            if (enroll.endMonth) await enrollSelects.nth(3).selectOption(String(enroll.endMonth));
          }
          await page.waitForTimeout(200);
        }

        const projects = companyData.projects || [];
        const proj = projects[0] || companyData.project;
        if (proj) {
          const projSection = modal.locator('[data-display-name="ProjectsSection_ProjectForm"]').first();
          const pName = proj.name || proj.projectName || '';
          if (pName) {
            await projSection.locator('[data-display-name="ProjectNameField_Input"] input').fill(pName);
          }

          const projPeriodSection = projSection.locator('[data-display-name="ProjectPeriodField_PeriodForm"]');
          const projSelects = projPeriodSection.locator('[data-display-name="PeriodForm_NumberSelect"] select');
          if (proj.startYear) await projSelects.nth(0).selectOption(String(proj.startYear));
          if (proj.startMonth) await projSelects.nth(1).selectOption(String(proj.startMonth));

          const projCurrentCheckbox = projPeriodSection.locator('[data-display-name="PeriodForm_Checkbox"] input[type="checkbox"]');
          const isProjCurrent = Boolean(proj.isCurrent || proj.endYear === null || proj.endYear === '現在');
          if (isProjCurrent) {
            if (!await projCurrentCheckbox.isChecked()) await projCurrentCheckbox.check();
          } else {
            if (await projCurrentCheckbox.isChecked()) await projCurrentCheckbox.uncheck();
            if (proj.endYear) await projSelects.nth(2).selectOption(String(proj.endYear));
            if (proj.endMonth) await projSelects.nth(3).selectOption(String(proj.endMonth));
          }

          if (proj.scaleId || proj.projectScaleId) {
            await projSection.locator('[data-display-name="ProjectScaleField_Select"] select').selectOption(String(proj.scaleId || proj.projectScaleId));
          }
          if (proj.positionId || proj.jobPositionId) {
            await projSection.locator('[data-display-name="JobPositionField_Select"] select').selectOption(String(proj.positionId || proj.jobPositionId));
          }
          if (proj.processId) {
            await projSection.locator('[data-display-name="ProcessField_Select"] select').selectOption(String(proj.processId));
          }
          const pDesc = proj.description || proj.projectDescription || '';
          if (pDesc) {
            await projSection.locator('textarea[name*="projectDescription"]').fill(pDesc);
          }
        }

        await page.waitForTimeout(300);
        const submitBtn = modal.locator('button[data-display-name="FormModal_Button"]');
        if (await submitBtn.isDisabled()) {
          throw new Error('モーダル内の必須項目が不足しているため、「入力を完了する」ボタンが非活性です。');
        }
        await submitBtn.click();
        await page.waitForTimeout(800);
        modifiedCount++;
      }

      if (p.addCompany && typeof p.addCompany === 'object') {
        const addBtn = page.locator('button[data-display-name="ExperiencedCompanyGroupSection_ProfileItemAddButton"]');
        await addBtn.click();
        await page.waitForTimeout(800);
        await fillCompanyModal(p.addCompany);
      }

      if (Array.isArray(p.companies) && p.companies.length > 0) {
        const cardContainer = page.locator('[data-display-name="ExperiencedCompanyGroupSection_SectionFieldset"]');
        let iconBtns = cardContainer.locator('button[data-display-name="CompanyCard_StyledIconButton"]');
        let btnCount = await iconBtns.count();

        while (btnCount >= 2) {
          await iconBtns.nth(1).click();
          await page.waitForTimeout(500);
          const confirmBtn = page.locator('[role="dialog"] button:has-text("削除する")');
          await confirmBtn.waitFor({ state: 'visible', timeout: 3000 });
          await confirmBtn.click();
          await page.waitForTimeout(800);
          iconBtns = cardContainer.locator('button[data-display-name="CompanyCard_StyledIconButton"]');
          btnCount = await iconBtns.count();
          modifiedCount++;
        }

        for (const comp of p.companies) {
          const addBtn = page.locator('button[data-display-name="ExperiencedCompanyGroupSection_ProfileItemAddButton"]');
          await addBtn.click();
          await page.waitForTimeout(800);
          await fillCompanyModal(comp);
        }
      }

      let saved = false;
      const saveBtn = page.locator('button[type="submit"][data-display-name="ProfileDetailLayout_Button"]');
      const isSaveDisabled = await saveBtn.isDisabled().catch(() => true);

      if (!IS_DRY_RUN && !isSaveDisabled) {
        await saveBtn.click();
        await page.waitForTimeout(2000);
        await page.waitForLoadState('domcontentloaded');
        saved = true;
      }

      const finalData = await extractCompanyData();
      return { success: true, section: 'company', action: 'update', dryRun: Boolean(IS_DRY_RUN), modifiedCount, saved, data: finalData };
    }
  }

  // ---------------------------------------------------------------------------
  // 3. RESUME (職務経歴・自己PR)
  // ---------------------------------------------------------------------------
  if (SECTION === 'resume') {
    await page.waitForSelector('textarea[name="resume"]', { timeout: 15000 });

    async function extractResumeData() {
      let nextResume = null;
      try {
        const nextDataEl = await page.$('#__NEXT_DATA__');
        if (nextDataEl) {
          const text = await nextDataEl.textContent();
          const parsed = JSON.parse(text);
          nextResume = parsed?.props?.pageProps?.profilesResume?.base?.resume || '';
        }
      } catch (_) {}

      const domData = await page.evaluate(() => {
        const textarea = document.querySelector('textarea[name="resume"]');
        const val = textarea ? textarea.value : '';
        let counterText = '';
        let updatedAtText = '';
        const spans = Array.from(document.querySelectorAll('span, p'));
        for (const el of spans) {
          const t = el.innerText || '';
          if (/\d+\s*\/\s*[\d,]+文字/.test(t) && !counterText) counterText = t.trim();
          if ((t.includes('最終更新：') || t.includes('最終更新:')) && !updatedAtText) {
            updatedAtText = t.replace(/最終更新[：:]/, '').trim();
          }
        }
        return { resume: val, charCount: val.length, counterText, updatedAtText };
      });

      const finalResume = domData.resume !== undefined && domData.resume !== '' ? domData.resume : (nextResume || '');
      return {
        resume: finalResume,
        charCount: finalResume.length,
        maxCharCount: 30000,
        counterText: domData.counterText || `${finalResume.length.toLocaleString()}/30,000文字`,
        updatedAtText: domData.updatedAtText || ''
      };
    }

    if (ACTION === 'fetch') {
      const data = await extractResumeData();
      return { success: true, section: 'resume', action: 'fetch', url: page.url(), data };
    }

    if (ACTION === 'update') {
      const p = PAYLOAD || {};
      const newResume = typeof p.resume === 'string' ? p.resume : '';

      if (newResume.length < 10) {
        throw new Error(`職務経歴・自己PRの文字数が不足しています（${newResume.length}文字 < 最小10文字）`);
      }
      if (newResume.length > 30000) {
        throw new Error(`職務経歴・自己PRの文字数が上限を超えています（${newResume.length}文字 > 上限30,000文字）`);
      }

      const textarea = page.locator('textarea[name="resume"]');
      const submitBtn = page.locator('button[type="submit"][data-display-name="ProfileDetailLayout_Button"]');

      const curData = await extractResumeData();
      const isSame = curData.resume === newResume;
      let modified = false;

      if (!isSame) {
        await textarea.fill(newResume);
        await textarea.dispatchEvent('input');
        await textarea.dispatchEvent('change');
        await page.waitForTimeout(400);
        modified = true;
      }

      const updatedData = await extractResumeData();
      const isSubmitDisabled = await submitBtn.isDisabled();

      if (IS_DRY_RUN) {
        if (modified) {
          await textarea.fill(curData.resume);
          await textarea.dispatchEvent('input');
          await textarea.dispatchEvent('change');
          await page.waitForTimeout(300);
        }
        return {
          success: true,
          section: 'resume',
          action: 'update',
          isDryRun: true,
          modified,
          canSubmit: !isSubmitDisabled,
          previousResume: curData.resume,
          data: updatedData
        };
      }

      if (isSame || isSubmitDisabled) {
        return {
          success: true,
          section: 'resume',
          action: 'update',
          isDryRun: false,
          noChanges: true,
          message: '既存の内容と同一のため保存処理をスキップしました。',
          data: updatedData
        };
      }

      try {
        await Promise.all([
          submitBtn.click(),
          page.waitForResponse(
            res => res.url().includes('/api/') || res.url().includes('/resume') || res.url().includes('/mypage'),
            { timeout: 8000 }
          ).catch(() => null)
        ]);
      } catch (_) {}

      try {
        await Promise.race([
          page.waitForSelector('.MuiAlert-root, [role="alert"]', { timeout: 6000 }),
          page.waitForFunction(btn => btn.disabled, await submitBtn.elementHandle(), { timeout: 6000 })
        ]);
      } catch (_) {}

      const errors = await page.evaluate(() => {
        const errNodes = Array.from(document.querySelectorAll('.Mui-error, [role="alert"]'));
        return errNodes.map(e => e.innerText?.trim()).filter(t => t && !t.includes('保存') && !t.includes('完了') && !t.includes('更新'));
      });
      if (errors.length > 0) {
        throw new Error(`保存処理バリデーションエラー: ${errors.join(' / ')}`);
      }

      await page.waitForTimeout(1000);
      const finalData = await extractResumeData();
      return { success: true, section: 'resume', action: 'update', isDryRun: false, data: finalData };
    }
  }

  // ---------------------------------------------------------------------------
  // 4. CONDITION (希望条件)
  // ---------------------------------------------------------------------------
  if (SECTION === 'condition') {
    await page.waitForSelector('form', { timeout: 15000 });

    async function extractConditionData() {
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

      const domData = await page.evaluate(() => {
        const val = sel => {
          const el = document.querySelector(sel);
          return el ? el.value : '';
        };

        const annualIncome = val('input[name="annualIncome"]');
        const jobChangePeriodEl = document.querySelector('input[name="jobChangePeriod"]:checked');
        const jobChangePeriod = jobChangePeriodEl ? jobChangePeriodEl.value : '';

        const businessFormEl = document.querySelector('input[name="jobConditions.businessForm"]:checked');
        const remoteWorkEl = document.querySelector('input[name="jobConditions.remoteWork"]:checked');
        const projectScaleEl = document.querySelector('input[name="jobConditions.projectScale"]:checked');

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

        const techDomainKeys = [
          'serverApplication', 'frontApplication', 'smartPhoneApplication',
          'infraMiddleware', 'embeddedControlSystem', 'aiDataAnalysis', 'technologyInvestigation'
        ];
        const technologyDomains = {};
        for (const k of techDomainKeys) {
          const r = document.querySelector(`input[name="technologyDomains.${k}"]:checked`);
          technologyDomains[k] = r ? r.value : '';
        }

        const employmentStatusEls = Array.from(document.querySelectorAll('[data-display-name="DesiredEmploymentStatusSection_Checkbox"] input[type="checkbox"]'));
        const desiredEmploymentStatuses = [];
        const statusLabels = ['regular_employee', 'dispatch_employee', 'contract_employee', 'freelance'];
        employmentStatusEls.forEach((el, idx) => {
          if (el.checked) {
            const valOrKey = el.value !== 'on' ? el.value : (statusLabels[idx] || '');
            if (valOrKey) desiredEmploymentStatuses.push(valOrKey);
          }
        });

        const minWorkFrequency = val('select[name="minWorkFrequency"]');
        const maxWorkFrequency = val('select[name="maxWorkFrequency"]');

        const workStyleEls = Array.from(document.querySelectorAll('[data-display-name="WorkStyleSection_Checkbox"] input[type="checkbox"]:checked'));
        const workStyles = workStyleEls.map(el => parseInt(el.value, 10)).filter(n => !isNaN(n));

        const requiredEls = Array.from(document.querySelectorAll('[data-display-name="RequiredAndOtherConditionSection_Checkbox"] input[type="checkbox"]:checked'));
        const requiredConditions = requiredEls.map(el => el.value);

        const other = val('textarea[name="other"]');

        const occSelects = Array.from(document.querySelectorAll('[data-display-name="DesiredOccupationField_Select"] select'));
        const occupations = occSelects.map(s => parseInt(s.value, 10)).filter(n => !isNaN(n) && n > 0);

        const skillInputs = Array.from(document.querySelectorAll('[data-display-name="Autocomplete_AutocompleteInput"] input'));
        const skillNames = skillInputs.map(i => i.value.trim()).filter(Boolean);

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

      const gdef = globalDefinition || {};
      const occMap = Object.fromEntries((gdef.occupations || []).map(o => [o.id, o.name]));
      const skillIdMap = Object.fromEntries((gdef.mainSkills || []).map(s => [s.name.toLowerCase(), s.id]));
      const placeMap = Object.fromEntries((gdef.workPlaces || []).map(p => [p.id, p.name]));
      const workStyleMap = Object.fromEntries((gdef.workStyles || []).map(w => [w.id, w.name]));
      const jobChangePeriodMap = Object.fromEntries((gdef.jobChangePeriods || []).map(j => [j.id, j.name]));
      const empStatusMap = Object.fromEntries((gdef.desiredEmploymentStatuses || []).map(e => [e.key, e.name]));
      const reqConditionMap = Object.fromEntries((gdef.employeeRequiredConditions || []).map(r => [r.key, r.name]));

      const skills = domData.skillNames.map(name => ({ id: skillIdMap[name.toLowerCase()] || null, name }));
      const occupations = domData.occupations.map(id => ({ id, name: occMap[id] || `職種ID: ${id}` }));
      const workPlaces = domData.workPlaces.map(id => ({ id, name: placeMap[id] || id }));
      const workStyles = domData.workStyles.map(id => ({ id, name: workStyleMap[id] || `条件ID: ${id}` }));
      const desiredEmploymentStatuses = domData.desiredEmploymentStatuses.map(key => ({ key, name: empStatusMap[key] || key }));
      const requiredConditions = domData.requiredConditions.map(key => ({ key, name: reqConditionMap[key] || key }));

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

    if (ACTION === 'fetch') {
      const data = await extractConditionData();
      return { success: true, section: 'condition', action: 'fetch', data };
    }

    if (ACTION === 'update') {
      const p = PAYLOAD || {};
      let modifiedCount = 0;

      async function setInput(locator, value) {
        if (value === undefined || value === null) return;
        if (await locator.count() === 0) return;
        const cur = await locator.inputValue();
        if (cur !== String(value)) {
          await locator.fill(String(value));
          await locator.dispatchEvent('change');
          await locator.dispatchEvent('input');
          modifiedCount++;
        }
      }

      async function setSelect(locator, value) {
        if (value === undefined || value === null) return;
        if (await locator.count() === 0) return;
        const cur = await locator.inputValue();
        if (cur !== String(value)) {
          await locator.selectOption(String(value));
          await locator.dispatchEvent('change');
          modifiedCount++;
        }
      }

      async function setRadio(name, value) {
        if (value === undefined || value === null || value === '') return;
        const loc = page.locator(`input[name="${name}"][value="${value}"]`);
        if (await loc.count() > 0) {
          if (!await loc.isChecked()) {
            await loc.check({ force: true, timeout: 5000 });
            modifiedCount++;
          }
        }
      }

      if (p.annualIncome !== undefined && p.annualIncome !== null) {
        await setInput(page.locator('input[name="annualIncome"]'), p.annualIncome);
      }
      if (p.jobChangePeriod !== undefined && p.jobChangePeriod !== null) {
        await setRadio('jobChangePeriod', String(p.jobChangePeriod));
      }
      if (p.jobConditions) {
        if (p.jobConditions.businessForm) await setRadio('jobConditions.businessForm', p.jobConditions.businessForm);
        if (p.jobConditions.remoteWork) await setRadio('jobConditions.remoteWork', p.jobConditions.remoteWork);
        if (p.jobConditions.projectScale) await setRadio('jobConditions.projectScale', p.jobConditions.projectScale);
      }
      if (p.businesses && typeof p.businesses === 'object') {
        for (const [key, val] of Object.entries(p.businesses)) {
          if (val) await setRadio(`businesses.${key}`, val);
        }
      }
      if (p.technologyDomains && typeof p.technologyDomains === 'object') {
        for (const [key, val] of Object.entries(p.technologyDomains)) {
          if (val) await setRadio(`technologyDomains.${key}`, val);
        }
      }

      // 勤務地
      if (Array.isArray(p.workPlaces)) {
        const targetPlaces = p.workPlaces.map(String);
        const placeSection = page.locator('[data-display-name="DesiredWorkPlaceSection_DesiredWorkPlacesField"]');
        const addPlaceBtn = placeSection.locator('[data-display-name="MultipleConditionField_AddConditionButton"]');
        let curCount = await placeSection.locator('[data-display-name="DesiredWorkPlacesField_Select"] select').count();

        while (curCount > targetPlaces.length && curCount > 1) {
          await placeSection.locator('[data-display-name="MultipleConditionField_RemoveConditionButton"]').last().click();
          await page.waitForTimeout(300);
          curCount = await placeSection.locator('[data-display-name="DesiredWorkPlacesField_Select"] select').count();
          modifiedCount++;
        }
        while (curCount < targetPlaces.length) {
          if (await addPlaceBtn.isVisible() && !await addPlaceBtn.isDisabled()) {
            await addPlaceBtn.click();
            await page.waitForTimeout(300);
            curCount = await placeSection.locator('[data-display-name="DesiredWorkPlacesField_Select"] select').count();
            modifiedCount++;
          } else break;
        }

        const selects = placeSection.locator('[data-display-name="DesiredWorkPlacesField_Select"] select');
        const total = await selects.count();
        for (let i = 0; i < Math.min(total, targetPlaces.length); i++) {
          await setSelect(selects.nth(i), targetPlaces[i]);
        }
      }

      // 職種
      if (Array.isArray(p.occupations)) {
        const targetOccs = p.occupations.map(String);
        const occSection = page.locator('[data-display-name="DesiredOccupationSection_DesiredOccupationField"]');
        const addOccBtn = occSection.locator('[data-display-name="MultipleConditionField_AddConditionButton"]');
        let curCount = await occSection.locator('[data-display-name="DesiredOccupationField_Select"] select').count();

        while (curCount > targetOccs.length && curCount > 1) {
          await occSection.locator('[data-display-name="MultipleConditionField_RemoveConditionButton"]').last().click();
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
          } else break;
        }

        const selects = occSection.locator('[data-display-name="DesiredOccupationField_Select"] select');
        const total = await selects.count();
        for (let i = 0; i < Math.min(total, targetOccs.length); i++) {
          await setSelect(selects.nth(i), targetOccs[i]);
        }
      }

      // スキル
      if (Array.isArray(p.skills)) {
        const targetSkills = p.skills.map(String);
        const skillSection = page.locator('[data-display-name="DesiredSkillSection_DesiredSkillField"]');
        const addSkillBtn = skillSection.locator('[data-display-name="MultipleConditionField_AddConditionButton"]');
        let curCount = await skillSection.locator('[data-display-name="Autocomplete_AutocompleteInput"] input').count();

        while (curCount > targetSkills.length && curCount > 1) {
          await skillSection.locator('[data-display-name="MultipleConditionField_RemoveConditionButton"]').last().click();
          await page.waitForTimeout(300);
          curCount = await skillSection.locator('[data-display-name="Autocomplete_AutocompleteInput"] input').count();
          modifiedCount++;
        }
        while (curCount < targetSkills.length) {
          if (await addSkillBtn.isVisible() && !await addSkillBtn.isDisabled()) {
            await addSkillBtn.click();
            await page.waitForTimeout(300);
            curCount = await skillSection.locator('[data-display-name="Autocomplete_AutocompleteInput"] input').count();
            modifiedCount++;
          } else break;
        }

        const inputs = skillSection.locator('[data-display-name="Autocomplete_AutocompleteInput"] input');
        const total = await inputs.count();
        for (let i = 0; i < Math.min(total, targetSkills.length); i++) {
          const targetSkill = targetSkills[i];
          const inputLoc = inputs.nth(i);
          if ((await inputLoc.inputValue()).toLowerCase() !== targetSkill.toLowerCase()) {
            await inputLoc.click();
            await inputLoc.fill(targetSkill);
            await page.waitForTimeout(400);

            const optionLoc = page.locator('[role="listbox"] [role="option"], ul.MuiAutocomplete-listbox li').first();
            if (await optionLoc.isVisible({ timeout: 1500 }).catch(() => false)) {
              await optionLoc.click();
            } else {
              await inputLoc.press('Enter');
            }
            await page.waitForTimeout(300);
            modifiedCount++;
          }
        }
      }

      // 雇用形態
      if (Array.isArray(p.desiredEmploymentStatuses)) {
        const targetStatuses = new Set(p.desiredEmploymentStatuses);
        const checkboxes = await page.locator('[data-display-name="DesiredEmploymentStatusSection_Checkbox"] input[type="checkbox"]').all();
        const statusLabels = ['regular_employee', 'dispatch_employee', 'contract_employee', 'freelance'];
        for (let idx = 0; idx < checkboxes.length; idx++) {
          const cb = checkboxes[idx];
          const key = statusLabels[idx];
          const shouldBeChecked = targetStatuses.has(key) || targetStatuses.has(cb);
          if (await cb.isChecked() !== shouldBeChecked) {
            if (shouldBeChecked) await cb.check({ force: true, timeout: 5000 });
            else await cb.uncheck({ force: true, timeout: 5000 });
            modifiedCount++;
          }
        }
      }

      if (p.minWorkFrequency !== undefined) await setSelect(page.locator('select[name="minWorkFrequency"]'), p.minWorkFrequency);
      if (p.maxWorkFrequency !== undefined) await setSelect(page.locator('select[name="maxWorkFrequency"]'), p.maxWorkFrequency);

      if (Array.isArray(p.workStyles)) {
        const targetStyles = new Set(p.workStyles.map(n => parseInt(n, 10)));
        const checkboxes = await page.locator('[data-display-name="WorkStyleSection_Checkbox"] input[type="checkbox"]').all();
        for (const cb of checkboxes) {
          const val = parseInt(await cb.getAttribute('value'), 10);
          if (await cb.isChecked() !== targetStyles.has(val)) {
            if (targetStyles.has(val)) await cb.check({ force: true, timeout: 5000 });
            else await cb.uncheck({ force: true, timeout: 5000 });
            modifiedCount++;
          }
        }
      }

      if (Array.isArray(p.requiredConditions)) {
        const targetReqs = new Set(p.requiredConditions);
        const checkboxes = await page.locator('[data-display-name="RequiredAndOtherConditionSection_Checkbox"] input[type="checkbox"]').all();
        for (const cb of checkboxes) {
          const val = await cb.getAttribute('value');
          if (await cb.isChecked() !== targetReqs.has(val)) {
            if (targetReqs.has(val)) await cb.check({ force: true, timeout: 5000 });
            else await cb.uncheck({ force: true, timeout: 5000 });
            modifiedCount++;
          }
        }
      }

      if (p.other !== undefined && p.other !== null) {
        await setInput(page.locator('textarea[name="other"]'), p.other);
      }

      const updatedData = await extractConditionData();
      const submitBtn = page.locator('button[type="submit"][data-display-name="ProfileDetailLayout_Button"]');
      const isSubmitDisabled = await submitBtn.isDisabled();

      if (IS_DRY_RUN) {
        return {
          success: true,
          section: 'condition',
          action: 'update',
          isDryRun: true,
          modifiedCount,
          canSubmit: !isSubmitDisabled,
          data: updatedData
        };
      }

      if (isSubmitDisabled) {
        return {
          success: true,
          section: 'condition',
          action: 'update',
          isDryRun: false,
          noChanges: true,
          message: '変更項目がなかったため保存処理をスキップしました。',
          data: updatedData
        };
      }

      try {
        await Promise.all([
          submitBtn.click(),
          page.waitForResponse(
            res => res.url().includes('/api/') || res.url().includes('/condition'),
            { timeout: 8000 }
          )
        ]);
      } catch (_) {}

      const errors = await page.evaluate(() => {
        const errNodes = Array.from(document.querySelectorAll('.Mui-error, [role="alert"]'));
        return errNodes.map(e => e.innerText?.trim()).filter(t => t && !t.includes('保存'));
      });
      if (errors.length > 0) {
        throw new Error(`保存処理バリデーションエラー: ${errors.join(' / ')}`);
      }

      const finalData = await extractConditionData();
      return { success: true, section: 'condition', action: 'update', isDryRun: false, data: finalData };
    }
  }

  // ---------------------------------------------------------------------------
  // 5. SKILL (保有スキル)
  // ---------------------------------------------------------------------------
  if (SECTION === 'skill') {
    await page.waitForSelector('[data-display-name="ExperienceSkillsSection_SectionFieldset"]', { timeout: 15000 });

    const EXPERIENCE_YEARS_MAP = {
      15: '半年未満', 6: '半年以上', 7: '1年以上', 8: '1年半以上',
      9: '2年以上', 10: '3年以上', 11: '4年以上', 12: '5年以上',
      13: '7年以上', 14: '10年以上'
    };
    const EXPERIENCE_YEARS_NAME_TO_ID = Object.fromEntries(
      Object.entries(EXPERIENCE_YEARS_MAP).map(([id, name]) => [name, parseInt(id, 10)])
    );

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
      if (m) return parseYearToId(parseFloat(m[1]));
      if (str.includes('半年未満')) return 15;
      if (str.includes('半年')) return 6;
      return null;
    }

    async function extractSkillData() {
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

      const gdef = nextGlobalDef || {};
      const skillMasterList = gdef.skills || gdef.mainSkills || [];
      const skillIdMap = Object.fromEntries(skillMasterList.map(s => [s.name.toLowerCase(), s.id]));
      const occList = gdef.occupations || [];
      const occNameMap = Object.fromEntries(occList.map(o => [o.id, o.name]));
      const procList = gdef.processes || [];
      const procNameMap = Object.fromEntries(procList.map(p => [p.id, p.name]));
      const mgmtList = gdef.managementScales || [];
      const mgmtNameMap = Object.fromEntries(mgmtList.map(m => [m.id, m.name]));

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

        const curOccEl = document.querySelector('select#currentOccupationsInput, select[name="currentOccupations.0"]');
        const curOccId = curOccEl ? parseInt(curOccEl.value, 10) || null : null;
        const curOccText = curOccEl && curOccEl.selectedIndex >= 0 ? curOccEl.options[curOccEl.selectedIndex]?.text : '';

        const mgmtEl = document.querySelector('select#managementScalesInput, select[name="managementScale"]');
        const mgmtId = mgmtEl ? parseInt(mgmtEl.value, 10) || null : null;
        const mgmtText = mgmtEl && mgmtEl.selectedIndex >= 0 ? mgmtEl.options[mgmtEl.selectedIndex]?.text : '';

        const submitBtn = document.querySelector('button[type="submit"][data-display-name="ProfileDetailLayout_Button"]');

        return {
          domSkills: rows,
          currentOccupation: { id: curOccId, name: curOccText },
          managementScale: { id: mgmtId, name: mgmtText },
          isSubmitDisabled: submitBtn ? submitBtn.disabled : true
        };
      });

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

      const occupations = (nextResume?.occupations || []).map(o => ({
        id: o.id,
        name: occNameMap[o.id] || `職種ID: ${o.id}`,
        experienceYearId: o.experienceYearId,
        experienceYears: EXPERIENCE_YEARS_MAP[o.experienceYearId] || ''
      }));

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

    if (ACTION === 'fetch') {
      const data = await extractSkillData();
      return { success: true, section: 'skill', action: 'fetch', data };
    }

    if (ACTION === 'update') {
      const p = PAYLOAD || {};
      let modifiedCount = 0;

      const skillSection = page.locator('[data-display-name="ExperienceSkillsSection_SectionFieldset"]');
      const addSkillBtn = skillSection.locator('button[data-display-name="MultipleConditionField_AddConditionButton"]');

      if (Array.isArray(p.skills)) {
        const targetSkills = p.skills.map(s => {
          if (typeof s === 'string') return { name: s, yearId: 9 };
          const yearId = parseYearToId(s.experienceYears || s.experienceYearId || s.years) || 9;
          return { name: s.name || s.skillName || '', yearId };
        }).filter(s => Boolean(s.name.trim()));

        let curInputs = skillSection.locator('input[placeholder="経験スキルを選択"]');
        let curCount = await curInputs.count();

        while (curCount > targetSkills.length && curCount > 0) {
          const removeBtns = skillSection.locator('button[data-display-name="MultipleConditionField_RemoveConditionButton"]');
          if (await removeBtns.count() === 0) break;
          await removeBtns.last().click();
          await page.waitForTimeout(300);
          curCount = await skillSection.locator('input[placeholder="経験スキルを選択"]').count();
          modifiedCount++;
        }

        while (curCount < targetSkills.length) {
          if (await addSkillBtn.isVisible() && !await addSkillBtn.isDisabled()) {
            await addSkillBtn.click();
            await page.waitForTimeout(300);
            curCount = await skillSection.locator('input[placeholder="経験スキルを選択"]').count();
            modifiedCount++;
          } else break;
        }

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
              if (optCount > 0) await options.first().click();
              else await inputLoc.press('Enter');
            }
            await page.waitForTimeout(300);
            modifiedCount++;
          }

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

      if (p.currentOccupation !== undefined && p.currentOccupation !== null) {
        const curOccEl = page.locator('select#currentOccupationsInput, select[name="currentOccupations.0"]');
        if (await curOccEl.isVisible()) {
          const targetOccId = String(p.currentOccupation);
          if (await curOccEl.inputValue() !== targetOccId) {
            await curOccEl.selectOption(targetOccId);
            await page.waitForTimeout(200);
            modifiedCount++;
          }
        }
      }

      if (p.managementScale !== undefined && p.managementScale !== null) {
        const mgmtEl = page.locator('select#managementScalesInput, select[name="managementScale"]');
        if (await mgmtEl.isVisible()) {
          const targetMgmtId = String(p.managementScale);
          if (await mgmtEl.inputValue() !== targetMgmtId) {
            await mgmtEl.selectOption(targetMgmtId);
            await page.waitForTimeout(200);
            modifiedCount++;
          }
        }
      }

      const submitBtn = page.locator('button[type="submit"][data-display-name="ProfileDetailLayout_Button"]');
      const isSubmitDisabled = await submitBtn.isDisabled();

      if (IS_DRY_RUN) {
        const previewData = await extractSkillData();
        return {
          success: true,
          section: 'skill',
          action: 'update',
          isDryRun: true,
          modifiedCount,
          isSubmitDisabled,
          data: previewData
        };
      }

      if (isSubmitDisabled) {
        const currentData = await extractSkillData();
        return {
          success: true,
          section: 'skill',
          action: 'update',
          isDryRun: false,
          modifiedCount: 0,
          message: '変更がありませんでした。',
          data: currentData
        };
      }

      await submitBtn.click();
      await page.waitForTimeout(1000);

      const errors = await page.evaluate(() => {
        const errNodes = Array.from(document.querySelectorAll('.Mui-error, [role="alert"]'));
        return errNodes.map(e => e.innerText?.trim()).filter(t => t && !t.includes('保存') && !t.includes('完了') && !t.includes('更新'));
      });
      if (errors.length > 0) {
        throw new Error(`保存処理バリデーションエラー: ${errors.join(' / ')}`);
      }

      await page.waitForTimeout(1500);
      const finalData = await extractSkillData();
      return { success: true, section: 'skill', action: 'update', isDryRun: false, modifiedCount, data: finalData };
    }
  }

  throw new Error(`未知のセクションまたはアクションです: section=${SECTION}, action=${ACTION}`);
};
