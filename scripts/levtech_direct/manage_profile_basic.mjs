// scripts/levtech_direct/manage_profile_basic.mjs
// レバテックダイレクト 基本情報画面（/mypage/profile/basic）DOM操作 Playwright スクリプト
// sharing-browser-with-user スキル準拠

async page => {
  const ACTION = '__LEVTECH_ACTION__';
  const PAYLOAD = __LEVTECH_PAYLOAD__;
  const IS_DRY_RUN = __LEVTECH_DRY_RUN__;

  const TARGET_URL = 'https://levtech-direct.jp/mypage/profile/basic';

  // 1. 現在のページURLを確認し、必要に応じて遷移
  if (!page.url().includes('/mypage/profile/basic')) {
    await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
  }

  // フォーム読み込み待機
  await page.waitForSelector('form', { timeout: 15000 });

  // 都道府県マップ (ID -> 名称)
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

  const GENDER_MAP = {
    1: '男性', 2: '女性', 3: '無回答'
  };

  const NATIVE_LANGUAGE_MAP = {
    1: '日本語', 2: '英語', 3: 'フランス語', 4: 'ドイツ語', 5: 'ロシア語',
    6: '中国語', 7: '韓国語', 8: 'イタリア語', 9: 'ポルトガル語', 10: 'スペイン語'
  };

  // 補助関数: 現在のフォーム値を取得する
  async function extractCurrentData() {
    // 1. __NEXT_DATA__ から取得
    let nextBasics = null;
    try {
      const nextDataEl = await page.$('#__NEXT_DATA__');
      if (nextDataEl) {
        const text = await nextDataEl.textContent();
        const parsed = JSON.parse(text);
        nextBasics = parsed?.props?.pageProps?.profilesBasics || null;
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

      const genderEl = document.querySelector('input[name="base.gender"]:checked');
      const marriedEl = document.querySelector('input[name="base.isMarried"]:checked');

      // 住所系
      const postalCode = val('div#address input[placeholder="1234567"]');
      const prefectureId = val('div#address select');
      const address = val('div#address input[placeholder="以降の住所を入力"]');

      // 学歴系
      const schoolCategorySelects = document.querySelectorAll('#schoolCategoryDetail select');
      const schoolCategoryId = schoolCategorySelects.length > 0 ? schoolCategorySelects[0].value : '';
      const schoolName = val('div#schoolCategoryDetail input[placeholder="学校名を入力"]');
      const facultyDepartment = val('div#schoolCategoryDetail input[placeholder="学部/学科/専攻を入力"]');
      const gradYear = schoolCategorySelects.length > 1 ? schoolCategorySelects[1].value : '';
      const gradMonth = schoolCategorySelects.length > 2 ? schoolCategorySelects[2].value : '';
      const educationalOther = val('textarea[name="educational.other"]');

      // 電話番号
      const phoneNumber = val('div#phoneNumber input[type="tel"]');
      const isAcceptedCallByHeadhunter = checked('div#phoneNumber input[type="checkbox"]');

      // その他言語1
      const langSelects = document.querySelectorAll('#languages select');
      const lang1Id = langSelects.length > 0 ? langSelects[0].value : '';
      const lang1Level = langSelects.length > 1 ? langSelects[1].value : '';

      // スクール受講
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

    // 統合データを作成
    const base = nextBasics?.base || {};
    const edu = nextBasics?.educational || {};

    const prefId = domData.prefectureId || String(base.prefectureId || '');
    const schoolCatId = domData.schoolCategoryId || String(edu.schoolCategoryId || '');
    const genderVal = domData.gender || String(base.gender || '');
    const nativeLangId = domData.nativeLanguageId || String(base.nativeLanguageId || '');

    // 生年月日のフォーマット
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

  // --- アクション分岐 ---

  if (ACTION === 'fetch') {
    const data = await extractCurrentData();
    return {
      success: true,
      action: 'fetch',
      url: page.url(),
      data
    };
  }

  if (ACTION === 'update') {
    const p = PAYLOAD || {};
    let modifiedCount = 0;

    // ヘルパー: fill if defined
    async function setInput(locator, value) {
      if (value === undefined || value === null) return;
      if (await locator.count() > 0) {
        await locator.fill(String(value));
        await locator.blur();
        modifiedCount++;
      }
    }

    // ヘルパー: selectOption if defined
    async function setSelect(locator, value) {
      if (value === undefined || value === null || value === '') return;
      if (await locator.count() > 0) {
        const valStr = String(value);
        try {
          await locator.selectOption(valStr);
        } catch (_) {
          // labelでフォールバック試行
          try {
            await locator.selectOption({ label: valStr });
          } catch (_) {}
        }
        await locator.blur();
        modifiedCount++;
      }
    }

    // 1. 氏名
    await setInput(page.locator('input[name="base.lastName"]'), p.lastName);
    await setInput(page.locator('input[name="base.firstName"]'), p.firstName);
    await setInput(page.locator('input[name="base.kanaLastName"]'), p.kanaLastName);
    await setInput(page.locator('input[name="base.kanaFirstName"]'), p.kanaFirstName);

    // 2. 生年月日
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

    // 3. 性別
    if (p.gender !== undefined && p.gender !== null) {
      const genderVal = String(p.gender);
      const loc = page.locator(`input[name="base.gender"][value="${genderVal}"]`);
      if (await loc.count() > 0) {
        await loc.check();
        modifiedCount++;
      }
    }

    // 4. 電話番号
    await setInput(page.locator('div#phoneNumber input[type="tel"]'), p.phoneNumber);

    // 5. 電話連絡許可
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

    // 6. 住所
    await setInput(page.locator('div#address input[placeholder="1234567"]'), p.postalCode);
    let prefValue = p.prefectureId;
    if (typeof prefValue === 'string' && PREFECTURE_NAME_TO_ID[prefValue]) {
      prefValue = PREFECTURE_NAME_TO_ID[prefValue];
    }
    await setSelect(page.locator('div#address select'), prefValue);
    await setInput(page.locator('div#address input[placeholder="以降の住所を入力"]'), p.address);

    // 7. 配偶者
    if (p.isMarried !== undefined && p.isMarried !== null) {
      const val = p.isMarried === true || p.isMarried === 1 || p.isMarried === '1' ? '1' : '0';
      const loc = page.locator(`input[name="base.isMarried"][value="${val}"]`);
      if (await loc.count() > 0) {
        await loc.check();
        modifiedCount++;
      }
    }

    // 8. 年収
    await setInput(page.locator('input[name="base.currentAnnualIncome"]'), p.currentAnnualIncome);

    // 9. 学歴
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

    // 10. 語学・資格
    const lang = p.language || p;
    await setSelect(page.locator('select[name="base.nativeLanguageId"]'), lang.nativeLanguageId);
    await setInput(page.locator('input[name="base.toeic"]'), lang.toeic);
    await setInput(page.locator('input[name="base.toefl"]'), lang.toefl);
    await setInput(page.locator('textarea#certificationInput'), p.certification);

    // 11. スクール受講
    const school = p.schoolAttendance || p;
    await setSelect(page.locator('div#schoolAttendanceExperience select'), school.schoolAttendanceExperience || school.experience);
    await setSelect(page.locator('div#schoolAttendancePeriod select'), school.schoolAttendancePeriod || school.period);

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
    await submitBtn.click();

    // トーストまたは保存完了待機（ボタンがdisabledに戻るか、トーストが表示される）
    try {
      await Promise.race([
        page.waitForSelector('.MuiAlert-root, [role="alert"]', { timeout: 8000 }),
        page.waitForFunction(
          btn => btn.disabled,
          await submitBtn.elementHandle(),
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
