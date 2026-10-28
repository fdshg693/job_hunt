// scripts/youtrust/navigate_messages.mjs
// YOUTRUST チャットルーム一覧およびメッセージ詳細取得 Playwright スクリプト
// Python側の execute_navigate_messages からパラメータ置換されて実行されます。

async page => {
  const BOX_TYPE = '__BOX_TYPE__'; // 'all', 'scout', 'unread', 'sales'
  const LIMIT = parseInt('__LIMIT__', 10) || 0;
  const FETCH_THREADS = __FETCH_THREADS__; // boolean
  const ROOM_ID = '__ROOM_ID__'; // string (optional)
  const MARK_AS_READ = __MARK_AS_READ__; // boolean

  const TARGET_URL = 'https://youtrust.jp/chat_rooms';

  // 1. ページ遷移
  if (!page.url().includes('/chat_rooms')) {
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

  // 3. データ取得ロジック (page.evaluate 内で内部REST APIを実行)
  const result = await page.evaluate(
    async ({ boxType, limit, fetchThreads, targetRoomId, markAsRead }) => {
      const fetchJson = async (endpoint, options = {}) => {
        try {
          const res = await fetch(endpoint, {
            headers: {
              Accept: 'application/json',
              'Content-Type': 'application/json',
              ...(options.headers || {}),
            },
            credentials: 'include',
            ...options,
          });
          if (!res.ok) {
            return { status: res.status, error: res.statusText, data: null };
          }
          const data = await res.json();
          return { status: res.status, data };
        } catch (e) {
          return { error: e.message, data: null };
        }
      };

      const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

      // 共通: 特定ルームの詳細情報（プロフィール・スレッド含む）を取得する関数
      const fetchSingleRoomDetail = async roomId => {
        // 基本情報
        const baseRes = await fetchJson(`/api/v2/chat_rooms/${roomId}`);
        const baseRoom = baseRes.data?.chat_rooms?.[0] || null;

        // 詳細情報（相手プロフィール、採用チーム等）
        const detailRes = await fetchJson(`/api/chat_rooms/${roomId}`);
        const detailData = detailRes.data || {};

        // 相手ユーザーの抽出
        const roomUsers = detailData.room_users || [];
        const otherDetailUser = roomUsers.find(u => !u.is_me) || null;

        let threadLines = [];
        if (fetchThreads || targetRoomId) {
          const linesRes = await fetchJson(`/api/chat_rooms/${roomId}/chat_room_line_ids`);
          const lineIds = linesRes.data?.chat_room_line_ids || [];

          for (const lineId of lineIds) {
            const lineDetail = await fetchJson(`/api/chat_rooms/${roomId}/chat_room_lines/${lineId}`);
            const item = lineDetail.data?.chat_room_lines?.[0];
            if (item) {
              threadLines.push({
                id: item.id,
                type: item.type,
                commentId: item.comment?.id,
                comment: item.comment?.comment || '',
                rawComment: item.comment?.raw_comment || '',
                createdAt: item.comment?.created_at,
                orderId: item.comment?.order_id,
                readAt: item.comment?.read_at,
                sender: {
                  id: item.comment?.user?.id,
                  name: item.comment?.user?.name,
                  profileImageUrl: item.comment?.user?.profile_image_url,
                },
              });
            }
            await delay(100); // 軽微なインターバル
          }

          // 意図的な既読化オプション
          if (markAsRead) {
            await fetchJson(`/api/v3/chat_rooms/${roomId}/mark_as_read`, {
              method: 'PATCH',
            });
          }
        }

        // 相手ユーザー情報の正規化
        const users = baseRoom?.users || [];
        const baseOtherUser = users.find(u => !u.is_me) || {};
        const companies = baseOtherUser.companies || baseOtherUser.affiliations || [];
        const companyName = companies[0]?.name || detailData.recruiter_team?.company_name || '';

        return {
          id: roomId,
          displayName: baseRoom?.display_name || detailData.display_name || '',
          chatRoomType: baseRoom?.chat_room_type || detailData.chat_room_type || '',
          scoutChatRoomType: baseRoom?.scout_chat_room_type || '',
          unreadCount: baseRoom?.unread_count || 0,
          isBookmarked: baseRoom?.is_bookmarked || false,
          isArchived: baseRoom?.is_archived || false,
          isMuted: baseRoom?.is_muted || false,
          lastCommentedAt: baseRoom?.last_commented_at || 0,
          lastCommentContent: baseRoom?.last_comment_content || '',
          lastComment: baseRoom?.last_comment || null,
          otherUser: {
            id: otherDetailUser?.id || baseOtherUser.id || '',
            name: otherDetailUser?.name || baseOtherUser.name || '',
            companyName: companyName,
            isRecruiter: otherDetailUser?.is_recruiter_account ?? baseOtherUser.is_recruiter_account ?? false,
            isSales: otherDetailUser?.is_sales_account ?? baseOtherUser.is_sales_account ?? false,
            isHeadhunter: otherDetailUser?.is_headhunter_account ?? baseOtherUser.is_headhunter_account ?? false,
            jobCategories: otherDetailUser?.v3_job_category_names || [],
            skills: (otherDetailUser?.skills || []).map(s => s.name || s),
            introduction: otherDetailUser?.introduction_content || '',
            lastLoginAt: otherDetailUser?.last_login_at || null,
          },
          recruiterTeam: detailData.recruiter_team
            ? {
                companyName: detailData.recruiter_team.company_name || '',
                companyId: detailData.recruiter_team.company_id || '',
                logoUrl: detailData.recruiter_team.logo_image_url || '',
              }
            : null,
          thread: threadLines,
        };
      };

      // Case A: 特定の room_id が指定された場合
      if (targetRoomId) {
        try {
          const room = await fetchSingleRoomDetail(targetRoomId);
          return {
            success: true,
            boxType,
            totalCount: 1,
            chatRoomIds: [targetRoomId],
            rooms: [room],
          };
        } catch (e) {
          return {
            success: false,
            error: `チャットルーム(${targetRoomId})の取得に失敗しました: ${e.message}`,
          };
        }
      }

      // Case B: チャットルーム一覧の取得
      const params = new URLSearchParams();
      if (boxType === 'unread') {
        params.set('is_only_unread', 'true');
      } else if (boxType === 'sales') {
        params.set('chat_room_types', 'sales_chat,group_sales');
      }

      const listUrl = `/api/v2/chat_rooms${params.toString() ? `?${params.toString()}` : ''}`;
      const listRes = await fetchJson(listUrl);
      if (!listRes.data) {
        return {
          success: false,
          error: `チャットルーム一覧API取得エラー: ${listRes.error || listRes.status}`,
        };
      }

      let roomIds = listRes.data.chat_room_ids || [];
      const totalAvailable = roomIds.length;

      if (limit > 0 && roomIds.length > limit) {
        roomIds = roomIds.slice(0, limit);
      }

      const rooms = [];
      for (const roomId of roomIds) {
        try {
          const room = await fetchSingleRoomDetail(roomId);

          // scout フィルタのチェック (boxType === 'scout' の場合)
          if (boxType === 'scout') {
            if (
              room.chatRoomType !== 'scout_chat' &&
              !room.otherUser.isRecruiter &&
              !room.otherUser.isHeadhunter
            ) {
              continue;
            }
          }

          rooms.push(room);
          await delay(150); // APIレートリミット保護
        } catch (e) {
          console.error(`Error fetching room ${roomId}:`, e);
        }
      }

      return {
        success: true,
        boxType,
        totalAvailable,
        totalCount: rooms.length,
        chatRoomIds: roomIds,
        rooms,
      };
    },
    {
      boxType: BOX_TYPE,
      limit: LIMIT,
      fetchThreads: FETCH_THREADS,
      targetRoomId: ROOM_ID,
      markAsRead: MARK_AS_READ,
    }
  );

  return {
    ...result,
    url: page.url(),
  };
}
