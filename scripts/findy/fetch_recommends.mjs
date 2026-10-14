// scripts/findy/fetch_recommends.mjs
// Findyの「おすすめ求人（sort=recommend）」一覧ページから求人リストを抽出する Playwright スクリプト
// 実行方法: playwright-cli -s=<session> run-code --filename=scripts/findy/fetch_recommends.mjs --raw

async page => {
  const pageNum = (typeof process !== 'undefined' && process.env && process.env.FINDY_RECOMMENDS_PAGE) || '1';
  const targetUrl = `https://findy-code.io/recommends?sort=recommend&page=${pageNum}`;

  if (!page.url().includes('/recommends') || !page.url().includes(`page=${pageNum}`)) {
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);
  }

  // __NEXT_DATA__ から求人データを抽出
  const extraction = await page.evaluate(() => {
    const nextDataEl = document.getElementById('__NEXT_DATA__');
    if (!nextDataEl || !nextDataEl.textContent) {
      return { error: '__NEXT_DATA__ not found', jobs: [] };
    }

    try {
      const data = JSON.parse(nextDataEl.textContent);
      const pageProps = data.props?.pageProps || {};
      const jdData = pageProps.jobDescriptionsData || {};
      const totalCount = jdData.paginationInfo?.totalCount || pageProps.totalCount || 0;
      const list = jdData.list || pageProps.jobs || pageProps.jobDescriptions || [];

      const jobs = list.map(item => {
        const company = item.company || {};
        const cid = company.id;
        const jhash = item.jdHash || item.hash || item.id;
        const url = cid && jhash
          ? `https://findy-code.io/companies/${cid}/jobs/${jhash}`
          : `https://findy-code.io/jobs/${jhash}`;

        return {
          id: String(item.id || ''),
          hash: String(jhash || ''),
          companyId: cid,
          company: company.name || '企業名非公開',
          title: item.title || '',
          url: url,
          salaryMin: item.numericSalaryMin || null,
          salaryMax: item.numericSalaryMax || null,
          skills: (item.skills || []).map(s => s.name).filter(Boolean),
          jobRoles: (item.jobRoles || []).map(r => r.name).filter(Boolean),
          tags: (item.tags || []).map(t => t.name).filter(Boolean),
          workHours: item.workHours || '',
          description: item.description || '',
          createdAt: item.createdAt || '',
          publishedAt: item.publishedAt || '',
          userLike: item.userLike || null,
        };
      });

      return {
        totalCount,
        count: jobs.length,
        jobs,
      };
    } catch (e) {
      return { error: e.message, jobs: [] };
    }
  });

  return {
    url: page.url(),
    page: parseInt(pageNum, 10),
    ...extraction,
  };
}
