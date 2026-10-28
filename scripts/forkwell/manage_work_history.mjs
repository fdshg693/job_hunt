// scripts/forkwell/manage_work_history.mjs
// Forkwell Jobs ダッシュボード（/dashboard）における
// 職歴・プロジェクト（company_users）の CRUD を実行する Playwright スクリプト
// Python側の execute_manage_action からテンプレート置換されて実行されます。

async page => {
  const ACTION = '__FORKWELL_ACTION__';
  const PAYLOAD = __FORKWELL_PAYLOAD__;

  const BASE_URL = 'https://jobs.forkwell.com';

  const result = {
    success: false,
    action: ACTION,
    timestamp: new Date().toISOString(),
    data: {},
    error: null,
  };

  try {
    // ダッシュボード画面への遷移確認
    const currentUrl = page.url();
    if (!currentUrl.includes('/dashboard') || currentUrl.includes('/preferences') || currentUrl.includes('/skills')) {
      await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'domcontentloaded', timeout: 20000 });
    }
    await page.waitForTimeout(500);

    // CSRFトークンおよびヘルパー関数をブラウザ内で評価
    const apiResult = await page.evaluate(
      async ({ action, payload }) => {
        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';

        const headers = {
          'Accept': 'application/json',
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        };
        if (csrfToken) {
          headers['X-CSRF-Token'] = csrfToken;
        }

        const endpointBase = '/api/v1/profile/company_users';

        // 1. 一覧取得 (list)
        if (action === 'list') {
          const res = await fetch(endpointBase, {
            method: 'GET',
            headers: {
              'Accept': 'application/json',
              'X-Requested-With': 'XMLHttpRequest',
            },
            credentials: 'include',
          });
          if (!res.ok) {
            const errText = await res.text();
            return { ok: false, status: res.status, error: `一覧取得エラー (HTTP ${res.status}): ${errText.slice(0, 200)}` };
          }
          const json = await res.json();
          return { ok: true, status: res.status, data: json };
        }

        // 2. 新規作成 (create)
        if (action === 'create') {
          const res = await fetch(endpointBase, {
            method: 'POST',
            headers,
            credentials: 'include',
            body: JSON.stringify(payload),
          });
          const text = await res.text();
          let json = null;
          try {
            json = JSON.parse(text);
          } catch (_) {}

          if (!res.ok) {
            return {
              ok: false,
              status: res.status,
              error: `新規作成エラー (HTTP ${res.status}): ${json ? JSON.stringify(json) : text.slice(0, 200)}`,
            };
          }
          return { ok: true, status: res.status, data: json || text };
        }

        // 3. 更新 (update)
        if (action === 'update') {
          const id = payload.id;
          if (!id) {
            return { ok: false, error: '更新対象のIDが指定されていません。' };
          }
          const res = await fetch(`${endpointBase}/${id}`, {
            method: 'PATCH',
            headers,
            credentials: 'include',
            body: JSON.stringify(payload),
          });
          const text = await res.text();
          let json = null;
          try {
            json = JSON.parse(text);
          } catch (_) {}

          if (!res.ok) {
            return {
              ok: false,
              status: res.status,
              error: `更新エラー (HTTP ${res.status}): ${json ? JSON.stringify(json) : text.slice(0, 200)}`,
            };
          }
          return { ok: true, status: res.status, data: json || text };
        }

        // 4. 削除 (delete)
        if (action === 'delete') {
          const id = payload.id;
          if (!id) {
            return { ok: false, error: '削除対象のIDが指定されていません。' };
          }
          const res = await fetch(`${endpointBase}/${id}`, {
            method: 'DELETE',
            headers: {
              'X-Requested-With': 'XMLHttpRequest',
              'X-CSRF-Token': csrfToken,
              'Accept': '*/*',
            },
            credentials: 'include',
          });
          if (!res.ok) {
            const errText = await res.text();
            return { ok: false, status: res.status, error: `削除エラー (HTTP ${res.status}): ${errText.slice(0, 200)}` };
          }
          return { ok: true, status: res.status, data: { deletedId: id } };
        }

        return { ok: false, error: `未知のアクション: ${action}` };
      },
      { action: ACTION, payload: PAYLOAD }
    );

    if (!apiResult.ok) {
      result.success = false;
      result.error = apiResult.error || `HTTP ${apiResult.status}`;
      return result;
    }

    result.success = true;
    result.data = apiResult.data;
    return result;
  } catch (err) {
    result.success = false;
    result.error = err.message || String(err);
    return result;
  }
}
