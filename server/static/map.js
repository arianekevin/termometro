// Termometro usage map, drawn over the app's own screen. The collector loads this file when the page was opened with
// `?termometro_map=<token>` (the dashboard's Map tab makes that link) and leaves
// window.termometroMap = { url, token, route(), mode, onClose() }. Three lenses:
//  - Routes: for each element, its most common next click when it is at least 15% of what comes next, as a curved
//    arrow from edge to edge, wider the bigger the share; a pair strong both ways is a "back and forth". Picking an
//    element (from the panel) shows all its next steps with % and, faint and dashed, where people come from;
//  - Problems: only what irritates — rage, dead clicks, errors right after, a second click, near misses — tinted by
//    the share of its clicks that went wrong, with that share in words;
//  - Usage: how much each element is clicked.
// The panel says what to look at on this screen. Marks never take a click (the app stays usable underneath), follow
// their elements every frame (transitions, animations, scrolling containers) and are left out where the element is
// hidden, clipped or covered (a modal, a menu).
;(() => {
  const cfg = window.termometroMap
  if (!cfg || window.__termometroMapOpen) return
  window.__termometroMapOpen = true

  const pt = /^pt\b/i.test(navigator.language)
  const fmt = (n) => Number(n || 0).toLocaleString(pt ? 'pt-BR' : 'en-US')
  const secs = (ms) => `${(ms / 1000).toLocaleString(pt ? 'pt-BR' : 'en-US', { maximumFractionDigits: 1 })} s`
  const pc = (f) => `${Math.round(Math.min(1, f) * 100)}%`
  const T = pt ? {
    title: 'Termometro · mapa', close: 'Fechar', collapse: 'Recolher', expand: 'Abrir', loading: 'Carregando…',
    days: 'dias', expired: 'O link do mapa expirou: abra de novo pelo painel.', down: 'O Termometro não respondeu.',
    lenses: { usage: 'Calor', problems: 'Problemas', routes: 'Rotas' },
    help: { routes: 'O caminho mais comum depois de cada elemento.', problems: 'Quanto mais quente, mais irrita.', usage: 'Quanto mais quente, mais clicam.',
      picked: (n) => `Só as rotas de ${n}.` },
    look: 'O que olhar nesta tela', lookLead: 'Os passos que mais dizem algo, primeiro o mais forte.',
    irritTitle: 'O que irrita nesta tela', irritLead: 'Parte dos cliques que viraram irritação, clique sem resposta ou erro.',
    usageTitle: 'O que é mais usado', usageLead: (d) => `Cliques nos últimos ${d} dias.`,
    back: '← Todas as rotas', times: (n) => `${fmt(n)} ${n === 1 ? 'vez' : 'vezes'}`, clicksN: (n) => `${fmt(n)} ${n === 1 ? 'clique' : 'cliques'}`,
    irritates: (p) => `${p} irrita`, backForth: 'vai e volta', after: (n) => `Depois: ${n}`, before: (n) => `Antes: ${n}`,
    arrivals: (n, total) => `${fmt(n)} das ${fmt(total)} chegadas`,
    noSteps: 'Ainda não há sequências de cliques nesta tela.', noStrong: 'Nenhum passo chega a 15% do que vem depois: as pessoas se espalham.',
    noProblems: 'Nada nesta tela irrita quem usa neste período.', noClicks: 'Nenhum clique nesta tela neste período.',
    kinds: { rage: 'cliques repetidos de irritação', dead: 'clicou e nada aconteceu', errors: 'erro logo depois',
      retry: 'precisou clicar de novo', near_miss: 'clicou do lado, quase acertou' },
    why: { rage: 'na maioria, cliques repetidos de irritação', dead: 'parece clicável e não faz nada', errors: 'na maioria, erro logo depois',
      retry: 'o primeiro clique não pega', near_miss: 'as pessoas erram o alvo por pouco' },
    advice: { rage: 'Mostre que está trabalhando (carregando, desabilitado) e responda mais rápido.',
      dead: 'Ou vira botão de verdade, ou deixa de parecer clicável.', errors: 'Veja os erros em Falhas: algo quebra logo depois do clique.',
      retry: 'O primeiro clique precisa responder: confira o que acontece nele.', near_miss: 'Aumente a área de clique ou afaste o que está em volta.' },
    noteDominant: (p, a, b) => `${p} de quem clica em ${a} vai direto para ${b}: é o caminho esperado e pode encurtar.`,
    notePairs: (names) => `${names} ficam em vai e volta: sinal de que as pessoas não acham o que fazer em seguida.`,
    noteSpread: 'Nenhum passo domina: se existe um caminho esperado, ele não está evidente na tela.',
    pickedDominant: (a, b) => `Quase todo mundo vai de ${a} para ${b}: vale abrir ${b} já com o foco, ou juntar os dois passos.`,
    pickedSpread: (a) => `Depois de ${a} as pessoas se espalham: nenhum próximo passo domina. Se existe um caminho esperado, ele não está evidente na tela.`,
    pickedNone: (a) => `Não há clique seguinte registrado depois de ${a}.`,
    noteProblem: (n, p, why, advice) => `${n} irrita ${p} das vezes que é clicado: ${why}. ${advice}`,
    causesTitle: 'Por que irrita', whyNote: (n, p, list, fix) => `${n}: ${p} dos cliques irritam. Por quê: ${list}. O que fazer: ${fix}`,
    noCauses: 'Nada irrita neste elemento no período.',
    cause: { rage_waiting: (c) => `clicou de novo enquanto carregava: o botão seguiu clicável${c.slow ? ` (${c.slow} levou ${secs(c.slow_ms)} na mediana)` : ''}`,
      rage_nothing: () => 'clicou de novo porque nada mudou na tela', rage_unclear: () => 'a tela mudou, mas não deu para perceber; clicou de novo',
      rage_error: () => 'clicou de novo depois de um erro', rage_disabled: () => 'insistiu no botão desabilitado',
      rage_not_clickable: () => 'clicou várias vezes em algo que não é clicável', rage: () => 'cliques repetidos sem motivo claro',
      dead: () => 'clicou e nada aconteceu', retry: () => 'o primeiro clique não pegou; clicou de novo', near_miss: () => 'clicou do lado, quase acertou',
      failed: (c) => `deu erro logo depois: ${c.detail}`, slow: (c) => `${c.slow} demorou ${secs(c.slow_ms)} depois do clique (mediana)` },
    fix: { rage_waiting: (c) => `trave o botão e mostre que está carregando já no primeiro clique${c.slow ? `; e veja por que ${c.slow} leva ${secs(c.slow_ms)}` : ''}.`,
      rage_nothing: () => 'faça o clique ter um efeito visível; se depende de algo, diga do quê.', rage_unclear: () => 'deixe o retorno evidente perto do clique (mensagem, destaque).',
      rage_error: () => 'corrija a falha que vem logo depois (aba Falhas) e mostre uma mensagem quando falhar.', rage_disabled: () => 'diga por que está desabilitado e o que falta para liberar.',
      rage_not_clickable: () => 'parece clicável e não é: torne clicável ou mude a aparência.', rage: () => 'mostre resposta logo no primeiro clique.',
      dead: () => 'ou faz algo visível, ou deixa de parecer clicável.', retry: () => 'o primeiro clique precisa responder: confira o que acontece nele.',
      near_miss: () => 'aumente a área de clique ou afaste o que está em volta.', failed: (c) => `corrija ${c.detail} e mostre uma mensagem quando falhar.`,
      slow: (c) => `mostre que está carregando e acelere ${c.slow}.` },
    noteUsage: (n, share) => `${n} leva ${share} dos cliques desta tela.`,
    scale: { usage: ['menos cliques', 'mais cliques'], problems: ['irrita pouco', 'irrita muito'] },
    legend: { next: 'próximo passo mais comum', back: 'vai e volta', wider: 'seta mais grossa = parte maior', min: 'só passos com 15% ou mais',
      in: 'de onde chegam', bad: 'cor mais forte = mais cliques que irritam', none: 'sem cor = nenhum problema',
      usage: 'amarelo mais forte = mais cliques', never: 'tracejado = pode ser clicado e ninguém clicou' },
    never: 'nunca clicados', offscreen: (names) => `Fora da vista agora (menu fechado, janela, rolagem ou outra tela): ${names}.`,
    offTag: 'fora da vista', many: (n) => `Aparece ${n} vezes nesta tela; os números são de todas juntas.`, notHere: 'Não está na tela agora.',
    total: (v, c) => `${fmt(v)} visitas · ${fmt(c)} cliques`
  } : {
    title: 'Termometro · map', close: 'Close', collapse: 'Collapse', expand: 'Open', loading: 'Loading…',
    days: 'days', expired: 'The map link expired: open it again from the dashboard.', down: 'Termometro did not answer.',
    lenses: { usage: 'Heat', problems: 'Problems', routes: 'Routes' },
    help: { routes: 'The most common path after each element.', problems: 'The hotter, the more it irritates.', usage: 'The hotter, the more clicks.',
      picked: (n) => `Only the routes of ${n}.` },
    look: 'What to look at on this screen', lookLead: 'The steps that say the most, strongest first.',
    irritTitle: 'What irritates on this screen', irritLead: 'Share of the clicks that turned into rage, no response or an error.',
    usageTitle: 'What is used the most', usageLead: (d) => `Clicks in the last ${d} days.`,
    back: '← All routes', times: (n) => `${fmt(n)} ${n === 1 ? 'time' : 'times'}`, clicksN: (n) => `${fmt(n)} ${n === 1 ? 'click' : 'clicks'}`,
    irritates: (p) => `${p} irritate`, backForth: 'back and forth', after: (n) => `Next: ${n}`, before: (n) => `Before: ${n}`,
    arrivals: (n, total) => `${fmt(n)} of ${fmt(total)} arrivals`,
    noSteps: 'No click sequences on this screen yet.', noStrong: 'No step reaches 15% of what comes next: people scatter.',
    noProblems: 'Nothing on this screen irritates people in this period.', noClicks: 'No clicks on this screen in this period.',
    kinds: { rage: 'angry repeated clicks', dead: 'clicked and nothing happened', errors: 'error right after',
      retry: 'had to click again', near_miss: 'clicked beside it, nearly hit' },
    why: { rage: 'mostly angry repeated clicks', dead: 'looks clickable and does nothing', errors: 'mostly an error right after',
      retry: 'the first click does not take', near_miss: 'people narrowly miss it' },
    advice: { rage: 'Show it is working (loading, disabled) and answer faster.', dead: 'Make it a real button, or stop it looking clickable.',
      errors: 'See the errors in Failures: something breaks right after the click.', retry: 'The first click has to respond: check what it does.',
      near_miss: 'Make the click area bigger or move what is around it.' },
    noteDominant: (p, a, b) => `${p} of those who click ${a} go straight to ${b}: the expected path, and it can be shortened.`,
    notePairs: (names) => `${names} go back and forth: a sign people do not find what to do next.`,
    noteSpread: 'No step dominates: if there is an expected path, the screen does not make it clear.',
    pickedDominant: (a, b) => `Almost everyone goes from ${a} to ${b}: open ${b} already focused, or merge the two steps.`,
    pickedSpread: (a) => `After ${a} people scatter: no next step dominates. If there is an expected path, the screen does not make it clear.`,
    pickedNone: (a) => `No next click recorded after ${a}.`,
    noteProblem: (n, p, why, advice) => `${n} irritates ${p} of the times it is clicked: ${why}. ${advice}`,
    causesTitle: 'Why it irritates', whyNote: (n, p, list, fix) => `${n}: ${p} of the clicks irritate. Why: ${list}. What to do: ${fix}`,
    noCauses: 'Nothing about this element irritates in this period.',
    cause: { rage_waiting: (c) => `clicked again while it was loading: the button stayed clickable${c.slow ? ` (${c.slow} took ${secs(c.slow_ms)}, median)` : ''}`,
      rage_nothing: () => 'clicked again because nothing changed on screen', rage_unclear: () => 'the screen changed, but not visibly; clicked again',
      rage_error: () => 'clicked again after an error', rage_disabled: () => 'kept clicking the disabled button',
      rage_not_clickable: () => 'clicked repeatedly on something not clickable', rage: () => 'repeated clicks, no clear reason',
      dead: () => 'clicked and nothing happened', retry: () => 'the first click did not take; clicked again', near_miss: () => 'clicked beside it, nearly hit',
      failed: (c) => `an error right after: ${c.detail}`, slow: (c) => `${c.slow} took ${secs(c.slow_ms)} after the click (median)` },
    fix: { rage_waiting: (c) => `lock the button and show it is loading on the first click${c.slow ? `; and see why ${c.slow} takes ${secs(c.slow_ms)}` : ''}.`,
      rage_nothing: () => 'make the click do something visible; if it depends on something, say what.', rage_unclear: () => 'make the answer obvious near the click (message, highlight).',
      rage_error: () => 'fix the failure that follows (Failures tab) and show a message when it fails.', rage_disabled: () => 'say why it is disabled and what is missing.',
      rage_not_clickable: () => 'it looks clickable and is not: make it clickable or change how it looks.', rage: () => 'answer on the first click.',
      dead: () => 'make it do something visible, or stop it looking clickable.', retry: () => 'the first click has to respond: check what it does.',
      near_miss: () => 'make the click area bigger or move what is around it.', failed: (c) => `fix ${c.detail} and show a message when it fails.`,
      slow: (c) => `show it is loading and speed up ${c.slow}.` },
    noteUsage: (n, share) => `${n} takes ${share} of this screen's clicks.`,
    scale: { usage: ['fewer clicks', 'more clicks'], problems: ['irritates a little', 'irritates a lot'] },
    legend: { next: 'most common next step', back: 'back and forth', wider: 'thicker arrow = bigger share', min: 'only steps of 15% or more',
      in: 'where they come from', bad: 'stronger colour = more irritating clicks', none: 'no colour = no problem',
      usage: 'stronger yellow = more clicks', never: 'dashed = clickable and nobody clicked' },
    never: 'never clicked', offscreen: (names) => `Out of view now (closed menu, dialog, scrolling or another screen): ${names}.`,
    offTag: 'out of view', many: (n) => `Appears ${n} times on this screen; the numbers are for all of them.`, notHere: 'Not on the screen now.',
    total: (v, c) => `${fmt(v)} visits · ${fmt(c)} clicks`
  }

  // Nectar warm palette (the approved reference's light theme).
  const C = { fg: '#2a2418', fg2: '#6b5f48', faint: '#8f8370', surface: '#ffffff', sunken: '#f1ece0', line: '#e4dccb',
    fill: '#fec10d', accent: '#8a5e00', warn: '#b3400a', bad: '#a81c3f', never: '#6b5f48', halo: 'rgba(255,255,255,.95)' }
  const MIN = 0.15 // a step is worth an arrow from this share of what comes next
  const DOMINANT = 0.6
  const MIN_IRR = 3 // fewer irritations than this is noise, not a problem
  const KINDS = ['rage', 'dead', 'errors', 'retry', 'near_miss']

  const ss = (key, value) => {
    try {
      if (value === null) sessionStorage.removeItem(key)
      else if (value !== undefined) sessionStorage.setItem(key, value)
      return sessionStorage.getItem(key)
    } catch { return null }
  }
  // An older collector (before 0.2.5) leaves `termometro_mode` in the address and never passes it on: read it here.
  const params = new URLSearchParams(location.search)
  const urlMode = params.get('termometro_mode')
  if (urlMode) {
    params.delete('termometro_mode')
    const rest = params.toString()
    try { history.replaceState(history.state, '', location.pathname + (rest ? '?' + rest : '') + location.hash) } catch {}
  }
  const kept = (ss('termometro.mapLens') || '').split('|')
  // A heat map first: where people click. "Open with the routes" asks for the routes.
  let lens = urlMode ? (urlMode === 'routes' ? 'routes' : 'usage')
    : kept[0] === cfg.token && T.lenses[kept[1]] ? kept[1] : cfg.mode === 'routes' ? 'routes' : 'usage'
  const keepLens = () => ss('termometro.mapLens', cfg.token + '|' + lens)
  keepLens()

  // The project comes inside the token: m.<project>.<expiry>.<signature>
  const project = cfg.token.split('.').slice(1, -2).join('.')

  const root = document.createElement('div')
  root.setAttribute('data-termometro', '')
  root.style.cssText = `position:fixed;inset:0;pointer-events:none;z-index:2147483000;font:13px/18px Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:${C.fg}`
  const layer = document.createElement('div')
  const panel = document.createElement('div')
  panel.setAttribute('role', 'dialog')
  panel.setAttribute('aria-label', T.title)
  root.append(layer, panel)
  document.body.appendChild(root)

  let days = 30
  let showNever = false // the dashed never-clicked marks crowd the heat: a box in the panel turns them on
  let collapsed = false
  let data = null, loadedRoute = null, message = null
  let hovered = null, picked = null // element targets (selectors)
  const SVG = 'http://www.w3.org/2000/svg'
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))

  // ---------- what is on screen ----------
  const found = new Map() // selector → elements
  let queryDirty = true, lastQuery = 0
  function find(selector) {
    try { return Array.from(document.querySelectorAll(selector)).filter((el) => !root.contains(el)) } catch { return [] }
  }
  function tracked() {
    if (!data) return []
    const s = new Set(data.elements.map((e) => e.target))
    for (const t of data.never_clicked || []) s.add(t)
    for (const p of data.paths || []) { s.add(p.from); s.add(p.to) }
    return [...s]
  }
  function requery() {
    found.clear()
    for (const t of tracked()) found.set(t, find(t))
    queryDirty = false
    lastQuery = performance.now()
  }

  // The part of the element a person can see now: not display:none, visibility:hidden or transparent, inside the
  // viewport and every scrolling/clipping ancestor, and not covered by something else (a modal, a menu).
  function seen(el) {
    const r = el.getBoundingClientRect()
    if (r.width < 1 || r.height < 1) return null
    if (el.checkVisibility) { if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return null }
    else if (getComputedStyle(el).visibility === 'hidden') return null
    let l = Math.max(0, r.left), t = Math.max(0, r.top), rr = Math.min(innerWidth, r.right), b = Math.min(innerHeight, r.bottom)
    let fixed = getComputedStyle(el).position === 'fixed'
    for (let a = el.parentElement; a && a !== document.body && a !== document.documentElement && !fixed; a = a.parentElement) {
      const cs = getComputedStyle(a)
      if (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') {
        const ar = a.getBoundingClientRect(), al = ar.left + a.clientLeft, at = ar.top + a.clientTop
        if (cs.overflowX !== 'visible') { l = Math.max(l, al); rr = Math.min(rr, al + a.clientWidth) }
        if (cs.overflowY !== 'visible') { t = Math.max(t, at); b = Math.min(b, at + a.clientHeight) }
      }
      if (cs.position === 'fixed') fixed = true
    }
    if (rr - l < 2 || b - t < 2) return null
    for (const [fx, fy] of [[0.5, 0.5], [0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]]) {
      // The first thing under that point that is the app's (the map's own panel does not count as a cover).
      const hit = document.elementsFromPoint(l + (rr - l) * fx, t + (b - t) * fy).find((h) => !root.contains(h))
      if (hit && (hit === el || el.contains(hit) || hit.contains(el))) return { left: l, top: t, right: rr, bottom: b, width: rr - l, height: b - t }
    }
    return null
  }

  let geo = new Map() // selector → visible rects
  function measure() {
    geo = new Map()
    for (const [t, list] of found) {
      const rects = []
      for (const el of list) { const r = seen(el); if (r) rects.push(r) }
      if (rects.length) geo.set(t, rects)
    }
  }
  const shown = (t) => geo.has(t)

  // ---------- the data, in people's words ----------
  let els = new Map(), outTotal = new Map(), inTotal = new Map()
  function model() {
    els = new Map(); outTotal = new Map(); inTotal = new Map()
    for (const e of data.elements) {
      const irr = KINDS.reduce((s, k) => s + (e[k] || 0), 0)
      const main = KINDS.filter((k) => e[k]).sort((a, b) => e[b] - e[a])[0]
      els.set(e.target, { ...e, irr, main, pain: e.clicks ? Math.min(1, irr / e.clicks) : irr ? 1 : 0 })
    }
    for (const p of paths()) {
      outTotal.set(p.from, (outTotal.get(p.from) || 0) + p.n)
      inTotal.set(p.to, (inTotal.get(p.to) || 0) + p.n)
    }
  }
  function nameOf(t) {
    const e = els.get(t)
    if (e?.label) return e.label
    for (const p of data?.paths || []) { if (p.from === t && p.from_label) return p.from_label; if (p.to === t && p.to_label) return p.to_label }
    const el = (found.get(t) || [])[0]
    const own = el && (el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') ||
      (el.innerText || '').trim().split('\n')[0].slice(0, 30))
    if (own && /\p{L}/u.test(own)) return own
    const m = /([#.])([\w-]+)[^#.]*$/.exec(t) // button#novo-ticket → "novo ticket"
    return m ? m[2].replace(/[-_]+/g, ' ') : t
  }
  // A step's share: of everything that came right after `from`, how much went to `to`.
  const share = (p) => p.n / (outTotal.get(p.from) || 1)
  const MIN_N = 5 // a step taken fewer times than this is an accident, not a route
  const paths = () => (data?.paths || []).filter((p) => p.n >= MIN_N)
  const step = (a, b) => paths().find((p) => p.from === a && p.to === b)
  const backAndForth = (p) => { const r = step(p.to, p.from); return share(p) >= MIN && !!r && share(r) >= MIN }
  function bestSteps() { // each element's single most common next step, when it is a real share
    const best = new Map()
    for (const p of paths()) if (!best.has(p.from) || p.n > best.get(p.from).n) best.set(p.from, p)
    return [...best.values()].filter((p) => share(p) >= MIN).sort((a, b) => share(b) - share(a))
  }
  const problems = () => [...els.values()].filter((e) => e.irr >= MIN_IRR).sort((a, b) => b.pain - a.pain || b.irr - a.irr)
  // Why it irritates, from the server's count of each cause: the sentence, the count, and what to do about the first.
  const causes = (e) => (e?.causes || []).filter((c) => T.cause[c.kind])
  const causeText = (c) => T.cause[c.kind](c)
  const causeLine = (e) => { const list = causes(e); const top = list[0]
    return top ? `${causeText(top)} · ${T.times(top.n)}` : (T.why[e.main] || '') }
  const whyNote = (e) => { const list = causes(e).slice(0, 3); if (!list.length) return T.noteProblem(nameOf(e.target), pc(e.pain), T.why[e.main], T.advice[e.main])
    return T.whyNote(nameOf(e.target), pc(e.pain), list.map((c) => `${causeText(c)} (${T.times(c.n)})`).join('; '), T.fix[list[0].kind](list[0])) }
  const used = () => [...els.values()].filter((e) => e.clicks > 0).sort((a, b) => b.clicks - a.clicks)

  // ---------- drawing ----------
  let placed = []
  const overlaps = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom
  function mark(r, color, { width = 2, fill = 'transparent', dashed = false, dim = false } = {}) {
    const d = document.createElement('div')
    d.style.cssText = `position:fixed;left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px;box-sizing:border-box;` +
      `border-radius:6px;background:${fill};border:${width}px ${dashed ? 'dashed' : 'solid'} ${color};` +
      `box-shadow:0 0 0 1px ${C.halo};opacity:${dim ? 0.3 : 1}`
    layer.appendChild(d)
  }
  function pill(text, bg, fg) {
    const b = document.createElement('div')
    b.textContent = text
    b.style.cssText = `position:fixed;left:0;top:0;background:${bg};color:${fg};font-weight:600;font-size:12px;line-height:16px;` +
      `border-radius:999px;padding:2px 8px;white-space:nowrap;border:2px solid ${C.surface};box-shadow:0 1px 3px rgba(0,0,0,.25);` +
      'max-width:240px;overflow:hidden;text-overflow:ellipsis;font-variant-numeric:tabular-nums'
    layer.appendChild(b)
    return b
  }
  // A pill above the element, or below, or at its right end — wherever it covers no other pill and not the panel.
  function badge(r, text, bg, fg, force) {
    const b = pill(text, bg, fg)
    const w = b.offsetWidth, h = b.offsetHeight
    const pr = panel.getBoundingClientRect()
    for (const [x0, y0] of [[r.left, r.top - h - 3], [r.left, r.bottom + 3], [r.right - w, r.top - h - 3], [r.right - w, r.bottom + 3]]) {
      const x = Math.max(2, Math.min(innerWidth - w - 2, x0)), y = Math.max(2, Math.min(innerHeight - h - 2, y0))
      const box = { left: x, top: y, right: x + w, bottom: y + h }
      if (!force && (placed.some((p) => overlaps(p, box)) || overlaps(pr, box))) continue
      b.style.left = x + 'px'; b.style.top = y + 'px'; placed.push(box)
      return
    }
    b.remove() // no free spot: the element keeps its colour and is in the panel's list
  }
  const focusOn = () => hovered || picked
  const dimOf = (t) => !!focusOn() && focusOn() !== t

  // Heat: a soft spot on each element, as strong as its clicks (or its irritation), adding up where they sit close, then
  // coloured from cool to hot. Drawn at half resolution: the blur hides it and scrolling stays smooth.
  const RAMP = {
    usage: [[0, [59, 130, 246]], [0.3, [34, 197, 94]], [0.55, [250, 204, 21]], [0.78, [249, 115, 22]], [1, [220, 38, 38]]],
    problems: [[0, [253, 224, 71]], [0.45, [249, 115, 22]], [0.75, [220, 38, 38]], [1, [127, 29, 29]]]
  }
  const paletteOf = (stops) => {
    const out = new Uint8ClampedArray(256 * 4)
    for (let i = 0; i < 256; i++) {
      const t = i / 255
      let k = 0; while (k < stops.length - 2 && t > stops[k + 1][0]) k++
      const [t0, c0] = stops[k], [t1, c1] = stops[k + 1], f = Math.min(1, Math.max(0, (t - t0) / (t1 - t0 || 1)))
      for (let c = 0; c < 3; c++) out[i * 4 + c] = c0[c] + (c1[c] - c0[c]) * f
      out[i * 4 + 3] = Math.min(165, 40 + t * 190) // see-through even at the hottest: the screen stays readable
    }
    return out
  }
  const PALETTE = { usage: paletteOf(RAMP.usage), problems: paletteOf(RAMP.problems) }
  const rampCss = (kind) => `linear-gradient(90deg,${RAMP[kind].map(([t, c]) => `rgb(${c.join(',')}) ${t * 100}%`).join(',')})`
  const heatValue = (e) => lens === 'problems' ? e.irr : e.clicks
  function drawHeat() {
    const list = lens === 'problems' ? problems() : used()
    const S = 0.5, W = Math.ceil(innerWidth * S), H = Math.ceil(innerHeight * S)
    const cv = document.createElement('canvas')
    cv.width = W; cv.height = H
    cv.style.cssText = `position:fixed;left:0;top:0;width:${innerWidth}px;height:${innerHeight}px;pointer-events:none`
    const ctx = cv.getContext('2d')
    // Each rect's share of its element (a control repeated in a list splits its clicks) on a log scale: the small ones show too.
    // Problems: how much of its clicks irritate, half or more is the hottest. Clicks: in proportion to the most clicked (a square
    // root, so the second tier still shows). A control repeated in a list (an icon on each row) is one element: which row got the
    // click is not known, so every copy shows the element's whole heat.
    const per = (e) => heatValue(e)
    const top = Math.max(1, ...list.map(per))
    for (const e of list) {
      const w = lens === 'problems' ? Math.min(1, e.pain / 0.5) : Math.sqrt(per(e) / top)
      if (w < 0.04) continue
      for (const r of geo.get(e.target) || []) {
        const cx = (r.left + r.width / 2) * S, cy = (r.top + r.height / 2) * S
        const rx = (r.width / 2 + 26) * S, ry = (r.height / 2 + 26) * S, R = Math.max(rx, ry)
        ctx.save(); ctx.translate(cx, cy); ctx.scale(rx / R, ry / R)
        const g = ctx.createRadialGradient(0, 0, 0, 0, 0, R)
        const a = 0.1 + 0.9 * w
        g.addColorStop(0, `rgba(0,0,0,${a})`); g.addColorStop(0.5, `rgba(0,0,0,${a * 0.8})`); g.addColorStop(1, 'rgba(0,0,0,0)')
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(0, 0, R, 0, Math.PI * 2); ctx.fill(); ctx.restore()
      }
    }
    const img = ctx.getImageData(0, 0, W, H), px = img.data, pal = PALETTE[lens === 'problems' ? 'problems' : 'usage']
    for (let i = 3; i < px.length; i += 4) {
      const a = px[i]
      if (a < 6) { px[i] = 0; continue }
      const o = a * 4
      px[i - 3] = pal[o]; px[i - 2] = pal[o + 1]; px[i - 1] = pal[o + 2]; px[i] = pal[o + 3] * Math.min(1, a / 40)
    }
    ctx.putImageData(img, 0, 0)
    layer.appendChild(cv)
    const f = focusOn()
    if (f) for (const r of geo.get(f) || []) mark(r, C.fg, { width: 3 })
    if (showNever) for (const t of data.never_clicked || []) for (const r of geo.get(t) || []) mark(r, C.never, { dashed: true, dim: !!f })
    // The number only on the hottest five (and the one in focus): the colour says the rest.
    const order = list.filter((e) => geo.has(e.target)).slice(0, 5)
    if (f && !order.some((e) => e.target === f) && els.get(f) && geo.has(f)) order.unshift(els.get(f))
    order.sort((a, b) => (b.target === f) - (a.target === f))
    for (const e of order) {
      const r = geo.get(e.target)[0]
      if (lens === 'problems') badge(r, T.irritates(pc(e.pain)), C.bad, '#fff', e.target === f)
      else badge(r, T.clicksN(e.clicks), C.fg, C.surface, e.target === f)
    }
  }

  const svgEl = (tag, attrs, parent) => { const el = document.createElementNS(SVG, tag); for (const k in attrs) el.setAttribute(k, attrs[k]); parent?.appendChild(el); return el }
  const mid = (r) => ({ x: r.left + r.width / 2, y: r.top + r.height / 2 })
  // Where the line from the centre of r towards (x, y) leaves r, a few pixels out.
  function edge(r, x, y, gap) {
    const c = mid(r), dx = x - c.x, dy = y - c.y, len = Math.hypot(dx, dy) || 1
    const k = Math.min(dx ? (r.width / 2) / Math.abs(dx) : Infinity, dy ? (r.height / 2) / Math.abs(dy) : Infinity, 1)
    return { x: c.x + dx * k + (dx / len) * gap, y: c.y + dy * k + (dy / len) * gap }
  }
  function drawRoutes() {
    const svg = svgEl('svg', { width: innerWidth, height: innerHeight })
    svg.style.cssText = 'position:fixed;inset:0;overflow:visible;pointer-events:none'
    const defs = svgEl('defs', {}, svg)
    for (const [id, color] of [['main', C.accent], ['warn', C.warn]]) {
      const m = svgEl('marker', { id: 'tm-ar-' + id, viewBox: '0 0 10 10', refX: 8, refY: 5, markerWidth: 5, markerHeight: 5, orient: 'auto-start-reverse' }, defs)
      svgEl('path', { d: 'M0,0 L10,5 L0,10 z', fill: color }, m)
    }
    layer.appendChild(svg)
    const ends = new Set(), missing = new Set(), labels = []
    function arrow(p, { faint = false } = {}) {
      const a = geo.get(p.from)?.[0], b = geo.get(p.to)?.[0]
      if (!a || !b) { if (!a) missing.add(p.from); if (!b) missing.add(p.to); return }
      ends.add(p.from); ends.add(p.to)
      const A = mid(a), B = mid(b), dx = B.x - A.x, dy = B.y - A.y, len = Math.hypot(dx, dy) || 1
      // A bend to one side, so A→B and B→A do not overlap; from the edge of one to the edge of the other.
      const bend = Math.min(90, len * 0.28), cx = (A.x + B.x) / 2 - (dy / len) * bend, cy = (A.y + B.y) / 2 + (dx / len) * bend
      const s = edge(a, cx, cy, 3), e = edge(b, cx, cy, 5)
      const d = `M${s.x},${s.y} Q${cx},${cy} ${e.x},${e.y}`
      if (faint) {
        svgEl('path', { d, fill: 'none', stroke: C.surface, 'stroke-width': 4, 'stroke-linecap': 'round', opacity: 0.8 }, svg)
        svgEl('path', { d, fill: 'none', stroke: C.faint, 'stroke-width': 1.5, 'stroke-dasharray': '4 5', opacity: 0.9 }, svg)
        return
      }
      const f = share(p), loop = backAndForth(p), color = loop ? C.warn : C.accent, w = 2 + f * 7
      svgEl('path', { d, fill: 'none', stroke: C.surface, 'stroke-width': w + 4, 'stroke-linecap': 'round', opacity: 0.85 }, svg)
      svgEl('path', { d, fill: 'none', stroke: color, 'stroke-width': w, 'stroke-linecap': 'round', opacity: 0.92,
        'marker-end': `url(#tm-ar-${loop ? 'warn' : 'main'})`, 'data-step': '' }, svg)
      labels.push({ x: 0.25 * s.x + 0.5 * cx + 0.25 * e.x, y: 0.25 * s.y + 0.5 * cy + 0.25 * e.y, text: pc(f), loop })
    }
    if (picked) {
      for (const p of paths().filter((p) => p.to === picked && share(p) >= MIN)) arrow(p, { faint: true })
      for (const p of paths().filter((p) => p.from === picked)) arrow(p)
      if (!shown(picked)) missing.add(picked)
    } else {
      for (const p of bestSteps()) arrow(p)
    }
    for (const t of ends) for (const r of geo.get(t) || []) {
      const on = t === picked || t === hovered
      mark(r, on ? C.fg : C.accent, { width: on ? 3 : 1.5, fill: on ? 'rgba(254,193,13,.22)' : 'transparent', dim: picked && t !== picked && !on ? false : false })
    }
    if (hovered && !ends.has(hovered)) for (const r of geo.get(hovered) || []) mark(r, C.fg, { width: 3, fill: 'rgba(254,193,13,.22)' })
    for (const l of labels) {
      const b = pill(l.text, l.loop ? C.warn : C.accent, '#fff')
      b.style.left = Math.max(2, Math.min(innerWidth - b.offsetWidth - 2, l.x - b.offsetWidth / 2)) + 'px'
      b.style.top = Math.max(2, Math.min(innerHeight - b.offsetHeight - 2, l.y - b.offsetHeight / 2)) + 'px'
    }
    return [...missing].filter((t) => !shown(t))
  }

  let lastDrawn = ''
  function draw(force) {
    const sig = [lens, hovered, picked, showNever, collapsed, innerWidth, innerHeight,
      ...[...geo].map(([t, rs]) => t + rs.map((r) => `${r.left | 0},${r.top | 0},${r.width | 0},${r.height | 0}`).join(';'))].join('|')
    if (!force && sig === lastDrawn) return
    lastDrawn = sig
    layer.replaceChildren()
    placed = []
    if (!data || collapsed) return
    let off
    if (lens === 'routes') off = drawRoutes()
    else {
      drawHeat()
      off = (lens === 'problems' ? problems() : used()).slice(0, 5).map((e) => e.target).filter((t) => !shown(t))
    }
    const note = panel.querySelector('[data-off]')
    const text = off.length ? T.offscreen([...new Set(off.map(nameOf))].slice(0, 5).join(', ')) : ''
    if (note && note.textContent !== text) { note.textContent = text; note.hidden = !text }
    for (const row of panel.querySelectorAll('[data-t]')) {
      const tag = row.querySelector('[data-offtag]')
      if (tag) tag.hidden = shown(row.dataset.t)
    }
  }

  // Every frame: a cheap rect check of what the map follows; a full pass (visibility, clipping, cover) when something
  // moved, or every 300 ms for what CSS changes on its own (hover menus, fades). The DOM changing re-finds the elements.
  let lastSig = '', lastFull = 0, raf = 0
  function tick(now) {
    raf = requestAnimationFrame(tick)
    if (!data) return
    if (queryDirty || now - lastQuery > 1000) requery()
    let sig = ''
    for (const list of found.values()) for (const el of list) { const r = el.getBoundingClientRect(); sig += `${r.left | 0},${r.top | 0},${r.width | 0},${r.height | 0};` }
    if (sig !== lastSig || now - lastFull > 300) {
      lastSig = sig; lastFull = now
      measure()
      draw(false)
    }
  }
  const redraw = () => { measure(); draw(true) }

  // ---------- panel ----------
  const btn = `font:inherit;font-size:12px;background:${C.surface};border:1px solid ${C.line};color:${C.fg};border-radius:8px;padding:3px 10px;cursor:pointer`
  const chip = (text, color) => `<span style="display:inline-block;font-size:11px;font-weight:600;padding:0 8px;border-radius:999px;color:${color};background:${color}22">${esc(text)}</span>`
  const code = (s) => `<code style="font:11px ui-monospace,'SF Mono',Menlo,monospace;color:${C.faint};overflow-wrap:anywhere">${esc(s)}</code>`
  function item(t, name, num, say, { dim = false, flat = false } = {}) {
    return `<li style="list-style:none"><button data-t="${esc(t)}" style="width:100%;text-align:left;font:inherit;color:inherit;border:0;border-radius:10px;` +
      `padding:7px 10px;cursor:pointer;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 10px;opacity:${dim ? 0.55 : 1};` +
      `background:${picked === t && !flat && !name.includes(':') ? C.sunken : 'none'}">` +
      `<span style="font-weight:600;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:${flat ? 'normal' : 'nowrap'}">${esc(name)}</span>` +
      `<span style="font-variant-numeric:tabular-nums;font-weight:600;text-align:right">${esc(num)}</span>` +
      `<span style="grid-column:1/-1;color:${C.fg2};font-size:12px">${say}<span data-offtag ${shown(t) ? 'hidden' : ''} style="color:${C.faint}"> · ${esc(T.offTag)}</span></span></button></li>`
  }
  // Title, lead, items and the reading note for the current lens.
  function reading() {
    if (picked) {
      const e = els.get(picked) || { clicks: 0, pain: 0, irr: 0 }
      const count = (found.get(picked) || []).length
      const go = paths().filter((p) => p.from === picked).sort((a, b) => b.n - a.n)
      const come = paths().filter((p) => p.to === picked).sort((a, b) => b.n - a.n).slice(0, 3)
      const name = nameOf(picked)
      if (lens === 'problems') {
        const list = causes(e), total = list.reduce((a, c) => a + c.n, 0)
        return {
          title: name,
          lead: `${esc(T.clicksN(e.clicks))}${e.irr >= MIN_IRR ? ' · ' + chip(T.irritates(pc(e.pain)), C.bad) : ''}<br>${code(picked)}`,
          items: list.map((c) => item(picked, causeText(c), pc(c.n / (total || 1)), esc(T.times(c.n)), { flat: true })).join(''),
          empty: list.length ? '' : T.noCauses, note: list.length ? whyNote(e) : ''
        }
      }
      return {
        title: name,
        lead: `${esc(T.clicksN(e.clicks))}${e.irr >= MIN_IRR ? ' · ' + chip(T.irritates(pc(e.pain)), C.bad) : ''}<br>${code(picked)}` +
          (count > 1 ? `<br>${esc(T.many(count))}` : count ? '' : `<br><span style="color:${C.bad}">${esc(T.notHere)}</span>`),
        items: go.map((p) => item(p.to, T.after(nameOf(p.to)), pc(share(p)), esc(T.times(p.n)) + (backAndForth(p) ? ' · ' + chip(T.backForth, C.warn) : ''), { dim: share(p) < MIN })).join('') +
          come.map((p) => item(p.from, T.before(nameOf(p.from)), pc(p.n / (inTotal.get(picked) || 1)), esc(T.arrivals(p.n, inTotal.get(picked) || 0)))).join(''),
        note: !go.length ? T.pickedNone(name) : share(go[0]) >= DOMINANT ? T.pickedDominant(name, nameOf(go[0].to)) : T.pickedSpread(name)
      }
    }
    if (lens === 'routes') {
      const best = bestSteps()
      const pairs = []
      for (const p of best) if (backAndForth(p)) for (const t of [p.from, p.to]) if (!pairs.includes(nameOf(t))) pairs.push(nameOf(t))
      const dominant = best.find((p) => share(p) >= DOMINANT)
      const notes = []
      if (dominant) notes.push(T.noteDominant(pc(share(dominant)), nameOf(dominant.from), nameOf(dominant.to)))
      if (pairs.length) notes.push(T.notePairs(pairs.join(', ')))
      if (!notes.length && best.length) notes.push(T.noteSpread)
      return {
        title: T.look, lead: esc(T.lookLead),
        items: best.map((p) => item(p.from, `${nameOf(p.from)} → ${nameOf(p.to)}`, pc(share(p)), esc(T.times(p.n)) + (backAndForth(p) ? ' · ' + chip(T.backForth, C.warn) : ''))).join(''),
        empty: !paths().length ? T.noSteps : !best.length ? T.noStrong : '', note: notes.join(' ')
      }
    }
    if (lens === 'problems') {
      const list = problems()
      const top = list[0]
      return {
        title: T.irritTitle, lead: esc(T.irritLead),
        items: list.slice(0, 6).map((e) => item(e.target, nameOf(e.target), pc(e.pain), esc(causeLine(e)))).join(''),
        empty: list.length ? '' : T.noProblems, note: top ? whyNote(top) : ''
      }
    }
    const list = used(), total = list.reduce((s, e) => s + e.clicks, 0)
    return {
      title: T.usageTitle, lead: esc(T.usageLead(days)),
      items: list.slice(0, 6).map((e) => item(e.target, nameOf(e.target), fmt(e.clicks), code(e.target))).join(''),
      empty: list.length ? '' : T.noClicks, note: list.length ? T.noteUsage(nameOf(list[0].target), pc(list[0].clicks / (total || 1))) : ''
    }
  }
  function legendHtml() {
    const line = (color, dashed) => `<i style="display:inline-block;width:22px;height:0;border-top:3px ${dashed ? 'dashed' : 'solid'} ${color};vertical-align:middle;margin-right:6px"></i>`
    const box = (style) => `<i style="display:inline-block;width:16px;height:11px;border-radius:3px;vertical-align:middle;margin-right:6px;${style}"></i>`
    const L = T.legend
    const never = showNever ? `<span>${box(`border:2px dashed ${C.never}`)}${esc(L.never)}</span>` : ''
    if (lens === 'routes') return `<span>${line(C.accent)}${esc(L.next)}</span><span>${line(C.warn)}${esc(L.back)}</span><span>${esc(L.wider)}</span>` +
      `<span>${esc(L.min)}</span>${picked ? `<span>${line(C.faint, true)}${esc(L.in)}</span>` : ''}`
    const [lo, hi] = T.scale[lens]
    return `<span style="display:inline-flex;align-items:center;gap:6px">${esc(lo)}<i style="display:inline-block;width:110px;height:10px;border-radius:999px;background:${rampCss(lens)}"></i>${esc(hi)}</span>${never}`
  }
  function renderPanel() {
    panel.style.cssText = `position:fixed;right:12px;bottom:12px;box-sizing:border-box;pointer-events:auto;background:${C.surface};color:${C.fg};` +
      `border:1px solid ${C.line};border-radius:14px;box-shadow:0 10px 30px rgba(42,36,24,.22);padding:${collapsed ? '8px 10px' : '14px 16px'};` +
      `width:${collapsed ? 'auto' : 'min(360px,calc(100vw - 24px))'};max-height:${innerWidth < 600 ? '42vh' : 'min(72vh,620px)'};overflow:auto;overscroll-behavior:contain`
    const head = `<div style="display:flex;align-items:center;gap:8px">
        <span style="font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:${C.faint};font-weight:600;white-space:nowrap">${esc(T.title)}</span>
        <span style="color:${C.faint};font:11px ui-monospace,Menlo,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0">${esc(collapsed ? '' : loadedRoute ?? '')}</span>
        <button data-act="collapse" style="margin-left:auto;${btn}">${esc(collapsed ? T.expand : T.collapse)}</button>
        <button data-act="close" style="${btn}">${esc(T.close)}</button></div>`
    if (collapsed) { panel.innerHTML = head; lastDrawn = ''; return }
    const tabs = Object.keys(T.lenses).map((m) => `<button data-lens="${m}" aria-pressed="${lens === m}" style="font:inherit;border:0;border-radius:999px;` +
      `padding:4px 12px;cursor:pointer;${lens === m ? `background:${C.fill};color:${C.fg};font-weight:600` : `background:none;color:${C.fg2}`}">${esc(T.lenses[m])}</button>`).join('')
    let body
    if (message) body = `<p style="color:${C.bad};margin:10px 0 0">${esc(message)}</p>`
    else if (!data) body = `<p style="color:${C.fg2};margin:10px 0 0">${esc(T.loading)}</p>`
    else {
      const r = reading()
      body = `
        <div style="color:${C.faint};font-size:12px;margin-top:6px">${esc(picked ? T.help.picked(nameOf(picked)) : T.help[lens])}</div>
        ${picked ? `<button data-act="unpick" style="${btn};margin-top:10px">${esc(T.back)}</button>` : ''}
        <h2 style="margin:10px 0 0;font-size:15px;line-height:20px">${esc(r.title)}</h2>
        <p style="margin:4px 0 8px;color:${C.fg2}">${r.lead}</p>
        ${r.empty ? `<p style="color:${C.fg2};margin:0">${esc(r.empty)}</p>` : ''}
        <ol style="margin:0;padding:0;display:grid;gap:2px">${r.items}</ol>
        ${r.note ? `<div style="margin-top:10px;padding:10px 12px;border-radius:10px;background:${C.sunken};color:${C.fg2};font-size:12.5px">${esc(r.note)}</div>` : ''}
        <div data-off hidden style="margin-top:8px;color:${C.warn};font-size:12px"></div>
        <div style="display:flex;flex-wrap:wrap;gap:4px 14px;margin-top:10px;font-size:11.5px;color:${C.fg2}">${legendHtml()}</div>
        <div style="display:flex;gap:10px;align-items:center;margin-top:10px;flex-wrap:wrap;font-size:12px;color:${C.fg2}">
          <select data-act="days" aria-label="${esc(T.days)}" style="${btn};padding:2px 4px">
            ${[7, 30, 90].map((n) => `<option value="${n}" ${n === days ? 'selected' : ''}>${n} ${esc(T.days)}</option>`).join('')}</select>
          ${lens !== 'routes' ? `<label style="display:flex;gap:5px;align-items:center;cursor:pointer;white-space:nowrap"><input type="checkbox" data-act="never" ${showNever ? 'checked' : ''}>${esc(T.never)}</label>` : ''}
          <span style="margin-left:auto">${esc(T.total(data.visits, data.elements.reduce((s, e) => s + e.clicks, 0)))}</span>
        </div>`
    }
    panel.innerHTML = `${head}
      <div role="group" style="display:inline-flex;margin-top:10px;border:1px solid ${C.line};border-radius:999px;padding:2px;background:${C.sunken}">${tabs}</div>${body}`
    lastDrawn = ''
  }

  async function load() {
    loadedRoute = cfg.route()
    data = null; message = null; picked = null; hovered = null
    renderPanel()
    layer.replaceChildren()
    const q = new URLSearchParams({ project, route: loadedRoute, days: String(days) })
    try {
      const res = await fetch(`${cfg.url}/api/usage?${q}`, { headers: { Authorization: 'Bearer ' + cfg.token }, credentials: 'omit' })
      if (res.status === 401) throw new Error(T.expired)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const read = await res.json()
      if (read.route !== cfg.route()) return // the screen changed while loading
      data = read
      model()
      requery(); measure()
    } catch (error) {
      message = error instanceof TypeError ? T.down : error.message
    }
    renderPanel()
    redraw()
  }

  function close() {
    root.remove()
    cancelAnimationFrame(raf)
    clearInterval(watch)
    observer.disconnect()
    removeEventListener('keydown', onKey, true)
    removeEventListener('popstate', onRoute)
    window.__termometroMapOpen = false
    ss('termometro.mapLens', null)
    cfg.onClose?.()
  }
  // Esc closes the map only from its own panel: in the app, Esc belongs to the app (closing its dialogs and menus).
  function onKey(e) { if (e.key === 'Escape' && panel.contains(document.activeElement)) close() }

  // Picking an element shows its routes; one that is not in view is scrolled to.
  function pick(t) {
    picked = picked === t ? null : t
    if (picked) {
      lens = 'routes'; keepLens()
      const el = (found.get(t) || [])[0]
      if (el && !shown(t)) el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' })
    }
    hovered = null
    renderPanel(); redraw()
  }
  panel.addEventListener('click', (e) => {
    const b = e.target.closest('button')
    if (!b) return
    if (b.dataset.act === 'close') return close()
    if (b.dataset.act === 'collapse') { collapsed = !collapsed; renderPanel(); return redraw() }
    if (b.dataset.act === 'unpick') { picked = null; renderPanel(); return redraw() }
    if (b.dataset.lens) { lens = b.dataset.lens; picked = null; hovered = null; keepLens(); renderPanel(); return redraw() }
    if (b.dataset.t) pick(b.dataset.t)
  })
  panel.addEventListener('change', (e) => {
    if (e.target.matches('[data-act="days"]')) { days = Number(e.target.value); load() }
    if (e.target.matches('[data-act="never"]')) { showNever = e.target.checked; renderPanel(); redraw() }
  })
  panel.addEventListener('mouseover', (e) => {
    const t = e.target.closest('[data-t]')?.dataset.t ?? null
    if (t !== hovered) { hovered = t; redraw() }
  })
  panel.addEventListener('mouseleave', () => { if (hovered) { hovered = null; redraw() } })
  addEventListener('keydown', onKey, true)
  const observer = new MutationObserver((changes) => { if (changes.some((m) => !root.contains(m.target))) queryDirty = true })
  observer.observe(document.body, { childList: true, subtree: true, attributes: true, characterData: true })
  // A screen change inside the app (SPA): reload when the collector's route changes.
  const onRoute = () => { if (cfg.route() !== loadedRoute) load() }
  addEventListener('popstate', onRoute)
  const watch = setInterval(onRoute, 400)
  raf = requestAnimationFrame(tick)
  load()
})()
