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

test('the map tab: time between clicks, exits to other screens, and the real screen as a secondary link', async ({ page }) => {
  const errors = watch(page)
  await open(page, 'map', '&route=/tickets')
  await expect(page.locator('.card', { hasText: 'Saídas para outras telas' })).toContainText(/Home|Users/)
  const unit = page.locator('#map-step-unit')
  await expect(page.locator('#map-step')).toHaveValue('30')
  const asked = page.waitForRequest((r) => r.url().includes('/api/usage') && r.url().includes('route=') && r.url().includes('step=0'))
  await unit.selectOption('none')
  await asked
  await expect(page.locator('#map-step')).toHaveCount(0)
  await expect(page.locator('.mapbar [data-open-map]')).toHaveCount(0) // the real screen is a link below, not the main bar
  await expect(page.locator('.mapopen')).toBeVisible()
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

// The seed's 1.1 arrived 4 days ago, slower on Invite and with a new 500 there: the band under the verdict cuts at it.
test('the morning check says since which version and each chip opens its evidence', async ({ page }) => {
  const errors = watch(page)
  await open(page, 'overview')
  const band = page.locator('section.verdict .since')
  await expect(band).toContainText(/Desde a 1\.1, que chegou em \d\d\/\d\d/)
  await expect(band).toContainText(/1 tela piorou, 2 falhas novas/) // the slow Invite and its 500
  await expect(band.locator('a.pill', { hasText: 'Users' })).toHaveAttribute('href', /#frustration\?.*route=%2Fusers/)
  const fresh = band.locator('a.pill', { hasText: 'POST /api/invites 500' })
  await expect(fresh).toHaveAttribute('href', /#failures\?.*signal=http_5xx/)
  await fresh.click()
  await expect(page.locator('a[data-tab="failures"]')).toHaveAttribute('aria-current', 'page')
  expect(errors).toEqual([])
})

test('the marks dialog offers the versions that arrived as one-click marks', async ({ page }) => {
  const errors = watch(page)
  await open(page, 'overview')
  // The mark is shared by every test on this server: the answer is faked here, the request is what is checked.
  let sent: any = null
  await page.route('**/api/mark?*', async (route) => {
    sent = route.request().postDataJSON()
    await route.fulfill({ json: { mark: sent.at, marks: [{ id: 'x1', name: sent.name, at: sent.at }] } })
  })
  await page.locator('#marks-open').click()
  const sug = page.locator('#mark-sug')
  await expect(sug.locator('button')).toHaveCount(2) // 1.1 and 1.0, newest first
  await expect(sug.locator('button').first()).toContainText(/1\.1\s+chegou em/)
  await sug.locator('button').first().click()
  await expect(page.locator('#marks')).toHaveCount(0)
  expect(sent).toMatchObject({ action: 'create', name: 'Versão 1.1' })
  expect(sent.at).toBeLessThan(Date.now() - 3 * 86400_000) // when 1.1 arrived, not now
  await expect(page.locator('#marks-open')).toContainText('Versão 1.1')
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
    expect(errors).toEqual([])
  })

  test('an element that is not on the screen says what opens it, or who has it', async ({ page }) => {
    const { panel, errors } = await openMap(page, '<button id="new" style="position:fixed;left:100px;top:100px">New ticket</button>')
    await panel.locator('[data-absent] button[data-t="button#export"]').click()
    await expect(panel).toContainText('Aparece depois de clicar em New ticket')
    await panel.locator('button[data-t="button#new"]', { hasText: 'Mostrar' }).click()
    await expect(panel.locator('h2')).toHaveText('New ticket') // now on what opens it, marked on the screen
    const box = (await page.locator('#new').boundingBox())!
    const marked = await page.evaluate(([x, y]) => [...document.querySelectorAll('[data-termometro] div')].some((d) => {
      const r = d.getBoundingClientRect(); return Math.abs(r.left - x) < 2 && Math.abs(r.top - y) < 2 && getComputedStyle(d).borderTopWidth === '3px' }), [box.x, box.y])
    expect(marked).toBe(true)
    await expect(panel.locator('[data-off]')).toBeHidden() // missing from the screen is not "out of view"
    expect(errors).toEqual([])
  })

  test('an element nobody reaches from this screen says who clicks it', async ({ page }) => {
    const { panel, errors } = await openMap(page, '<button id="export" style="position:fixed;left:100px;top:100px">Export</button>')
    await panel.locator('[data-absent] button[data-t="button#new"]').click()
    await expect(panel).toContainText(/Quem clica: (agent|manager) \(\d+ cliques\)/)
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
    expect(errors).toEqual([])
  })
})

// Finding, sharing and reading numbers ---------------------------------------------------------------------------
test.describe('share this view', () => {
  test.use({ permissions: ['clipboard-read', 'clipboard-write'] })
  const clip = (page: Page) => page.evaluate(() => navigator.clipboard.readText())
  const share = async (page: Page, what: 'link' | 'text') => {
    await page.locator('#share-open').click()
    await page.locator(`#share [data-share="${what}"]`).click()
    await expect(page.locator(`#share [data-share="${what}"]`)).toHaveText('Copiado')
  }

  test('copies the link with the tab, period and filters', async ({ page }) => {
    const errors = watch(page)
    await open(page, 'versions', '&account=4821&role=agent')
    await share(page, 'link')
    const link = await clip(page)
    expect(link).toContain('#versions?')
    for (const part of ['project=demo', 'days=30', 'account=4821', 'role=agent']) expect(link).toContain(part)
    expect(errors).toEqual([])
  })

  for (const [tab, title] of [['overview', 'Início'], ['frustration', 'Frustração'], ['failures', 'Falhas'], ['versions', 'Versões'], ['usage', 'Uso'], ['people', 'Pessoas']]) {
    test(`the text summary of ${tab} has title, period, filters, numbers and the link`, async ({ page }) => {
      const errors = watch(page)
      await open(page, tab, '&account=4821')
      await share(page, 'text')
      const text = await clip(page)
      const lines = text.split('\n')
      expect(lines[0]).toContain(title)
      expect(text).toContain('Período: nos últimos 30 dias')
      expect(text).toContain('Filtros: Conta: 4821')
      expect(lines.filter((l) => /\d/.test(l) && !l.startsWith('Link:')).length).toBeGreaterThan(2) // the numbers, not only the frame
      expect(lines.at(-1)).toContain(`#${tab}?`)
      expect(errors).toEqual([])
    })
  }

  test('keyboard: opens on the first item, arrows move, Escape closes and gives the focus back', async ({ page }) => {
    await open(page, 'overview')
    await page.locator('#share-open').focus()
    await page.keyboard.press('Enter')
    await expect(page.locator('#share [data-share="link"]')).toBeFocused()
    await page.keyboard.press('ArrowDown')
    await expect(page.locator('#share [data-share="text"]')).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(page.locator('#share')).toHaveCount(0)
    await expect(page.locator('#share-open')).toBeFocused()
  })

  test('tabs without a summary still share the link', async ({ page }) => {
    await open(page, 'dictionary')
    await share(page, 'text')
    const text = await clip(page)
    expect(text).toContain('Dicionário')
    expect(text).toContain('#dictionary?')
  })
})

test('choosing a search result empties the search field', async ({ page }) => {
  const errors = watch(page)
  await open(page, 'overview')
  const input = page.locator('#search')
  await input.fill('users')
  const first = page.locator('#results a').first()
  await expect(first).toBeVisible()
  await first.click()
  await expect(input).toHaveValue('')
  await expect(page.locator('#results')).toBeHidden()
  expect(errors).toEqual([])
})

test.describe('active filters show on every tab', () => {
  for (const tab of TABS.filter((t) => t !== 'map')) {
    test(`${tab}: chips and "Limpar tudo"`, async ({ page }) => {
      await open(page, tab, '&account=4821&role=agent')
      const chips = page.locator('#active-filters .chip')
      await expect(chips).toHaveCount(2)
      await expect(chips.nth(0)).toContainText('Conta: 4821')
      await expect(chips.nth(1)).toContainText('Papel: agent')
      await page.locator('#active-filters [data-clear="**"]').click()
      await expect(page.locator('#active-filters')).toBeHidden()
      await expect(page.locator('#account')).toHaveValue('')
      await expect(page.locator('#role')).toHaveValue('')
    })
  }
})

test('numbers say what they count', async ({ page }) => {
  const errors = watch(page)
  await open(page, 'versions')
  const tile = page.locator('.numbers .card', { hasText: 'Falhas por sessão' })
  await expect(tile).toContainText(/\d+(,\d+)? → \d+(,\d+)?/)
  await expect(tile).toContainText(/falhas · .* sessões · esperado: 0/)
  await expect(page.locator('#content')).not.toContainText('por 100 sessões')
  await open(page, 'overview')
  await expect(page.locator('.tile', { hasText: 'Pessoas' })).toContainText('pessoas diferentes')
  await expect(page.locator('.tile', { hasText: 'Visitas' })).toContainText('telas abertas')
  await expect(page.locator('.tile', { hasText: 'Falhas' })).toContainText('erros, lentidões e pedidos recusados')
  // The lists beside "who was hit" count times (the server counts events per account), and the title counts who.
  await open(page, 'failures', `&signal=http_5xx&detail=${encodeURIComponent('POST /api/invites 500')}`)
  const hit = page.locator('.facts > div', { hasText: 'Contas atingidas' })
  await expect(hit).toContainText(/Contas atingidas \(\d+\)/)
  await expect(hit).toContainText('vezes em cada uma')
  await expect(hit.locator('li b').first()).toHaveText(/^\d+×$/)
  expect(errors).toEqual([])
})

test('phone: the open tab is in view, the tab bar hints it scrolls, the search has its own row', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 })
  await open(page, 'accounts')
  const nav = page.locator('nav.tabs')
  await expect(nav).toHaveClass(/fade-l/) // more tabs to the left: the fade says so
  const inView = await page.evaluate(() => {
    const a = document.querySelector('nav.tabs a.on')!.getBoundingClientRect(), n = document.querySelector('nav.tabs')!.getBoundingClientRect()
    return a.left >= n.left && a.right <= n.right
  })
  expect(inView).toBe(true)
  await open(page, 'overview')
  await expect(nav).toHaveClass(/fade-r/) // more tabs to the right
  const [search, tour] = await Promise.all([page.locator('.search').boundingBox(), page.locator('#tour-open').boundingBox()])
  expect(search!.y).toBeGreaterThan(tour!.y + tour!.height - 1)
})
