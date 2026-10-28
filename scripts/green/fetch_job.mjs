// scripts/green/fetch_job.mjs
// Green（https://www.green-japan.com）の求人詳細（/job/{id} または /company/{cid}/job/{jid}）から
// 構造化求人データおよび企業情報を抽出する Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/green/fetch_job.mjs --raw

async page => {
  const result = {
    success: false,
    fetchedAt: new Date().toISOString(),
    url: '__JOB_URL__',
    jobOffer: null,
    client: null,
    errors: [],
  };

  const targetUrl = __JOB_URL__;
  if (!targetUrl) {
    result.errors.push('対象求人URLまたはIDが指定されていません');
    return result;
  }

  try {
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(1500);

    const currentUrl = page.url();
    result.url = currentUrl;

    // 認証壁・ログイン画面チェック
    if (currentUrl.includes('/login') || currentUrl.includes('accounts.google.com')) {
      result.errors.push(`未ログイン状態または認証壁に到達しました（現在のURL: ${currentUrl}）`);
      return result;
    }

    // Next.js の __NEXT_DATA__ から求人データおよび企業データを抽出
    const extracted = await page.evaluate(() => {
      const pp = window.__NEXT_DATA__?.props?.pageProps;
      if (!pp) {
        return { error: 'window.__NEXT_DATA__.props.pageProps が存在しません' };
      }

      const jobOffer = pp.jobOffer || null;
      const client = pp.client || pp.company || null;
      const pageTitle = document.title;

      return {
        jobOffer,
        client,
        pageTitle,
      };
    });

    if (extracted.error) {
      result.errors.push(extracted.error);
      return result;
    }

    if (!extracted.jobOffer) {
      result.errors.push('求人データ (jobOffer) が取得できませんでした。求人が非公開または終了している可能性があります。');
      return result;
    }

    result.success = true;
    result.jobOffer = extracted.jobOffer;
    result.client = extracted.client;
  } catch (err) {
    result.errors.push(`詳細取得例外: ${err.message || String(err)}`);
  }

  return result;
}
