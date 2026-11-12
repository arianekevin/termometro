/**
 * Termometro collector — usage and frustration signals from the browser, never content.
 *
 * No text a user typed or a record shows leaves the browser. A click target is a selector (`button#save`,
 * `div.toolbar > button.btn`) plus, for people who do not read selectors, the control's own label ("New user"):
 * only of buttons, menu items, tabs and links outside tables, lists of records and fields, up to 40 characters,
 * scrubbed like everything else. A screen's name comes from your `screen` option, `data-termometro-screen` or the
 * page title, and only on routes without `:id` (a record's page title is the record). `data-termometro-private`
 * on any element keeps its labels home. Every long number, e-mail address or identifier becomes `:id`. Who the
 * user is travels only as the ids you hand to `identity` (account, user, role).
 *
 * Signals: rage (3 clicks on the same spot within 1 s), dead (a click on a button or link that changed nothing
 * within 1 s), js_error, http_4xx / http_5xx (401 is left out: an expired session is not frustration), abandon
 * (started filling a form or dialog and left the screen without saving), bounce (went back within 4 s) and slow
 * (a request that answered after 3 s while the page was in front of the user).
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
  /** Optional: the user's name, shown on the dashboard next to the id. Kept apart from the events, dropped with the
   *  retention, never in what an AI reads; a server whose project has "people_names": false throws it away. */
  name?: string | null
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
  /** The current screen's name for people ("Users"), read on every screen change. Without it: the element with
   *  `data-termometro-screen` (its value or text), else the page title's first part, and never on a route with `:id`. */
  screen?: () => string | null | undefined
  /** Who is using it, read on every event; null before sign-in. Or call `identify()`. */
  identity?: () => Identity | null
  /** How often a batch is sent. Default: 10 s. */
  flushIntervalMs?: number
  /** Your router calls `page()` for the first screen too (Vue Router's `afterEach` does); otherwise it is counted here. */
  pagesFromRouter?: boolean
  /** Count clicks fired by code too (`el.click()`, `dispatchEvent`). Off: only a person's clicks count. For tests. */
  countScriptedClicks?: boolean
  /** A request slower than this is a "slow" signal. Default: 3000 ms; 0 turns it off (long polling, big exports). */
  slowMs?: number
  /** Requests that are not the user's experience of the app. Each item is `"METHOD /path"` or `"/path"`: the path is
   *  matched by prefix against the request's path with ids replaced by `:id` (an item may use `:id` too); the method,
   *  if given, ignores case; the host never matters. */
  requests?: {
    /** Never counted: not a failure, not slow, not an action. `/cdn-cgi/` is always here. */
    ignore?: string[]
    /** Requests the app makes on its own (polling, health checks): never slow, never an action; while they keep failing, only the first failure of the episode is recorded, and the episode ends at the next background request that succeeds. */
    background?: string[]
    /** Writes that are not something the user did (heartbeats, counters, "seen" marks): not recorded as actions and they do not reset the clicks/time counted towards the next action. Their failures still count. */
    notActions?: string[]
  }
}

export interface Termometro {
  /** Call on every screen change, e.g. from the router's `afterEach`, with the route pattern. */
  page(route?: string): void
  /** Something that matters to the business and has no click or request of its own on this screen (an import that
   *  created opportunities, a step finished in the background): `track('opportunity_created')`. The name only — up to
   *  60 characters, scrubbed — never a value or a record. Watch it as a feature on the dashboard. */
  track(name: string): void
  /** An error your framework swallowed before `window.onerror` (Vue's `app.config.errorHandler`, React's error boundary). */
  error(error: unknown): void
  /** Sets who is using it, when there is no `identity` function. `null` on sign-out. */
  identify(identity: Identity | null): void
  /** Removes every hook and sends what is left in the queue. */
  stop(): void
}

type EventType = 'page' | 'rage' | 'dead' | 'js_error' | 'http_4xx' | 'http_5xx' | 'abandon' | 'bounce' | 'slow' |
  'click' | 'action' | 'inventory' | 'track'
interface TrackedEvent {
  type: EventType
  route: string
  target?: string
  detail?: string
  clicks?: number
  duration_ms?: number
  targets?: string[]
  /** For people: a click's control label, a page's screen name, an action's button. `labels` goes with `targets`. */
  label?: string
  labels?: string[]
  /** When it happened (the browser's clock); the server lines it up with its own by the batch's `sent`. */
  t?: number
  /** js_error only: where in the code, as `function @ /path/file.js:line:col` lines — never the page's query or data. */
  stack?: string
}
interface Who { account: string; user: string; role: string; user_name?: string }
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
const SLOW_MS = 3000
// Requests under this path prefix (any host) belong to the proxy/CDN, not the app: Cloudflare's RUM beacon
// (POST /cdn-cgi/rum) is injected into pages and ad blockers cancel it (ERR_BLOCKED_BY_CLIENT), which would
// otherwise show up as a "network failure" on every screen. Always part of `requests.ignore`.
const BUILT_IN_IGNORE = ['/cdn-cgi/']
const MAX_FRAMES = 8
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

/** The code locations of an error's stack: function and file path with line and column; the host, the query and the
 * message are left out (the message is already in `detail`, scrubbed). */
export function stackOf(err: Error): string {
  const frames: string[] = []
  for (const line of String(err.stack ?? '').split('\n')) {
    // Chrome: "    at fn (https://app/x.js:1:2)" or "    at https://app/x.js:1:2"; Firefox/Safari: "fn@https://app/x.js:1:2"
    const m = line.match(/^\s*(?:at\s+)?(?:(.*?)\s*[@(]\s*)?((?:https?|file|webpack|blob):\/*[^\s)]*?|\/[^\s)]*?):(\d+):(\d+)\)?\s*$/)
    if (!m) continue
    let path = m[2]!
    try { path = new URL(path).pathname } catch { path = path.split(/[?#]/)[0]! }
    const fn = (m[1] ?? '').replace(/^async\s+/, '').replace(/[^\w$.<>\[\] -]/g, '').slice(0, 60)
    frames.push(`${fn || '?'} @ ${path.slice(0, 120)}:${m[3]}:${m[4]}`)
    if (frames.length >= MAX_FRAMES) break
  }
  return frames.join('\n')
}

/** The kind of screen, not its size: enough to tell a phone problem from a desktop one. */
function device(): string {
  const w = typeof innerWidth === 'number' ? innerWidth : 0
  return !w ? '' : w < 640 ? 'phone' : w < 1024 ? 'tablet' : 'desktop'
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

// PrimeVue numbers its generated ids (`pv_id_95_tab_mine`), so the same tab would look like a new element on every visit.
function stableId(value: string): string {
  return value.replace(/pv_id_\\?\d+/g, 'pv_id_:id')
}

function selectorPart(el: Element): string {
  const tag = el.tagName.toLowerCase()
  const id = el.getAttribute('id')
  const testId = el.getAttribute('data-testid')
  if (id) return `${tag}#${cssEscape(stableId(scrub(id)))}`
  if (testId) return `${tag}[data-testid="${scrub(testId).replace(/"/g, '')}"]`
  const classes = Array.from(el.classList).filter((c) => !/\d{3,}/.test(c)).slice(0, 2)
  return classes.length ? `${tag}.${classes.map((c) => cssEscape(stableId(c))).join('.')}` : tag
}

const MAX_LABEL = 40
// Controls whose label is the app's words, not a record's.
const LABELED = 'button,a[href],[role="button"],[role="menuitem"],[role="tab"],summary,input[type="submit"],input[type="button"]'
// Where text is the user's or a record's: tables, grids, lists of records, fields, and whatever the app marks private.
const PRIVATE = 'table,[role="grid"],[role="table"],[role="row"],[role="treegrid"],[role="listbox"],[role="feed"],[role="log"],' +
  'input:not([type="submit"]):not([type="button"]),textarea,select,[contenteditable=""],[contenteditable="true"],[data-termometro-private]'
// A list is a menu when it sits in navigation; otherwise its items are usually records (contacts, tickets).
const MENU = 'nav,header,aside,[role="navigation"],[role="menu"],[role="menubar"],[role="tablist"],[role="toolbar"]'

function clean(text: string | null | undefined): string {
  const t = scrub((text ?? '').replace(/\s+/g, ' ').trim())
  return t.length > MAX_LABEL ? '' : t // a long text is content, not a label
}

/** The words people see on a control ("New user"), or '' where they could be someone's data. */
export function labelOf(el: Element | null): string {
  const control = el?.closest(LABELED)
  if (!control || control.closest(PRIVATE)) return ''
  const list = control.closest('ul,ol,dl')
  if (list && !list.closest(MENU) && !control.closest(MENU)) return ''
  const own = control.closest('[data-termometro-label]')?.getAttribute('data-termometro-label')
  if (own) return clean(own)
  const by = control.getAttribute('aria-labelledby')
  const labelled = by ? by.split(/\s+/).map((id) => document.getElementById(id)?.textContent ?? '').join(' ') : ''
  const value = control instanceof HTMLInputElement ? control.value : ''
  return clean(control.getAttribute('aria-label') || labelled || control.getAttribute('title') || value || control.textContent)
}

/** The screen's name for people, or '' on a record's page (`:id` in the route) and wherever it is not known. */
export function screenOf(route: string, given?: string | null): string {
  if (given) return clean(given)
  if (route.includes(':id')) return ''
  const marked = document.querySelector('[data-termometro-screen]')
  if (marked) return clean(marked.getAttribute('data-termometro-screen') || marked.textContent)
  return clean(document.title.split(/\s+[|\-–—·]\s+/)[0])
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

interface RequestRule { method: string; path: string }

function rulesOf(items: string[] | undefined): RequestRule[] {
  return (items ?? []).map((item) => {
    const m = /^(?:([A-Za-z]+)\s+)?(\S+)$/.exec(item.trim())
    return { method: (m?.[1] ?? '').toUpperCase(), path: routeFromPath(m?.[2] ?? item.trim()) }
  })
}

/** `path` is the request's path after `routeFromPath`; `method` is upper case. */
function matches(rules: RequestRule[], method: string, path: string): boolean {
  return rules.some((r) => (!r.method || r.method === method) && path.startsWith(r.path))
}

export function start(options: Options): Termometro {
  const base = options.url.replace(/\/$/, '')
  const endpoint = base + '/api/events'
  const session = sessionId()
  const queue: Queued[] = []
  const undo: Array<() => void> = []
  const errorsSeen = new Map<string, number>()
  // Per visit: a slow endpoint polled every few seconds is one complaint about the screen, not dozens.
  const slowSeen = new Set<string>()
  const slowMs = options.slowMs ?? SLOW_MS
  const inventoried = new Set<string>()
  const ignore = rulesOf([...BUILT_IN_IGNORE, ...(options.requests?.ignore ?? [])])
  const background = rulesOf(options.requests?.background)
  const notActions = rulesOf(options.requests?.notActions)
  // Background endpoints that are failing right now: the episode is recorded once, until one of them succeeds.
  const backgroundDown = new Set<string>()

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
  // The last labelled control clicked: the name an action gets ("Save" for POST /api/tickets).
  let lastLabel = ''
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
    const name = text(id?.name).trim().slice(0, 80)
    return { account: text(id?.account), user: text(id?.user), role: text(id?.role), ...(name ? { user_name: name } : {}) }
  }

  const record = (event: TrackedEvent): TrackedEvent | undefined => {
    if (queue.length >= MAX_QUEUE) return undefined
    const queued = { event: { ...event, t: Date.now() }, who: who() }
    queue.push(queued)
    return queued.event // still in the queue: a detail known a moment later can be added to it
  }
  const recentClick = () => (lastClick && Date.now() - lastClick.t < AFTER_CLICK_MS ? lastClick.target : undefined)

  function flush(leaving = false) {
    while (queue.length) {
      // One batch per identity: a sign-in or sign-out in the middle of the queue splits it.
      const first = JSON.stringify(queue[0]!.who)
      let n = 0
      while (n < queue.length && n < MAX_BATCH && JSON.stringify(queue[n]!.who) === first) n++
      const items = queue.splice(0, n)
      const batch = { key: options.key, version: options.version ?? '', session, ...items[0]!.who, device: device(), sent: Date.now(),
        events: items.map((q) => q.event) }
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
    if (times <= MAX_SAME_ERROR) record({ type: 'js_error', route: currentRoute, target: recentClick(), detail, stack: stackOf(err) || undefined })
  }

  function network(method: string, url: string, status: number, ms: number) {
    if (url.startsWith(base)) return
    const verb = method.toUpperCase()
    const path = pathOf(url)
    if (matches(ignore, verb, path)) return
    const where = `${verb} ${path}`
    const isBackground = matches(background, verb, path)
    const ok = status > 0 && status < 400
    if (isBackground) {
      // The app's own polling is not the user's experience: it does not make a click "alive" either.
      if (ok) { backgroundDown.delete(where); return }
      if (status === 401 || backgroundDown.has(where)) return
      backgroundDown.add(where)
    } else {
      networkCount++
    }
    if (!isBackground && slowMs > 0 && ms >= slowMs && ok && document.visibilityState === 'visible' && !slowSeen.has(where)) {
      slowSeen.add(where)
      record({ type: 'slow', route: currentRoute, target: recentClick(), detail: where, duration_ms: Math.round(ms) })
    }
    if (!isBackground && /^(POST|PUT|PATCH|DELETE)$/.test(verb) && ok && !matches(notActions, verb, path)) {
      filling = null
      // A write nobody clicked for (a heartbeat, a background save) is not an action.
      if (actionClicks > 0) {
        record({ type: 'action', route: currentRoute, detail: where, clicks: actionClicks, duration_ms: Date.now() - actionStart,
          label: lastLabel || undefined })
        actionClicks = 0
        lastLabel = ''
      }
    }
    if (status === 401 || ok) return
    const type = status >= 400 && status < 500 ? 'http_4xx' : 'http_5xx'
    record({ type, route: currentRoute, target: recentClick(), detail: `${where} ${status || 'network failure'}` })
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
      const seen = new Map<string, string>()
      for (const el of Array.from(document.querySelectorAll(CLICKABLE))) {
        if (el.closest(OVERLAY) || !el.getClientRects().length) continue
        const selector = selectorOf(el)
        if (!seen.get(selector)) seen.set(selector, labelOf(el))
        if (seen.size >= MAX_INVENTORY) break
      }
      if (seen.size) record({ type: 'inventory', route, targets: Array.from(seen.keys()), labels: Array.from(seen.values()) })
    }, INVENTORY_DELAY_MS)
  }

  function page(route?: string) {
    leaveForm()
    currentRoute = route ?? options.route?.() ?? routeFromPath(location.pathname)
    arrivedAt = Date.now()
    slowSeen.clear()
    pageEvent()
    scheduleInventory()
  }

  // The title usually changes just after the router does: the name is read a moment later, on the same visit.
  function pageEvent() {
    const event = record({ type: 'page', route: currentRoute })
    const route = currentRoute
    setTimeout(() => {
      if (route !== currentRoute) return
      let given: string | null | undefined
      try { given = options.screen?.() } catch { /* the app is not ready */ }
      const name = screenOf(route, given)
      if (name && event) event.label = name
    }, 300)
  }

  // Clicks: usage, rage, dead, and the effort of the next action.
  listen(document, 'click', (e) => {
    // Only what a person did: a click the app fires by code (el.click(), dispatchEvent) is not usage, not
    // effort and not a dead or rage click. Mouse, touch and Enter/Space on a control are trusted.
    if (!e.isTrusted && !options.countScriptedClicks) return
    const target = e.target instanceof Element ? e.target : null
    if (target?.closest(OVERLAY)) return
    const now = Date.now()
    const clickable = target?.closest(CLICKABLE) ?? null
    const selector = selectorOf(clickable ?? target)
    const label = labelOf(clickable) || undefined
    record({ type: 'click', route: currentRoute, target: selector, label })
    lastClick = { target: selector, t: now }
    if (label) lastLabel = label
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
      record({ type: 'rage', route: currentRoute, target: selectorOf(target), label: labelOf(target) || undefined })
    }

    if (!clickable) return
    const before = { route: currentRoute, href: location.href, mutations: mutationCount, requests: networkCount }
    setTimeout(() => {
      const reacted = mutationCount !== before.mutations || networkCount !== before.requests || location.href !== before.href
      if (!reacted && !rageInBurst) record({ type: 'dead', route: before.route, target: selectorOf(clickable), label })
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
    const sent = performance.now()
    try {
      const response = await nativeFetch.call(window, input, init)
      network(method, url, response.status, performance.now() - sent)
      return response
    } catch (failure) {
      if (!(failure instanceof DOMException && failure.name === 'AbortError')) network(method, url, 0, performance.now() - sent)
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
      const sent = performance.now()
      this.addEventListener('abort', () => { aborted = true })
      this.addEventListener('loadend', () => { if (!aborted) network(req.method, req.url, this.status, performance.now() - sent) })
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
    pageEvent()
    scheduleInventory()
  }

  return {
    page,
    error,
    track(name) {
      const detail = scrub(String(name ?? '').trim()).slice(0, 60)
      if (detail) record({ type: 'track', route: currentRoute, detail })
    },
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
