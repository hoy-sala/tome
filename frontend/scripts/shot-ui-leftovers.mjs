// Screenshot the pages touched by the UI-leftovers pass (series stats,
// settings headers, admin audit log). Usage:
//   TOKEN=<jwt> node scripts/shot-ui-leftovers.mjs [theme]
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const token = process.env.TOKEN
if (!token) { console.error('TOKEN env required'); process.exit(1) }
const theme = process.argv[2] || 'light'
const base = 'http://localhost:5176'
const outDir = `/tmp/ui-refresh-shots/${theme}`
mkdirSync(outDir, { recursive: true })

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
await ctx.addInitScript(([t, th]) => {
  localStorage.setItem('tome_token', t)
  localStorage.setItem('tome_theme', th)
}, [token, theme])
const page = await ctx.newPage()

async function shot(url, name, after) {
  await page.goto(`${base}${url}`, { waitUntil: 'networkidle' })
  if (after) await after()
  await page.waitForTimeout(600)
  await page.screenshot({ path: `${outDir}/${name}.png`, fullPage: false })
  console.log(`${outDir}/${name}.png`)
}

await shot('/?tab=home', 'home', async () => {
  await page.waitForSelector('text=Continue Reading', { timeout: 10000 })
})
await shot('/?tab=series&series_detail=Re%3AZERO', 'series-stats', async () => {
  await page.waitForSelector('text=Reading Stats', { timeout: 10000 })
})
await shot('/settings', 'settings')
await shot('/admin', 'admin-audit', async () => {
  await page.getByRole('button', { name: 'Audit Log' }).click()
  await page.waitForTimeout(800)
})

await browser.close()
