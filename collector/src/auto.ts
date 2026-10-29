/**
 * The <script> tag entry, served by your server as /termometro.js:
 *
 *   <script src="https://termometro.example.com/termometro.js" data-key="tk_..." data-version="1.4.0" async></script>
 *
 * It starts on its own and leaves the instance in `window.termometro`, so the page can call
 * `termometro.identify({ account, user, role })` after sign-in and `termometro.page('/orders/:id')` on route changes.
 */
import { start, type Termometro } from './index'

declare global {
  interface Window { termometro?: Termometro }
}

const script = document.currentScript as HTMLScriptElement | null
const key = script?.dataset.key
if (script && key && !window.termometro) {
  window.termometro = start({
    key,
    url: script.dataset.url ?? new URL(script.src).origin,
    version: script.dataset.version
  })
} else if (script && !key) {
  console.warn('termometro: add data-key="…" to the script tag')
}
