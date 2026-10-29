/**
 * Termometro collector — usage and frustration signals from the browser, never content.
 *
 * No text from the screen, a field or the user leaves the browser. A click target is a selector
 * (`button#save`, `div.toolbar > button.btn`), and every long number, e-mail address or identifier becomes
 * `:id`. Who the user is travels only as the ids you hand to `identity` (account, user, role).
 *
 * Signals: rage (3 clicks on the same spot within 1 s), dead (a click on a button or link that changed nothing
 * within 1 s), js_error, http_4xx / http_5xx (401 is left out: an expired session is not frustration), abandon
 * (started filling a form or dialog and left the screen without saving) and bounce (went back within 4 s).
 * Usage: page (a visit), click (every click), inventory (what can be clicked on a screen, once per screen per
 * session) and action (a write the backend accepted, with the clicks and time it took since the previous one).
 *
 * Opened with `?termometro_map=<token>` (the dashboard's "Open heat map" button), it loads the server's heat
 * map over the page.
 */

export interface Identity {
  /** Your customer account. */
  account?: string | number | null
  /** The user's id — never a name or an e-mail. */
  user?: string | number | null
  /** The user's role, to compare groups without looking at anyone. */
  role?: string | null
}

export interface Options {
  /** The project key, from your server's TERMOMETRO_PROJECTS. */
  key: string
  /** Your Termometro server, e.g. `https://termometro.example.com`. */
  url: string
  /** Your app's version, to compare one deploy with the previous one. */
  version?: string
  /** The current route as a pattern (`/orders/:id`). Without it, the URL path with ids replaced by `:id`. */
  route?: () => string
  /** Who is using it, read on every event; null before sign-in. Or call `identify()`. */
  identity?: () => Identity | null
  /** How often a batch is sent. Default: 10 s. */
  flushIntervalMs?: number
  /** Your router calls `page()` for the first screen too (Vue Router's `afterEach` does); otherwise it is counted here. */
  pagesFromRouter?: boolean
}

export interface Termometro {
  /** Call on every screen change, e.g. from the router's `afterEach`, with the route pattern. */
  page(route?: string): void
  /** An error your framework swallowed before `window.onerror` (Vue's `app.config.errorHandler`, React's error boundary). */
  error(error: unknown): void
  /** Sets who is using it, when there is no `identity` function. `null` on sign-out. */
  identify(identity: Identity | null): void
  /** Removes every hook and sends what is left in the queue. */
  stop(): void
}

type EventType = 'page' | 'rage' | 'dead' | 'js_error' | 'http_4xx' | 'http_5xx' | 'abandon' | 'bounce' |
  'click' | 'action' | 'inventory'
interface TrackedEvent {
  type: EventType
  route: string
  target?: string
  detail?: string
  clicks?: number
  duration_ms?: number
  targets?: string[]
}
interface Who { account: string; user: string; role: string }
interface Queued { event: TrackedEvent; who: Who }

const RAGE_CLICKS = 3
const RAGE_WINDOW_MS = 1000
const RAGE_RADIUS_PX = 30
const DEAD_WAIT_MS = 1000
const BOUNCE_MS = 4000
const AFTER_CLICK_MS = 2000
const ACTION_IDLE_MS = 120_000
const INVENTORY_DELAY_MS = 1500
const MAX_INVENTORY = 300
const MAX_QUEUE = 500
const MAX_BATCH = 100
const MAX_SAME_ERROR = 3
const OVERLAY = '[data-termometro]'

const CLICKABLE = 'a[href],button,[role="button"],[role="menuitem"],[role="tab"],summary,' +
  'input[type="submit"],input[type="button"],input[type="checkbox"],input[type="radio"]'

/** Strips what could identify someone: e-mail, uuid, any run of 3+ digits and quoted text. */
export function scrub(text: string): string {
  return text
    .replace(/[\w.+-]+@[\w-]+\.[\w.-]+/g, ':email')
    .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, ':id')
    .replace(/\d{3,}/g, ':id')
    .replace(/(["'`])[^"'`]*\1/g, '"…"')
}

/** URL path with the segments that look like ids replaced by `:id`. */
export function routeFromPath(path: string): string {
  return path
    .split('/')
    .map((s) => (/^\d+$/.test(s) || /^[0-9a-f-]{16,}$/i.test(s) || /\d{3,}/.test(s) ? ':id' : s))
    .join('/') || '/'
}

// Escaped so the heat map can hand the selector back to querySelectorAll (`h-[3px]`, `md:flex`).
function cssEscape(value: string): string {
  return typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(value) : value.replace(/[^\w-]/g, (c) => `\\${c}`)
}

function selectorPart(el: Element): string {
  const tag = el.tagName.toLowerCase()
  const id = el.getAttribute('id')
  const testId = el.getAttribute('data-testid')
  if (id) return `${tag}#${cssEscape(scrub(id))}`
  if (testId) return `${tag}[data-testid="${scrub(testId).replace(/"/g, '')}"]`
  const classes = Array.from(el.classList).filter((c) => !/\d{3,}/.test(c)).slice(0, 2)
  return classes.length ? `${tag}.${classes.map(cssEscape).join('.')}` : tag
}

/** Short selector: the element and up to two ancestors, stopping at the first one with an id. */
export function selectorOf(el: Element | null): string {
  const parts: string[] = []
  for (let cur = el; cur && cur !== document.body && parts.length < 3; cur = cur.parentElement) {
    const part = selectorPart(cur)
    parts.unshift(part)
    if (part.includes('#') || part.includes('data-testid')) break
  }
  return parts.join(' > ').slice(0, 200)
}

function storage(key: string, value?: string | null): string | null {
  try {
    if (value === null) sessionStorage.removeItem(key)
    else if (value !== undefined) sessionStorage.setItem(key, value)
    return sessionStorage.getItem(key)
  } catch {
    return null
  }
}

function sessionId(): string {
  const kept = storage('termometro.session')
  if (kept) return kept
  const fresh = typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2) + Date.now().toString(36)
  return storage('termometro.session', fresh) ?? fresh // private window: a session for this load only
}

function pathOf(url: string): string {
  try {
    return routeFromPath(new URL(url, location.href).pathname)
  } catch {
    return '?'
  }
}

export function start(options: Options): Termometro {
  const base = options.url.replace(/\/$/, '')
  const endpoint = base + '/api/events'
  const session = sessionId()
  const queue: Queued[] = []
  const undo: Array<() => void> = []
  const errorsSeen = new Map<string, number>()
  const inventoried = new Set<string>()

  let identified: Identity | null = null
  let currentRoute = options.route?.() ?? routeFromPath(location.pathname)
  let arrivedAt = Date.now()
  // Counters, not clocks: a change in the same millisecond as the click still counts as its reaction.
  let networkCount = 0
  let mutationCount = 0
  let clicks: Array<{ t: number; x: number; y: number }> = []
  let rageInBurst = false
  let filling: string | null = null
  let lastClick: { target: string; t: number } | null = null
  // The clicks since the last accepted write: the effort the next one took.
  let actionClicks = 0
  let actionStart = 0
  let lastClickAt = 0
  let inventoryTimer: ReturnType<typeof setTimeout> | undefined

  function who(): Who {
    let id: Identity | null = identified
    try {
      if (options.identity) id = options.identity()
    } catch { /* the app's store is not ready: anonymous */ }
    const text = (v: unknown) => (v === null || v === undefined ? '' : String(v))
    return { account: text(id?.account), user: text(id?.user), role: text(id?.role) }
  }

  const record = (event: TrackedEvent) => {
    if (queue.length < MAX_QUEUE) queue.push({ event, who: who() })
  }
  const recentClick = () => (lastClick && Date.now() - lastClick.t < AFTER_CLICK_MS ? lastClick.target : undefined)

  function flush(leaving = false) {
    while (queue.length) {
      // One batch per identity: a sign-in or sign-out in the middle of the queue splits it.
      const first = JSON.stringify(queue[0]!.who)
      let n = 0
      while (n < queue.length && n < MAX_BATCH && JSON.stringify(queue[n]!.who) === first) n++
      const items = queue.splice(0, n)
      const batch = { key: options.key, version: options.version ?? '', session, ...items[0]!.who, events: items.map((q) => q.event) }
      // text/plain needs no CORS preflight; the server parses the JSON all the same.
      const body = new Blob([JSON.stringify(batch)], { type: 'text/plain' })
      if (leaving && navigator.sendBeacon?.(endpoint, body)) continue
      nativeFetch.call(window, endpoint, { method: 'POST', body, keepalive: true, mode: 'cors', credentials: 'omit' })
        .catch(() => { /* server down: losing a measurement beats getting in the page's way */ })
    }
  }

  function listen<K extends keyof WindowEventMap | keyof DocumentEventMap>(
    target: Window | Document,
    type: K,
    fn: (e: K extends keyof WindowEventMap ? WindowEventMap[K] : K extends keyof DocumentEventMap ? DocumentEventMap[K] : never) => void
  ) {
    target.addEventListener(type, fn as EventListener, true)
    undo.push(() => target.removeEventListener(type, fn as EventListener, true))
  }

  function error(e: unknown) {
    const err = e instanceof Error ? e : new Error(String(e))
    const detail = scrub(`${err.name}: ${err.message}`).slice(0, 200)
    const times = (errorsSeen.get(detail) ?? 0) + 1
    errorsSeen.set(detail, times)
    if (times <= MAX_SAME_ERROR) record({ type: 'js_error', route: currentRoute, target: recentClick(), detail })
  }

  function network(method: string, url: string, status: number) {
    if (url.startsWith(base)) return
    networkCount++
    const verb = method.toUpperCase()
    if (/^(POST|PUT|PATCH|DELETE)$/.test(verb) && status > 0 && status < 400) {
      filling = null
      // A write nobody clicked for (a heartbeat, a background save) is not an action.
      if (actionClicks > 0) {
        record({ type: 'action', route: currentRoute, detail: `${verb} ${pathOf(url)}`, clicks: actionClicks, duration_ms: Date.now() - actionStart })
        actionClicks = 0
      }
    }
    if (status === 401 || (status > 0 && status < 400)) return
    const type = status >= 400 && status < 500 ? 'http_4xx' : 'http_5xx'
    record({ type, route: currentRoute, target: recentClick(), detail: `${verb} ${pathOf(url)} ${status || 'network failure'}` })
  }

  function leaveForm() {
    if (filling) record({ type: 'abandon', route: currentRoute, target: filling })
    filling = null
  }

  // What can be clicked on this screen, once per screen per session: the base for "never clicked".
  function scheduleInventory() {
    clearTimeout(inventoryTimer)
    const route = currentRoute
    if (inventoried.has(route)) return
    inventoryTimer = setTimeout(() => {
      if (route !== currentRoute || inventoried.has(route)) return
      inventoried.add(route)
      const seen = new Set<string>()
      for (const el of Array.from(document.querySelectorAll(CLICKABLE))) {
        if (el.closest(OVERLAY) || !el.getClientRects().length) continue
        seen.add(selectorOf(el))
        if (seen.size >= MAX_INVENTORY) break
      }
      if (seen.size) record({ type: 'inventory', route, targets: Array.from(seen) })
    }, INVENTORY_DELAY_MS)
  }

  function page(route?: string) {
    leaveForm()
    currentRoute = route ?? options.route?.() ?? routeFromPath(location.pathname)
    arrivedAt = Date.now()
    record({ type: 'page', route: currentRoute })
    scheduleInventory()
  }

  // Clicks: usage, rage, dead, and the effort of the next action.
  listen(document, 'click', (e) => {
    const target = e.target instanceof Element ? e.target : null
    if (target?.closest(OVERLAY)) return
    const now = Date.now()
    const clickable = target?.closest(CLICKABLE) ?? null
    const selector = selectorOf(clickable ?? target)
    record({ type: 'click', route: currentRoute, target: selector })
    lastClick = { target: selector, t: now }
    if (!actionClicks || now - lastClickAt > ACTION_IDLE_MS) {
      actionClicks = 0
      actionStart = now
    }
    actionClicks++
    lastClickAt = now

    clicks = clicks.filter((c) => now - c.t < RAGE_WINDOW_MS && Math.hypot(c.x - e.clientX, c.y - e.clientY) < RAGE_RADIUS_PX)
    if (!clicks.length) rageInBurst = false
    clicks.push({ t: now, x: e.clientX, y: e.clientY })
    if (clicks.length >= RAGE_CLICKS && !rageInBurst) {
      rageInBurst = true
      record({ type: 'rage', route: currentRoute, target: selectorOf(target) })
    }

    if (!clickable) return
    const before = { route: currentRoute, href: location.href, mutations: mutationCount, requests: networkCount }
    setTimeout(() => {
      const reacted = mutationCount !== before.mutations || networkCount !== before.requests || location.href !== before.href
      if (!reacted && !rageInBurst) record({ type: 'dead', route: before.route, target: selectorOf(clickable) })
    }, DEAD_WAIT_MS)
  })

  const observer = new MutationObserver((mutations) => {
    if (mutations.some((m) => !(m.target instanceof Element && m.target.closest(OVERLAY)))) mutationCount++
  })
  observer.observe(document.documentElement, { childList: true, subtree: true, attributes: true, characterData: true })
  undo.push(() => observer.disconnect())

  // A form started: the place only, never the value. Outside a form or dialog it is a filter or a search and
  // does not count; ticking a table row (checkbox, radio) does not either.
  listen(document, 'input', (e) => {
    const field = e.target instanceof Element ? e.target : null
    if (!field || field.closest(OVERLAY) || field.matches('input[type="checkbox"],input[type="radio"],input[type="search"]')) return
    const place = field.closest('form,[role="dialog"]')
    if (place && !field.closest('[role="search"]')) filling = selectorOf(place)
  })
  listen(document, 'submit', () => { filling = null })

  listen(window, 'popstate', () => {
    if (Date.now() - arrivedAt < BOUNCE_MS) record({ type: 'bounce', route: currentRoute })
  })

  listen(window, 'error', (e) => {
    if (e instanceof ErrorEvent) error(e.error ?? e.message)
  })
  listen(window, 'unhandledrejection', (e) => error(e.reason))

  // Network: fetch and XMLHttpRequest (axios uses the latter).
  const nativeFetch = window.fetch
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const method = init?.method ?? (input instanceof Request ? input.method : 'GET')
    try {
      const response = await nativeFetch.call(window, input, init)
      network(method, url, response.status)
      return response
    } catch (failure) {
      if (!(failure instanceof DOMException && failure.name === 'AbortError')) network(method, url, 0)
      throw failure
    }
  }
  undo.push(() => { window.fetch = nativeFetch })

  const proto = XMLHttpRequest.prototype
  const openOriginal = proto.open
  const sendOriginal = proto.send
  const requests = new WeakMap<XMLHttpRequest, { method: string; url: string }>()
  proto.open = function (this: XMLHttpRequest, method: string, url: string | URL, ...rest: unknown[]) {
    requests.set(this, { method, url: String(url) })
    return (openOriginal as (...a: unknown[]) => void).call(this, method, url, ...rest)
  } as typeof proto.open
  proto.send = function (this: XMLHttpRequest, body?: Document | XMLHttpRequestBodyInit | null) {
    const req = requests.get(this)
    if (req) {
      let aborted = false
      this.addEventListener('abort', () => { aborted = true })
      this.addEventListener('loadend', () => { if (!aborted) network(req.method, req.url, this.status) })
    }
    return sendOriginal.call(this, body)
  }
  undo.push(() => { proto.open = openOriginal; proto.send = sendOriginal })

  const timer = setInterval(() => flush(), options.flushIntervalMs ?? 10_000)
  undo.push(() => clearInterval(timer))
  undo.push(() => clearTimeout(inventoryTimer))
  listen(document, 'visibilitychange', () => { if (document.visibilityState === 'hidden') flush(true) })
  listen(window, 'pagehide', () => { leaveForm(); flush(true) })

  // Heat map: the dashboard opens the app with a one-hour token, kept for the tab until the map is closed.
  // The token leaves the address bar at once, so it is not shared by copying the link.
  const params = new URLSearchParams(location.search)
  const fromUrl = params.get('termometro_map')
  if (fromUrl) {
    storage('termometro.map', fromUrl)
    params.delete('termometro_map')
    const rest = params.toString()
    history.replaceState(history.state, '', location.pathname + (rest ? '?' + rest : '') + location.hash)
  }
  const mapToken = storage('termometro.map')
  if (mapToken) {
    const w = window as unknown as { termometroMap?: unknown }
    w.termometroMap = { url: base, token: mapToken, route: () => currentRoute, onClose: () => storage('termometro.map', null) }
    const script = document.createElement('script')
    script.src = `${base}/map.js`
    script.async = true
    document.head.appendChild(script)
  }

  if (!options.pagesFromRouter) {
    record({ type: 'page', route: currentRoute })
    scheduleInventory()
  }

  return {
    page,
    error,
    identify(identity) {
      identified = identity
      // What this tab recorded before sign-in (the first visit, with a <script> tag) is the same person.
      const now = who()
      for (const q of queue) if (!q.who.user && !q.who.account) q.who = now
    },
    stop() {
      undo.splice(0).forEach((fn) => fn())
      flush(true)
    }
  }
}
