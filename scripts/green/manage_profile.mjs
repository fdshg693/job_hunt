// scripts/green/manage_profile.mjs
// Green プロフィール（基本情報・職歴・スキル・職務経歴書等）の閲覧・更新を実行する Playwright スクリプト
// 実行方法: manage_profile.py からテンプレ置換または直接実行

async page => {
  const action = '__GREEN_ACTION__';
  const payload = __GREEN_PAYLOAD__;
  const isDryRun = __GREEN_DRY_RUN__;

  const TARGET_URL = 'https://www.green-japan.com/profiles/edit';

  const cleanMultiline = str =>
    (str || '')
      .replace(/\r?\n/g, '\n')
      .split('\n')
      .map(line => line.trimEnd())
      .join('\n')
      .trim();

  // 1. プロフィール編集画面へ遷移（まだその画面にいない場合、または確実な最新データ取得のため）
  const currentUrl = page.url();
  if (!currentUrl.includes('/profiles/edit')) {
    await page.goto(TARGET_URL, {
      waitUntil: 'domcontentloaded',
      timeout: 30000,
    });
  }

  // 認証チェック
  const isAuthWall = /green-japan\.com\/login|accounts\.google\.com/i.test(page.url());
  if (isAuthWall) {
    return {
      success: false,
      error: 'ログインが必要です（認証画面にリダイレクトされました）。',
      onAuthWall: true,
      currentUrl: page.url(),
    };
  }

  // Next.js の初期データ（__NEXT_DATA__）のロード待機
  try {
    await page.waitForFunction(
      () => window.__NEXT_DATA__ && window.__NEXT_DATA__.props && window.__NEXT_DATA__.props.pageProps,
      { timeout: 15000 }
    );
  } catch (e) {
    // 画面再読み込みを試みる
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForFunction(
      () => window.__NEXT_DATA__ && window.__NEXT_DATA__.props && window.__NEXT_DATA__.props.pageProps,
      { timeout: 15000 }
    );
  }

  // 現在の全プロフィールデータを取得するヘルパー
  const getPageData = async () => {
    return await page.evaluate(() => {
      const pageProps = window.__NEXT_DATA__?.props?.pageProps || {};
      return {
        userData: pageProps.userData || null,
        userResume: pageProps.userResume || null,
        blockCompanies: pageProps.blockCompanies || null,
        prefectureMasterData: pageProps.prefectureMasterData || null,
        employmentStatusMasterData: pageProps.employmentStatusMasterData || null,
        schoolMasterData: pageProps.schoolMasterData || null,
        jobTagCategoriesData: pageProps.jobTagCategoriesData || null,
        masterSkillData: pageProps.masterSkillData || null,
        masterAreaData: pageProps.masterAreaData || null,
        languageMasterData: pageProps.languageMasterData || null,
        masterUserNeedsForJob: pageProps.masterUserNeedsForJob || null,
      };
    });
  };

  // ページ内 fetch で内部REST APIを呼び出すヘルパー
  const callApi = async (url, method, body = null) => {
    const fullUrl = url.startsWith('/api/v2')
      ? url
      : `/api/v2${url.startsWith('/') ? '' : '/'}${url}`;
    return await page.evaluate(
      async ({ apiUrl, apiMethod, apiBody }) => {
        const headers = {
          'Accept': 'application/json',
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        };
        const options = {
          method: apiMethod,
          headers: headers,
          credentials: 'include',
        };

        const decamelize = (val) => {
          if (Array.isArray(val)) return val.map(decamelize);
          if (val !== null && typeof val === 'object' && !(val instanceof Date)) {
            const res = {};
            for (const [k, v] of Object.entries(val)) {
              const snakeKey = k.replace(/[A-Z]/g, letter => `_${letter.toLowerCase()}`);
              res[snakeKey] = decamelize(v);
            }
            return res;
          }
          return val;
        };

        if (apiBody !== null && apiBody !== undefined) {
          const bodyPayload = typeof apiBody === 'string' ? apiBody : decamelize(apiBody);
          options.body = typeof bodyPayload === 'string' ? bodyPayload : JSON.stringify(bodyPayload);
        }

        const res = await window.fetch(apiUrl, options);
        let data = null;
        const text = await res.text();
        try {
          data = JSON.parse(text);
        } catch (_) {
          data = text;
        }

        return {
          status: res.status,
          ok: res.ok,
          statusText: res.statusText,
          data: data,
        };
      },
      { apiUrl: fullUrl, apiMethod: method, apiBody: body }
    );
  };

  try {
    // ==========================================
    // ACTION: view (プロフィール全取得)
    // ==========================================
    if (action === 'view') {
      const fullData = await getPageData();
      return {
        success: true,
        action: 'view',
        data: fullData,
      };
    }

    // ==========================================
    // ACTION: update-resume (職務経歴書フリーテキスト更新)
    // ==========================================
    if (action === 'update-resume') {
      const newResume = cleanMultiline(payload.resume || payload.text || '');
      const currentData = await getPageData();
      const currentResume = cleanMultiline(currentData.userResume?.resume || '');

      if (isDryRun) {
        return {
          success: true,
          dryRun: true,
          action: 'update-resume',
          previousResume: currentResume,
          newResume: newResume,
          lengthDiff: newResume.length - currentResume.length,
        };
      }

      // API更新実行: POST /user/me/resume
      const apiRes = await callApi('/user/me/resume', 'POST', { resume: newResume });
      if (!apiRes.ok) {
        return {
          success: false,
          action: 'update-resume',
          error: `APIエラー (${apiRes.status}): ${JSON.stringify(apiRes.data)}`,
        };
      }

      return {
        success: true,
        action: 'update-resume',
        previousResume: currentResume,
        newResume: newResume,
        apiResponse: apiRes.data,
      };
    }

    // ==========================================
    // ACTION: update-basic (基本情報・現年収等更新)
    // ==========================================
    if (action === 'update-basic') {
      const currentData = await getPageData();
      const currentUserData = currentData.userData || {};

      // 変更対象のフィールドをマージ
      const updatePayload = {};
      const fields = [
        'firstName', 'lastName', 'firstKana', 'lastKana',
        'birthdayTimestamp', 'areaId', 'address', 'phoneNumber',
        'salary', 'toeic', 'toefl', 'userGraduationSchool'
      ];

      for (const key of fields) {
        if (payload[key] !== undefined) {
          updatePayload[key] = payload[key];
        } else if (currentUserData[key] !== undefined) {
          updatePayload[key] = currentUserData[key];
        }
      }

      // 電話番号は phone と phoneNumber 両方設定
      updatePayload.phone = payload.phone || payload.phoneNumber || currentUserData.phoneNumber || currentUserData.phone || '';

      // 学歴情報の更新を反映
      const school = { ...(currentUserData.userGraduationSchool || {}) };
      if (payload.schoolGraduationYear !== undefined) {
        school.schoolGraduationYear = Number(payload.schoolGraduationYear);
      }
      if (payload.schoolDepartmentName !== undefined) {
        school.departmentName = payload.schoolDepartmentName;
      }
      if (payload.schoolName !== undefined) {
        school.schoolName = payload.schoolName;
      }
      updatePayload.userGraduationSchool = school;
      updatePayload.schoolName = school.schoolName || '';
      updatePayload.schoolDepartmentName = school.departmentName || '';
      updatePayload.schoolGraduationYear = school.schoolGraduationYear || 0;
      updatePayload.schoolGraduationMonth = school.schoolGraduationMonth || 3;
      updatePayload.schoolTypeId = school.schoolTypeId || 4;
      updatePayload.schoolGraduationTypeId = school.graduationTypeId || 1;

      if (isDryRun) {
        return {
          success: true,
          dryRun: true,
          action: 'update-basic',
          previousBasic: currentUserData,
          updatePayload: updatePayload,
        };
      }

      // API更新実行: PATCH /user/me/basic_info
      const apiRes = await callApi('/user/me/basic_info', 'PATCH', updatePayload);
      if (!apiRes.ok) {
        return {
          success: false,
          action: 'update-basic',
          error: `APIエラー (${apiRes.status}): ${JSON.stringify(apiRes.data)}`,
        };
      }

      return {
        success: true,
        action: 'update-basic',
        previousBasic: currentUserData,
        updatePayload: updatePayload,
        apiResponse: apiRes.data,
      };
    }

    // ==========================================
    // ACTION: update-skills (保有スキル一括置換)
    // ==========================================
    if (action === 'update-skills') {
      const currentData = await getPageData();
      const currentSkills = currentData.userData?.userSkills || [];
      const inputSkills = payload.userSkills || payload.skills || [];

      // masterSkillData から名前 -> skillId の辞書を生成
      const skillNameMap = new Map();
      const walkSkills = (obj) => {
        if (!obj) return;
        if (Array.isArray(obj)) {
          obj.forEach(walkSkills);
        } else if (typeof obj === 'object') {
          if (obj.id && obj.name) {
            skillNameMap.set(String(obj.name).toLowerCase().trim(), Number(obj.id));
          }
          Object.values(obj).forEach(walkSkills);
        }
      };
      walkSkills(currentData.masterSkillData);

      const scoreToId = (score) => {
        if (typeof score === 'number') return score;
        const str = String(score || '').trim();
        if (str.includes('1年未満') || str === '1') return 1;
        if (str.includes('1年') || str.includes('2年') || str.includes('3年') || str === '2') return 2;
        if (str.includes('3年') || str.includes('4年') || str.includes('5年') || str === '3') return 3;
        if (str.includes('5年') || str === '4') return 4;
        return 2;
      };

      const formattedSkills = [];
      for (const item of inputSkills) {
        let skillId = item.skillId || item.id;
        const sName = item.name || item.skillName || (item.skill && item.skill.name);
        if (!skillId && sName) {
          skillId = skillNameMap.get(sName.toLowerCase().trim());
        }
        let scoreId = item.skillScoreId || item.scoreId || item.score;
        if (!scoreId) {
          scoreId = scoreToId(item.experienceYears || item.experience || (item.skillScore && item.skillScore.name));
        }
        if (skillId) {
          formattedSkills.push({
            skillId: Number(skillId),
            skillScoreId: Number(scoreId || 2),
            skillName: sName || '',
          });
        }
      }

      const requestPayload = {
        skills: formattedSkills.map(s => ({ skillId: s.skillId, skillScoreId: s.skillScoreId }))
      };

      if (isDryRun) {
        return {
          success: true,
          dryRun: true,
          action: 'update-skills',
          previousSkills: currentSkills,
          newSkills: formattedSkills,
          requestPayload: requestPayload,
        };
      }

      // API更新実行: POST /user/me/skills/replace_all
      const apiRes = await callApi('/user/me/skills/replace_all', 'POST', requestPayload);
      if (!apiRes.ok) {
        return {
          success: false,
          action: 'update-skills',
          error: `APIエラー (${apiRes.status}): ${JSON.stringify(apiRes.data)}`,
        };
      }

      return {
        success: true,
        action: 'update-skills',
        previousSkills: currentSkills,
        newSkills: formattedSkills,
        apiResponse: apiRes.data,
      };
    }

    // ==========================================
    // ACTION: update-companies (在籍企業一括置換)
    // ==========================================
    if (action === 'update-companies') {
      const currentData = await getPageData();
      const currentCompanies = currentData.userData?.userCompanies || [];
      const newCompanies = payload.userCompanies || payload.companies || [];

      if (isDryRun) {
        return {
          success: true,
          dryRun: true,
          action: 'update-companies',
          previousCompanies: currentCompanies,
          newCompanies: newCompanies,
        };
      }

      // API更新実行: POST /user/me/exp_companies/replace_all
      const apiRes = await callApi('/user/me/exp_companies/replace_all', 'POST', { userCompanies: newCompanies });
      if (!apiRes.ok) {
        return {
          success: false,
          action: 'update-companies',
          error: `APIエラー (${apiRes.status}): ${JSON.stringify(apiRes.data)}`,
        };
      }

      return {
        success: true,
        action: 'update-companies',
        previousCompanies: currentCompanies,
        newCompanies: newCompanies,
        apiResponse: apiRes.data,
      };
    }

    // ==========================================
    // ACTION: update-career-statement (企業に伝えたいこと更新)
    // ==========================================
    if (action === 'update-career-statement') {
      const currentData = await getPageData();
      const currentStatement = currentData.userData?.careerChangeStatement || {};

      const pointObj = (currentStatement && typeof currentStatement.careerChangePoint === 'object')
        ? currentStatement.careerChangePoint
        : { comment: currentStatement.careerChangePoint || '' };
      const pointCategories = pointObj.careerChangePointCategories || [];
      const categoryIds = payload.careerChangePointCategoryIds || (pointCategories.length ? pointCategories.map(c => c.id || c) : [1]);

      const reqBody = {
        careerChangePoint: {
          careerChangePointCategoryIds: categoryIds,
          comment: payload.careerChangePoint !== undefined ? payload.careerChangePoint : (pointObj.comment || null),
        },
        careerHighlight: {
          comment: payload.careerHighlight !== undefined ? payload.careerHighlight : ((currentStatement.careerHighlight && currentStatement.careerHighlight.comment) || currentStatement.careerHighlight || null),
        },
        careerChangeStatementSupplement: {
          comment: payload.careerChangeStatementSupplement !== undefined ? payload.careerChangeStatementSupplement : ((currentStatement.careerChangeStatementSupplement && currentStatement.careerChangeStatementSupplement.comment) || currentStatement.careerChangeStatementSupplement || null),
        },
      };

      if (isDryRun) {
        return {
          success: true,
          dryRun: true,
          action: 'update-career-statement',
          previousStatement: currentStatement,
          newStatement: reqBody,
        };
      }

      // API更新実行: PATCH /user/career_change_statement
      const apiRes = await callApi('/user/career_change_statement', 'PATCH', reqBody);
      if (!apiRes.ok) {
        return {
          success: false,
          action: 'update-career-statement',
          error: `APIエラー (${apiRes.status}): ${JSON.stringify(apiRes.data)}`,
        };
      }

      return {
        success: true,
        action: 'update-career-statement',
        previousStatement: currentStatement,
        newStatement: reqBody,
        apiResponse: apiRes.data,
      };
    }

    return {
      success: false,
      error: `未知のアクション: ${action}`,
    };
  } catch (err) {
    return {
      success: false,
      error: `実行中例外: ${err.message || String(err)}`,
      stack: err.stack,
    };
  }
}
