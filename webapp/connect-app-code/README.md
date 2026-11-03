# Connect app code

The **Modulate connection webapp** at
[modulate-connect.vercel.app/connect](https://modulate-connect.vercel.app/connect).
This repository is its production source; it no longer deploys through the portfolio. This folder contains
only the connection flow and workspace, its server endpoints, tests and build
setup. It now uses **Next.js 16.4.3 and React 19.3.1**, replacing the original
Create React App shell. The guided flow is deployed and verified; see the
repository [build log](../../context/build-log.md).

The 11 application/test files listed in [source-manifest.json](source-manifest.json)
were extracted from portfolio commit
`1c190a4b4c2bad49eed09ee4bee5071c62a736da`. The original export added a standalone
React shell and build setup; the current Next.js routes and setup plugin were
authored here. `source_sha256` preserves the portfolio baseline; `sha256`
verifies the current versions of those eleven files. The manifest is provenance
for those files, not a claim that newly added files came from the portfolio.

## User flow

1. **Connect:** a brief explanation and the eight-digit code, with setup help if
   needed. No workspace sidebar or access switches appear before connection.
2. **Choose access:** review the device's current permissions. Keep them as they
   are or save only edited switches; connection itself does not reset access.
3. **Studio:** the active app and request composer. **App library**, **Device**
   and **Access** are separate destinations. **Developer tools** discloses agent
   activity and generated code/checks when needed.

Returning valid sessions open Studio. Stop/cancel controls remain available
during active work, including on setup and access screens. The access switches
apply to the whole device, and macOS still owns its native permission dialogs.

## Online demo

The homepage's **Online demo** button opens `/demo`, with Studio, App library and
Device views. Visitors attach virtual Pi components and type a request. The server
calls Meta `muse-spark-1.3` to generate original JavaScript, runs independent checks,
and sends the results back to Meta for approval or repair (at most three calls).
There are no preset apps or keyword-to-template fallback paths.

Generated apps run inside QuickJS/WASM, in a dedicated browser worker with no
host callbacks, imports, DOM, network or privileged services. The contract allows
only bounded drawing and sound commands and declarative input descriptions.
Both server and browser verify 151 frames before activation. Revision-matching
acknowledgement, cancellation and failure handling preserve the previous app.
Playing, restarting and restoring saved apps make no model calls. The generated
source, Meta response IDs, usage and check results are visible in Code & checks.

Hardware is conceptual, not electrical/firmware emulation or Arduino compatibility.
No physical device, native Mac action, camera or microphone is accessed. Prompts
and the previous app's code go to Meta; apps persist locally under
`modulate.playground.live.v2`, capped at 24 entries. Old preset storage is not
imported. Storage failures allow a clearly labeled session-only workspace.

`/api/demo` uses the existing server-only Meta key, signed HttpOnly anonymous
sessions, same-origin/CSRF checks, bounded requests and fixed provider/model IDs.
The existing Cloudflare Worker supplies a separate durable allowance with daily
visitor/network limits, per-call reservations and unknown-cost holds. **It starts
disabled.** First reserve $5 from the authoritative Pi's existing $50 ledger using
`scripts/allocate_demo_budget.py`; then configure the exact same reservation and
amount in the Worker. See `deploy/discovery-worker/README.md`. This is an allocation
inside the original ceiling, not an additional budget. Native access stays separate.

Implementation: `src/modulate/demo/`, `shared/demo-runtime.mjs`, and `server/demo-*.mjs`.
`prebuild`/`predev` bundle the pinned QuickJS browser worker; generated bundles are
ignored. Tests cover sandbox limits, malformed/missing capabilities, review/repair,
CSRF, concurrency, unknown billing, stale acknowledgements, cancellation and
persistence. Tests with fixtures do not establish live Meta inference.

## Read the implementation

| Code | Responsibility |
| --- | --- |
| [src/app/connect/\[\[...screen\]\]/page.js](src/app/connect/[[...screen]]/page.js) | Next.js workspace URLs and supported-screen routing |
| [src/modulate/EntryScreens.js](src/modulate/EntryScreens.js) | Connection landing, coding-agent setup help and post-connection access review |
| [src/modulate/Connect.js](src/modulate/Connect.js) | Session recovery, workspace navigation, Studio, separate Device/Access pages and developer views |
| [src/modulate/Library.js](src/modulate/Library.js) | Saved apps, favorites, Trash and restore |
| [src/modulate/api.js](src/modulate/api.js) | Same-origin requests and CSRF handling |
| [src/modulate/connect.css](src/modulate/connect.css) | Responsive dashboard styling |
| [api/modulate.js](api/modulate.js) | Revocable browser cookies, origin checks and fixed companion command proxy |
| [api/modulate-provider.js](api/modulate-provider.js) | Server-only authenticated Meta/ElevenLabs gateway |
| [src/app/api](src/app/api) | Next.js route handlers adapting the existing server gateways |
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
npm run dev
```

Visit `http://localhost:3000/connect`. The Next.js server runs both page and API
routes; unconfigured gateway operations fail explicitly. This does not create a
synthetic pairing or bypass secure cookies and origin checks. Full linking needs
an HTTPS deployment and the configured running companion. No live device is
needed for the automated tests. After `npm run build`, `npm start` serves the
production build; it is not the development command.

To verify the preserved baseline against a portfolio checkout at the recorded
source commit (not the restored portfolio main branch):

```sh
npm run verify:source -- /path/to/portfolio
```

## Hosting and secrets

Build with `npm run build`. Vercel project **modulate-connect** tracks this
repository’s `main` branch with root `webapp/connect-app-code` and Node.js 22.
`vercel.json` selects the Next.js framework. The App Router serves both gateway
routes and `/connect` screens; `/` redirects to `/connect`. Security headers
apply to all paths. Separate URLs cover setup, access review, Studio, library,
Device, Access, activity and code/checks.

Configure these only in the server environment; no secret values are included:

- `MODULATE_COMPANION_URL`: fixed HTTPS companion gateway origin.
- `MODULATE_PUBLIC_ORIGIN`: exact HTTPS web origin (`https://modulate-connect.vercel.app` in production).
- `MODULATE_REMOTE_SECRET`: shared Vercel-to-companion gateway credential.
- `MODULATE_CLOUD_KEY`: companion-to-provider-gateway credential.
- `MODULATE_META_API_KEY` and `MODULATE_ELEVENLABS_API_KEY`: provider credentials.

Never prefix credentials with `REACT_APP_`, `VITE_` or `NEXT_PUBLIC_`. The Mac
companion still enforces permissions, pairing expiry and durable spending
limits. A browser dashboard cannot itself grant native computer access.

## Coding-agent setup download

`/connect/setup` offers **Copy setup prompt** and an optional plugin download at
`/downloads/modulate-setup.zip`. The source is
[plugins/modulate-setup](../../plugins/modulate-setup). Unzip it, open the folder
in your coding agent, and ask it to read `skills/modulate-setup/SKILL.md` and
follow it. The Markdown skill works without a native plugin installation; the
agent needs local file and command tools to perform setup. Optionally keep it
using your agent's supported skill mechanism. The package includes a separately
documented optional Codex adapter, not a universal installer. Downloading does
not run an installer or grant device access automatically.

The skill discovers existing installations before proposing changes, preserves
private state and ledgers, and guides necessary physical/macOS steps. The public
site still reaches **one configured companion**. A new user's Mac/Pi needs its
own companion and, for remote access, a separate configured deployment.

Regenerate and verify downloads from the repository root:

```sh
python3 scripts/package_setup_plugin.py
python3 scripts/verify_setup_plugin.py
```

The deterministic archive includes only reviewed plugin files, with a checksum
and plain-text prompt alongside it. The web prompt export is generated from the
same source; no credentials or development-specific enrollment data are bundled.

Next.js, React, React DOM, Jest and Testing Library are reused dependencies;
Lucide supplies icons. The Modulate-specific UI and gateway code were developed
during this hackathon. No portfolio pages, personal assets, private runtime
state, credentials or unrelated integrations are included.

The footer's [Meta symbol](src/modulate/assets/meta.svg) is a pre-existing asset
from [Simple Icons](https://github.com/simple-icons/simple-icons/blob/develop/icons/meta.svg),
retrieved October 29, 2026 under its
[CC0 distribution](https://github.com/simple-icons/simple-icons/blob/develop/LICENSE.md).
Meta owns the brand and trademark; see its
[brand resources](https://www.meta.com/brand/resources/meta/company-brand/).
