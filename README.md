# Termometro

**See where your users struggle — without recording anyone.**

Termometro measures frustration and effort on every screen of your web app: rage clicks, dead clicks, errors,
abandoned forms, how many clicks each save takes, and what nobody ever clicks. It never records sessions or
collects what users type or see, and it runs on your own server.

[Português](README.pt-BR.md)

- **A score per screen**, 0 to 100, so you know where to look first.
- **Where it irritates:** the element behind each rage click, and which request failed after which click.
- **Effort per action:** "creating an order takes 12 clicks and 25 s" (median and p90).
- **Usage:** most and least used screens, and the elements nobody clicks.
- **People:** usage by role, account and user — ids only.
- **Heat map** over your own app, opened from the dashboard.
- **By version:** did the last deploy make things better or worse?

## Why

Session replay tools capture the screen. That is a problem when the screen holds health records, legal cases,
bank data or anything under LGPD/GDPR. Termometro keeps only the shape of the interaction:

| Sent | Never sent |
|---|---|
| the signal (rage click, dead click, error…) | text on the screen or in fields |
| the route as a pattern (`/orders/:id`) | the real ids in the URL |
| a short selector (`button#save`) | names, e-mails |
| the ids you choose to give (account, user, role) | recordings, screenshots |

E-mails, uuids, numbers with 3+ digits and quoted text are scrubbed in the browser before anything is sent.

## Run the server

**On a server with a domain** (HTTPS included, via Caddy):

```bash
curl -O https://raw.githubusercontent.com/arianekevin/termometro/main/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/arianekevin/termometro/main/.env.example
# edit .env: your domain, a password, your project (make a key with the command below)
docker compose run --rm termometro python termometro.py new-key
docker compose up -d
```

Open `https://your-domain`, sign in, and the dashboard shows the snippet for your app with its key.

**Just trying it on your machine:**

```bash
docker run --rm -p 8080:8080 -e TERMOMETRO_PASSWORD=try \
  -e TERMOMETRO_PROJECTS='[{"name":"local","key":"tk_local","origins":[]}]' \
  ghcr.io/arianekevin/termometro:latest
```

Then open http://localhost:8080 (password `try`).

### Configuration

| Variable | |
|---|---|
| `TERMOMETRO_PROJECTS` | JSON list of projects: `name`, `key`, `origins` (where the collector may send from; empty = any) and `url` (your app, for the heat map). Or `TERMOMETRO_CONFIG` with a file holding the same JSON. |
| `TERMOMETRO_PASSWORD` | a single password for the dashboard |
| `TERMOMETRO_GOOGLE_CLIENT_ID`, `TERMOMETRO_GOOGLE_CLIENT_SECRET` | sign in with Google instead of (or besides) the password |
| `TERMOMETRO_ALLOWED_EMAILS`, `TERMOMETRO_ALLOWED_DOMAINS` | who may sign in with Google, comma separated |
| `TERMOMETRO_PUBLIC_URL` | where the server is reached, e.g. `https://termometro.example.com` (needed for Google) |
| `TERMOMETRO_RETENTION_DAYS` | how long events with user ids are kept (default 90); after that they become id-less daily totals |
| `TERMOMETRO_NO_AUTH=1` | no sign-in, for a dashboard already behind your own VPN or proxy auth |

At least one way in — Google or a password — is required unless `TERMOMETRO_NO_AUTH=1`.

**Google sign-in:** in Google Cloud Console, create an OAuth client of type *Web application* with the
redirect URI `https://YOUR-SERVER/auth/google/callback`, then set the client id and secret above.

## Add the collector to your app

With a bundler:

```bash
npm install termometro
```

```ts
import { start } from 'termometro'

const termometro = start({
  key: 'tk_REPLACE',
  url: 'https://termometro.example.com',
  version: import.meta.env.VITE_APP_VERSION,          // compare deploys
  identity: () => user ? { account: user.accountId, user: user.id, role: user.role } : null,
  pagesFromRouter: true,
})

// Vue Router — one row per screen, not per id
router.afterEach((to, _from, failure) => { if (!failure) termometro.page(to.matched.at(-1)?.path ?? to.path) })
app.config.errorHandler = (err) => { termometro.error(err); console.error(err) }
```

Without a bundler:

```html
<script src="https://termometro.example.com/termometro.js" data-key="tk_REPLACE" async></script>
<script>
  // after sign-in, if you want people in the dashboard
  window.termometro?.identify({ account: 'acme', user: '42', role: 'admin' })
</script>
```

## How the score works

Each signal weighs points: rage click 3, dead click 2, screen error 5, server error 5, refused request 2,
abandoned form 2, quick back 1. A screen's score is its points divided by its visits, times 20, capped at 100.
Up to 19 is calm, 20–49 needs attention, 50+ is very frustrating.

An **action** is a write your backend accepted (POST, PUT, PATCH, DELETE answered 2xx/3xx), with the clicks and
time since the previous one; two idle minutes start the count again, and a write nobody clicked for is ignored.

## Known limits

- A dead click is "nothing in the page changed within 1 s". On a screen that updates by itself (toasts, clocks,
  live feeds) dead clicks are undercounted.
- Selectors are short (the element and up to two ancestors). Identical elements, like table rows, add up under
  one selector; the heat map shows `×N` when that happens.
- An automatic write right after a click (e.g. "mark as read" on open) takes that click as its effort.

## Develop

```bash
python3 -m unittest discover server/tests      # server
cd collector && npm install && npm test        # collector
cd collector && npm run build                  # also copies termometro.js into server/static
TERMOMETRO_PASSWORD=dev TERMOMETRO_PROJECTS='[{"name":"dev","key":"tk_dev","origins":[]}]' python3 server/termometro.py
docker build -t termometro .                   # the image, from source
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[AGPL-3.0](LICENSE). You can use, change and host Termometro freely; if you offer a changed version to others
as a service, you share those changes under the same license.
