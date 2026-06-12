import { chromium } from 'playwright';

const TOKEN = process.env.TOME_TOKEN;
const BASE = 'http://localhost:5173';
const themes = ['light', 'dark'];

const browser = await chromium.launch();
for (const theme of themes) {
  const ctx = await browser.newContext({ viewport: { width: 1680, height: 1050 }, deviceScaleFactor: 2 });
  await ctx.addInitScript(([token, t]) => {
    localStorage.setItem('tome_token', token);
    localStorage.setItem('tome_theme', t);
    localStorage.setItem('tome_stats_hint', 'dismissed');
  }, [TOKEN, theme]);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/stats`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `/tmp/stats-refresh-${theme}.png`, fullPage: true });
  console.log(`shot ${theme}: ${page.url()}`);
  await ctx.close();
}
await browser.close();
