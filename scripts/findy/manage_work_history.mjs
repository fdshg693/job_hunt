// scripts/findy/manage_work_history.mjs
// Findy「キャリア・スキル」画面（/me/career-skills）における
// 職歴（workHistories）およびプロジェクト（workHistoryProjects）の CRUD / マスタ取得を実行する Playwright スクリプト
// Python 側から action と variables が埋め込まれて実行されます。

async page => {
  const GRAPHQL_ENDPOINT = 'https://api.findy-code.io/graphql/user';

  const MUTATIONS = {
    createWorkHistory: `
      mutation CreateCareerSkillsWorkHistory($input: CreateWorkHistoryInput!) {
        createWorkHistory(input: $input) {
          clientMutationId
        }
      }
    `,
    updateWorkHistory: `
      mutation UpdateCareerSkillsWorkHistory($input: UpdateWorkHistoryInput!) {
        updateWorkHistory(input: $input) {
          clientMutationId
        }
      }
    `,
    deleteWorkHistory: `
      mutation DeleteCareerSkillsWorkHistory($input: DeleteWorkHistoryInput!) {
        deleteWorkHistory(input: $input) {
          success
        }
      }
    `,
    createWorkHistoryProject: `
      mutation CreateCareerSkillsWorkHistoryProject($input: CreateWorkHistoryProjectInput!) {
        createWorkHistoryProject(input: $input) {
          clientMutationId
        }
      }
    `,
    updateWorkHistoryProject: `
      mutation UpdateCareerSkillsWorkHistoryProject($input: UpdateWorkHistoryProjectInput!) {
        updateWorkHistoryProject(input: $input) {
          clientMutationId
        }
      }
    `,
    deleteWorkHistoryProject: `
      mutation DeleteCareerSkillsWorkHistoryProject($input: DeleteWorkHistoryProjectInput!) {
        deleteWorkHistoryProject(input: $input) {
          success
        }
      }
    `,
    fetchMasters: `
      query FetchMasters {
        allEmploymentPatterns {
          id
          name
        }
        allPositionTypes {
          id
          name
        }
        allTeamScaleTypes {
          id
          name
        }
        allJobRoles {
          id
          name
          identifier
          position
        }
      }
    `,
    searchSkills: `
      query FetchAllSearchSkills($query: String!) {
        allSearchSkills(query: $query) {
          id
          name
        }
      }
    `
  };

  const OPERATION_NAMES = {
    createWorkHistory: 'CreateCareerSkillsWorkHistory',
    updateWorkHistory: 'UpdateCareerSkillsWorkHistory',
    deleteWorkHistory: 'DeleteCareerSkillsWorkHistory',
    createWorkHistoryProject: 'CreateCareerSkillsWorkHistoryProject',
    updateWorkHistoryProject: 'UpdateCareerSkillsWorkHistoryProject',
    deleteWorkHistoryProject: 'DeleteCareerSkillsWorkHistoryProject',
    fetchMasters: 'FetchMasters',
    searchSkills: 'FetchAllSearchSkills'
  };

  const action = '__FINDY_ACTION__';
  const variables = __FINDY_VARIABLES__;

  if (!action || !MUTATIONS[action]) {
    return {
      success: false,
      error: `不正なアクションまたは未指定: ${action}. 利用可能: ${Object.keys(MUTATIONS).join(', ')}`
    };
  }

  const query = MUTATIONS[action];
  const operationName = OPERATION_NAMES[action];

  // ページがキャリア・スキル画面にいない場合は移動
  const currentUrl = page.url();
  if (!currentUrl.includes('findy-code.io')) {
    await page.goto('https://findy-code.io/me/career-skills', {
      waitUntil: 'domcontentloaded',
      timeout: 20000
    });
  }

  // ブラウザコンテキスト内で fetch を実行（Cookieが自動添付され、x-requested-with を付与）
  const result = await page.evaluate(
    async ({ endpoint, query, variables, operationName }) => {
      try {
        const url = `${endpoint}?opname=${encodeURIComponent(operationName)}`;
        const response = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': '*/*',
            'x-requested-with': 'XMLHttpRequest'
          },
          credentials: 'include',
          body: JSON.stringify({
            query,
            variables,
            operationName
          })
        });

        const status = response.status;
        const text = await response.text();
        let json;
        try {
          json = JSON.parse(text);
        } catch (_) {
          return {
            success: false,
            status,
            error: `APIレスポンスのパースに失敗しました (HTTP ${status}): ${text.slice(0, 200)}`
          };
        }

        if (json.errors && json.errors.length > 0) {
          const errorMsg = json.errors.map(e => e.message || JSON.stringify(e)).join('; ');
          return {
            success: false,
            status,
            error: `GraphQL Error: ${errorMsg}`,
            errors: json.errors,
            data: json.data
          };
        }

        return {
          success: true,
          status,
          data: json.data
        };
      } catch (err) {
        return {
          success: false,
          error: `Fetch例外: ${err.message}`
        };
      }
    },
    {
      endpoint: GRAPHQL_ENDPOINT,
      query,
      variables,
      operationName
    }
  );

  return result;
}
