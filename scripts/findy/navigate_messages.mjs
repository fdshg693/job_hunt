// scripts/findy/navigate_messages.mjs
// Findyのメッセージ一覧画面（/matches）へ遷移し、GraphQL API (FetchMessageContexts) または DOM から
// メッセージ・スカウト一覧を取得・構造化して返却する Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/findy/navigate_messages.mjs --raw

async page => {
  const targetUrl = 'https://findy-code.io/matches';

  // メッセージ一覧画面に未到達の場合は遷移
  if (!page.url().includes('/matches')) {
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 20000 });
  }

  // 画面レンダリング待機
  try {
    await page.waitForSelector('main, h1, [class*="match"], [class*="message"]', {
      timeout: 10000
    });
  } catch (_) {
    // タイムアウトしてもGraphQL fetchを試行
  }

  // URL文字列からタブ・件数パラメータを安全に抽出（環境依存を排除）
  const currentUrl = page.url();
  let filterTab = 'all';
  const tabMatch = currentUrl.match(/[?&]tab=([^&#]+)/);
  if (tabMatch) {
    filterTab = decodeURIComponent(tabMatch[1]);
  }

  let requestedLimit = 0;
  const limitMatch = currentUrl.match(/[?&]limit=([0-9]+)/);
  if (limitMatch) {
    requestedLimit = parseInt(limitMatch[1], 10);
  }

  const pageSize = 50;

  // GraphQLクエリ定義
  const GRAPHQL_QUERY = `
query FetchMessageContexts($page: Int, $pageSize: Int, $filter: MessageContextsFilter) {
  messageContexts(page: $page, pageSize: $pageSize, filter: $filter) {
    ...MessageContextPagination
    __typename
  }
}

fragment MessageContextPagination on MessageContextPagination {
  list {
    ...MessageContextMatch
    ...MessageContextFindyMessageConversation
    ...MessageContextEnterprisePremiumScout
    ...MessageContextAgentMatch
    __typename
  }
  paginationInfo {
    ...MessageContextWithOffsetPageInfo
    __typename
  }
  __typename
}

fragment MessageContextMatch on Match {
  __typename
  id
  matchHash
  jobDescription {
    id
    company {
      id
      name
      __typename
    }
    __typename
  }
  enterprisePremiumScouts {
    __typename
    id
    messages {
      id
      message
      createdAt
      __typename
    }
  }
  isArchived
  isPinned
  isReadAllMessagesFromUser
  isRepliedScout
  isRepliedMessage
  isUserSuccessConsultation
  isUserSuccessCommitmentJobInterview
  latestMessage {
    ...MessageContextEnterpriseUserMessage
    ...MessageContextUserMessage
    __typename
  }
  updatedAt
}

fragment MessageContextEnterpriseUserMessage on EnterpriseUserMessage {
  ...MessageContextEnterpriseUserMessageBase
  message
  __typename
}

fragment MessageContextEnterpriseUserMessageBase on EnterpriseUserMessage {
  __typename
  id
  createdAt
  userReadAt
}

fragment MessageContextUserMessage on UserMessage {
  ...MessageContextUserMessageBase
  message
  __typename
}

fragment MessageContextUserMessageBase on UserMessage {
  __typename
  id
  createdAt
}

fragment MessageContextFindyMessageConversation on FindyMessageConversation {
  __typename
  conversationHash
  id
  isRepliedMessage
  isAllUserRead
  latestMessage {
    ...MessageContextFindyMessageAdminUserMessage
    ...MessageContextFindyMessageUserMessage
    __typename
  }
}

fragment MessageContextFindyMessageAdminUserMessage on FindyMessageAdminUserMessage {
  ...MessageContextFindyMessageAdminUserMessageBase
  message
  __typename
}

fragment MessageContextFindyMessageAdminUserMessageBase on FindyMessageAdminUserMessage {
  __typename
  createdAt
  id
  isRead
}

fragment MessageContextFindyMessageUserMessage on FindyMessageUserMessage {
  ...MessageContextFindyMessageUserMessageBase
  message
  __typename
}

fragment MessageContextFindyMessageUserMessageBase on FindyMessageUserMessage {
  __typename
  createdAt
  id
}

fragment MessageContextEnterprisePremiumScout on EnterprisePremiumScout {
  __typename
  createdAt
  updatedAt
  id
  scoutHash
  isArchived
  isReadAllMessagesFromUser
  isRepliedMessage
  jobDescription {
    id
    company {
      id
      name
      __typename
    }
    __typename
  }
  match {
    id
    latestMessage {
      ...MessageContextEnterpriseUserMessage
      ...MessageContextUserMessage
      __typename
    }
    __typename
  }
  premiumScoutMessages: messages {
    ...MessageContextEnterprisePremiumScoutMessage
    __typename
  }
}

fragment MessageContextEnterprisePremiumScoutMessage on EnterprisePremiumScoutMessage {
  createdAt
  id
  message
  __typename
}

fragment MessageContextAgentMatch on AgentMatch {
  __typename
  id
  matchHash
  createdAt
  lastCommunicatedAt
  isAllUserRead
  isRepliedMessage
  agentJobDescription {
    id
    companySummary {
      id
      name
      __typename
    }
    __typename
  }
  latestMessage {
    id
    message
    createdAt
    __typename
  }
}

fragment MessageContextWithOffsetPageInfo on WithOffsetPageInfo {
  pageSize
  currentPage
  totalCount
  totalPagesCount
  __typename
}
`;

  // フィルター引数マッピング
  let filterParam = null;
  if (filterTab === 'unread') {
    filterParam = { isReadMessage: false };
  } else if (filterTab === 'unreplied') {
    filterParam = { isRepliedMessage: false };
  } else if (filterTab === 'archived') {
    filterParam = { isArchived: true };
  }

  // ブラウザ内 evaluate で GraphQL API を直接実行
  let apiResult = null;
  try {
    apiResult = await page.evaluate(
      async ({ query, filter, limit, pSize }) => {
        let currentPage = 1;
        let allItems = [];
        let totalCount = 0;
        let totalPages = 1;

        while (currentPage <= totalPages) {
          const res = await fetch(
            'https://api.findy-code.io/graphql/user?opname=FetchMessageContexts',
            {
              method: 'POST',
              headers: {
                'content-type': 'application/json',
                'x-requested-with': 'XMLHttpRequest'
              },
              credentials: 'include',
              body: JSON.stringify({
                operationName: 'FetchMessageContexts',
                variables: {
                  page: currentPage,
                  pageSize: pSize,
                  filter: filter
                },
                query: query
              })
            }
          );

          if (!res.ok) {
            break;
          }

          const json = await res.json();
          const mc = json?.data?.messageContexts;
          if (!mc || !mc.list) {
            break;
          }

          totalCount = mc.paginationInfo?.totalCount ?? mc.list.length;
          totalPages = mc.paginationInfo?.totalPagesCount ?? 1;
          allItems = allItems.concat(mc.list);

          if (limit > 0 && allItems.length >= limit) {
            allItems = allItems.slice(0, limit);
            break;
          }

          if (currentPage >= totalPages) {
            break;
          }
          currentPage += 1;
        }

        return {
          totalCount,
          totalPages,
          rawList: allItems
        };
      },
      { query: GRAPHQL_QUERY, filter: filterParam, limit: requestedLimit, pSize: pageSize }
    );
  } catch (err) {
    // APIフェッチ失敗時はフォールバックへ進む
  }

  // GraphQL結果の正規化
  let normalizedMessages = [];
  if (apiResult && Array.isArray(apiResult.rawList) && apiResult.rawList.length > 0) {
    for (const item of apiResult.rawList) {
      const typeName = item.__typename || '';
      let id = item.id;
      let threadUrl = '';
      let company = '企業名不明';
      let jobId = null;
      let jobUrl = null;
      let scoutType = '通常';
      let isUnread = false;
      let isReplied = false;
      let isArchived = !!item.isArchived;
      let isPinned = !!item.isPinned;
      let latestMessageText = '';
      let latestMessageAt = '';
      let updatedAt = item.updatedAt || '';
      let subject = '';

      if (typeName === 'Match') {
        const hash = item.matchHash || item.id;
        threadUrl = `https://findy-code.io/matches/${hash}`;
        company = item.jobDescription?.company?.name || '企業名不明';
        jobId = item.jobDescription?.id || null;
        if (jobId && item.jobDescription?.company?.id) {
          jobUrl = `https://findy-code.io/companies/${item.jobDescription.company.id}/jobs/${jobId}`;
        }

        const scouts = item.enterprisePremiumScouts || [];
        if (scouts.length > 0) {
          scoutType = 'プレミアムスカウト';
          const firstMsg = scouts[0]?.messages?.[0]?.message || '';
          if (firstMsg) {
            const lines = firstMsg.split('\n').map(l => l.trim()).filter(Boolean);
            subject = lines[0] || '';
          }
        }

        isUnread = !item.isReadAllMessagesFromUser;
        isReplied = !!(item.isRepliedMessage || item.isRepliedScout);

        const lm = item.latestMessage;
        if (lm) {
          latestMessageText = lm.message || '';
          latestMessageAt = lm.createdAt || '';
          if (lm.userReadAt === null) {
            isUnread = true;
          }
        }
      } else if (typeName === 'EnterprisePremiumScout') {
        const hash = item.scoutHash || item.id;
        threadUrl = `https://findy-code.io/matches/${hash}`;
        company = item.jobDescription?.company?.name || '企業名不明';
        jobId = item.jobDescription?.id || null;
        if (jobId && item.jobDescription?.company?.id) {
          jobUrl = `https://findy-code.io/companies/${item.jobDescription.company.id}/jobs/${jobId}`;
        }
        scoutType = 'プレミアムスカウト';
        isUnread = !item.isReadAllMessagesFromUser;
        isReplied = !!item.isRepliedMessage;
        updatedAt = item.updatedAt || item.createdAt || '';

        const pMsgs = item.premiumScoutMessages || [];
        if (pMsgs.length > 0) {
          const first = pMsgs[0];
          latestMessageText = first.message || '';
          latestMessageAt = first.createdAt || '';
          const lines = latestMessageText.split('\n').map(l => l.trim()).filter(Boolean);
          subject = lines[0] || '';
        }
        if (item.match?.latestMessage) {
          const lm = item.match.latestMessage;
          latestMessageText = lm.message || latestMessageText;
          latestMessageAt = lm.createdAt || latestMessageAt;
        }
      } else if (typeName === 'AgentMatch') {
        const hash = item.matchHash || item.id;
        threadUrl = `https://findy-code.io/matches/${hash}`;
        company = item.agentJobDescription?.companySummary?.name || 'エージェント紹介求人';
        jobId = item.agentJobDescription?.id || null;
        scoutType = 'エージェント';
        isUnread = !item.isAllUserRead;
        isReplied = !!item.isRepliedMessage;
        updatedAt = item.lastCommunicatedAt || item.createdAt || '';

        const lm = item.latestMessage;
        if (lm) {
          latestMessageText = lm.message || '';
          latestMessageAt = lm.createdAt || '';
        }
      } else if (typeName === 'FindyMessageConversation') {
        const hash = item.conversationHash || item.id;
        threadUrl = `https://findy-code.io/matches/${hash}`;
        company = 'Findy運営事務局';
        scoutType = '事務局連絡';
        isUnread = !item.isAllUserRead;
        isReplied = !!item.isRepliedMessage;

        const lm = item.latestMessage;
        if (lm) {
          latestMessageText = lm.message || '';
          latestMessageAt = lm.createdAt || '';
          if (lm.isRead === false) {
            isUnread = true;
          }
        }
      }

      if (!subject && latestMessageText) {
        const bracketMatch = latestMessageText.match(/【([^】]+)】/);
        if (bracketMatch) {
          subject = `【${bracketMatch[1]}】`;
        } else {
          const lines = latestMessageText.split('\n').map(l => l.trim()).filter(Boolean);
          let candidate = lines[0] || '';
          if (candidate.match(/^.+様$/) && lines.length > 1) {
            candidate = `${candidate} - ${lines[1]}`;
          }
          subject = candidate.length > 50 ? `${candidate.slice(0, 50)}...` : candidate;
        }
      }

      const snippet = latestMessageText
        ? latestMessageText.replace(/\r?\n+/g, ' ').trim().slice(0, 150)
        : '';

      normalizedMessages.push({
        id,
        type: typeName,
        company,
        jobId,
        jobUrl,
        subject: subject || '（件名・タイトルなし）',
        snippet,
        latestMessage: latestMessageText,
        date: latestMessageAt || updatedAt,
        url: threadUrl,
        isUnread,
        isReplied,
        isArchived,
        isPinned,
        scoutType
      });
    }
  }

  // DOM フォールバック（GraphQL API で取得できなかった場合）
  if (normalizedMessages.length === 0) {
    const domExtraction = await page.evaluate(() => {
      const cardLinks = Array.from(
        document.querySelectorAll('a[href^="/matches/"]')
      );
      const items = [];
      const seen = new Set();

      for (const link of cardLinks) {
        const href = link.getAttribute('href') || '';
        const cleanHref = href.split('?')[0];
        if (!cleanHref || cleanHref === '/matches' || seen.has(cleanHref)) {
          continue;
        }
        seen.add(cleanHref);

        const fullUrl = cleanHref.startsWith('http')
          ? cleanHref
          : `https://findy-code.io${cleanHref}`;

        const compEl = link.querySelector('[class*="companyName"], [class*="company-name"], [class*="company"]');
        const comp = compEl ? compEl.textContent.trim() : '企業名不明';

        const textEl = link.querySelector('[class*="messageCardText"], [class*="message"], [class*="snippet"]');
        const text = textEl ? textEl.textContent.trim() : '';

        const dateEl = link.querySelector('[class*="updateAt"], [class*="date"], time');
        const date = dateEl ? dateEl.textContent.trim() : '';

        const isUnread = !!link.querySelector('[class*="unread"], [class*="badge-unread"]');
        const isReplied = !link.querySelector('[class*="noReply"], [class*="not-replied"]');
        const isPremium = link.textContent.includes('プレミアム') || !!link.querySelector('[class*="premium"]');

        items.push({
          company: comp,
          subject: text ? text.slice(0, 40) : '（件名なし）',
          snippet: text ? text.slice(0, 150) : '',
          latestMessage: text,
          date: date,
          url: fullUrl,
          isUnread: isUnread,
          isReplied: isReplied,
          scoutType: isPremium ? 'プレミアムスカウト' : '通常'
        });
      }
      return items;
    });

    if (domExtraction.length > 0) {
      normalizedMessages = domExtraction;
    }
  }

  // 件数制限
  if (requestedLimit > 0 && normalizedMessages.length > requestedLimit) {
    normalizedMessages = normalizedMessages.slice(0, requestedLimit);
  }

  const finalUrl = page.url();
  const pageTitle = await page.title();
  const totalCount = apiResult?.totalCount ?? normalizedMessages.length;

  return {
    success: normalizedMessages.length > 0 || finalUrl.includes('/matches'),
    source: 'findy',
    url: finalUrl,
    title: pageTitle,
    tab: filterTab,
    totalCount: totalCount,
    fetchedCount: normalizedMessages.length,
    messages: normalizedMessages,
    extractionSource: apiResult ? 'graphql' : 'dom'
  };
}
