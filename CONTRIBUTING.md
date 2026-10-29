# Contributing

Thanks for helping. A few rules keep Termometro what it is:

1. **Nothing that identifies a person leaves the browser** unless the site hands it over explicitly through
   `identity`. No screen text, no field values, no recordings. A change that weakens this will not be merged.
2. **The server stays on the Python standard library** and one SQLite file, so anyone can run it anywhere.
3. **The collector has no runtime dependencies** and stays small (check the gzip size in your PR).
4. **Every behaviour ships with a test** that fails without it — `server/tests` for the server, `collector/test`
   for the collector.
5. Code, comments and commit messages in English. The dashboard and the map speak English and Portuguese; add a
   language by extending the dictionaries at the top of `server/static/index.html` and `server/static/map.js`.

## Running everything

```bash
python3 -m unittest discover server/tests
cd collector && npm install && npm test && npm run typecheck && npm run build
```

## Reporting a security issue

Please do not open a public issue. Write to the maintainer through GitHub's private vulnerability reporting
on this repository.
