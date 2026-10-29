import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { routeFromPath, scrub, selectorOf, start as startTermometro, type Termometro, type Identity } from '../src/index'

interface SentEvent { type: string; route: string; target?: string; detail?: string; clicks?: number; duration_ms?: number; targets?: string[] }
interface SentBatch { key: string; version: string; session: string; account: string; user: string; role: string; events: SentEvent[] }

describe('termometro', () => {
  let sent: SentBatch[]
  let termometro: Termometro | null
  const originalFetch = window.fetch

  beforeEach(() => {
    vi.useFakeTimers()
    sent = []
    termometro = null
    window.fetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.body instanceof Blob) sent.push(JSON.parse(await init.body.text()))
      return new Response(null, { status: 204 })
    }) as typeof fetch
    document.body.innerHTML = ''
    // happy-dom sends beacons for real; the tests only look at what goes through fetch.
    Object.defineProperty(navigator, 'sendBeacon', { value: () => false, configurable: true })
  })

  afterEach(() => {
    termometro?.stop()
    window.fetch = originalFetch
    vi.useRealTimers()
  })

  function start(pagesFromRouter = true, identity?: () => Identity | null) {
    termometro = startTermometro({ url: 'http://t.test/', key: 'tk_1', version: '1.0', pagesFromRouter, identity, flushIntervalMs: 1000 })
    return termometro
  }

  async function events() {
    await vi.advanceTimersByTimeAsync(1000)
    await vi.waitFor(() => expect(sent.length).toBeGreaterThan(0))
    return sent.flatMap((b) => b.events)
  }

  function click(el: Element, x = 10, y = 10) {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: x, clientY: y }))
  }

  it('scrubs what could identify someone', () => {
    expect(scrub('User ana@x.com.br not found in "Acme Ltda" (42871)')).toBe('User :email not found in "…" (:id)')
    expect(routeFromPath('/tickets/4821/edit')).toBe('/tickets/:id/edit')
    expect(routeFromPath('/contacts/3f2a9c1e-0b7d-4e55-9f00-1a2b3c4d5e6f')).toBe('/contacts/:id')
  })

  it('builds a short selector without text', () => {
    document.body.innerHTML = '<div id="toolbar"><span class="grp"><button class="p-button save">Salvar Maria</button></span></div>'
    expect(selectorOf(document.querySelector('button'))).toBe('div#toolbar > span.grp > button.p-button.save')
  })

  it('sends the visit with app, version and session', async () => {
    start().page('/tickets/:id')
    const [batch] = (await events(), sent)
    expect(batch).toMatchObject({ key: 'tk_1', version: '1.0' })
    expect(batch!.session).toBeTruthy()
    expect(batch!.events).toEqual([{ type: 'page', route: '/tickets/:id' }])
    expect(batch).toMatchObject({ account: '', user: '', role: '' })
  })

  it('counts the first visit itself when no router reports it', async () => {
    start(false)
    expect((await events()).filter((e) => e.type !== 'inventory').map((e) => e.type)).toEqual(['page'])
  })

  it('reports one rage click per burst and no dead click for it', async () => {
    start().page('/tickets')
    document.body.innerHTML = '<button id="save">Salvar</button>'
    const button = document.querySelector('button')!
    for (let i = 0; i < 5; i++) click(button)
    await vi.advanceTimersByTimeAsync(1500)
    const signals = (await events()).filter((e) => e.type !== 'page' && e.type !== 'click' && e.type !== 'inventory')
    expect(signals).toEqual([{ type: 'rage', route: '/tickets', target: 'button#save' }])
  })

  it('reports a dead click when nothing changes after it', async () => {
    start().page('/tickets')
    document.body.innerHTML = '<button id="nothing">x</button><button id="opens">y</button>'
    await vi.advanceTimersByTimeAsync(0) // the observer hears the test's own markup before the click
    click(document.querySelector('#nothing')!, 10, 10)
    await vi.advanceTimersByTimeAsync(1500)
    click(document.querySelector('#opens')!, 200, 200)
    document.body.appendChild(document.createElement('div'))
    await vi.advanceTimersByTimeAsync(1500)
    const dead = (await events()).filter((e) => e.type === 'dead')
    expect(dead.map((e) => e.target)).toEqual(['button#nothing'])
  })

  it('ignores clicks on things that are not clickable', async () => {
    start().page('/x')
    document.body.innerHTML = '<p id="text">texto</p>'
    click(document.querySelector('p')!)
    await vi.advanceTimersByTimeAsync(1500)
    expect((await events()).some((e) => e.type === 'dead')).toBe(false)
  })

  it('reports an abandoned form when the user leaves the screen, but not after it was saved', async () => {
    const t = start()
    t.page('/a')
    document.body.innerHTML = '<div role="dialog" id="new-ticket"><input id="subject"></div>'
    document.querySelector('input')!.dispatchEvent(new Event('input', { bubbles: true }))
    t.page('/b')
    document.querySelector('input')!.dispatchEvent(new Event('input', { bubbles: true }))
    document.dispatchEvent(new Event('submit'))
    t.page('/c')
    const abandoned = (await events()).filter((e) => e.type === 'abandon')
    expect(abandoned).toEqual([{ type: 'abandon', route: '/a', target: 'div#new-ticket' }])
  })

  it('does not count typing outside a form or dialog (filters, searches)', async () => {
    const t = start()
    t.page('/a')
    document.body.innerHTML = '<input id="filter">'
    document.querySelector('input')!.dispatchEvent(new Event('input', { bubbles: true }))
    t.page('/b')
    expect((await events()).some((e) => e.type === 'abandon')).toBe(false)
  })

  it('reports failed requests with the path scrubbed, and leaves 401 out', async () => {
    window.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.body instanceof Blob) {
        sent.push(JSON.parse(await init.body.text()))
        return new Response(null, { status: 204 })
      }
      const status = String(input).includes('expired') ? 401 : String(input).includes('missing') ? 404 : 500
      return new Response(null, { status })
    }) as typeof fetch
    start().page('/tickets/:id')
    await fetch('/api/tickets/9182/missing?q=ana')
    await fetch('/api/tickets/9182', { method: 'PUT' })
    await fetch('/api/auth/expired')
    const failures = (await events()).filter((e) => e.type.startsWith('http'))
    expect(failures).toEqual([
      { type: 'http_4xx', route: '/tickets/:id', detail: 'GET /api/tickets/:id/missing 404' },
      { type: 'http_5xx', route: '/tickets/:id', detail: 'PUT /api/tickets/:id 500' }
    ])
  })

  it('reports errors scrubbed and caps repeats of the same one', async () => {
    const t = start()
    t.page('/x')
    for (let i = 0; i < 5; i++) t.error(new TypeError('Cannot read "name" of ticket 12345'))
    const errors = (await events()).filter((e) => e.type === 'js_error')
    expect(errors).toHaveLength(3)
    expect(errors[0]!.detail).toBe('TypeError: Cannot read "…" of ticket :id')
  })

  it('reports a bounce when the user goes back right after arriving', async () => {
    const t = start()
    t.page('/tickets/:id')
    window.dispatchEvent(new PopStateEvent('popstate'))
    expect((await events()).filter((e) => e.type === 'bounce')).toEqual([{ type: 'bounce', route: '/tickets/:id' }])
  })

  it('records every click with a selector the heat map can query back', async () => {
    start().page('/tickets')
    document.body.innerHTML = '<div class="toolbar h-[3px]"><button class="md:flex">Salvar Maria</button></div><p id="txt">x</p>'
    click(document.querySelector('button')!)
    click(document.querySelector('p')!, 300, 300)
    const clicks = (await events()).filter((e) => e.type === 'click').map((e) => e.target!)
    expect(clicks).toEqual(['div.toolbar.h-\\[3px\\] > button.md\\:flex', 'p#txt'])
    expect(document.querySelector(clicks[0]!)).toBe(document.querySelector('button'))
  })

  it('sends who is using it as ids, one batch per identity', async () => {
    let id: Identity | null = { account: 77, user: 'u-1', role: 'Agent' }
    const t = start(true, () => id)
    t.page('/a')
    id = null
    t.page('/login')
    await events()
    expect(sent.map((b) => [b.account, b.user, b.role, b.events.map((e) => e.route)])).toEqual([
      ['77', 'u-1', 'Agent', ['/a']],
      ['', '', '', ['/login']]
    ])
  })

  it('reports an accepted write as an action with the clicks and time it took', async () => {
    window.fetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.body instanceof Blob) sent.push(JSON.parse(await init.body.text()))
      return new Response(null, { status: init?.method === 'PUT' ? 500 : 201 })
    }) as typeof fetch
    start().page('/tickets/new')
    document.body.innerHTML = '<button id="a">a</button><button id="b">b</button>'
    await fetch('/api/heartbeat', { method: 'POST' }) // nobody clicked: not an action
    click(document.querySelector('#a')!, 10, 10)
    await vi.advanceTimersByTimeAsync(2000)
    click(document.querySelector('#b')!, 100, 10)
    click(document.querySelector('#a')!, 200, 10)
    await fetch('/api/tickets', { method: 'POST' })
    click(document.querySelector('#b')!, 300, 10)
    await fetch('/api/tickets/4821', { method: 'PUT' }) // refused: not an action, and the failure names the click
    const all = await events()
    expect(all.filter((e) => e.type === 'action')).toEqual([
      { type: 'action', route: '/tickets/new', detail: 'POST /api/tickets', clicks: 3, duration_ms: 2000 }
    ])
    expect(all.find((e) => e.type === 'http_5xx')).toMatchObject({ target: 'button#b', detail: 'PUT /api/tickets/:id 500' })
  })

  it('starts counting an action again after two idle minutes', async () => {
    start().page('/x')
    document.body.innerHTML = '<button id="a">a</button>'
    click(document.querySelector('#a')!, 10, 10)
    await vi.advanceTimersByTimeAsync(121_000)
    click(document.querySelector('#a')!, 10, 10)
    await fetch('/api/x', { method: 'POST' })
    expect((await events()).find((e) => e.type === 'action')).toMatchObject({ clicks: 1, duration_ms: 0 })
  })

  it('lists what can be clicked on a screen once per session', async () => {
    const t = start()
    document.body.innerHTML = '<button id="save">s</button><a href="/h" id="help">h</a><span>x</span><div data-termometro><button id="map">m</button></div>'
    t.page('/a')
    await vi.advanceTimersByTimeAsync(1500)
    t.page('/b')
    t.page('/a')
    await vi.advanceTimersByTimeAsync(1500)
    const inventories = (await events()).filter((e) => e.type === 'inventory')
    expect(inventories.map((e) => [e.route, e.targets])).toEqual([['/a', ['button#save', 'a#help']]])
  })

  it('ignores clicks on its own heat map', async () => {
    start().page('/x')
    document.body.innerHTML = '<div data-termometro><button id="close">x</button></div>'
    click(document.querySelector('#close')!)
    await vi.advanceTimersByTimeAsync(1500)
    expect((await events()).some((e) => e.type === 'click' || e.type === 'dead')).toBe(false)
  })

  it('opens the heat map with the token from the URL and takes the token out of the address bar', () => {
    history.replaceState(null, '', '/orders?tab=2&termometro_map=m.shop.123.sig#top')
    try {
      start().page('/orders')
      expect(location.pathname + location.search + location.hash).toBe('/orders?tab=2#top')
      const script = document.head.querySelector<HTMLScriptElement>('script[src="http://t.test/map.js"]')
      expect(script).not.toBeNull()
      const map = (window as unknown as { termometroMap: { url: string; token: string; route: () => string; onClose: () => void } }).termometroMap
      expect([map.url, map.token, map.route()]).toEqual(['http://t.test', 'm.shop.123.sig', '/orders'])
      expect(sessionStorage.getItem('termometro.map')).toBe('m.shop.123.sig')
      map.onClose()
      expect(sessionStorage.getItem('termometro.map')).toBeNull()
      script!.remove()
    } finally {
      history.replaceState(null, '', '/')
    }
  })

  it('gives the visit recorded before identify() to the person who signed in', async () => {
    const t = start(false)
    t.identify({ account: 'acme', user: 'u-7', role: 'buyer' })
    const first = (await events(), sent[0]!)
    expect([first.user, first.events[0]!.type]).toEqual(['u-7', 'page'])
  })

  it('takes who is using it from identify() when there is no identity function', async () => {
    const t = start()
    t.identify({ account: 9, user: 'u-2', role: 'admin' })
    t.page('/a')
    t.identify(null)
    t.page('/b')
    await events()
    expect(sent.map((b) => [b.account, b.user, b.role])).toEqual([['9', 'u-2', 'admin'], ['', '', '']])
  })

  it('restores fetch on stop', () => {
    const before = window.fetch
    start().stop()
    termometro = null
    expect(window.fetch).toBe(before)
  })
})
