// scripts/youtrust/manage_background.mjs
// YOUTRUST 職歴・学歴（/settings/background）の閲覧・更新・削除・追加 Playwright スクリプト
// Python側の execute_manage_action からテンプレート置換されて実行されます。

async page => {
  const ACTION = '__YOUTRUST_ACTION__';
  const TARGET = '__YOUTRUST_TARGET__'; // 'career' | 'education' | 'all'
  const PAYLOAD = __YOUTRUST_PAYLOAD__;
  const IS_DRY_RUN = __YOUTRUST_DRY_RUN__;

  const TARGET_URL = 'https://youtrust.jp/settings/background';

  // 1. ページ遷移
  if (!page.url().includes('/settings/background')) {
    await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
  }

  // 2. 認証壁チェック
  const currentUrl = page.url();
  const isAuthWall = /youtrust\.jp\/sign_in|accounts\.google\.com/i.test(currentUrl);
  if (isAuthWall) {
    return {
      success: false,
      error: 'ログインが必要です（認証画面にリダイレクトされました）。',
      onAuthWall: true,
      currentUrl,
    };
  }

  // 3. ブラウザ内REST APIヘルパー関数を定義
  const executeApiInPage = async (method, endpoint, body = null) => {
    return await page.evaluate(
      async ({ method, endpoint, body }) => {
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
        const headers = {
          Accept: 'application/json',
          'Content-Type': 'application/json',
        };
        if (csrfToken) {
          headers['X-CSRF-Token'] = csrfToken;
        }

        const options = {
          method,
          headers,
          credentials: 'include',
        };
        if (body) {
          options.body = JSON.stringify(body);
        }

        try {
          const res = await fetch(endpoint, options);
          let data = null;
          const text = await res.text();
          if (text) {
            try {
              data = JSON.parse(text);
            } catch (e) {
              data = { rawText: text };
            }
          }
          return {
            ok: res.ok,
            status: res.status,
            statusText: res.statusText,
            data,
            rawText: text,
          };
        } catch (err) {
          return {
            ok: false,
            status: 0,
            error: err.message,
            rawText: '',
          };
        }
      },
      { method, endpoint, body }
    );
  };

  // カテゴリ正規化ヘルパー
  const normalizeCategories = (cats) => {
    if (!cats || !Array.isArray(cats)) return [];
    return cats.map(c => {
      if (typeof c === 'string') return c;
      return c.v3_category_type || c.category_type || c.id || '';
    }).filter(Boolean);
  };

  // 4. 全職歴・学歴データの取得ヘルパー
  const fetchAllBackgroundData = async () => {
    // 職歴: GET /api/v3/users/@me/career_company_histories
    // 学歴: GET /api/users/@me (educations 配列)
    const [careersRes, meRes] = await Promise.all([
      executeApiInPage('GET', '/api/v3/users/@me/career_company_histories'),
      executeApiInPage('GET', '/api/users/@me'),
    ]);

    const careerCompanyHistories =
      careersRes.ok && careersRes.data ? careersRes.data.career_company_histories || careersRes.data : [];
    const educations = meRes.ok && meRes.data ? meRes.data.educations || [] : [];

    return {
      career_company_histories: careerCompanyHistories,
      educations: educations,
    };
  };

  // 5. アクション分岐

  if (ACTION === 'show' || ACTION === 'view' || ACTION === 'backup') {
    const data = await fetchAllBackgroundData();
    return {
      success: true,
      action: ACTION,
      target: TARGET,
      data,
    };
  }

  // 5.2 追加 (add)
  if (ACTION === 'add') {
    if (TARGET === 'education') {
      const endpoint = '/api/v3/users/@me/educations';
      const body = {
        education: {
          name: PAYLOAD.name || '',
          major_subject: PAYLOAD.major_subject || '',
          entered_at: PAYLOAD.entered_at || null,
          graduated_at: PAYLOAD.graduated_at || null,
          school_master_id: PAYLOAD.school_master_id || null,
          seminar_name: PAYLOAD.seminar_name || null,
          club_name: PAYLOAD.club_name || null,
        },
      };

      if (IS_DRY_RUN) {
        return {
          success: true,
          action: 'add',
          target: 'education',
          isDryRun: true,
          endpoint,
          payload: body,
        };
      }

      const res = await executeApiInPage('POST', endpoint, body);
      if (!res.ok) {
        return {
          success: false,
          error: `学歴の追加に失敗しました (HTTP ${res.status}): ${res.rawText || JSON.stringify(res.data) || res.statusText}`,
        };
      }

      const updatedData = await fetchAllBackgroundData();
      return {
        success: true,
        action: 'add',
        target: 'education',
        isDryRun: false,
        created: res.data,
        data: updatedData,
      };
    } else {
      // TARGET === 'career'
      // 既存企業への部署追加 (career) か、企業職歴の新規作成 (career_company_history) か
      if (PAYLOAD.career_company_history_id) {
        const historyId = PAYLOAD.career_company_history_id;
        const endpoint = `/api/v3/users/@me/career_company_histories/${historyId}/careers`;
        const body = {
          career: {
            name: PAYLOAD.department_name || PAYLOAD.name || '',
            role: PAYLOAD.role || '',
            career_job_categories: normalizeCategories(PAYLOAD.career_job_categories),
            began_at: PAYLOAD.began_at || null,
            ended_at: PAYLOAD.ended_at || null,
            description: PAYLOAD.description || '',
            career_users: (PAYLOAD.career_users || []).map(e => ({ user_id: e.id || e.user_id })),
            add_current_affiliation: Boolean(PAYLOAD.add_current_affiliation),
          },
        };

        if (IS_DRY_RUN) {
          return {
            success: true,
            action: 'add',
            target: 'career_dept',
            isDryRun: true,
            endpoint,
            payload: body,
          };
        }

        const res = await executeApiInPage('POST', endpoint, body);
        if (!res.ok) {
          return {
            success: false,
            error: `部署・プロジェクトの追加に失敗しました (HTTP ${res.status}): ${res.rawText || JSON.stringify(res.data) || res.statusText} | Sent: ${JSON.stringify(body)}`,
          };
        }

        const updatedData = await fetchAllBackgroundData();
        return {
          success: true,
          action: 'add',
          target: 'career_dept',
          isDryRun: false,
          created: res.data,
          data: updatedData,
        };
      } else {
        // 企業職歴新規作成
        const endpoint = '/api/v3/users/@me/career_company_histories';
        const body = {
          career_company_history: {
            company_name: PAYLOAD.company_name || '',
            corporate_number: PAYLOAD.corporate_number || null,
            label_type: PAYLOAD.label_type || 'label_type_none',
            joined_at: PAYLOAD.joined_at || null,
            left_at: PAYLOAD.left_at || null,
            career: {
              name: PAYLOAD.department_name || PAYLOAD.name || PAYLOAD.role || '',
              role: PAYLOAD.role || '',
              career_job_categories: normalizeCategories(PAYLOAD.career_job_categories),
              began_at: PAYLOAD.joined_at || null,
              ended_at: PAYLOAD.left_at || null,
              description: PAYLOAD.description || '',
              career_users: [],
              add_current_affiliation: Boolean(PAYLOAD.left_at ? false : true),
            },
          },
        };

        if (IS_DRY_RUN) {
          return {
            success: true,
            action: 'add',
            target: 'career',
            isDryRun: true,
            endpoint,
            payload: body,
          };
        }

        const res = await executeApiInPage('POST', endpoint, body);
        if (!res.ok) {
          return {
            success: false,
            error: `企業職歴の追加に失敗しました (HTTP ${res.status}): ${res.rawText || JSON.stringify(res.data) || res.statusText}`,
          };
        }

        const updatedData = await fetchAllBackgroundData();
        return {
          success: true,
          action: 'add',
          target: 'career',
          isDryRun: false,
          created: res.data,
          data: updatedData,
        };
      }
    }
  }

  // 5.3 更新 (update)
  if (ACTION === 'update') {
    if (TARGET === 'education') {
      const eduId = PAYLOAD.id || PAYLOAD.education_id;
      if (!eduId) {
        return { success: false, error: '更新対象の学歴ID (--id / --edu-id) が指定されていません。' };
      }
      const endpoint = `/api/v3/users/@me/educations/${eduId}`;
      const body = {
        education: {
          name: PAYLOAD.name,
          major_subject: PAYLOAD.major_subject,
          entered_at: PAYLOAD.entered_at,
          graduated_at: PAYLOAD.graduated_at,
          school_master_id: PAYLOAD.school_master_id,
          seminar_name: PAYLOAD.seminar_name,
          club_name: PAYLOAD.club_name,
        },
      };
      Object.keys(body.education).forEach(k => body.education[k] === undefined && delete body.education[k]);

      if (IS_DRY_RUN) {
        return {
          success: true,
          action: 'update',
          target: 'education',
          isDryRun: true,
          id: eduId,
          endpoint,
          payload: body,
        };
      }

      const res = await executeApiInPage('PATCH', endpoint, body);
      if (!res.ok) {
        return {
          success: false,
          error: `学歴の更新に失敗しました (HTTP ${res.status}): ${res.rawText || JSON.stringify(res.data) || res.statusText}`,
        };
      }

      const updatedData = await fetchAllBackgroundData();
      return {
        success: true,
        action: 'update',
        target: 'education',
        isDryRun: false,
        updated: res.data,
        data: updatedData,
      };
    } else {
      // TARGET === 'career'
      // 部署更新か企業更新か
      if (PAYLOAD.career_id) {
        const historyId = PAYLOAD.career_company_history_id || PAYLOAD.history_id;
        if (!historyId) {
          return { success: false, error: '部署更新には企業職歴ID (--history-id) が必要です。' };
        }
        const endpoint = `/api/v3/users/@me/career_company_histories/${historyId}/careers/${PAYLOAD.career_id}`;
        const body = {
          career: {
            name: PAYLOAD.department_name !== undefined ? PAYLOAD.department_name : (PAYLOAD.name || ''),
            role: PAYLOAD.role || '',
            career_job_categories: normalizeCategories(PAYLOAD.career_job_categories),
            began_at: PAYLOAD.began_at || null,
            ended_at: PAYLOAD.ended_at || null,
            description: PAYLOAD.description || '',
            new_career_users: (PAYLOAD.new_career_users || []).map(e => ({ user_id: e.id || e.user_id })),
            delete_career_users: (PAYLOAD.delete_career_users || []).map(e => ({ id: e.id })),
            add_current_affiliation: Boolean(PAYLOAD.add_current_affiliation),
          },
        };

        if (IS_DRY_RUN) {
          return {
            success: true,
            action: 'update',
            target: 'career_dept',
            isDryRun: true,
            history_id: historyId,
            career_id: PAYLOAD.career_id,
            endpoint,
            payload: body,
          };
        }

        const res = await executeApiInPage('PATCH', endpoint, body);
        if (!res.ok) {
          return {
            success: false,
            error: `部署・プロジェクトの更新に失敗しました (HTTP ${res.status}): ${res.rawText || JSON.stringify(res.data) || res.statusText}`,
          };
        }

        const updatedData = await fetchAllBackgroundData();
        return {
          success: true,
          action: 'update',
          target: 'career_dept',
          isDryRun: false,
          updated: res.data,
          data: updatedData,
        };
      } else {
        // 企業職歴の更新
        const historyId = PAYLOAD.career_company_history_id || PAYLOAD.id || PAYLOAD.history_id;
        if (!historyId) {
          return { success: false, error: '更新対象の企業職歴ID (--id / --history-id) が指定されていません。' };
        }

        // 既存データを参照して必須項目を補完
        const curData = await fetchAllBackgroundData();
        const existingHist = (curData.career_company_histories || []).find(h => h.id === historyId);
        const compObj = existingHist?.company || {};
        const corpMaster = existingHist?.corporate_master || {};
        const defaultCompName = existingHist?.company_name || compObj.name || corpMaster.name || '';
        const defaultCorpNum = existingHist?.corporate_number || corpMaster.corporate_number || null;

        const endpoint = `/api/v3/users/@me/career_company_histories/${historyId}`;
        const histPayload = {
          company_name: PAYLOAD.company_name || defaultCompName,
          corporate_number: PAYLOAD.corporate_number !== undefined ? PAYLOAD.corporate_number : defaultCorpNum,
          label_type: PAYLOAD.label_type || existingHist?.label_type || 'label_type_none',
          joined_at: PAYLOAD.joined_at !== undefined ? PAYLOAD.joined_at : existingHist?.joined_at,
        };
        if (PAYLOAD.left_at) {
          histPayload.left_at = PAYLOAD.left_at;
        }
        const body = {
          career_company_history: histPayload,
        };

        if (IS_DRY_RUN) {
          return {
            success: true,
            action: 'update',
            target: 'career',
            isDryRun: true,
            id: historyId,
            endpoint,
            payload: body,
          };
        }

        const res = await executeApiInPage('PATCH', endpoint, body);
        if (!res.ok) {
          return {
            success: false,
            error: `企業職歴の更新に失敗しました (HTTP ${res.status}): ${res.rawText || JSON.stringify(res.data) || res.statusText} | Sent: ${JSON.stringify(body)}`,
          };
        }

        const updatedData = await fetchAllBackgroundData();
        return {
          success: true,
          action: 'update',
          target: 'career',
          isDryRun: false,
          updated: res.data,
          data: updatedData,
        };
      }
    }
  }

  // 5.4 削除 (delete)
  if (ACTION === 'delete') {
    if (TARGET === 'education') {
      const eduId = PAYLOAD.id || PAYLOAD.education_id;
      if (!eduId) {
        return { success: false, error: '削除対象の学歴ID (--id / --edu-id) が指定されていません。' };
      }
      const endpoint = `/api/v3/users/@me/educations/${eduId}`;

      if (IS_DRY_RUN) {
        return {
          success: true,
          action: 'delete',
          target: 'education',
          isDryRun: true,
          id: eduId,
          endpoint,
        };
      }

      const res = await executeApiInPage('DELETE', endpoint);
      if (!res.ok) {
        return {
          success: false,
          error: `学歴の削除に失敗しました (HTTP ${res.status}): ${JSON.stringify(res.data || res.error)}`,
        };
      }

      const updatedData = await fetchAllBackgroundData();
      return {
        success: true,
        action: 'delete',
        target: 'education',
        isDryRun: false,
        deleted_id: eduId,
        data: updatedData,
      };
    } else {
      // TARGET === 'career'
      if (PAYLOAD.career_id) {
        const historyId = PAYLOAD.career_company_history_id || PAYLOAD.history_id;
        if (!historyId) {
          return { success: false, error: '部署削除には企業職歴ID (--history-id) が必要です。' };
        }
        const endpoint = `/api/v3/users/@me/career_company_histories/${historyId}/careers/${PAYLOAD.career_id}`;

        if (IS_DRY_RUN) {
          return {
            success: true,
            action: 'delete',
            target: 'career_dept',
            isDryRun: true,
            history_id: historyId,
            career_id: PAYLOAD.career_id,
            endpoint,
          };
        }

        const res = await executeApiInPage('DELETE', endpoint);
        if (!res.ok) {
          return {
            success: false,
            error: `部署・プロジェクトの削除に失敗しました (HTTP ${res.status}): ${JSON.stringify(res.data || res.error)}`,
          };
        }

        const updatedData = await fetchAllBackgroundData();
        return {
          success: true,
          action: 'delete',
          target: 'career_dept',
          isDryRun: false,
          history_id: historyId,
          deleted_career_id: PAYLOAD.career_id,
          data: updatedData,
        };
      } else {
        // 企業職歴の削除
        const historyId = PAYLOAD.career_company_history_id || PAYLOAD.id || PAYLOAD.history_id;
        if (!historyId) {
          return { success: false, error: '削除対象の企業職歴ID (--id / --history-id) が指定されていません。' };
        }
        const endpoint = `/api/v3/users/@me/career_company_histories/${historyId}`;

        if (IS_DRY_RUN) {
          return {
            success: true,
            action: 'delete',
            target: 'career',
            isDryRun: true,
            id: historyId,
            endpoint,
          };
        }

        const res = await executeApiInPage('DELETE', endpoint);
        if (!res.ok) {
          return {
            success: false,
            error: `企業職歴の削除に失敗しました (HTTP ${res.status}): ${JSON.stringify(res.data || res.error)}`,
          };
        }

        const updatedData = await fetchAllBackgroundData();
        return {
          success: true,
          action: 'delete',
          target: 'career',
          isDryRun: false,
          deleted_id: historyId,
          data: updatedData,
        };
      }
    }
  }

  return {
    success: false,
    error: `未知のアクションです: ${ACTION}`,
  };
}
