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

test('the verdict link opens the list on what needs you, even with the list already in view', async ({ page }) => {
  const errors = watch(page)
  await page.setViewportSize({ width: 1400, height: 2000 })
  await open(page, 'overview')
  // The other view first: the link has to bring the list back.
  await page.locator('[data-todo-view="type"]').click()
  const go = page.locator('[data-todo-go]')
  test.skip(!(await go.count()), 'the seed has nothing that needs you')
  await go.click()
  await expect(page.locator('.card.todo .todo-list')).toBeVisible()
  const bad = page.locator('.todo-list .todo-row:has(.kchip.bad)')
  await expect(bad.first()).toBeVisible()
  await expect(bad.first()).toHaveClass(/\bhit\b/)
  expect(await bad.evaluateAll((rows) => rows.every((r) => !(r as HTMLElement).hidden))).toBe(true)
  expect(errors).toEqual([])
})

// The map drawn over a stand-in for the app: the seed's /tickets controls, plus one control other people clicked that this
// screen does not have (it must be listed, not lost).
test.describe('map over the app', () => {
  async function openMap(page: Page, html: string) {
    const errors = watch(page)
    await page.goto(`${process.env.PANEL_URL}/api/status`) // same origin, no panel scripts
    const { token } = await page.evaluate(async () => (await fetch('/api/map-token?project=demo', { method: 'POST' })).json())
    await page.evaluate(([body, token]) => {
      document.body.innerHTML = body
      ;(window as any).termometroMap = { url: location.origin, token, route: () => '/tickets' }
      sessionStorage.setItem('termometro.lang', 'pt')
    }, [html, token])
    await page.addScriptTag({ url: '/map.js' })
    const panel = page.locator('[data-termometro] [role="dialog"]')
    await expect(panel).toContainText('visitas')
    return { panel, errors }
  }

  test('lists what is not on this screen, numbers the list and cuts by role', async ({ page }) => {
    const { panel, errors } = await openMap(page, '<button id="new" style="margin:200px">New ticket</button>')
    await expect(panel.locator('[data-absent]')).toContainText('Export') // clicked by others, missing here
    await expect(panel.locator('ol [data-t]').first()).toContainText(/^1\./)
    const who = panel.locator('select[data-act="who"]')
    await expect(who.locator('optgroup[label="Papel"] option')).toHaveCount(2)
    await who.selectOption('role:agent')
    await expect(panel.locator('select[data-act="who"]')).toHaveValue('role:agent')
    if (process.env.MAP_SHOT) await page.screenshot({ path: process.env.MAP_SHOT.replace('.png', '-heat.png') })
    expect(errors).toEqual([])
  })

  test('routes: arrows only on the step pointed at, the time window and leaving the screen', async ({ page }) => {
    const { panel, errors } = await openMap(page,
      '<button id="new" style="position:fixed;left:100px;top:100px">New ticket</button><button id="export" style="position:fixed;left:500px;top:300px">Export</button>')
    await panel.locator('[data-lens="routes"]').click()
    const steps = panel.locator('ol [data-t]')
    await expect(steps.first()).toContainText('New ticket → Export')
    await expect(panel).toContainText(/abre (Home|Users)/) // the last click leaves to another screen, by its name
    await expect(page.locator('[data-termometro] path[data-step]')).toHaveCount(0) // nothing drawn until pointed at
    await steps.first().hover()
    await expect(page.locator('[data-termometro] path[data-step]')).toHaveCount(1)
    await panel.locator('select[data-act="unit"]').selectOption('none')
    await expect(panel.locator('input[data-act="step"]')).toHaveCount(0)
    await expect(panel.locator('select[data-act="unit"]')).toHaveValue('none')
    await panel.locator('select[data-act="unit"]').selectOption('min')
    await expect(panel.locator('input[data-act="step"]')).toHaveValue('1')
    if (process.env.MAP_SHOT) { await steps.first().hover(); await page.screenshot({ path: process.env.MAP_SHOT }) }
    expect(errors).toEqual([])
  })
})
