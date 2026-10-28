// scripts/findy/fetch_profile.mjs
// Findyの「キャリア・スキル」画面（/me/career-skills）へ遷移し、
// GraphQL APIレスポンス（FetchCareerSkillsCurrentUser）をインターセプトして完全なプロフィールデータを取得する Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/findy/fetch_profile.mjs --raw

async page => {
  const targetUrl = 'https://findy-code.io/me/career-skills';
  let careerSkillsData = null;
  let currentUserInfo = null;

  // GraphQLレスポンスのリスナーを設定
  const onResponse = async (res) => {
    try {
      const url = res.url();
      if (url.includes('/graphql/user')) {
        if (url.includes('opname=FetchCareerSkillsCurrentUser')) {
          const body = await res.json();
          if (body && body.data) {
            careerSkillsData = body.data;
          }
        } else if (url.includes('opname=FetchCurrentUserInfo')) {
          const body = await res.json();
          if (body && body.data) {
            currentUserInfo = body.data;
          }
        }
      }
    } catch (_) {
      // JSONパース失敗等は無視
    }
  };

  page.on('response', onResponse);

  try {
    // 画面に到達していない場合は遷移、すでにいる場合はリロードして通信をキャプチャ
    const currentUrl = page.url();
    if (!currentUrl.includes('/me/career-skills')) {
      await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 20000 });
    } else {
      await page.reload({ waitUntil: 'domcontentloaded', timeout: 20000 });
    }

    // 主要見出しまたはコンテンツが表示されるのを待機
    try {
      await page.waitForSelector('h1, h2, main', { timeout: 15000 });
    } catch (_) {}

    // GraphQLレスポンスが届くまでポーリング待機（最大10秒）
    const waitStart = Date.now();
    while (!careerSkillsData && Date.now() - waitStart < 10000) {
      await page.waitForTimeout(300);
    }
  } finally {
    page.off('response', onResponse);
  }

  const finalUrl = page.url();
  const pageTitle = await page.title();

  // DOMからのフォールバック情報収集
  const domExtraction = await page.evaluate(() => {
    // ユーザー名
    const nameEl = document.querySelector('h1, [class*="userName"], [class*="user-name"]');
    const name = nameEl ? nameEl.textContent.trim() : null;

    // スキルタグ
    const skillEls = Array.from(document.querySelectorAll('[class*="skill"], [class*="tag"], [class*="badge"]'));
    const skills = skillEls.map(el => el.textContent.trim()).filter(t => t.length > 0 && t.length < 40);

    return {
      name,
      skills: Array.from(new Set(skills)).slice(0, 30)
    };
  });

  return {
    success: !!careerSkillsData || finalUrl.includes('/me/career-skills'),
    url: finalUrl,
    title: pageTitle,
    careerSkills: careerSkillsData,
    currentUserInfo: currentUserInfo,
    domFallback: domExtraction,
    sourceType: careerSkillsData ? 'graphql' : 'dom'
  };
}
