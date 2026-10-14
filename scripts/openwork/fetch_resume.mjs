// scripts/openwork/fetch_resume.mjs
// OpenWork WEB履歴書画面（/mypage/resume）からのデータ抽出 Playwright スクリプト

async page => {
  const currentUrl = page.url();
  const targetUrl = 'https://www.openwork.jp/mypage/resume';

  // CDP User-Agent override (WAF対策)
  try {
    const client = await page.context().newCDPSession(page);
    await client.send('Network.setUserAgentOverride', {
      userAgent:
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
      acceptLanguage: 'ja,en-US;q=0.9,en;q=0.8',
      platform: 'Win32',
    });
  } catch (_) {}

  // もしまだ対象ページにいなければ遷移する
  if (!currentUrl.includes('/mypage/resume')) {
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  }

  // テーブルまたは主要コンテンツが表示されるのを待機
  try {
    await page.waitForSelector('#mainColumn.mypage, #mainColumn', { timeout: 10000 });
  } catch (_) {
    // タイムアウトしても続行
  }

  const result = await page.evaluate(() => {
    // 単一行用のテキスト整形（改行を空白に変換）
    const cleanLine = str =>
      (str || '')
        .replace(/[\r\n\t]+/g, ' ')
        .replace(/[ ]+/g, ' ')
        .trim();

    // 複数行用のテキスト整形（改行を保持）
    const cleanMultiline = str =>
      (str || '')
        .replace(/\r?\n/g, '\n')
        .split('\n')
        .map(line => line.trim())
        .join('\n')
        .trim();

    // 最終更新日の抽出
    let lastUpdatedAt = null;
    const h2El = document.querySelector('h2.w-100p, h2');
    if (h2El) {
      const match = h2El.textContent.match(/最終更新日：([0-9]{4}年[0-9]{2}月[0-9]{2}日)/);
      if (match) {
        lastUpdatedAt = match[1];
      }
    }

    // 各セクション見出し要素を取得
    const sections = {
      profile: document.getElementById('profile'),
      education: document.getElementById('education'),
      career: document.getElementById('career'),
      skill: document.getElementById('skill'),
      requirement: document.getElementById('requirement'),
    };

    // ある要素から次のセクション見出し要素までの間にある table.table 要素を取得するヘルパー
    const getTablesBetween = (startEl, stopEl) => {
      const tables = [];
      if (!startEl) return tables;
      let curr = startEl.nextElementSibling;
      while (curr && curr !== stopEl) {
        if (curr.classList && curr.classList.contains('articleTitle')) {
          break;
        }
        if (curr.tagName.toLowerCase() === 'table') {
          tables.push(curr);
        } else {
          // ネストされたテーブルがある場合も拾う
          const nested = curr.querySelectorAll('table.table');
          nested.forEach(t => tables.push(t));
        }
        curr = curr.nextElementSibling;
      }
      return tables;
    };

    // 1. 基本情報 (#profile)
    const profileData = {};
    const profileTables = getTablesBetween(sections.profile, sections.education);
    if (profileTables.length > 0) {
      const rows = profileTables[0].querySelectorAll('tr');
      rows.forEach(tr => {
        const th = tr.querySelector('th');
        const td = tr.querySelector('td');
        if (th && td) {
          const key = cleanLine(th.textContent);
          const val = cleanLine(td.textContent);
          profileData[key] = val;
        }
      });
    }

    // 2. 学歴 (#education)
    const educationList = [];
    const eduTables = getTablesBetween(sections.education, sections.career);
    eduTables.forEach(table => {
      const eduItem = {};
      const rows = table.querySelectorAll('tr');
      rows.forEach(tr => {
        const th = tr.querySelector('th');
        const td = tr.querySelector('td');
        if (th && td) {
          const key = cleanLine(th.textContent);
          const val = cleanLine(td.textContent);
          eduItem[key] = val;
        }
      });
      if (Object.keys(eduItem).length > 0) {
        educationList.push(eduItem);
      }
    });

    // 3. 職務経歴 (#career)
    let experienceCompanyCount = null;
    const careerList = [];
    let careerOther = null;
    const careerTables = getTablesBetween(sections.career, sections.skill);
    careerTables.forEach(table => {
      const rows = table.querySelectorAll('tr');
      const tableData = {};
      rows.forEach(tr => {
        const th = tr.querySelector('th');
        const td = tr.querySelector('td');
        if (th && td) {
          const key = cleanLine(th.textContent);
          let val = '';
          if (key === '職務内容') {
            const clone = td.cloneNode(true);
            clone.querySelectorAll('br').forEach(br => br.replaceWith('\n'));
            val = cleanMultiline(clone.textContent);
          } else if (key === 'その他（空白期間の説明など）') {
            const clone = td.cloneNode(true);
            clone.querySelectorAll('br').forEach(br => br.replaceWith('\n'));
            val = cleanMultiline(clone.textContent);
          } else {
            val = cleanLine(td.textContent);
          }
          tableData[key] = val;
        }
      });

      if ('経験社数' in tableData) {
        experienceCompanyCount = tableData['経験社数'];
      } else if ('その他（空白期間の説明など）' in tableData) {
        careerOther = tableData['その他（空白期間の説明など）'];
      } else if ('会社名' in tableData) {
        careerList.push(tableData);
      }
    });

    // 4. 経験・スキル (#skill)
    const skillData = {
      experiencedJobCategories: [],
      experiencedBusinesses: [],
      managementExperience: null,
      englishSkill: null,
      englishScores: [],
      otherLanguages: null,
      certifications: [],
      other: null,
    };

    const skillTables = getTablesBetween(sections.skill, sections.requirement);
    if (skillTables.length > 0) {
      const rows = skillTables[0].querySelectorAll('tr');
      rows.forEach(tr => {
        const th = tr.querySelector('th');
        const td = tr.querySelector('td');
        if (!th || !td) return;
        const key = cleanLine(th.textContent);

        if (key === '経験職種') {
          const h4Elements = td.querySelectorAll('h4.categoryTitle');
          if (h4Elements.length > 0) {
            h4Elements.forEach(h4 => {
              const catTitle = cleanLine(h4.textContent);
              const ul = h4.nextElementSibling;
              const items = [];
              if (ul && ul.tagName.toLowerCase() === 'ul') {
                ul.querySelectorAll('li').forEach(li => {
                  items.push(cleanLine(li.textContent));
                });
              }
              skillData.experiencedJobCategories.push({
                category: catTitle,
                items,
              });
            });
          } else {
            const items = [];
            td.querySelectorAll('li').forEach(li => items.push(cleanLine(li.textContent)));
            if (items.length > 0) {
              skillData.experiencedJobCategories.push({ category: '経験職種', items });
            }
          }
        } else if (key === '経験業務') {
          const h4Elements = td.querySelectorAll('h4.categoryTitle');
          if (h4Elements.length > 0) {
            h4Elements.forEach(h4 => {
              const mainCat = cleanLine(h4.textContent);
              const subCats = [];

              // h4の直後のコンテナ（div等）または後続要素群から h5 と ul を探索
              let curr = h4.nextElementSibling;
              while (curr && !curr.matches('h4.categoryTitle')) {
                // コンテナ内に h5 がある場合
                const h5List = curr.tagName.toLowerCase() === 'h5' ? [curr] : Array.from(curr.querySelectorAll('h5'));
                h5List.forEach(h5El => {
                  const subTitle = cleanLine(h5El.textContent);
                  const ul = h5El.nextElementSibling || (h5El.parentElement && h5El.parentElement.querySelector('ul'));
                  const items = [];
                  if (ul && ul.tagName.toLowerCase() === 'ul') {
                    ul.querySelectorAll('li').forEach(li => {
                      items.push(cleanLine(li.textContent));
                    });
                  }
                  subCats.push({ subCategory: subTitle, items });
                });
                curr = curr.nextElementSibling;
              }

              skillData.experiencedBusinesses.push({
                mainCategory: mainCat,
                subCategories: subCats,
              });
            });
          } else {
            const items = [];
            td.querySelectorAll('li').forEach(li => items.push(cleanLine(li.textContent)));
            skillData.experiencedBusinesses.push({
              mainCategory: '経験業務',
              subCategories: [{ subCategory: '', items }],
            });
          }
        } else if (key === 'マネジメント経験') {
          skillData.managementExperience = cleanLine(td.textContent);
        } else if (key === '英語力') {
          const levelEl = td.querySelector('span.d-b');
          if (levelEl) {
            skillData.englishSkill = cleanLine(levelEl.textContent);
          }
          const scoreSpans = td.querySelectorAll('span.mr-10, span:not(.d-b)');
          scoreSpans.forEach(sp => {
            const txt = cleanLine(sp.textContent);
            if (txt && (txt.includes('TOEIC') || txt.includes('TOEFL') || txt.includes('点'))) {
              skillData.englishScores.push(txt);
            }
          });
          if (!skillData.englishSkill && !skillData.englishScores.length) {
            skillData.englishSkill = cleanLine(td.textContent);
          }
        } else if (key === 'その他の語学') {
          skillData.otherLanguages = cleanLine(td.textContent);
        } else if (key === '保有資格') {
          td.querySelectorAll('span.d-b').forEach(sp => {
            const txt = cleanLine(sp.textContent);
            if (txt && txt !== '未入力') {
              skillData.certifications.push(txt);
            }
          });
          if (skillData.certifications.length === 0) {
            const txt = cleanLine(td.textContent);
            if (txt && txt !== '未入力') {
              skillData.certifications.push(txt);
            }
          }
        } else if (key === 'その他') {
          const clone = td.cloneNode(true);
          clone.querySelectorAll('br').forEach(br => br.replaceWith('\n'));
          skillData.other = cleanMultiline(clone.textContent);
        }
      });
    }

    // 5. 希望条件 (#requirement)
    const requirementData = {
      industries: [],
      jobTypes: [],
      locations: [],
      workStyles: [],
      preferredTiming: null,
      desiredSalary: null,
      other: null,
    };

    const reqTables = getTablesBetween(sections.requirement, null);
    if (reqTables.length > 0) {
      const rows = reqTables[0].querySelectorAll('tr');
      rows.forEach(tr => {
        const th = tr.querySelector('th');
        const td = tr.querySelector('td');
        if (!th || !td) return;
        const key = cleanLine(th.textContent);

        const extractList = () => {
          const list = [];
          td.querySelectorAll('li').forEach(li => {
            const txt = cleanLine(li.textContent);
            if (txt) list.push(txt);
          });
          if (list.length === 0) {
            const txt = cleanLine(td.textContent);
            if (txt && txt !== '未入力') list.push(txt);
          }
          return list;
        };

        if (key === '希望業種') {
          requirementData.industries = extractList();
        } else if (key === '希望職種') {
          requirementData.jobTypes = extractList();
        } else if (key === '希望勤務地') {
          requirementData.locations = extractList();
        } else if (key === '興味がある働き方') {
          requirementData.workStyles = extractList();
        } else if (key === '転職希望時期') {
          requirementData.preferredTiming = cleanLine(td.textContent);
        } else if (key === '希望年収') {
          requirementData.desiredSalary = cleanLine(td.textContent);
        } else if (key === 'その他') {
          const clone = td.cloneNode(true);
          clone.querySelectorAll('br').forEach(br => br.replaceWith('\n'));
          requirementData.other = cleanMultiline(clone.textContent);
        }
      });
    }

    return {
      lastUpdatedAt,
      profile: profileData,
      education: educationList,
      career: {
        experienceCompanyCount,
        companies: careerList,
        other: careerOther,
      },
      skills: skillData,
      requirements: requirementData,
    };
  });

  return {
    success: true,
    url: page.url(),
    title: await page.title(),
    resume: result,
  };
}
