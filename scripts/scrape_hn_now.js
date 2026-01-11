#!/usr/bin/env node

import { chromium } from 'playwright';

async function scrapeHackerNews(limit = 5) {
    console.log('🔍 正在抓取 Hacker News...\n');

    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();

    await page.goto('https://news.ycombinator.com/', { timeout: 30000 });

    const newsItems = await page.locator('.athing').all();

    console.log(`找到 ${newsItems.length} 条新闻，显示前 ${limit} 条:\n`);

    const results = [];
    for (let i = 0; i < Math.min(limit, newsItems.length); i++) {
        const item = newsItems[i];

        const titleElem = item.locator('.titleline > a');
        const title = await titleElem.textContent();
        const link = await titleElem.getAttribute('href');

        const rank = await item.locator('.rank').textContent();

        results.push({ rank: rank.replace('.', ''), title, link });

        console.log(`${rank} ${title}`);
        console.log(`   ${link}\n`);
    }

    await browser.close();

    return results;
}

scrapeHackerNews(5).catch(console.error);
