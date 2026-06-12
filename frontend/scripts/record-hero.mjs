// Record hero videos for all 3 themes against the showcase instance.
//
// Usage:
//   scripts/run-showcase.sh           # in another terminal
//   node frontend/scripts/record-hero.mjs
//
// Output: website/public/hero-{light,dark,amber}.webm
import { chromium } from 'playwright'
import { rename, readdir, unlink } from 'node:fs/promises'
import path from 'node:path'

const BASE = process.env.TOME_SCREENSHOT_BASE ?? 'http://localhost:5174'
const API = 'http://localhost:8090'
const USER = 'benedict'
const PASS = 'showcase'

const __dir = path.dirname(new URL(import.meta.url).pathname)
const TMP_DIR = path.resolve(__dir, '../../docs/_herotmp')
const OUT_DIR = path.resolve(__dir, '../../website/public')

const VIEWPORT = { width: 1400, height: 900 }
const THEMES = ['light', 'dark', 'amber']

async function getToken() {
  const res = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: USER, password: PASS }),
  })
  const { access_token } = await res.json()
  return access_token
}

async function recordTheme(token, theme) {
  const tmpDir = path.join(TMP_DIR, theme)
  await import('node:fs').then(fs => fs.mkdirSync(tmpDir, { recursive: true }))

  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 1,
    recordVideo: { dir: tmpDir, size: VIEWPORT },
  })

  // Use a non-recording browser to log in, set theme, and pre-warm the page
  const warmBrowser = await chromium.launch({ headless: true })
  const warmContext = await warmBrowser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1 })
  const warmPage = await warmContext.newPage()
  await warmPage.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await warmPage.evaluate(({ t, theme }) => {
    localStorage.setItem('tome_token', t)
    localStorage.setItem('tome_sidebar', 'open')
    localStorage.setItem('tome_theme', theme)
  }, { t: token, theme })
  await warmPage.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await warmPage.locator('button:has-text("All Books")').first().waitFor({ state: 'visible', timeout: 20000 })
  // Page is warm — grab the storage state so the recording context starts authenticated
  const storageState = await warmContext.storageState()
  await warmBrowser.close()

  // Now start the recording context with auth already in place
  const page = await context.newPage()
  await page.addInitScript(({ t, theme }) => {
    localStorage.setItem('tome_token', t)
    localStorage.setItem('tome_sidebar', 'open')
    localStorage.setItem('tome_theme', theme)
  }, { t: token, theme })
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.locator('button:has-text("All Books")').first().waitFor({ state: 'visible', timeout: 20000 })
  // Minimal pause — page is already warm, content is cached
  await page.waitForTimeout(200)

  await smoothScroll(page, 400, 1000)
  await page.waitForTimeout(600)
  await smoothScroll(page, -400, 1000)
  await page.waitForTimeout(400)

  // 2. All Books
  await page.locator('button:has-text("All Books")').first().click()
  await page.waitForTimeout(1500)

  // 3. Book detail
  const bookCard = page.locator('img[loading="lazy"]').first()
  if (await bookCard.isVisible()) {
    await bookCard.click()
    await page.waitForTimeout(2500)
  }

  // 4. Series view
  await page.goBack()
  await page.waitForTimeout(1000)
  await page.locator('button:has-text("Series")').first().click()
  await page.waitForTimeout(2000)

  // 5. Berserk series detail
  const berserk = page.locator('text=Berserk').first()
  if (await berserk.isVisible()) {
    await berserk.click()
    await page.waitForTimeout(2500)
    await smoothScroll(page, 500, 1500)
    await page.waitForTimeout(1000)
  }

  // 6. Stats
  await page.goto(`${BASE}/stats`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(2000)
  await smoothScroll(page, 400, 1200)
  await page.waitForTimeout(1000)

  // 7. Habits tab
  const habitsBtn = page.locator('button:has-text("Habits")').first()
  if (await habitsBtn.isVisible()) {
    await habitsBtn.click()
    await page.waitForTimeout(2000)
  }

  await page.waitForTimeout(1000)

  await page.close()
  await context.close()
  await browser.close()

  // Find the generated video and move it to the output
  const files = await readdir(tmpDir)
  const fs = await import('node:fs')
  const webm = files.find(f => f.endsWith('.webm') && fs.statSync(path.join(tmpDir, f)).size > 0)
  if (webm) {
    const dest = path.join(OUT_DIR, `hero-${theme}.webm`)
    await rename(path.join(tmpDir, webm), dest)
    console.log(`  ${theme}: ${dest}`)
  }

  // Clean up tmp
  const remaining = await readdir(tmpDir)
  for (const f of remaining) await unlink(path.join(tmpDir, f)).catch(() => {})
  await import('node:fs').then(fs => fs.rmdirSync(tmpDir, { recursive: true }))
}

async function smoothScroll(page, distance, duration) {
  await page.evaluate(({ distance, duration }) => {
    return new Promise((resolve) => {
      const start = window.scrollY
      const startTime = performance.now()
      function step(now) {
        const elapsed = now - startTime
        const progress = Math.min(elapsed / duration, 1)
        const ease = progress < 0.5
          ? 2 * progress * progress
          : 1 - Math.pow(-2 * progress + 2, 2) / 2
        window.scrollTo(0, start + distance * ease)
        if (progress < 1) requestAnimationFrame(step)
        else resolve()
      }
      requestAnimationFrame(step)
    })
  }, { distance, duration })
}

async function run() {
  const token = await getToken()
  console.log('Recording hero videos…')
  for (const theme of THEMES) {
    console.log(`  Recording ${theme}…`)
    await recordTheme(token, theme)
  }
  // Clean up tmp root
  await import('node:fs').then(fs => fs.rmSync(TMP_DIR, { recursive: true, force: true }))
  console.log('Done.')
}

run().catch((e) => { console.error(e); process.exit(1) })
