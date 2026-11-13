# Termometro

**See where your users struggle — without recording anyone.**

Termometro measures frustration and effort on every screen of your web app: rage clicks, dead clicks, errors,
slow responses, abandoned forms, how many clicks each save takes, and what nobody ever clicks. It never records sessions or
collects what users type or see, and it runs on your own server.

[Português](README.pt-BR.md)

- **An overview that explains:** this period against the one before, and a list of what deserves a look —
  a screen that got worse, a new failure, a laborious action, a button used a lot and far away — each linking to the details.
- **A frustration level per screen**, 0 to 100 (the higher, the worse), so you know where to look first.
- **Where it irritates:** the element behind each rage click, and which request failed after which click.
- **Failures a developer can fix:** grouped by message, with the code stack, browsers, versions, kind of screen, what
  was clicked right before and the steps of the last sessions up to it — copied as Markdown for an issue.
- **Effort per action:** "creating an order takes 12 clicks and 25 s" (median and p90).
- **Journeys:** how many clicks and screens it takes to reach each button and action against how much it is used
  (used a lot and far away = it deserves a better place), actions that tend to follow one another (bring them closer
  or merge them), where people come from and go to on each screen, and funnels you build from screens, actions and buttons.
- **Usage:** most and least used screens, and the elements nobody clicks.
- **People:** usage by role, account and user — ids only.
- **Heat map:** each screen looking like your app (colours, blocks and lines of text, without the words) with three
  lenses: Heat (where people click most, blue to red), Problems (where it irritates most, with why for each element
  and what to do) and Routes (where people go next, with back-and-forth pairs marked). The same map opens over your
  own app too.
- **By version:** did the last deploy make things better or worse? Screen by screen, action by action, and the
  failures only the new version has — and a Slack or Google Chat message when it got worse.
- **Each failure dated:** in which version it started and when it was last seen, so you know whether the fix worked.
- **Search and links:** one box finds screens, buttons, errors, actions and ids (`/` focuses it); every view lives in the
  address, so it can be shared and the back button works. Every table downloads as CSV.
- **For an AI:** the whole period in one document with the definitions needed to read it (copy as Markdown or
  download JSON), and an MCP server so an assistant can look things up by itself.

## Why

Session replay tools capture the screen. That is a problem when the screen holds health records, legal cases,
bank data or anything under LGPD/GDPR. Termometro keeps only the shape of the interaction:

| Sent | Never sent |
|---|---|
| the signal (rage click, dead click, error…) | what users typed or what a record shows |
| the route as a pattern (`/orders/:id`) | the real ids in the URL |
| a short selector (`button#save`) | names, e-mails |
| that someone typed in a field and whether they pressed Enter, with the field's name (its label or placeholder) | what was typed |
| the app's own words on a control ("New user") and the screen's name ("Users"), up to 40 characters | text inside tables, lists of records and fields, a record page's title, anything under `data-termometro-private` |
| the ids you choose to give (account, user, role) | recordings, screenshots |
| optionally, the user's name (`identity.name`), kept apart and never in what an AI reads; `"people_names": false` on the project drops it | |
| browser and system family (`Chrome 130 · macOS`), kind of screen (phone, tablet, desktop) | exact versions, IP |
| once per screen and window size (wide or narrow): the box of each visible control and field (fields outside tables and lists, named as above) and of the page's regions (main, nav, header, forms, dialogs, the title) in whole pixels, the window's and page's size, and how it looks: colours, corner radius and font size of those controls, the blocks that have a background or border, and where each line of text sits with its colour (scrolled-out parts cut off); what a click opens (a dialog, a menu) is added the same way — for the screen map | what is inside the boxes: no text beyond the labels above, no words of the lines of text, no field values, nothing inside what the app marks private, no screenshots |
| where an error happened in your code (`loadRows @ /assets/index.js:1:4567`) | the page's query string or data |

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

Then open http://localhost:8080 (password `try`). For a real project, make a key with
`docker run --rm ghcr.io/arianekevin/termometro python termometro.py new-key`, and list your app's address
(e.g. `http://localhost:5173` while developing) in the project's `origins`: events from anywhere else are refused.

### Configuration

| Variable | |
|---|---|
| `TERMOMETRO_PROJECTS` | JSON list of projects: `name`, `key`, `origins` (where the collector may send from; empty = any) and `url` (your app, for the heat map). Or `TERMOMETRO_CONFIG` with a file holding the same JSON. |
| `TERMOMETRO_PASSWORD` | a single password for the dashboard |
| `TERMOMETRO_GOOGLE_CLIENT_ID`, `TERMOMETRO_GOOGLE_CLIENT_SECRET` | sign in with Google instead of (or besides) the password |
| `TERMOMETRO_ALLOWED_EMAILS`, `TERMOMETRO_ALLOWED_DOMAINS` | who may sign in with Google, comma separated |
| `TERMOMETRO_PUBLIC_URL` | where the server is reached, e.g. `https://termometro.example.com` (needed for Google) |
| `TERMOMETRO_RETENTION_DAYS` | how long events with user ids are kept (default 90); after that they become id-less daily totals |
| `TERMOMETRO_WEBHOOK_URL` | a Slack or Google Chat incoming webhook; a project can have its own `webhook` in `TERMOMETRO_PROJECTS` |
| `TERMOMETRO_LANGUAGE` | language of the webhook messages: `en` (default) or `pt-BR` |
| `TERMOMETRO_API_TOKENS` | comma-separated tokens that read everything with `Authorization: Bearer <token>`, for the MCP server or your scripts; `python termometro.py new-token` makes one |
| `TERMOMETRO_NO_AUTH=1` | no sign-in, for a dashboard already behind your own VPN or proxy auth |

At least one way in — Google or a password — is required unless `TERMOMETRO_NO_AUTH=1`.

**Warnings after a deploy:** with a webhook, the server checks every hour whether the latest version (the one that
started sending last) is worse than the one before, and posts once about each of these:

- a screen whose frustration went up by 15 or more, with at least 30 visits in each version;
- a screen error or server error the previous version never had, that already happened 5 times.

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
  // slowMs: 3000,                                   // a request slower than this is a "slow" signal; 0 turns it off
})

// Vue Router — one row per screen, not per id
router.afterEach((to, _from, failure) => { if (!failure) termometro.page(to.matched[to.matched.length - 1]?.path ?? to.path) })
app.config.errorHandler = (err) => { termometro.error(err); console.error(err) }
```

Requests that are not the user's experience can be declared with `requests`. Each item is `"METHOD /path"` or `"/path"`;
the path is matched by prefix after ids become `:id` (an item may use `:id` too), the method ignores case, the host never matters.

```ts
start({
  // ...
  requests: {
    ignore: ['POST /api/analytics'],              // never counted (`/cdn-cgi/` is always ignored)
    background: ['GET /api/notifications'],       // polling: never slow or an action; one failure per outage
    notActions: ['PUT /api/tickets/:id/presence'] // heartbeats: not an action, and they do not reset the click count
  }
})
```

Without a bundler:

```html
<script src="https://termometro.example.com/termometro.js" data-key="tk_REPLACE" async></script>
<script>
  // after sign-in, if you want people in the dashboard
  window.termometro?.identify({ account: 'acme', user: '42', role: 'admin' })
</script>
```

## Let an AI analyse it

**Paste:** on the Overview, *Copy analysis (Markdown)* puts the whole period — numbers, failures with stack and
steps, journeys, effort, definitions — on the clipboard. Paste it into any assistant and ask for the problems and
the improvements. The same document is at `GET /api/report?project=…&days=…` (JSON, or `&format=md`).

**MCP:** for an assistant that looks things up by itself (Claude Code, Claude Desktop, Cursor…), give the server an
API token and run the MCP server, a single file with no dependencies that your Termometro serves:

```bash
docker compose run --rm termometro python termometro.py new-token   # add it to TERMOMETRO_API_TOKENS
curl -O https://termometro.example.com/termometro_mcp.py
claude mcp add termometro -e TERMOMETRO_URL=https://termometro.example.com -e TERMOMETRO_TOKEN=tt_… \
  -e TERMOMETRO_PROJECT=my-app -- python3 termometro_mcp.py
```

Tools: `report` (start there), `overview`, `search`, `frustration`, `failures`, `failure`, `session`, `journeys`,
`funnel`, `usage`, `effort`, `people`, `compare_versions` and `list_projects`. The token reads every project of the
instance; keep it like a password.

## The dashboard, tab by tab

At the top: the period (1, 7, 30 or 90 days), the account, **Filters** (version, role, feature)
with each filter in use as a chip, **Marks** and, under ⋯, the appearance (theme, text size, palette, colour-blind
mode, language). Everything you pick lives in the address. The **Tour** button walks through the open screen point by
point: what you can do there, a tip and a day-to-day example. The tabs come in groups:

**Summary**
- **Overview:** the period's verdict, the numbers against the previous period, the **To do** list ranked by impact
  (how many people and sessions each item reaches), the latest version's card and what you are following.

**Problems**
- **Frustration:** each screen's level, by kind of signal, and where it irritates inside it.
- **Failures:** errors grouped by message, with the stack, browser, the version where it started, who was hit and the
  steps up to it; copied as Markdown for an issue.
- **Actions:** what each save costs (clicks and time, median and p90).
- **Versions:** one version against another, screen by screen, and the failures only the new one has.

**Usage**
- **Usage:** the most and least used screens and elements, and what nobody clicks.
- **Journeys:** distance to each button and action against its use, actions that go together, where people come from
  and go to, and funnels.
- **Map:** the heat map of the chosen screen, on desktop and phone.
  - **Heat:** each element's spot goes from blue to red with its clicks; only the five hottest carry the number.
  - **Problems:** the same heat for the share of clicks that irritate (half or more is the deepest red). Beside it,
    why each element irritates, with counts: clicked again while it was loading (with the slow request and how long
    it took), nothing changed on screen, an error (which one), not clickable, nearly hit. And what to do.
  - **Routes:** the most common next step after each element, as arrows; click an element for everything before and
    after it.
  - What a click opens (a dialog, a menu) is part of the drawing. **Open with the heat** and **Open with the routes**
    take the same map over the real app, which stays clickable.
- **Product:** use by area of the app, what is little used and what is new.
- **Features:** the features you watch (screens, buttons and actions you group under a name, in Settings): use,
  frustration and who uses them. Picking a feature in Filters cuts the whole dashboard to it.

**People**
- **People:** use by role and by user (ids, and the name if you send it).
- **Accounts:** each account with people per day, feature use, frustration and failures, and a warning when an
  account's use drops (60% or more, out of its normal). "Worst first" sorts by what needs attention most.

**Settings**
- **Dictionary:** the name people use for each screen, button, action, account and area. The whole dashboard then
  speaks that name, with the technical one below.

## How frustration is measured

Each signal weighs points: rage click 3, dead click 2, screen error 5, server error 5, refused request 2,
abandoned form 2, quick back 1, slow response 1 (a request that took 3 s or more while the page was in front of the
user, counted once per endpoint per visit). A screen's frustration is its points divided by its visits, times 20, from 0 to 100: the higher, the worse.
Up to 19 is low, 20–49 medium, 50+ high. (The API calls it `score`.)

An **action** is a write your backend accepted (POST, PUT, PATCH, DELETE answered 2xx/3xx), with the clicks and
time since the previous one; two idle minutes start the count again, and a write nobody clicked for is ignored.

## Marks

After a redesign, a version or a big fix, save a **mark** (Marks, at the top): a name and a date — today or any
day before. The dashboard, the alerts, the report and "new failure" then count only what came after the mark in
use; pick another one, or the whole period, at any time. Nothing is deleted, and old data still leaves with the
retention. (`all=1` on any read still shows everything.)

## Follow

Decided to fix something on Início's to-do list? Click **Follow** on its row. Today's value becomes the baseline —
the screen's frustration, failures per 100 sessions, the action's clicks per use or the account's people a day —
and the **Following** card measures the same number on what came since, with the filters in use: Improved, Same
(within 5 frustration points, or 20%) or Worse, "since dd/mm (version x)". Only keys are kept, never people
(`GET/POST/DELETE /api/follow`).

## Known limits

- A dead click is "nothing in the page changed within 1 s". On a screen that updates by itself (toasts, clocks,
  live feeds) dead clicks are undercounted.
- Selectors are short (the element and up to two ancestors). Identical elements, like table rows, add up under
  one selector; the heat map shows `×N` when that happens.
- An automatic write right after a click (e.g. "mark as read" on open) takes that click as its effort.
  List such writes in `requests.notActions` and they stop counting.
- Only a person's clicks count (mouse, touch, Enter or Space on a control): a click the app fires by code
  (`el.click()`, `dispatchEvent`) is not usage, effort, a dead click or a rage click.
- Stacks come from the built code: minified names and positions. Look them up in your source maps.
- Collectors before 0.2.1 send no time per event, stack or kind of screen: their trails keep the order but not the gaps.

## Develop

```bash
python3 -m unittest discover server/tests      # server
cd collector && npm install && npm test        # collector
cd collector && npm run build                  # also copies termometro.js into server/static
cd e2e && npm ci && npx playwright install chromium && npm test   # the panel in a browser (seeds its own data)
TERMOMETRO_PASSWORD=dev TERMOMETRO_PROJECTS='[{"name":"dev","key":"tk_dev","origins":[]}]' python3 server/termometro.py
docker build -t termometro .                   # the image, from source
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[AGPL-3.0](LICENSE). You can use, change and host Termometro freely; if you offer a changed version to others
as a service, you share those changes under the same license.
