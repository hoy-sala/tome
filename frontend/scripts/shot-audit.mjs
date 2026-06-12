import { chromium } from 'playwright'
const token = process.env.TOKEN
const base = 'http://localhost:5176'
const browser = await chromium.launch()
const authed = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
await authed.addInitScript(([t]) => { localStorage.setItem('tome_token', t); localStorage.setItem('tome_theme', 'dark') }, [token])
const p = await authed.newPage()
for (const [url, name] of [['/bindery', 'bindery'], ['/wishlist', 'wishlist'], ['/admin', 'admin']]) {
  await p.goto(base + url, { waitUntil: 'networkidle' })
  if (name === 'admin') { await p.getByRole('button', { name: 'Audit Log' }).click(); await p.waitForTimeout(800) }
  await p.waitForTimeout(600)
  await p.screenshot({ path: `/tmp/ui-refresh-shots/audit-${name}.png` })
  console.log(name)
}
const anon = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
await anon.addInitScript(() => localStorage.setItem('tome_theme', 'dark'))
const lp = await anon.newPage()
await lp.goto(base + '/login', { waitUntil: 'networkidle' })
await lp.waitForTimeout(600)
await lp.screenshot({ path: '/tmp/ui-refresh-shots/audit-login.png' })
console.log('login')
await browser.close()
