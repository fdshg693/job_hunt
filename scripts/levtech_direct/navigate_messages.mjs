// scripts/levtech_direct/navigate_messages.mjs
// レバテックダイレクト（https://levtech-direct.jp/mypage/message）から
// スカウトおよびメッセージ一覧・スレッド詳細を取得する Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/levtech_direct/navigate_messages.mjs --raw

async page => {
  const result = {
    success: false,
    fetchedAt: new Date().toISOString(),
    url: 'https://levtech-direct.jp/mypage/message',
    tab: '__LEVTECH_TAB__',
    totalCount: 0,
    messages: [],
    errors: [],
  };

  const BASE_URL = 'https://levtech-direct.jp';
  const targetTab = ('__LEVTECH_TAB__' || 'active').toLowerCase();
  const fetchDetails = __FETCH_DETAILS__;
  const limit = __LIMIT__;

  try {
    const currentUrl = page.url();
    if (!currentUrl.includes('/mypage/message')) {
      await page.goto(`${BASE_URL}/mypage/message`, { waitUntil: 'domcontentloaded', timeout: 25000 });
    }
    await page.waitForTimeout(1500);

    // 1. 内部REST API経由でのアプローチ一覧取得（CSR利用）
    const apiResult = await page.evaluate(async () => {
      try {
        const res = await fetch('/api/employees/approaches', {
          headers: {
            'Accept': 'application/json, text/plain, */*',
          },
          credentials: 'include',
        });
        if (!res.ok) {
          return { error: `HTTP ${res.status}: ${res.statusText}` };
        }
        const data = await res.json();
        return { data };
      } catch (e) {
        return { error: e.message };
      }
    });

    let approaches = [];
    if (apiResult && apiResult.data && Array.isArray(apiResult.data.approach_list)) {
      approaches = apiResult.data.approach_list;
    } else {
      result.errors.push(`API approaches fetch failed: ${apiResult ? apiResult.error : 'Unknown error'}`);
    }

    // API取得が成功した場合
    if (approaches.length > 0) {
      // フィルタリング
      const filtered = approaches.filter(item => {
        if (targetTab === 'unread') {
          return !item.is_message_trashed && item.is_unread;
        } else if (targetTab === 'company') {
          return !item.is_message_trashed && !item.is_headhunter;
        } else if (targetTab === 'headhunter') {
          return !item.is_message_trashed && item.is_headhunter;
        } else if (targetTab === 'trash' || targetTab === 'archived') {
          return item.is_message_trashed;
        } else if (targetTab === 'all') {
          return true;
        } else {
          // active (デフォルト)
          return !item.is_message_trashed;
        }
      });

      const itemsToProcess = limit > 0 ? filtered.slice(0, limit) : filtered;

      // 各アイテムの詳細データ（スレッド履歴・面談情報）の取得
      const messageResults = [];
      for (const item of itemsToProcess) {
        const approachId = item.id;
        let threadMessages = [];
        let interviews = [];

        if (fetchDetails && approachId) {
          try {
            const detailRes = await page.evaluate(async (appId) => {
              const resObj = { messages: [], interviews: [] };
              try {
                const msgRes = await fetch(`/api/employees/approaches/${appId}/messages`, {
                  headers: { 'Accept': 'application/json, text/plain, */*' },
                  credentials: 'include',
                });
                if (msgRes.ok) {
                  const msgData = await msgRes.json();
                  resObj.messages = msgData.message_list || [];
                }
              } catch (_) {}

              try {
                const intRes = await fetch(`/api/employees/approaches/${appId}/interviews`, {
                  headers: { 'Accept': 'application/json, text/plain, */*' },
                  credentials: 'include',
                });
                if (intRes.ok) {
                  const intData = await intRes.json();
                  resObj.interviews = intData.interview_list || [];
                }
              } catch (_) {}

              return resObj;
            }, approachId);

            if (detailRes) {
              threadMessages = detailRes.messages || [];
              interviews = detailRes.interviews || [];
            }
          } catch (detErr) {
            result.errors.push(`Detail fetch error for approach ${approachId}: ${detErr.message}`);
          }
        }

        // バッジ生成
        const badges = [];
        if (item.is_unread) badges.push('未読');
        if (item.is_pinned) badges.push('ピン留め');
        if (item.is_scouted) {
          if (item.scout_option === 'request_meeting') {
            badges.push('スカウト（面談希望）');
          } else {
            badges.push('スカウト');
          }
        }
        if (item.is_headhunter) {
          badges.push('ヘッドハンター');
        } else {
          badges.push('企業直接');
        }
        if (item.is_message_trashed) badges.push('ゴミ箱');

        // 件名・本文・求人情報
        const subject = item.scouted_title ||
          (item.latest_message ? item.latest_message.title : '') ||
          (item.job ? item.job.title : '') ||
          '（件名なし）';

        let body = '';
        if (threadMessages.length > 0) {
          // 直近のメッセージ、またはスカウト本文
          const recruiterMsgs = threadMessages.filter(m => m.from_type === 'recruiter');
          const targetMsg = recruiterMsgs.length > 0 ? recruiterMsgs[recruiterMsgs.length - 1] : threadMessages[threadMessages.length - 1];
          body = targetMsg.content || '';
        } else if (item.latest_message && item.latest_message.content) {
          body = item.latest_message.content;
        } else if (item.scouted_message) {
          body = item.scouted_message;
        }

        const snippet = body ? body.replace(/\r?\n+/g, ' ').trim().slice(0, 200) : '';

        // 求人情報マッピング
        const jobInfo = item.job ? {
          id: item.job.id,
          title: item.job.title || '',
          salaryMin: item.job.min_annual_income ? `${item.job.min_annual_income}万円〜` : '',
          workStyle: item.job.job_work_style || '',
          appealPoints: Array.isArray(item.job.appeal_point_list)
            ? item.job.appeal_point_list.map(ap => ap.name).filter(Boolean)
            : [],
        } : null;

        messageResults.push({
          id: String(item.id),
          approachId: item.id,
          companyId: item.company_id,
          company: item.company_name || '企業名不明',
          companyLogo: item.logo_image || '',
          corporateNumber: item.corporate_number || '',
          isHeadhunter: !!item.is_headhunter,
          isScouted: !!item.is_scouted,
          isUnread: !!item.is_unread,
          isPinned: !!item.is_pinned,
          isTrashed: !!item.is_message_trashed,
          route: item.route || '',
          scoutOption: item.scout_option || '',
          progressStatus: item.progress_status || '',
          subject: subject,
          badges: badges,
          date: item.latest_message ? item.latest_message.sent_at : item.approach_created_at,
          createdAt: item.approach_created_at || '',
          threadUrl: `${BASE_URL}/mypage/message/${item.id}`,
          jobUrl: item.job && item.job.id ? `${BASE_URL}/job/${item.job.id}` : '',
          jobTitle: jobInfo ? jobInfo.title : '',
          jobSalary: jobInfo ? jobInfo.salaryMin : '',
          jobWorkStyle: jobInfo ? jobInfo.workStyle : '',
          job: jobInfo,
          latestMessage: item.latest_message || null,
          messagesCount: threadMessages.length,
          messages: threadMessages,
          interviews: interviews,
          body: body,
          snippet: snippet,
        });
      }

      result.success = true;
      result.totalCount = messageResults.length;
      result.messages = messageResults;
      return result;
    }

    // 2. フォールバック: DOMからのスクレイピング
    result.errors.push('Falling back to DOM extraction');
    const domMessages = await page.evaluate((maxLimit) => {
      const items = [];
      const listItems = document.querySelectorAll('ul.MuiList-root li.MuiListItem-root');
      const count = maxLimit > 0 ? Math.min(listItems.length, maxLimit) : listItems.length;

      for (let i = 0; i < count; i++) {
        const li = listItems[i];
        const btn = li.querySelector('button[data-display-name="TalkRoomListItem_ButtonBase"]');
        let additionalData = {};
        if (btn && btn.getAttribute('data-additional-value')) {
          try {
            additionalData = JSON.parse(btn.getAttribute('data-additional-value'));
          } catch (_) {}
        }

        const companyEl = li.querySelector('p.MuiTypography-body1');
        const company = companyEl ? companyEl.innerText.trim() : '企業名不明';

        const subjectEl = li.querySelector('p.MuiTypography-body2');
        const subject = subjectEl ? subjectEl.innerText.trim() : '（件名なし）';

        const chips = Array.from(li.querySelectorAll('.MuiChip-root .MuiChip-label')).map(c => c.innerText.trim());
        const dateEl = li.querySelectorAll('p.MuiTypography-body2');
        const dateText = dateEl.length > 1 ? dateEl[dateEl.length - 1].innerText.trim() : '';

        const approachId = additionalData.approach_id ? String(additionalData.approach_id) : '';

        items.push({
          id: approachId,
          approachId: additionalData.approach_id || null,
          company: company,
          subject: subject,
          badges: chips,
          date: dateText,
          isUnread: !!additionalData.unread,
          threadUrl: approachId ? `https://levtech-direct.jp/mypage/message/${approachId}` : '',
          jobUrl: '',
          body: '',
          snippet: subject,
        });
      }
      return items;
    }, limit);

    result.success = true;
    result.totalCount = domMessages.length;
    result.messages = domMessages;
    return result;

  } catch (globalErr) {
    result.errors.push(`Global error: ${globalErr.message}`);
    return result;
  }
}
