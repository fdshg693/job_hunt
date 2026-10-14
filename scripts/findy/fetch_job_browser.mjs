// scripts/findy/fetch_job_browser.mjs
async page => {
  const targetUrl = 'https://findy-code.io/companies/806/jobs/jurRXuULM7BXf';
  await page.goto(targetUrl, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);

  const data = await page.evaluate(() => {
    const nextDataEl = document.querySelector('#__NEXT_DATA__');
    let nextData = null;
    if (nextDataEl) {
      try {
        nextData = JSON.parse(nextDataEl.textContent);
      } catch (e) {}
    }

    const title = document.querySelector('h1')?.textContent?.trim() || '';
    const company = document.querySelector('[class*="company"]')?.textContent?.trim() || '';
    const bodyText = document.body.innerText;

    return {
      title,
      company,
      pageProps: nextData?.props?.pageProps || null,
      bodyTextSnippet: bodyText.slice(0, 3000)
    };
  });

  return {
    success: true,
    data
  };
}
