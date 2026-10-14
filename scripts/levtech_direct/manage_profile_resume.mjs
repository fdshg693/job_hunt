// scripts/levtech_direct/manage_profile_resume.mjs
// レバテックダイレクト 職務経歴・自己PR画面（/mypage/profile/resume）DOM操作 Playwright スクリプト
// sharing-browser-with-user スキル準拠

async page => {
  const ACTION = '__LEVTECH_ACTION__';
  const PAYLOAD = __LEVTECH_PAYLOAD__;
  const IS_DRY_RUN = __LEVTECH_DRY_RUN__;

  const TARGET_URL = 'https://levtech-direct.jp/mypage/profile/resume';

  // 1. 現在のページURLを確認し、必要に応じて遷移
  if (!page.url().includes('/mypage/profile/resume')) {
    await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
  }

  // テキストエリアまたはフォームの読み込み待機
  await page.waitForSelector('textarea[name="resume"]', { timeout: 15000 });

  // 補助関数: 現在のフォーム値・状態を取得する
  async function extractCurrentData() {
    // 1. __NEXT_DATA__ から取得
    let nextResume = null;
    try {
      const nextDataEl = await page.$('#__NEXT_DATA__');
      if (nextDataEl) {
        const text = await nextDataEl.textContent();
        const parsed = JSON.parse(text);
        nextResume = parsed?.props?.pageProps?.profilesResume?.base?.resume || '';
      }
    } catch (_) {}

    // 2. DOMのフォームから現在の入力値を取得
    const domData = await page.evaluate(() => {
      const textarea = document.querySelector('textarea[name="resume"]');
      const val = textarea ? textarea.value : '';

      // カウンターテキスト（例: "0/30,000文字"）
      let counterText = '';
      const spans = Array.from(document.querySelectorAll('span, p'));
      for (const el of spans) {
        const t = el.innerText || '';
        if (/\d+\s*\/\s*[\d,]+文字/.test(t)) {
          counterText = t.trim();
          break;
        }
      }

      // 最終更新日テキスト（例: "最終更新：2026/10/09"）
      let updatedAtText = '';
      for (const el of spans) {
        const t = el.innerText || '';
        if (t.includes('最終更新：') || t.includes('最終更新:')) {
          updatedAtText = t.replace(/最終更新[：:]/, '').trim();
          break;
        }
      }

      return {
        resume: val,
        charCount: val.length,
        counterText,
        updatedAtText
      };
    });

    const finalResume = domData.resume !== undefined && domData.resume !== '' ? domData.resume : (nextResume || '');

    return {
      resume: finalResume,
      charCount: finalResume.length,
      maxCharCount: 30000,
      counterText: domData.counterText || `${finalResume.length.toLocaleString()}/30,000文字`,
      updatedAtText: domData.updatedAtText || ''
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
    const newResume = typeof p.resume === 'string' ? p.resume : '';

    // 文字数制限チェック (10文字以上、30,000文字以内)
    if (newResume.length < 10) {
      throw new Error(`職務経歴・自己PRの文字数が不足しています（${newResume.length}文字 < 最小10文字）`);
    }
    if (newResume.length > 30000) {
      throw new Error(`職務経歴・自己PRの文字数が上限を超えています（${newResume.length}文字 > 上限30,000文字）`);
    }

    const textarea = page.locator('textarea[name="resume"]');
    const submitBtn = page.locator('button[type="submit"][data-display-name="ProfileDetailLayout_Button"]');

    const curData = await extractCurrentData();
    const isSame = curData.resume === newResume;

    let modified = false;
    if (!isSame) {
      await textarea.fill(newResume);
      await textarea.dispatchEvent('input');
      await textarea.dispatchEvent('change');
      await page.waitForTimeout(400);
      modified = true;
    }

    // 変更後のデータ抽出
    const updatedData = await extractCurrentData();
    const isSubmitDisabled = await submitBtn.isDisabled();

    if (IS_DRY_RUN) {
      // ドライラン後は元の値に戻してフォームを汚さない
      if (modified) {
        await textarea.fill(curData.resume);
        await textarea.dispatchEvent('input');
        await textarea.dispatchEvent('change');
        await page.waitForTimeout(300);
      }
      return {
        success: true,
        action: 'update',
        isDryRun: true,
        modified,
        canSubmit: !isSubmitDisabled,
        previousResume: curData.resume,
        data: updatedData
      };
    }

    // 実際の保存実行
    if (isSame || isSubmitDisabled) {
      return {
        success: true,
        action: 'update',
        isDryRun: false,
        noChanges: true,
        message: '既存の内容と同一のため保存処理をスキップしました。',
        data: updatedData
      };
    }

    // 保存ボタンクリック
    try {
      await Promise.all([
        submitBtn.click(),
        page.waitForResponse(
          res => res.url().includes('/api/') || res.url().includes('/resume') || res.url().includes('/mypage'),
          { timeout: 8000 }
        ).catch(() => null)
      ]);
    } catch (_) {}

    // ボタンの非活性化またはトースト通知待機
    try {
      await Promise.race([
        page.waitForSelector('.MuiAlert-root, [role="alert"]', { timeout: 6000 }),
        page.waitForFunction(
          btn => btn.disabled,
          await submitBtn.elementHandle(),
          { timeout: 6000 }
        )
      ]);
    } catch (_) {}

    // バリデーションエラー確認
    const errors = await page.evaluate(() => {
      const errNodes = Array.from(document.querySelectorAll('.Mui-error, [role="alert"]'));
      return errNodes
        .map(e => e.innerText?.trim())
        .filter(t => t && !t.includes('保存') && !t.includes('完了') && !t.includes('更新'));
    });

    if (errors.length > 0) {
      throw new Error(`保存処理バリデーションエラー: ${errors.join(' / ')}`);
    }

    // 最新状態を再取得
    await page.waitForTimeout(1000);
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
