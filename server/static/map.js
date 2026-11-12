// Termometro heat map, drawn over the app's own screen. The collector loads this file when the page was
// opened with `?termometro_map=<token>` (the dashboard's "Open heat map" button makes that link) and leaves
// window.termometroMap = { url, token, route(), mode, onClose() }. Each element of the current screen is painted by
// how much it is clicked, with a badge for rage clicks, dead clicks and errors after it; what can be clicked
// and never was is dashed. In "Routes" mode, arrows link each click to the next one on this screen, thicker and
// hotter the more often that step was taken. Esc or "Close" turn it off.
;(() => {
  const cfg = window.termometroMap
  if (!cfg || window.__termometroMapOpen) return
  window.__termometroMapOpen = true

  const pt = /^pt\b/i.test(navigator.language)
  const T = pt
    ? { title: 'Termometro · mapa de uso', close: 'Fechar', loading: 'Carregando…', visits: 'visitas', clicks: 'cliques',
        inView: (n, total) => `${n} de ${total} elementos com dados estão à vista`, never: 'nunca clicados',
        neverCount: (n) => `${n} elementos nunca clicados`, days: 'dias', expired: 'o link do mapa expirou: abra de novo pelo painel',
        down: 'o Termometro não respondeu', less: 'pouco → muito clicado', heat: 'Calor', routes: 'Rotas',
        routesInfo: (shown, total) => `${shown} das ${total} rotas mais feitas nesta tela`, routesLess: 'pouco → muito feita',
        noRoutes: 'nenhuma sequência de cliques nesta tela ainda', top: (n) => `${n} mais feitas`, step: (a, b, n) => `${a} → ${b}\n${n} vezes`,
        tip: (e, n) => `${e.target}\n${e.clicks} cliques de ${e.users} usuários\nrage ${e.rage} · sem resposta ${e.dead} · erros depois ${e.errors}` +
          (n > 1 ? `\n${n} elementos com este seletor; o número é a soma` : '') }
    : { title: 'Termometro · usage map', close: 'Close', loading: 'Loading…', visits: 'visits', clicks: 'clicks',
        inView: (n, total) => `${n} of ${total} elements with data are in view`, never: 'never clicked',
        neverCount: (n) => `${n} elements never clicked`, days: 'days', expired: 'the map link expired: open it again from the dashboard',
        down: 'Termometro did not answer', less: 'few → many clicks', heat: 'Heat', routes: 'Routes',
        routesInfo: (shown, total) => `${shown} of the ${total} most taken routes on this screen`, routesLess: 'rarely → often taken',
        noRoutes: 'no click sequence on this screen yet', top: (n) => `top ${n}`, step: (a, b, n) => `${a} → ${b}\n${n} times`,
        tip: (e, n) => `${e.target}\n${e.clicks} clicks by ${e.users} users\nrage ${e.rage} · dead ${e.dead} · errors after ${e.errors}` +
          (n > 1 ? `\n${n} elements share this selector; the number is their sum` : '') }

  // The project comes inside the token: m.<project>.<expiry>.<signature>
  const project = cfg.token.split('.').slice(1, -2).join('.')

  const root = document.createElement('div')
  root.setAttribute('data-termometro', '')
  root.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2147483000;font:12px/16px system-ui,-apple-system,"Segoe UI",Roboto,sans-serif'
  const layer = document.createElement('div')
  const panel = document.createElement('div')
  panel.style.cssText = 'position:fixed;right:12px;bottom:12px;max-width:min(360px,calc(100vw - 24px));pointer-events:auto;' +
    'background:#1d1b22;color:#fff;border-radius:12px;padding:12px 14px;box-shadow:0 8px 24px rgba(0,0,0,.35)'
  root.append(layer, panel)
  document.body.appendChild(root)

  let days = 30
  let showNever = true
  let mode = cfg.mode === 'routes' ? 'routes' : 'heat' // the dashboard's Map tab may open it straight in Routes
  let routesShown = 5
  const SVG = 'http://www.w3.org/2000/svg'
  let data = null
  let loadedRoute = null
  let frame = 0

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))

  // Cold to hot: blue, yellow, orange, red — the fraction of the most clicked element.
  function heat(f, alpha) {
    const stops = [[59, 130, 246], [250, 204, 21], [249, 115, 22], [220, 38, 38]]
    const x = Math.min(1, Math.max(0, f)) * (stops.length - 1)
    const i = Math.min(stops.length - 2, Math.floor(x)), k = x - i
    const [r, g, b] = stops[i].map((v, j) => Math.round(v + (stops[i + 1][j] - v) * k))
    return `rgba(${r},${g},${b},${alpha})`
  }

  function visible(el) {
    const r = el.getBoundingClientRect()
    return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth
  }

  function find(selector) {
    try { return Array.from(document.querySelectorAll(selector)).filter((el) => !root.contains(el)) } catch { return [] }
  }

  function box(r, style) {
    const div = document.createElement('div')
    div.style.cssText = `position:fixed;left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px;border-radius:4px;${style}`
    layer.appendChild(div)
  }

  const center = (el) => { const r = el.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2, r } }
  const svgEl = (tag, attrs) => { const el = document.createElementNS(SVG, tag); for (const k in attrs) el.setAttribute(k, attrs[k]); return el }

  // Routes: the most taken steps from one click to the next, as curved arrows between the elements.
  function drawRoutes() {
    const paths = data.paths ?? []
    const shown = []
    for (const p of paths) {
      if (shown.length >= routesShown) break
      const a = find(p.from).find(visible), b = find(p.to).find(visible)
      if (a && b) shown.push({ ...p, a: center(a), b: center(b) })
    }
    const svg = svgEl('svg', { width: innerWidth, height: innerHeight })
    svg.style.cssText = 'position:fixed;inset:0;overflow:visible'
    const defs = svgEl('defs', {})
    svg.appendChild(defs)
    const max = Math.max(1, ...shown.map((p) => p.n))
    const outlined = new Set()
    // Least taken first, so the most taken are drawn on top.
    shown.slice().reverse().forEach((p, i) => {
      const f = p.n / max, color = heat(f, 0.95), width = 2 + f * 6, id = `tm-arrow-${i}`
      const marker = svgEl('marker', { id, viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 3, markerHeight: 3, orient: 'auto-start-reverse' })
      marker.appendChild(svgEl('path', { d: 'M0,0 L10,5 L0,10 z', fill: color }))
      defs.appendChild(marker)
      // A bend to one side, so A→B and B→A do not overlap; the end stops at the target's edge.
      const dx = p.b.x - p.a.x, dy = p.b.y - p.a.y, len = Math.hypot(dx, dy) || 1
      const bend = Math.min(80, len * 0.25), cx = (p.a.x + p.b.x) / 2 - (dy / len) * bend, cy = (p.a.y + p.b.y) / 2 + (dx / len) * bend
      const stop = Math.min(len / 3, Math.max(p.b.r.width, p.b.r.height) / 2 + 4)
      const ex = p.b.x - ((p.b.x - cx) / Math.hypot(p.b.x - cx, p.b.y - cy)) * stop, ey = p.b.y - ((p.b.y - cy) / Math.hypot(p.b.x - cx, p.b.y - cy)) * stop
      svg.appendChild(svgEl('path', { d: `M${p.a.x},${p.a.y} Q${cx},${cy} ${ex},${ey}`, fill: 'none', stroke: color, 'stroke-width': width,
        'stroke-linecap': 'round', 'marker-end': `url(#${id})`, opacity: 0.85 }))
      const mx = 0.25 * p.a.x + 0.5 * cx + 0.25 * ex, my = 0.25 * p.a.y + 0.5 * cy + 0.25 * ey
      const badge = document.createElement('div')
      badge.style.cssText = `position:fixed;left:${mx - 14}px;top:${my - 10}px;pointer-events:auto;cursor:help;background:${heat(f, 1)};color:#fff;` +
        'font-weight:700;border-radius:999px;padding:1px 7px;font-size:11px;border:2px solid #fff;white-space:nowrap'
      badge.textContent = String(p.n)
      badge.title = T.step(p.from_label || p.from, p.to_label || p.to, p.n)
      for (const [sel, c] of [[p.from, p.a], [p.to, p.b]]) {
        if (outlined.has(sel)) continue
        outlined.add(sel)
        box(c.r, 'outline:2px solid rgba(29,27,34,.55);background:rgba(255,255,255,.12)')
      }
      layer.appendChild(badge)
    })
    layer.prepend(svg)
    const counter = panel.querySelector('[data-in-view]')
    if (counter) counter.textContent = paths.length ? T.routesInfo(shown.length, paths.length) : T.noRoutes
  }

  function draw() {
    frame = 0
    layer.replaceChildren()
    if (!data) return
    if (mode === 'routes') return drawRoutes()
    const max = Math.max(1, ...data.elements.map((e) => e.clicks))
    let inView = 0
    for (const e of data.elements) {
      const els = find(e.target)
      if (els.length) inView++
      els.filter(visible).forEach((el, i) => {
        const r = el.getBoundingClientRect()
        const f = e.clicks / max
        box(r, `background:${heat(f, 0.18 + f * 0.37)};outline:2px solid ${heat(f, 0.9)}`)
        if (i > 0) return // several elements with one selector (table rows): one badge
        const problems = e.rage + e.dead + e.errors
        const badge = document.createElement('div')
        badge.style.cssText = `position:fixed;left:${Math.max(0, r.left)}px;top:${Math.max(0, r.top - 18)}px;pointer-events:auto;` +
          `background:${heat(f, 1)};color:#fff;font-weight:700;border-radius:999px;padding:1px 6px;font-size:11px;white-space:nowrap;cursor:help`
        badge.textContent = `${e.clicks}${problems ? ' ⚠' + problems : ''}${els.length > 1 ? ' ×' + els.length : ''}`
        badge.title = T.tip(e, els.length)
        layer.appendChild(badge)
      })
    }
    if (showNever) {
      for (const selector of data.never_clicked) {
        for (const el of find(selector).filter(visible)) box(el.getBoundingClientRect(), 'outline:2px dashed rgba(120,120,130,.9)')
      }
    }
    // The app's screen changes after the map opens (loading, tabs): the count follows every repaint.
    const counter = panel.querySelector('[data-in-view]')
    if (counter) counter.textContent = T.inView(inView, data.elements.length)
  }

  const schedule = () => { if (!frame) frame = requestAnimationFrame(draw) }

  function renderPanel(message) {
    const d = data
    const clicks = d ? d.elements.reduce((s, e) => s + e.clicks, 0) : 0
    const button = 'background:none;border:1px solid #555;color:#fff;border-radius:6px;padding:2px 8px;cursor:pointer'
    panel.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
        <b style="font-size:13px">${esc(T.title)}</b>
        <button data-act="close" style="margin-left:auto;${button}">${esc(T.close)}</button>
      </div>
      <div style="color:#d4d4d8;overflow-wrap:anywhere">${esc(loadedRoute ?? '')}</div>
      ${message ? `<div style="margin-top:6px;color:#fca5a5">${esc(message)}</div>` : d ? `
        <div style="margin-top:6px">${d.visits} ${T.visits} · ${clicks} ${T.clicks}</div>
        <div data-in-view style="margin-top:2px"></div>
        <div style="margin-top:2px;color:#a1a1aa">${esc(T.neverCount(d.never_clicked.length))}</div>` : `<div style="margin-top:6px">${T.loading}</div>`}
      <div style="display:flex;gap:4px;margin-top:8px">${['heat', 'routes'].map((m) => `<button data-mode="${m}" style="${button};${mode === m ? 'background:#fff;color:#1d1b22;font-weight:600' : ''}">${esc(T[m])}</button>`).join('')}</div>
      <div style="display:flex;gap:8px;align-items:center;margin-top:8px;flex-wrap:wrap">
        <select data-act="days" style="background:#27252d;color:#fff;border:1px solid #555;border-radius:6px;padding:2px 4px">
          ${[7, 30, 90].map((n) => `<option value="${n}" ${n === days ? 'selected' : ''}>${n} ${T.days}</option>`).join('')}
        </select>
        ${mode === 'heat' ? `<label style="display:flex;gap:4px;align-items:center;cursor:pointer"><input type="checkbox" data-act="never" ${showNever ? 'checked' : ''}>${esc(T.never)}</label>`
          : `<select data-act="shown" aria-label="${esc(T.routes)}" style="background:#27252d;color:#fff;border:1px solid #555;border-radius:6px;padding:2px 4px">
              ${[5, 10, 15].map((n) => `<option value="${n}" ${n === routesShown ? 'selected' : ''}>${esc(T.top(n))}</option>`).join('')}</select>`}
        <span title="${esc(mode === 'heat' ? T.less : T.routesLess)}" style="margin-left:auto;display:inline-block;width:80px;height:8px;border-radius:4px;background:linear-gradient(90deg,${heat(0, 1)},${heat(0.5, 1)},${heat(1, 1)})"></span>
      </div>`
  }

  async function load() {
    loadedRoute = cfg.route()
    data = null
    renderPanel()
    schedule()
    const q = new URLSearchParams({ project, route: loadedRoute, days: String(days) })
    try {
      const res = await fetch(`${cfg.url}/api/usage?${q}`, { headers: { Authorization: 'Bearer ' + cfg.token }, credentials: 'omit' })
      if (res.status === 401) throw new Error(T.expired)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const read = await res.json()
      if (read.route !== cfg.route()) return // the screen changed while loading
      data = read
      renderPanel()
    } catch (error) {
      renderPanel(error instanceof TypeError ? T.down : error.message)
    }
    schedule()
  }

  function close() {
    root.remove()
    clearInterval(watch)
    observer.disconnect()
    removeEventListener('scroll', schedule, true)
    removeEventListener('resize', schedule)
    removeEventListener('keydown', onKey, true)
    window.__termometroMapOpen = false
    cfg.onClose?.()
  }

  function onKey(e) { if (e.key === 'Escape') close() }

  panel.addEventListener('click', (e) => {
    if (e.target.closest('[data-act="close"]')) return close()
    const m = e.target.closest('[data-mode]')
    if (m) { mode = m.dataset.mode; renderPanel(); schedule() }
  })
  panel.addEventListener('change', (e) => {
    if (e.target.matches('[data-act="days"]')) { days = Number(e.target.value); load() }
    if (e.target.matches('[data-act="never"]')) { showNever = e.target.checked; schedule() }
    if (e.target.matches('[data-act="shown"]')) { routesShown = Number(e.target.value); schedule() }
  })
  addEventListener('scroll', schedule, true)
  addEventListener('resize', schedule)
  addEventListener('keydown', onKey, true)
  const observer = new MutationObserver((changes) => { if (changes.some((m) => !root.contains(m.target))) schedule() })
  observer.observe(document.body, { childList: true, subtree: true, attributes: true })
  // A screen change inside the app (SPA): reload when the collector's route changes.
  const watch = setInterval(() => { if (cfg.route() !== loadedRoute) load() }, 500)

  load()
})()
