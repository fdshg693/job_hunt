// scripts/youtrust/manage_profile.mjs
// YOUTRUST プロフィール（基本情報・自己紹介・場所等）の閲覧・更新 Playwright スクリプト
// Python側の execute_manage_action からテンプレート置換されて実行されます。

async page => {
  const ACTION = '__YOUTRUST_ACTION__';
  const PAYLOAD = __YOUTRUST_PAYLOAD__;
  const IS_DRY_RUN = __YOUTRUST_DRY_RUN__;

  const TARGET_URL = 'https://youtrust.jp/settings/profile';

  // 1. ページ遷移
  if (!page.url().includes('/settings/profile')) {
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

  // 3. データ取得ヘルパー
  const fetchAllProfileData = async () => {
    // REST API経由の構造化データ取得
    const apiData = await page.evaluate(async () => {
      const fetchJson = async endpoint => {
        try {
          const res = await fetch(endpoint, {
            headers: { Accept: 'application/json' },
            credentials: 'include',
          });
          if (!res.ok) return { status: res.status, error: res.statusText };
          return { status: res.status, data: await res.json() };
        } catch (e) {
          return { error: e.message };
        }
      };

      const [sessionUser, me, affiliations, careers, motivation, qualifications, awards, links] =
        await Promise.all([
          fetchJson('/api/session_user'),
          fetchJson('/api/users/@me'),
          fetchJson('/api/users/@me/user_current_affiliations'),
          fetchJson('/api/v2/users/@me/careers'),
          fetchJson('/api/users/@me/career_motivation'),
          fetchJson('/api/users/@me/user_profile_qualifications'),
          fetchJson('/api/users/@me/user_profile_awards'),
          fetchJson('/api/users/@me/user_profile_links'),
        ]);

      return {
        sessionUser: sessionUser.data || null,
        me: me.data || null,
        affiliations: affiliations.data?.user_current_affiliations || affiliations.data || null,
        careers: careers.data?.careers || careers.data || null,
        motivation: motivation.data?.career_motivation || motivation.data || null,
        qualifications: qualifications.data?.user_profile_qualifications || qualifications.data || null,
        awards: awards.data?.user_profile_awards || awards.data || null,
        links: links.data?.user_profile_links || links.data || null,
      };
    });

    // DOM経由の現在値取得
    const domData = await page.evaluate(() => {
      const nameInput = document.querySelector('input[placeholder="テキスト"]');
      const businessNameInput = document.querySelector('input[placeholder="ニックネーム、旧姓など"]');
      const locationDetailInput = document.querySelector('input[placeholder="田園都市線の民"]');
      const introTextarea = document.querySelector('textarea:not([aria-hidden="true"])');
      const saveButton = Array.from(document.querySelectorAll('button')).find(
        b => b.textContent && b.textContent.includes('保存')
      );

      // 場所Select表示（生年月日のdisabledなcomboboxを除外）
      const locationSelect = document.querySelector('div[role="combobox"]:not([aria-disabled="true"])');
      const locationText = locationSelect ? locationSelect.textContent.trim() : '';

      // ラジオボタン
      const radioFriend = document.querySelector('input[type="radio"][value="birthday_scope_friend"]');
      const radioPrivate = document.querySelector('input[type="radio"][value="birthday_scope_private"]');
      let birthdayScope = 'friend';
      if (radioPrivate && radioPrivate.checked) {
        birthdayScope = 'private';
      } else if (radioFriend && radioFriend.checked) {
        birthdayScope = 'friend';
      }

      const radioAllUsers = document.querySelector('input[type="radio"][value="all_users"]');
      const radioOnlyFriends = document.querySelector('input[type="radio"][value="only_friends"]');
      let locationScope = 'only_friends';
      if (radioAllUsers && radioAllUsers.checked) {
        locationScope = 'all_users';
      } else if (radioOnlyFriends && radioOnlyFriends.checked) {
        locationScope = 'only_friends';
      }

      return {
        name: nameInput ? nameInput.value : '',
        businessName: businessNameInput ? businessNameInput.value : '',
        location: locationText === '例: 東京都' ? '' : locationText,
        locationDetail: locationDetailInput ? locationDetailInput.value : '',
        birthdayScope,
        locationScope,
        introduction: introTextarea ? introTextarea.value : '',
        saveButtonDisabled: saveButton ? saveButton.disabled : true,
      };
    });

    return {
      api: apiData,
      dom: domData,
    };
  };

  // 4. アクション分岐
  if (ACTION === 'show' || ACTION === 'view' || ACTION === 'backup') {
    const profile = await fetchAllProfileData();
    return {
      success: true,
      action: ACTION,
      data: profile,
    };
  }

  if (ACTION === 'update') {
    // 変更前データの取得
    const prevData = await fetchAllProfileData();
    const prevDom = prevData.dom;

    const changes = {};
    const previous = {};

    // 名前
    if (PAYLOAD.name !== undefined && PAYLOAD.name !== null && PAYLOAD.name !== prevDom.name) {
      previous.name = prevDom.name;
      changes.name = PAYLOAD.name;
      const nameInput = page.locator('input[placeholder="テキスト"]');
      await nameInput.fill(PAYLOAD.name);
      await page.waitForTimeout(300);
    }

    // ビジネスネーム
    if (PAYLOAD.business_name !== undefined && PAYLOAD.business_name !== null && PAYLOAD.business_name !== prevDom.businessName) {
      previous.business_name = prevDom.businessName;
      changes.business_name = PAYLOAD.business_name;
      const bInput = page.locator('input[placeholder="ニックネーム、旧姓など"]');
      await bInput.fill(PAYLOAD.business_name);
      await page.waitForTimeout(300);
    }

    // 場所（都道府県）
    if (PAYLOAD.location !== undefined && PAYLOAD.location !== null && PAYLOAD.location !== prevDom.location) {
      previous.location = prevDom.location;
      changes.location = PAYLOAD.location;
      const combobox = page.locator('div[tabindex="0"][role="combobox"]:not([aria-disabled="true"])');
      await combobox.click();
      await page.waitForTimeout(500);
      const option = page.locator('li[role="option"]').filter({ hasText: new RegExp(`^${PAYLOAD.location}$`) }).first();
      if (await option.count() > 0) {
        await option.click();
      } else {
        // オプションが見つからない場合はEscapeで閉じる
        await page.keyboard.press('Escape');
      }
      await page.waitForTimeout(300);
    }

    // 場所の補足
    if (PAYLOAD.location_detail !== undefined && PAYLOAD.location_detail !== null && PAYLOAD.location_detail !== prevDom.locationDetail) {
      previous.location_detail = prevDom.locationDetail;
      changes.location_detail = PAYLOAD.location_detail;
      const locDetailInput = page.locator('input[placeholder="田園都市線の民"]');
      await locDetailInput.fill(PAYLOAD.location_detail);
      await page.waitForTimeout(300);
    }

    // 生年月日の公開範囲
    if (PAYLOAD.birthday_scope !== undefined && PAYLOAD.birthday_scope !== null) {
      const scopeVal = PAYLOAD.birthday_scope === 'private' ? 'birthday_scope_private' : 'birthday_scope_friend';
      const curScopeVal = prevDom.birthdayScope === 'private' ? 'birthday_scope_private' : 'birthday_scope_friend';
      if (scopeVal !== curScopeVal) {
        previous.birthday_scope = prevDom.birthdayScope;
        changes.birthday_scope = PAYLOAD.birthday_scope;
        const radio = page.locator(`input[type="radio"][value="${scopeVal}"]`);
        await radio.check({ force: true });
        await page.waitForTimeout(300);
      }
    }

    // 場所の公開範囲
    if (PAYLOAD.location_scope !== undefined && PAYLOAD.location_scope !== null) {
      const scopeVal = (PAYLOAD.location_scope === 'all' || PAYLOAD.location_scope === 'all_users') ? 'all_users' : 'only_friends';
      const curScopeVal = prevDom.locationScope === 'all_users' ? 'all_users' : 'only_friends';
      if (scopeVal !== curScopeVal) {
        previous.location_scope = prevDom.locationScope;
        changes.location_scope = PAYLOAD.location_scope;
        const radio = page.locator(`input[type="radio"][value="${scopeVal}"]`);
        await radio.check({ force: true });
        await page.waitForTimeout(300);
      }
    }

    // 自己紹介
    if (PAYLOAD.introduction !== undefined && PAYLOAD.introduction !== null && PAYLOAD.introduction !== prevDom.introduction) {
      previous.introduction = prevDom.introduction;
      changes.introduction = PAYLOAD.introduction;
      const introTextarea = page.locator('textarea:not([aria-hidden="true"])');
      await introTextarea.fill(PAYLOAD.introduction);
      await page.waitForTimeout(300);
    }

    // 保存ボタンの状態確認
    const saveButton = page.locator('button:has-text("保存")');
    const isSaveDisabled = await saveButton.isDisabled();

    // Dry Run の場合
    if (IS_DRY_RUN) {
      // 画面上の入力を元の状態に復元
      if (changes.name !== undefined) {
        await page.locator('input[placeholder="テキスト"]').fill(prevDom.name);
      }
      if (changes.business_name !== undefined) {
        await page.locator('input[placeholder="ニックネーム、旧姓など"]').fill(prevDom.businessName);
      }
      if (changes.location !== undefined && prevDom.location) {
        const combobox = page.locator('div[tabindex="0"][role="combobox"]:not([aria-disabled="true"])');
        await combobox.click();
        await page.waitForTimeout(300);
        const opt = page.locator('li[role="option"]').filter({ hasText: new RegExp(`^${prevDom.location}$`) }).first();
        if (await opt.count() > 0) await opt.click();
        else await page.keyboard.press('Escape');
      }
      if (changes.location_detail !== undefined) {
        await page.locator('input[placeholder="田園都市線の民"]').fill(prevDom.locationDetail);
      }
      if (changes.birthday_scope !== undefined) {
        const prevScopeVal = prevDom.birthdayScope === 'private' ? 'birthday_scope_private' : 'birthday_scope_friend';
        await page.locator(`input[type="radio"][value="${prevScopeVal}"]`).check({ force: true });
      }
      if (changes.location_scope !== undefined) {
        const prevLocScopeVal = prevDom.locationScope === 'all_users' ? 'all_users' : 'only_friends';
        await page.locator(`input[type="radio"][value="${prevLocScopeVal}"]`).check({ force: true });
      }
      if (changes.introduction !== undefined) {
        await page.locator('textarea:not([aria-hidden="true"])').fill(prevDom.introduction);
      }
      await page.waitForTimeout(300);

      return {
        success: true,
        action: 'update',
        isDryRun: true,
        previous,
        changes,
        canSave: !isSaveDisabled,
      };
    }

    // 本番保存
    if (isSaveDisabled) {
      return {
        success: true,
        action: 'update',
        isDryRun: false,
        message: '変更項目がないか、保存ボタンが無効です。',
        previous,
        changes,
      };
    }

    // 保存ボタンをクリック
    await saveButton.click();
    await page.waitForTimeout(1500);

    // 保存完了待機（ボタンが無効になる、または保存通信完了）
    try {
      await page.waitForFunction(
        () => {
          const btn = Array.from(document.querySelectorAll('button')).find(
            b => b.textContent && b.textContent.includes('保存')
          );
          return btn ? btn.disabled : true;
        },
        { timeout: 10000 }
      );
    } catch (e) {
      // タイムアウトしても進行
    }

    // 最新のプロフィールデータを再取得
    const updatedProfile = await fetchAllProfileData();

    return {
      success: true,
      action: 'update',
      isDryRun: false,
      previous,
      changes,
      data: updatedProfile,
    };
  }

  return {
    success: false,
    error: `未知のアクションです: ${ACTION}`,
  };
}
