import { expect, test, type Page } from '@playwright/test'

const TABS = ['overview', 'frustration', 'failures', 'actions', 'versions', 'usage', 'journeys', 'map', 'product', 'features', 'people', 'accounts', 'dictionary']
const WIDTHS = [390, 1400]
const url = (tab: string, extra = '') => `${process.env.PANEL_URL}/#${tab}?project=demo&days=30${extra}`

// Collects every page error and console error; the test asserts the list is empty at the end.
function watch(page: Page) {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message))
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()) })
  return errors
}

async function open(page: Page, tab: string, extra = '') {
  await page.goto(url(tab, extra))
  await expect(page.locator(`a[data-tab="${tab}"]`)).toHaveAttribute('aria-current', 'page')
  await expect(page.locator('#content')).toHaveAttribute('aria-busy', 'false')
  await expect(page.locator('#content')).not.toHaveText(/^\s*$/)
  // The panel catches a render error and shows it as text, so a page error alone would miss it.
  await expect(page.locator('#content')).not.toContainText(/Não consegui ler os dados|Could not read the data/)
  await expect(page.locator('#content')).not.toContainText(/Nenhuma visita neste período|No visits in this period/) // the seed has data
}

for (const width of WIDTHS) {
  for (const tab of TABS) {
    test(`${tab} at ${width}px: no errors, no horizontal scroll`, async ({ page }) => {
      const errors = watch(page)
      await page.setViewportSize({ width, height: 900 })
      await open(page, tab)
      await page.waitForLoadState('networkidle')
      const scroll = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(scroll, 'horizontal page scroll').toBeLessThanOrEqual(0)
      expect(errors).toEqual([])
    })
  }
}

test('map draws the screen that has a layout', async ({ page }) => {
  const errors = watch(page)
  await open(page, 'map', '&route=/tickets')
  const svg = page.locator('svg.mapsvg')
  await expect(svg).toBeVisible()
  expect(await svg.locator('.me').count()).toBeGreaterThan(0)
  await page.waitForLoadState('networkidle')
  expect(errors).toEqual([])
})

test.describe('tour', () => {
  for (const tab of TABS) {
    test(`${tab}: opens, moves and closes`, async ({ page }) => {
      const errors = watch(page)
      await open(page, tab)
      await page.locator('#tour-open').click()
      const card = page.locator('.tour-card')
      await expect(card).toBeVisible()
      const counter = card.locator('.tour-n')
      await expect(counter).toHaveText(/^1\D+\d+$/) // "1 de N": at least one step
      const total = Number((await counter.textContent())!.match(/\d+$/)![0])
      expect(total).toBeGreaterThan(0)
      if (total > 1) {
        await page.keyboard.press('ArrowRight')
        await expect(counter).toHaveText(/^2\D/)
        await page.keyboard.press('ArrowLeft')
        await expect(counter).toHaveText(/^1\D/)
        await card.locator('[data-tour="next"]').click()
        await expect(counter).toHaveText(/^2\D/)
      }
      await page.keyboard.press('Escape')
      await expect(card).toHaveCount(0)
      expect(errors).toEqual([])
    })
  }
})

test('the language pick switches the panel to English after reload', async ({ page }) => {
  const errors = watch(page)
  await open(page, 'overview')
  await expect(page.locator('a[data-tab="overview"]')).toHaveText('Início')
  await page.locator('#prefs-open').click()
  await page.locator('[data-pref="lang"][data-value="en"]').click()
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page.locator('a[data-tab="overview"]')).toHaveText('Overview')
  expect(errors).toEqual([])
})
