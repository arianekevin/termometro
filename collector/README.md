# termometro

The browser collector of [Termometro](https://github.com/arianekevin/termometro): see where your users struggle —
rage clicks, dead clicks, errors, abandoned forms, effort per action and a heat map — **without recording anyone**.
No screen text, no field values, no session replay. ~3 kB gzipped, no dependencies.

It sends to your own Termometro server. [Run one with Docker](https://github.com/arianekevin/termometro#run-the-server)
first; its dashboard shows your project key.

```bash
npm install termometro
```

```ts
import { start } from 'termometro'

const termometro = start({
  key: 'tk_...',                              // from your server's project
  url: 'https://termometro.example.com',      // your server
  version: '1.4.0',                           // optional: compare deploys
  identity: () => user ? { account: user.accountId, user: user.id, role: user.role } : null, // optional, ids only
  pagesFromRouter: true,                      // if you call page() on route changes
})

router.afterEach((to) => termometro.page(to.matched[to.matched.length - 1]?.path ?? to.path)) // one row per screen, not per id
app.config.errorHandler = (err) => { termometro.error(err); console.error(err) }
```

| Method | |
|---|---|
| `page(route?)` | a screen change; pass the route pattern (`/orders/:id`) |
| `error(err)` | an error your framework caught before `window.onerror` |
| `identify({ account, user, role } \| null)` | who is using it, when you have no `identity` function |
| `stop()` | removes every hook and sends what is queued |

Without a bundler, your server also serves it as a tag:

```html
<script src="https://termometro.example.com/termometro.js" data-key="tk_..." async></script>
```

License: [AGPL-3.0](https://github.com/arianekevin/termometro/blob/main/LICENSE).
