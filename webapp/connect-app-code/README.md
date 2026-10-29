# Connect app code

The complete **Modulate connection webapp** at
[modulate-connect.vercel.app/connect](https://modulate-connect.vercel.app/connect).
This repository is its production source; it no longer deploys through the portfolio. This folder contains
only the connection dashboard, its server endpoints, tests and build setup.

The 11 application/test files listed in [source-manifest.json](source-manifest.json)
were extracted from portfolio commit
`1c190a4b4c2bad49eed09ee4bee5071c62a736da`. The standalone entry point, HTML,
minimal package, Vercel configuration and verification script were added for
the original export. `source_sha256` preserves that baseline; `sha256` verifies
the current standalone code after migration.

## Read the implementation

| Code | Responsibility |
| --- | --- |
| [src/modulate/Connect.js](src/modulate/Connect.js) | Browser linking, permissions, Studio, prompt editing, agent progress, code/checks and device controls |
| [src/modulate/Library.js](src/modulate/Library.js) | Saved apps, favorites, Trash and restore |
| [src/modulate/api.js](src/modulate/api.js) | Same-origin requests and CSRF handling |
| [src/modulate/connect.css](src/modulate/connect.css) | Responsive dashboard styling |
| [api/modulate.js](api/modulate.js) | Revocable browser cookies, origin checks and fixed companion command proxy |
| [api/modulate-provider.js](api/modulate-provider.js) | Server-only authenticated Meta/ElevenLabs gateway |
| [server/modulate-http.cjs](server/modulate-http.cjs) | Bounded parsing/reads, authentication helpers and private errors |

The native Mac/Pi implementation remains in [modulate](../../modulate):
[remote access and permissions](../../modulate/remote_access.py),
[local Studio](../../modulate/studio.py) and
[device runtime](../../modulate/device.py).
See [connection architecture and setup](../../context/connect.md) for the full
browser → Vercel → companion → Pi path.

## Run and check

Use Node.js 22 or newer, then run inside this folder:

```sh
npm ci
npm run check
npm start
```

After `npm start`, visit the UI-only preview at `http://localhost:3000/connect`. It does
not run the Vercel functions, make a synthetic pairing, or bypass HTTPS cookie
requirements. Full linking needs an HTTPS deployment of the included functions
and the configured running companion. No live device is needed for the tests.

To verify the preserved baseline against a portfolio checkout at the recorded
source commit (not the restored portfolio main branch):

```sh
npm run verify:source -- /path/to/portfolio
```

## Hosting and secrets

Build with `npm run build`. Vercel project **modulate-connect** tracks this
repository’s `main` branch with root `webapp/connect-app-code` and Node.js 22.
`vercel.json` retains both API routes and the SPA fallback, with security headers
applying to all pages. Both `/` and `/connect` open the same dashboard.

Configure these only in the server environment; no secret values are included:

- `MODULATE_COMPANION_URL`: fixed HTTPS companion gateway origin.
- `MODULATE_PUBLIC_ORIGIN`: exact HTTPS web origin (`https://modulate-connect.vercel.app` in production).
- `MODULATE_REMOTE_SECRET`: shared Vercel-to-companion gateway credential.
- `MODULATE_CLOUD_KEY`: companion-to-provider-gateway credential.
- `MODULATE_META_API_KEY` and `MODULATE_ELEVENLABS_API_KEY`: provider credentials.

Never prefix credentials with `REACT_APP_`, `VITE_` or `NEXT_PUBLIC_`. The Mac
companion still enforces permissions, pairing expiry and durable spending
limits. A browser dashboard cannot itself grant native computer access.

React, React DOM, Create React App and Testing Library are reused dependencies;
Lucide supplies icons. The Modulate-specific UI and gateway code were developed
during this hackathon. No portfolio pages, personal assets, private runtime
state, credentials or unrelated integrations are included.

The footer's [Meta symbol](src/modulate/assets/meta.svg) is a pre-existing asset
from [Simple Icons](https://github.com/simple-icons/simple-icons/blob/develop/icons/meta.svg),
retrieved October 29, 2026 under its
[CC0 distribution](https://github.com/simple-icons/simple-icons/blob/develop/LICENSE.md).
Meta owns the brand and trademark; see its
[brand resources](https://www.meta.com/brand/resources/meta/company-brand/).
