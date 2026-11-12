import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fieldLabelOf, labelOf, routeFromPath, scrub, screenOf, selectorOf, stackOf, start as startTermometro, type Termometro, type Identity } from '../src/index'

interface SentEvent { type: string; route: string; label?: string; labels?: string[]; target?: string; detail?: string; clicks?: number; duration_ms?: number; targets?: string[]; t?: number; stack?: string }
interface SentBatch { key: string; version: string; session: string; account: string; user: string; role: string; device?: string; sent?: number; events: SentEvent[] }

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
    termometro = startTermometro({ url: 'http://t.test/', key: 'tk_1', countScriptedClicks: true, version: '1.0', pagesFromRouter, identity, flushIntervalMs: 1000 })
    return termometro
  }

  async function events() {
    await vi.advanceTimersByTimeAsync(1000)
    await vi.waitFor(() => expect(sent.length).toBeGreaterThan(0))
    // Every event carries its time; the tests below look at the rest.
    return sent.flatMap((b) => b.events).map(({ t: _t, ...e }) => e)
  }

  function click(el: Element, x = 10, y = 10) {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: x, clientY: y }))
  }

  it('scrubs what could identify someone', () => {
    expect(scrub('User ana@x.com.br not found in "Acme Ltda" (42871)')).toBe('User :email not found in "…" (:id)')
    expect(routeFromPath('/tickets/4821/edit')).toBe('/tickets/:id/edit')
    expect(routeFromPath('/contacts/3f2a9c1e-0b7d-4e55-9f00-1a2b3c4d5e6f')).toBe('/contacts/:id')
  })

  it('names a control by its own words, never by a record or a field', () => {
    document.body.innerHTML = `
      <nav><ul><li><a href="/u" id="menu">Usuários</a></li></ul></nav>
      <div class="toolbar"><button id="new"> Novo
        usuário </button><button id="icon" aria-label="Exportar"><svg></svg></button><button id="bare"><svg></svg></button>
        <button id="mine" data-termometro-label="Criar conta">+</button><input type="submit" id="send" value="Enviar"></div>
      <table><tr><td><button id="row">Maria Souza</button></td></tr></table>
      <ul class="contacts"><li><a href="/c/1" id="contact">João Lima</a></li></ul>
      <div data-termometro-private><button id="private">Ana</button></div>
      <button id="long">Este texto é comprido demais para ser o rótulo de um botão qualquer</button>
      <button id="mail">Enviar para ana@x.com</button>`
    const label = (id: string) => labelOf(document.getElementById(id))
    expect(['menu', 'new', 'icon', 'bare', 'mine', 'send'].map(label)).toEqual(['Usuários', 'Novo usuário', 'Exportar', '', 'Criar conta', 'Enviar'])
    expect(['row', 'contact', 'private', 'long'].map(label)).toEqual(['', '', '', ''])
    expect(label('mail')).toBe('Enviar para :email')
  })

  it('names a screen from the app, a marked element or the title, never on a record page', () => {
    document.title = 'Usuários | ndesk'
    expect(screenOf('/config/usuarios')).toBe('Usuários')
    expect(screenOf('/tickets/:id')).toBe('') // the title of a record page is the record
    expect(screenOf('/tickets/:id', 'Ticket')).toBe('Ticket')
    document.body.innerHTML = '<h2 data-termometro-screen="Configurações">x</h2>'
    expect(screenOf('/config')).toBe('Configurações')
  })

  it('sends the screen name with the visit and the labels with the inventory', async () => {
    document.title = 'Usuários — ndesk'
    document.body.innerHTML = '<button id="new">Novo usuário</button><table><tr><td><a href="/u/1" id="u">Maria</a></td></tr></table>'
    start().page('/config/usuarios')
    await vi.advanceTimersByTimeAsync(1500)
    const all = await events()
    expect(all.find((e) => e.type === 'page')).toMatchObject({ label: 'Usuários' })
    expect(all.find((e) => e.type === 'inventory')).toMatchObject({ targets: ['button#new', 'a#u'], labels: ['Novo usuário', ''] })
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
    expect(batch!.events).toEqual([{ type: 'page', route: '/tickets/:id', t: expect.any(Number) }])
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
    expect(signals).toEqual([{ type: 'rage', route: '/tickets', target: 'button#save', label: 'Salvar', detail: 'nothing' }])
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

  it('ignores the CDN proxy beacon (/cdn-cgi/) on any host: no failure, no slow', async () => {
    window.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.body instanceof Blob) {
        sent.push(JSON.parse(await init.body.text()))
        return new Response(null, { status: 204 })
      }
      if (String(input).includes('blocked')) throw new TypeError('Failed to fetch')
      await new Promise((r) => setTimeout(r, 3500))
      return new Response(null, { status: String(input).includes('rum') ? 200 : 500 })
    }) as typeof fetch
    start().page('/tickets/:id')
    const wait = async (url: string, init?: RequestInit) => {
      const p = fetch(url, init).catch(() => {})
      await vi.advanceTimersByTimeAsync(3500)
      await p
    }
    await wait('/cdn-cgi/rum', { method: 'POST' })
    await wait('https://app.example.com/cdn-cgi/rum?x=1', { method: 'POST' })
    await wait('/cdn-cgi/blocked', { method: 'POST' })
    await wait('/api/tickets/9182', { method: 'PUT' })
    const e = (await events()).filter((x) => x.type.startsWith('http') || x.type === 'slow')
    expect(e.map((x) => x.detail)).toEqual(['PUT /api/tickets/:id 500'])
  })

  // A fetch whose status comes from a script, and that takes `delay` ms.
  function scripted(status: (url: string, method: string) => number | 'fail', delay = 0) {
    window.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.body instanceof Blob) {
        sent.push(JSON.parse(await init.body.text()))
        return new Response(null, { status: 204 })
      }
      const r = status(String(input), (init?.method ?? 'GET').toUpperCase())
      if (delay) await new Promise((res) => setTimeout(res, delay))
      if (r === 'fail') throw new TypeError('Failed to fetch')
      return new Response(null, { status: r })
    }) as typeof fetch
  }
  async function call(url: string, init?: RequestInit, wait = 0) {
    const p = fetch(url, init).catch(() => {})
    if (wait) await vi.advanceTimersByTimeAsync(wait)
    await p
  }
  const signals = (all: Array<{ type: string }>) => all.filter((x) => x.type !== 'click' && x.type !== 'page' && x.type !== 'inventory')

  it('requests.ignore: never a failure, slow or action (host and case do not matter)', async () => {
    scripted((url) => (url.includes('/api/beacon') ? 500 : 200), 3500)
    termometro = startTermometro({ url: 'http://t.test/', key: 'tk_1', countScriptedClicks: true, pagesFromRouter: true, flushIntervalMs: 1000,
      requests: { ignore: ['POST /api/beacon', 'get /api/quiet'] } })
    termometro.page('/x')
    document.body.innerHTML = '<button id="a">a</button>'
    click(document.querySelector('#a')!)
    await call('/api/beacon', { method: 'POST' }, 3500)
    await call('https://other.example.com/api/beacon/1', { method: 'POST' }, 3500)
    await call('/api/quiet', undefined, 3500)
    expect(signals(await events())).toEqual([])
  })

  it('requests.background: one failure per episode, never slow, never an action', async () => {
    let down = true
    scripted(() => (down ? 503 : 200), 3500)
    termometro = startTermometro({ url: 'http://t.test/', key: 'tk_1', countScriptedClicks: true, pagesFromRouter: true, flushIntervalMs: 1000,
      requests: { background: ['/api/poll'] } })
    termometro.page('/x')
    document.body.innerHTML = '<button id="a">a</button>'
    click(document.querySelector('#a')!)
    for (let i = 0; i < 3; i++) await call('/api/poll', undefined, 3500)
    down = false
    await call('/api/poll', { method: 'POST' }, 3500) // succeeds: ends the episode, no slow, no action
    await call('/api/poll', undefined, 3500)
    down = true
    await call('/api/poll', undefined, 3500)
    await call('/api/poll', undefined, 3500)
    expect(signals(await events()).map((e) => [e.type, (e as { detail?: string }).detail])).toEqual([
      ['http_5xx', 'GET /api/poll 503'],
      ['http_5xx', 'GET /api/poll 503']
    ])
  })

  it('requests.notActions: not an action, and the next action counts the clicks from before it', async () => {
    scripted(() => 200)
    termometro = startTermometro({ url: 'http://t.test/', key: 'tk_1', countScriptedClicks: true, pagesFromRouter: true, flushIntervalMs: 1000,
      requests: { notActions: ['/api/heartbeat'] } })
    termometro.page('/x')
    document.body.innerHTML = '<button id="a">a</button>'
    click(document.querySelector('#a')!, 10, 10)
    click(document.querySelector('#a')!, 100, 10)
    await call('/api/heartbeat', { method: 'POST' })
    click(document.querySelector('#a')!, 200, 10)
    await call('/api/save', { method: 'POST' })
    expect((await events()).filter((e) => e.type === 'action')).toEqual([
      { type: 'action', route: '/x', detail: 'POST /api/save', clicks: 3, here: 3, duration_ms: 0, label: 'a' }
    ])
  })

  it('requests.notActions: a failed write still counts as a failure', async () => {
    scripted(() => 500)
    termometro = startTermometro({ url: 'http://t.test/', key: 'tk_1', countScriptedClicks: true, pagesFromRouter: true, flushIntervalMs: 1000,
      requests: { notActions: ['/api/heartbeat'] } })
    termometro.page('/x')
    await call('/api/heartbeat', { method: 'POST' })
    expect(signals(await events()).map((e) => e.type)).toEqual(['http_5xx'])
  })

  it('a request rule with a method only matches that method', async () => {
    scripted(() => 500)
    termometro = startTermometro({ url: 'http://t.test/', key: 'tk_1', countScriptedClicks: true, pagesFromRouter: true, flushIntervalMs: 1000,
      requests: { ignore: ['post /api/things'] } })
    termometro.page('/x')
    await call('/api/things', { method: 'POST' })
    await call('/api/things', { method: 'PUT' })
    await call('/api/things')
    expect(signals(await events()).map((e) => (e as { detail?: string }).detail)).toEqual(['PUT /api/things 500', 'GET /api/things 500'])
  })

  it('a request rule can use :id and matches by prefix', async () => {
    scripted(() => 500)
    termometro = startTermometro({ url: 'http://t.test/', key: 'tk_1', countScriptedClicks: true, pagesFromRouter: true, flushIntervalMs: 1000,
      requests: { ignore: ['/api/tickets/:id/presence'] } })
    termometro.page('/x')
    await call('/api/tickets/4821/presence', { method: 'PUT' })
    await call('/api/tickets/4821/presence/extra')
    await call('/api/tickets/4821/other')
    expect(signals(await events()).map((e) => (e as { detail?: string }).detail)).toEqual(['GET /api/tickets/:id/other 500'])
  })

  it('gives PrimeVue generated ids a stable selector', () => {
    document.body.innerHTML = '<div id="pv_id_95_tab_mine" class="pv_id_1234"><b id="pv_id_7"></b></div>'
    expect(selectorOf(document.querySelector('div'))).toBe('div#pv_id_\\:id_tab_mine')
    expect(selectorOf(document.querySelector('b'))).toBe('b#pv_id_\\:id')
    document.body.innerHTML = '<div id="pv_id_12_tab_mine"></div>'
    expect(selectorOf(document.querySelector('div'))).toBe('div#pv_id_\\:id_tab_mine')
    document.body.innerHTML = '<div id="pv_id_\\95_x"></div>'
    expect(selectorOf(document.querySelector('div'))).toBe('div#pv_id_\\:id_x')
  })

  it('reports a slow request once per visit, and not a quick or failed one', async () => {
    window.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.body instanceof Blob) {
        sent.push(JSON.parse(await init.body.text()))
        return new Response(null, { status: 204 })
      }
      await new Promise((r) => setTimeout(r, String(input).includes('quick') ? 200 : 3500))
      return new Response(null, { status: String(input).includes('broken') ? 500 : 200 })
    }) as typeof fetch
    const t = start()
    t.page('/reports')
    const wait = async (url: string) => { const p = fetch(url); await vi.advanceTimersByTimeAsync(3500); await p }
    await wait('/api/reports/2024')
    await wait('/api/reports/2025')
    await wait('/api/quick')
    await wait('/api/broken')
    t.page('/reports')
    await wait('/api/reports/2026')
    const slow = (await events()).filter((e) => e.type === 'slow')
    expect(slow.map((e) => [e.route, e.detail])).toEqual([['/reports', 'GET /api/reports/:id'], ['/reports', 'GET /api/reports/:id']])
    expect(slow[0]!.duration_ms).toBeGreaterThanOrEqual(3000)
  })

  it('does not report slow requests with slowMs: 0', async () => {
    window.fetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.body instanceof Blob) {
        sent.push(JSON.parse(await init.body.text()))
        return new Response(null, { status: 204 })
      }
      await new Promise((r) => setTimeout(r, 5000))
      return new Response(null, { status: 200 })
    }) as typeof fetch
    termometro = startTermometro({ url: 'http://t.test/', key: 'tk_1', countScriptedClicks: true, pagesFromRouter: true, flushIntervalMs: 1000, slowMs: 0 })
    termometro.page('/poll')
    const p = fetch('/api/long-poll'); await vi.advanceTimersByTimeAsync(5000); await p
    expect((await events()).some((e) => e.type === 'slow')).toBe(false)
  })

  it('reports errors scrubbed and caps repeats of the same one', async () => {
    const t = start()
    t.page('/x')
    for (let i = 0; i < 5; i++) t.error(new TypeError('Cannot read "name" of ticket 12345'))
    const errors = (await events()).filter((e) => e.type === 'js_error')
    expect(errors).toHaveLength(3)
    expect(errors[0]!.detail).toBe('TypeError: Cannot read "…" of ticket :id')
  })

  it('stamps each event with the browser time and the batch with when it was sent and the kind of screen', async () => {
    start().page('/x')
    await events()
    const [batch] = sent
    expect(typeof batch!.events[0]!.t).toBe('number')
    expect(batch!.sent).toBeGreaterThanOrEqual(batch!.events[0]!.t!)
    expect(['phone', 'tablet', 'desktop']).toContain(batch!.device)
  })

  it('sends where an error happened in the code, without host or query', async () => {
    const err = new TypeError('boom')
    err.stack = 'TypeError: boom\n    at loadRows (https://app.example.com/assets/index-a1b2c3.js?v=123:1:4567)\n' +
      '    at https://app.example.com/assets/vendor.js:2:10\n    at async Object.save [as run] (http://localhost:5173/src/pages/Tickets.vue:88:12)'
    expect(stackOf(err)).toBe('loadRows @ /assets/index-a1b2c3.js:1:4567\n? @ /assets/vendor.js:2:10\nObject.save [as run] @ /src/pages/Tickets.vue:88:12')
    const firefox = new Error('x'); firefox.stack = 'save@https://app.example.com/a.js:3:4\n@https://app.example.com/b.js:5:6'
    expect(stackOf(firefox)).toBe('save @ /a.js:3:4\n? @ /b.js:5:6')
    start().page('/x')
    termometro!.error(err)
    const [e] = (await events()).filter((x) => x.type === 'js_error')
    expect(e!.stack).toContain('loadRows @ /assets/index-a1b2c3.js:1:4567')
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
      { type: 'action', route: '/tickets/new', detail: 'POST /api/tickets', clicks: 3, here: 3, duration_ms: 2000, label: 'a' }
    ])
    expect(all.find((e) => e.type === 'http_5xx')).toMatchObject({ target: 'button#b', detail: 'PUT /api/tickets/:id 500' })
  })

  it('splits an action\'s clicks into the way to the screen and the clicks on it', async () => {
    scripted(() => 201)
    termometro = startTermometro({ url: 'http://t.test/', key: 'tk_1', countScriptedClicks: true, pagesFromRouter: true, flushIntervalMs: 1000 })
    termometro.page('/home')
    document.body.innerHTML = '<a id="menu" href="#">Usuários</a><button id="new">Novo</button><button id="save">Salvar</button>'
    click(document.querySelector('#menu')!, 10, 10) // the way there
    termometro.page('/users')
    click(document.querySelector('#new')!, 100, 10); click(document.querySelector('#save')!, 200, 10)
    await call('/api/users', { method: 'POST' })
    expect((await events()).find((e) => e.type === 'action')).toMatchObject({ clicks: 3, here: 2 })
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

  it('sends the user name only when the app gives it', async () => {
    const t = start(true, () => ({ account: 1, user: 'u-1', name: 'Maria Souza' }))
    t.page('/a')
    await events()
    expect(sent[0]).toMatchObject({ user: 'u-1', user_name: 'Maria Souza' })
    termometro?.stop(); sent = []
    start(true, () => ({ account: 1, user: 'u-2' })).page('/b')
    await events()
    expect(sent[0]).not.toHaveProperty('user_name')
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

  it('counts only clicks a person made, not the ones the app fires by code', async () => {
    termometro = startTermometro({ url: 'http://t.test/', key: 'tk_1', pagesFromRouter: true, flushIntervalMs: 1000 })
    termometro.page('/x')
    document.body.innerHTML = '<button id="auto">Salvar</button>'
    const b = document.querySelector('button')!
    for (let i = 0; i < 4; i++) b.click() // scripted: isTrusted is false
    await vi.advanceTimersByTimeAsync(1500)
    expect((await events()).filter((e) => ['click', 'rage', 'dead'].includes(e.type))).toEqual([])
  })

  it('says why someone rage clicked, as far as the page can tell', async () => {
    scripted((url) => (url.includes('/fail') ? 500 : 200), 3000) // every request takes 3 s
    termometro = startTermometro({ url: 'http://t.test/', key: 'tk_1', countScriptedClicks: true, pagesFromRouter: true, flushIntervalMs: 1000 })
    termometro.page('/x')
    document.body.innerHTML = `<button id="save">Salvar</button><button id="err">Enviar</button><p id="txt">um texto</p>
      <button id="off" aria-disabled="true">Excluir</button><button id="moves">Abrir</button>`
    // People click about 100 ms apart, and the page gets to react in between.
    const burst = async (el: Element, x: number) => { for (let i = 0; i < 3; i++) { click(el, x, 10); await vi.advanceTimersByTimeAsync(100) } }
    const save = document.querySelector('#save')!
    save.addEventListener('click', () => { fetch('/api/save', { method: 'POST' }).catch(() => {}) }, { once: true })
    await burst(save, 10) // the first click opened a request still running: waiting
    await vi.advanceTimersByTimeAsync(4000)
    const err = document.querySelector('#err')!
    err.addEventListener('click', () => { window.dispatchEvent(new ErrorEvent('error', { error: new TypeError('x is undefined') })) }, { once: true })
    await burst(err, 200) // it failed right away: error
    await vi.advanceTimersByTimeAsync(1500)
    await burst(document.querySelector('#txt')!, 400) // text that is not a control: not_clickable
    await vi.advanceTimersByTimeAsync(1500)
    await burst(document.querySelector('#off')!, 600) // disabled
    await vi.advanceTimersByTimeAsync(1500)
    const moves = document.querySelector('#moves')!
    moves.addEventListener('click', () => { document.body.append(document.createElement('span')) })
    await burst(moves, 800) // the page reacted and they kept clicking: unclear
    await vi.advanceTimersByTimeAsync(1500)
    expect((await events()).filter((e) => e.type === 'rage').map((e) => [e.target, e.detail])).toEqual([
      ['button#save', 'waiting'], ['button#err', 'error'], ['p#txt', 'not_clickable'], ['button#off', 'disabled'], ['button#moves', 'unclear']])
  })

  it('three clicks that select text are not a rage click', async () => {
    start().page('/x')
    document.body.innerHTML = '<p id="txt">um parágrafo para copiar</p>'
    const p = document.querySelector('#txt')!
    click(p); click(p)
    getSelection()?.selectAllChildren(p) // the browser selects the paragraph on the third click
    click(p)
    await vi.advanceTimersByTimeAsync(1500)
    expect((await events()).filter((e) => e.type === 'rage')).toEqual([])
  })

  it('sees when a control needed a second click, and a click that nearly hit a control', async () => {
    start().page('/x')
    document.body.innerHTML = '<div id="card"><button id="save">Salvar</button></div><button id="ok">Abrir</button>'
    const save = document.querySelector('#save')!, ok = document.querySelector('#ok')!
    await vi.advanceTimersByTimeAsync(100) // the screen is drawn before anyone clicks
    click(save, 10, 10); await vi.advanceTimersByTimeAsync(800); click(save, 10, 10) // nothing happened: retry
    await vi.advanceTimersByTimeAsync(6000)
    ok.addEventListener('click', () => document.body.append(document.createElement('i')))
    click(ok, 50, 50); await vi.advanceTimersByTimeAsync(800); click(ok, 50, 50) // the first one worked: no retry
    await vi.advanceTimersByTimeAsync(6000)
    Object.defineProperty(document, 'elementsFromPoint', { configurable: true, value: (x: number) => (x > 100 ? [save] : []) })
    click(document.querySelector('#card')!, 95, 10) // just left of the button
    const all = await events()
    expect(all.filter((e) => e.type === 'retry' || e.type === 'near_miss').map((e) => [e.type, e.target, e.label]))
      .toEqual([['retry', 'button#save', 'Salvar'], ['near_miss', 'button#save', 'Salvar']])
  })

  it('marks typing (once per field per visit) and Enter in a field, by the field name, never the text', async () => {
    const t = start()
    t.page('/search')
    document.body.innerHTML = '<label for="q">Buscar cliente</label><input id="q" placeholder="nome ou e-mail"><textarea id="n"></textarea>'
    const q = document.querySelector<HTMLInputElement>('#q')!
    for (const v of ['M', 'Ma', 'Maria']) { q.value = v; q.dispatchEvent(new Event('input', { bubbles: true })) }
    q.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    document.querySelector('#n')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })) // a new line, not a submit
    t.page('/search')
    q.dispatchEvent(new Event('input', { bubbles: true }))
    const all = await events()
    expect(all.filter((e) => e.type === 'typed' || e.type === 'enter').map((e) => [e.type, e.target, e.label]))
      .toEqual([['typed', 'input#q', 'Buscar cliente'], ['enter', 'input#q', 'Buscar cliente'], ['typed', 'input#q', 'Buscar cliente']])
    expect(JSON.stringify(sent)).not.toContain('Maria')
  })

  it('tracks a business event by name only', async () => {
    const t = start()
    t.page('/import')
    t.track('opportunity_created')
    t.track('  ')
    t.track('sent to ana@x.com')
    expect((await events()).filter((e) => e.type === 'track')).toEqual([
      { type: 'track', route: '/import', detail: 'opportunity_created' },
      { type: 'track', route: '/import', detail: 'sent to :email' }
    ])
  })

  it('restores fetch on stop', () => {
    const before = window.fetch
    start().stop()
    termometro = null
    expect(window.fetch).toBe(before)
  })
})
