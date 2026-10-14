// scripts/wellfound/manage_profile.mjs
// Wellfound プロフィール（Candidate 情報、スキル、職歴、学歴、Bio/Social更新）Playwright スクリプト
// Python側の execute_manage_action からテンプレート置換されて実行されます。

async page => {
  const ACTION = __WELLFOUND_ACTION__;
  const PAYLOAD = __WELLFOUND_PAYLOAD__;
  const IS_DRY_RUN = __WELLFOUND_DRY_RUN__;

  const TARGET_URL = 'https://wellfound.com/profile/edit';

  const result = {
    success: false,
    action: ACTION,
    isDryRun: IS_DRY_RUN,
    timestamp: new Date().toISOString(),
    data: {},
    error: null,
  };

  try {
    // 1. プロフィール編集画面へ遷移（まだその画面にいない場合）
    const currentUrl = page.url();
    if (!currentUrl.includes('/profile/edit')) {
      await page.goto(TARGET_URL, {
        waitUntil: 'domcontentloaded',
        timeout: 30000,
      });
    }

    // 認証チェック
    const isAuthWall = /wellfound\.com\/(?:login|join)|accounts\.google\.com/i.test(page.url());
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
    } catch (_) {
      // 再読み込みを試みる
      await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForFunction(
        () => window.__NEXT_DATA__ && window.__NEXT_DATA__.props && window.__NEXT_DATA__.props.pageProps,
        { timeout: 15000 }
      );
    }

    // Apollo キャッシュから構造化データを抽出するヘルパー
    const extractProfileData = async () => {
      return await page.evaluate(() => {
        const nextData = window.__NEXT_DATA__ || {};
        const apolloData = nextData.props?.pageProps?.apolloState?.data || {};

        // Candidate エンティティの探索
        let candidateKey = Object.keys(apolloData).find(k => k.startsWith('Candidate:'));
        let talentViewerKey = Object.keys(apolloData).find(k => k.startsWith('TalentViewer:'));
        let userKey = Object.keys(apolloData).find(k => k.startsWith('User:'));

        const candidate = candidateKey ? apolloData[candidateKey] : null;
        const talentViewer = talentViewerKey ? apolloData[talentViewerKey] : null;
        const user = userKey ? apolloData[userKey] : null;

        // タグ解決ヘルパー
        const resolveTag = (ref) => {
          if (!ref) return null;
          const key = typeof ref === 'string' ? ref : (ref.__ref || ref.id);
          if (key && apolloData[key]) {
            return apolloData[key];
          }
          return ref;
        };

        // スキル解決
        const skills = [];
        if (candidate && Array.isArray(candidate.skillTags)) {
          for (const sRef of candidate.skillTags) {
            const tag = resolveTag(sRef);
            if (tag) {
              skills.push({
                id: tag.id || '',
                name: tag.displayName || tag.name || '',
                slug: tag.slug || '',
              });
            }
          }
        }

        // 職歴解決
        const experiences = [];
        if (candidate && Array.isArray(candidate.startupRoleMetadata)) {
          for (const rRef of candidate.startupRoleMetadata) {
            const roleMeta = resolveTag(rRef);
            if (roleMeta) {
              const startup = resolveTag(roleMeta.startup);
              experiences.push({
                id: roleMeta.id || '',
                title: roleMeta.title || '',
                description: roleMeta.description || '',
                current: Boolean(roleMeta.current),
                startedAtMonth: roleMeta.startedAtMonth || null,
                startedAtYear: roleMeta.startedAtYear || null,
                endedAtMonth: roleMeta.endedAtMonth || null,
                endedAtYear: roleMeta.endedAtYear || null,
                company: startup ? {
                  id: startup.id || '',
                  name: startup.name || '',
                  logoUrl: startup.logoUrl || '',
                } : null,
              });
            }
          }
        }

        // 学歴解決
        const education = [];
        if (candidate && Array.isArray(candidate.education)) {
          for (const eRef of candidate.education) {
            const edu = resolveTag(eRef);
            if (edu) {
              const college = resolveTag(edu.college);
              education.push({
                id: edu.id || '',
                degree: edu.degree || '',
                graduationYear: edu.graduationYear || null,
                collegeName: college ? (college.displayName || college.name || '') : '',
              });
            }
          }
        }

        // 居住地タグ
        const locationTag = candidate?.basedInLocation ? resolveTag(candidate.basedInLocation) : null;
        const locationName = locationTag ? (locationTag.displayName || locationTag.name || '') : '';

        // Analytics traits パース
        let analyticsTraits = {};
        if (talentViewer && talentViewer.analytics) {
          try {
            const parsed = typeof talentViewer.analytics === 'string'
              ? JSON.parse(talentViewer.analytics)
              : talentViewer.analytics;
            analyticsTraits = parsed.traits || parsed || {};
          } catch (_) {}
        }

        // DOMのフォールバック値（inputフィールドから取得）
        const domBio = document.querySelector('textarea#form-input--bio')?.value || '';
        const domName = document.querySelector('input#form-input--name')?.value || '';
        const domLinkedin = document.querySelector('input#form-input--linkedinUrl')?.value || '';
        const domGithub = document.querySelector('input#form-input--githubUrl')?.value || '';
        const domTwitter = document.querySelector('input#form-input--twitterUrl')?.value || '';
        const domWebsite = document.querySelector('input#form-input--onlineBioUrl')?.value || '';
        const domAchievements = document.querySelector('textarea#form-input--whatIveBuilt')?.value || '';

        return {
          candidateId: candidate?.id || '',
          name: domName || user?.name || analyticsTraits.name || '',
          email: user?.email || '',
          bio: domBio || candidate?.bio || '',
          primaryRole: candidate?.primaryRole || [],
          yearsExperienceInPrimaryRole: candidate?.yearsExperienceInPrimaryRole || null,
          roleIds: candidate?.roleIds || [],
          location: locationName,
          skills: skills,
          experiences: experiences,
          education: education,
          socials: {
            linkedinUrl: domLinkedin || candidate?.linkedinUrl || '',
            githubUrl: domGithub || candidate?.githubUrl || '',
            twitterUrl: domTwitter || candidate?.twitterUrl || '',
            onlineBioUrl: domWebsite || candidate?.onlineBioUrl || '',
          },
          whatIveBuilt: domAchievements || candidate?.whatIveBuilt || '',
          resumeUrl: candidate?.resumeUrl || '',
          preferences: {
            desiredSalary: analyticsTraits.candidate_desired_salary || null,
            desiredSalaryCurrency: analyticsTraits.candidate_desired_salary_currency || null,
            remotePreference: analyticsTraits.candidate_remote_work_preference !== undefined ? analyticsTraits.candidate_remote_work_preference : null,
            interestedLocations: analyticsTraits.candidate_interested_locations || [],
            roleTags: analyticsTraits.candidate_role_tags || [],
          },
          rawNextData: nextData,
        };
      });
    };

    // -------------------------------------------------------------
    // アクション 1: view（閲覧・抽出）
    // -------------------------------------------------------------
    if (ACTION === 'view') {
      const profileData = await extractProfileData();
      result.success = true;
      result.data = profileData;
      return result;
    }

    // -------------------------------------------------------------
    // アクション 2: update_bio（自己紹介の更新）
    // -------------------------------------------------------------
    if (ACTION === 'update_bio') {
      const currentData = await extractProfileData();
      const previousBio = currentData.bio;
      const newBio = (PAYLOAD.bio || '').slice(0, 160); // 160文字上限

      if (IS_DRY_RUN) {
        result.success = true;
        result.data = {
          previousBio: previousBio,
          newBio: newBio,
          profileData: currentData,
        };
        return result;
      }

      // 入力フィールド操作
      const bioSelector = 'textarea#form-input--bio';
      await page.waitForSelector(bioSelector, { timeout: 10000 });
      await page.click(bioSelector);
      await page.fill(bioSelector, newBio);
      await page.waitForTimeout(500);

      // 保存ボタン（Save）の出現待機 & クリック
      const saveBtnSelector = 'button:has-text("Save")';
      await page.waitForSelector(saveBtnSelector, { timeout: 5000 });
      await page.click(saveBtnSelector);

      // 保存完了待機（Saveボタンまたはアクションバーが消えるまで、または一定時間）
      try {
        await page.waitForSelector('div[class*="styles_actionBar"]', { state: 'detached', timeout: 8000 });
      } catch (_) {
        await page.waitForTimeout(2000);
      }

      // 更新後のデータ取得
      const updatedData = await extractProfileData();
      result.success = true;
      result.data = {
        previousBio: previousBio,
        newBio: newBio,
        updatedBio: updatedData.bio,
        profileData: updatedData,
      };
      return result;
    }

    // -------------------------------------------------------------
    // アクション 3: update_socials（ソーシャルリンクの更新）
    // -------------------------------------------------------------
    if (ACTION === 'update_socials') {
      const currentData = await extractProfileData();
      const previousSocials = { ...currentData.socials };
      const newSocials = { ...previousSocials };

      if (PAYLOAD.linkedinUrl !== undefined) newSocials.linkedinUrl = PAYLOAD.linkedinUrl;
      if (PAYLOAD.githubUrl !== undefined) newSocials.githubUrl = PAYLOAD.githubUrl;
      if (PAYLOAD.twitterUrl !== undefined) newSocials.twitterUrl = PAYLOAD.twitterUrl;
      if (PAYLOAD.onlineBioUrl !== undefined) newSocials.onlineBioUrl = PAYLOAD.onlineBioUrl;

      if (IS_DRY_RUN) {
        result.success = true;
        result.data = {
          previousSocials: previousSocials,
          newSocials: newSocials,
          profileData: currentData,
        };
        return result;
      }

      // 各フィールドの入力
      const fieldMap = {
        linkedinUrl: 'input#form-input--linkedinUrl',
        githubUrl: 'input#form-input--githubUrl',
        twitterUrl: 'input#form-input--twitterUrl',
        onlineBioUrl: 'input#form-input--onlineBioUrl',
      };

      for (const [key, selector] of Object.entries(fieldMap)) {
        if (PAYLOAD[key] !== undefined) {
          const el = await page.$(selector);
          if (el) {
            await page.fill(selector, PAYLOAD[key]);
            await page.waitForTimeout(300);
          }
        }
      }

      // 保存ボタンのクリック
      const saveBtnSelector = 'button:has-text("Save")';
      await page.waitForSelector(saveBtnSelector, { timeout: 5000 });
      await page.click(saveBtnSelector);

      try {
        await page.waitForSelector('div[class*="styles_actionBar"]', { state: 'detached', timeout: 8000 });
      } catch (_) {
        await page.waitForTimeout(2000);
      }

      const updatedData = await extractProfileData();
      result.success = true;
      result.data = {
        previousSocials: previousSocials,
        newSocials: newSocials,
        updatedSocials: updatedData.socials,
        profileData: updatedData,
      };
      return result;
    }

    // -------------------------------------------------------------
    // アクション 4: update_achievements（What I've built 実績の更新）
    // -------------------------------------------------------------
    if (ACTION === 'update_achievements') {
      const currentData = await extractProfileData();
      const previousAchievements = currentData.whatIveBuilt;
      const newAchievements = (PAYLOAD.whatIveBuilt || '').slice(0, 1000); // 1000文字上限

      if (IS_DRY_RUN) {
        result.success = true;
        result.data = {
          previousAchievements: previousAchievements,
          newAchievements: newAchievements,
          profileData: currentData,
        };
        return result;
      }

      const achSelector = 'textarea#form-input--whatIveBuilt';
      await page.waitForSelector(achSelector, { timeout: 10000 });
      await page.click(achSelector);
      await page.fill(achSelector, newAchievements);
      await page.waitForTimeout(500);

      const saveBtnSelector = 'button:has-text("Save")';
      await page.waitForSelector(saveBtnSelector, { timeout: 5000 });
      await page.click(saveBtnSelector);

      try {
        await page.waitForSelector('div[class*="styles_actionBar"]', { state: 'detached', timeout: 8000 });
      } catch (_) {
        await page.waitForTimeout(2000);
      }

      const updatedData = await extractProfileData();
      result.success = true;
      result.data = {
        previousAchievements: previousAchievements,
        newAchievements: newAchievements,
        updatedAchievements: updatedData.whatIveBuilt,
        profileData: updatedData,
      };
      return result;
    }

    // -------------------------------------------------------------
    // アクション 5: update_experience（既存職歴の編集・終了日設定など）
    // -------------------------------------------------------------
    if (ACTION === 'update_experience') {
      const currentData = await extractProfileData();
      const targetCompany = PAYLOAD.companyName || '';
      const endedAt = PAYLOAD.endedAt || ''; // 'MM/YYYY'
      const isCurrent = PAYLOAD.current;
      const newTitle = PAYLOAD.title;
      const newDesc = PAYLOAD.description;

      if (IS_DRY_RUN) {
        result.success = true;
        result.data = {
          targetCompany,
          endedAt,
          isCurrent,
          profileData: currentData,
        };
        return result;
      }

      // 該当企業の職歴カード内の Edit リンクを探す
      const editClicked = await page.evaluate((compName) => {
        const cards = Array.from(document.querySelectorAll('div[class*="styles_aside"]'));
        for (const card of cards) {
          const parent = card.closest('div');
          if (parent && parent.textContent && parent.textContent.toLowerCase().includes(compName.toLowerCase())) {
            const editBtn = Array.from(parent.querySelectorAll('a')).find(a => a.textContent?.trim() === 'Edit') ||
              parent.querySelector('a[class*="styles_edit"]');
            if (editBtn) {
              editBtn.click();
              return true;
            }
          }
        }
        // フォールバック: 最初の Edit リンク
        const allA = Array.from(document.querySelectorAll('a'));
        const firstEdit = allA.find(a => a.textContent?.trim() === 'Edit' && a.className.includes('styles_edit__qR593')) ||
          allA.find(a => a.textContent?.trim() === 'Edit');
        if (firstEdit) {
          firstEdit.click();
          return true;
        }
        return false;
      }, targetCompany);

      if (!editClicked) {
        throw new Error(`職歴の編集リンクが見つかりませんでした (企業名: ${targetCompany})`);
      }

      await page.waitForTimeout(1000);

      // フォーム入力
      if (newTitle) {
        const titleInput = await page.$('input#form-input--title');
        if (titleInput) await titleInput.fill(newTitle);
      }

      if (isCurrent !== undefined) {
        const currentCheckbox = await page.$('input#form-input--current--true');
        if (currentCheckbox) {
          const isChecked = await currentCheckbox.isChecked();
          if (isChecked !== isCurrent) {
            const label = await page.$('label[for="form-input--current--true"]');
            if (label) {
              await label.click();
            } else {
              await page.evaluate(() => {
                const cb = document.querySelector('input#form-input--current--true');
                if (cb) (cb.closest('label') || cb.parentElement).click();
              });
            }
            await page.waitForTimeout(500);
          }
        }
      }

      if (endedAt) {
        const endInput = await page.waitForSelector('input[placeholder="End date"]', { timeout: 5000 });
        if (endInput) {
          await endInput.click();
          await page.keyboard.type(endedAt, { delay: 100 });
          await page.keyboard.press('Enter');
          await page.waitForTimeout(300);
        }
      }

      if (newDesc) {
        const descInput = await page.$('textarea#form-input--description');
        if (descInput) {
          await descInput.fill(newDesc);
          await page.waitForTimeout(300);
        }
      }

      // 保存ボタンをクリック（フォーム内のsubmit）
      const saveBtn = await page.$('form button[type="submit"]:has-text("Save")');
      if (saveBtn) {
        await saveBtn.click();
      } else {
        const fallbackSave = await page.$('button:has-text("Save")');
        if (fallbackSave) await fallbackSave.click();
      }

      await page.waitForTimeout(4000);

      const updatedData = await extractProfileData();
      result.success = true;
      result.data = {
        updatedExperiences: updatedData.experiences,
        profileData: updatedData,
      };
      return result;
    }

    // -------------------------------------------------------------
    // アクション 6: add_experience（新規職歴の追加）
    // -------------------------------------------------------------
    if (ACTION === 'add_experience') {
      const currentData = await extractProfileData();
      const compName = PAYLOAD.companyName || '';
      const title = PAYLOAD.title || '';
      const startedAt = PAYLOAD.startedAt || ''; // 'MM/YYYY'
      const isCurrent = PAYLOAD.current !== undefined ? PAYLOAD.current : true;
      const endedAt = PAYLOAD.endedAt || '';
      const description = PAYLOAD.description || '';

      if (IS_DRY_RUN) {
        result.success = true;
        result.data = {
          compName,
          title,
          startedAt,
          isCurrent,
          profileData: currentData,
        };
        return result;
      }

      // "+ Add work experience" リンクをクリック
      const addLink = await page.$('a.styles_add__EROyj, a:has-text("+ Add work experience")');
      if (!addLink) {
        throw new Error('"+ Add work experience" リンクが見つかりませんでした。');
      }
      await addLink.click();
      await page.waitForTimeout(1000);

      // 会社名入力
      const compInput = await page.$('input[placeholder="Type to search"]');
      if (!compInput) {
        throw new Error('会社名入力欄が見つかりませんでした。');
      }
      await compInput.click();
      await page.keyboard.type(compName, { delay: 100 });
      await page.waitForTimeout(1500);

      // ドロップダウン選択（mousedown + click）
      await page.evaluate((target) => {
        const items = Array.from(document.querySelectorAll('[role="option"], [id*="downshift-"][id*="-item-"]'));
        if (items.length === 0) return false;

        const exact = items.find(it => it.textContent?.trim().toLowerCase() === target.toLowerCase());
        const createOpt = items.find(it => it.textContent?.trim().toLowerCase().startsWith(`create ${target.toLowerCase()}`)) ||
          items.find(it => it.textContent?.trim().toLowerCase().startsWith('create'));
        const choice = exact || createOpt || items[0];

        choice.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
        choice.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
        choice.click();
        return true;
      }, compName);

      await page.waitForTimeout(500);

      // 役職名入力
      const titleInput = await page.$('input#form-input--title');
      if (titleInput && title) {
        await titleInput.fill(title);
        await page.waitForTimeout(300);
      }

      // 開始日入力 (react-datepicker)
      if (startedAt) {
        const startInput = await page.$('input[placeholder="Start date"]');
        if (startInput) {
          await startInput.click();
          await page.keyboard.type(startedAt, { delay: 100 });
          await page.keyboard.press('Enter');
          await page.waitForTimeout(300);
        }
      }

      // 在籍中チェックボックス
      const currentBox = await page.$('input#form-input--current--true');
      if (currentBox) {
        const isChecked = await currentBox.isChecked();
        if (isChecked !== isCurrent) {
          const label = await page.$('label[for="form-input--current--true"]');
          if (label) {
            await label.click();
          } else {
            await page.evaluate(() => {
              const cb = document.querySelector('input#form-input--current--true');
              if (cb) (cb.closest('label') || cb.parentElement).click();
            });
          }
          await page.waitForTimeout(500);
        }
      }

      // 終了日入力
      if (!isCurrent && endedAt) {
        const endInput = await page.waitForSelector('input[placeholder="End date"]', { timeout: 5000 });
        if (endInput) {
          await endInput.click();
          await page.keyboard.type(endedAt, { delay: 100 });
          await page.keyboard.press('Enter');
          await page.waitForTimeout(300);
        }
      }

      // 職務内容入力
      if (description) {
        const descInput = await page.$('textarea#form-input--description');
        if (descInput) {
          await descInput.fill(description);
          await page.waitForTimeout(300);
        }
      }

      // 保存ボタンをクリック
      const saveBtn = await page.$('form button[type="submit"]:has-text("Save")');
      if (saveBtn) {
        await saveBtn.click();
      } else {
        const fallbackSave = await page.$('button:has-text("Save")');
        if (fallbackSave) await fallbackSave.click();
      }

      await page.waitForTimeout(4000);

      const updatedData = await extractProfileData();
      result.success = true;
      result.data = {
        addedCompany: compName,
        experiences: updatedData.experiences,
        profileData: updatedData,
      };
      return result;
    }

    // -------------------------------------------------------------
    // アクション 6.5: remove_experience（職歴の削除）
    // -------------------------------------------------------------
    if (ACTION === 'remove_experience') {
      const currentData = await extractProfileData();
      const compName = (PAYLOAD.companyName || '').toLowerCase();
      const expId = PAYLOAD.experienceId || '';

      if (IS_DRY_RUN) {
        result.success = true;
        result.data = {
          compName,
          expId,
          profileData: currentData,
        };
        return result;
      }

      const editButtons = await page.$$('.styles_edit__qR593');
      let targetBtn = null;

      console.error(`[MJS remove_experience] found ${editButtons.length} edit buttons`);
      for (const btn of editButtons) {
        const text = await page.evaluate(el => el.closest('div[class*="experience"], div[class*="Position"], li, div')?.textContent || '', btn);
        console.error(`[MJS remove_experience] candidate button text: ${text.slice(0, 60)}`);
        if (!compName || text.toLowerCase().includes(compName)) {
          targetBtn = btn;
          break;
        }
      }

      if (!targetBtn && editButtons.length > 0) {
        targetBtn = editButtons[0];
      }

      if (!targetBtn) {
        throw new Error('削除対象の職歴が見つかりませんでした。');
      }

      console.error('[MJS remove_experience] clicking target Edit button');
      await targetBtn.click();
      await page.waitForTimeout(1500);

      page.on('dialog', async dialog => {
        result.dialogMessage = dialog.message();
        console.error(`[MJS remove_experience] dialog message: ${dialog.message()}`);
        await dialog.accept();
      });

      console.error('[MJS remove_experience] waiting for removeLink');
      const removeLink = await page.waitForSelector('a.styles_destroy__pSrL8, a:has-text("Remove position")', { timeout: 5000 });
      if (!removeLink) {
        throw new Error('"Remove position" リンクが見つかりませんでした。');
      }
      console.error('[MJS remove_experience] clicking removeLink');
      await removeLink.click();
      await page.waitForTimeout(4000);

      const confirmBtn = await page.$('button:has-text("Delete"), button:has-text("Yes"), button:has-text("Remove")');
      if (confirmBtn) {
        console.error('[MJS remove_experience] clicking confirmBtn');
        await confirmBtn.click();
        await page.waitForTimeout(2000);
      }

      await page.waitForTimeout(3000);

      const updatedData = await extractProfileData();
      result.success = true;
      result.data = {
        deletedCompany: compName,
        experiences: updatedData.experiences,
        profileData: updatedData,
      };
      console.log(JSON.stringify(result));
      return result;
    }

    // -------------------------------------------------------------
    // アクション 7: add_skills（スキルの追加）
    // -------------------------------------------------------------
    if (ACTION === 'add_skills') {
      const currentData = await extractProfileData();
      const existingNames = new Set((currentData.skills || []).map(s => (s.name || '').toLowerCase()));
      const skillsToAdd = (PAYLOAD.skills || []).filter(s => s && !existingNames.has(s.toLowerCase()));

      if (IS_DRY_RUN) {
        result.success = true;
        result.data = {
          skillsToAdd,
          alreadyExisting: Array.from(existingNames),
          profileData: currentData,
        };
        return result;
      }

      const skillInputSelector = 'input[placeholder*="Python, React"]';
      for (const skill of skillsToAdd) {
        const input = await page.$(skillInputSelector);
        if (!input) break;

        await input.click();
        await input.fill(skill);
        await page.waitForTimeout(1000);

        // オプションから選択
        await page.evaluate((targetSkill) => {
          const items = Array.from(document.querySelectorAll('[role="option"], [id*="downshift-"][id*="-item-"]'));
          if (items.length === 0) return false;

          // 対象スキル名で始まるもの、または完全一致を探す
          const match = items.find(it => {
            const txt = it.textContent?.trim().toLowerCase() || '';
            return txt.startsWith(targetSkill.toLowerCase());
          });

          if (match) {
            match.click();
            return true;
          }
          items[0].click();
          return true;
        }, skill);

        await page.waitForTimeout(800);
      }

      // 保存ボタンがあればクリック
      const saveBtn = await page.$('div[class*="styles_actionBar"] button:has-text("Save"), button:has-text("Save")');
      if (saveBtn) {
        const isVisible = await saveBtn.isVisible();
        if (isVisible) {
          await saveBtn.click();
          try {
            await page.waitForSelector('div[class*="styles_actionBar"]', { state: 'detached', timeout: 8000 });
          } catch (_) {
            await page.waitForTimeout(2000);
          }
        }
      }

      const updatedData = await extractProfileData();
      result.success = true;
      result.data = {
        skillsToAdd,
        updatedSkills: updatedData.skills,
        profileData: updatedData,
      };
      return result;
    }

    // -------------------------------------------------------------
    // アクション 8: update_identity（人種・エスニシティ等の修正）
    // -------------------------------------------------------------
    if (ACTION === 'update_identity') {
      const currentData = await extractProfileData();

      if (IS_DRY_RUN) {
        result.success = true;
        result.data = {
          payload: PAYLOAD,
          profileData: currentData,
        };
        return result;
      }

      await page.evaluate((payload) => {
        const toggleCheckbox = (selector, targetState) => {
          const input = document.querySelector(selector);
          if (input && input.checked !== targetState) {
            const parent = input.closest('label') || input.parentElement;
            if (parent) {
              parent.click();
            } else {
              input.click();
            }
          }
        };

        if (payload.eastAsian !== undefined) {
          toggleCheckbox('input#form-input--raceEthnicityOrigins--EAST_ASIAN', Boolean(payload.eastAsian));
        }
        if (payload.southAsian !== undefined) {
          toggleCheckbox('input#form-input--raceEthnicityOrigins--SOUTH_ASIAN', Boolean(payload.southAsian));
        }
      }, PAYLOAD);

      await page.waitForTimeout(500);

      const saveBtn = await page.$('button:has-text("Save")');
      if (saveBtn) {
        await saveBtn.click();
        try {
          await page.waitForSelector('div[class*="styles_actionBar"]', { state: 'detached', timeout: 8000 });
        } catch (_) {
          await page.waitForTimeout(2000);
        }
      }

      const updatedData = await extractProfileData();
      result.success = true;
      result.data = {
        profileData: updatedData,
      };
      return result;
    }

    throw new Error(`未対応のアクションです: ${ACTION}`);
  } catch (err) {
    result.success = false;
    result.error = err.message || String(err);
    console.log(JSON.stringify(result));
    return result;
  }
}
