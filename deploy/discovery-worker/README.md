# Free connection registry

Replaces Vercel Blob for the single current Pi tunnel address. Uses a SQLite
Durable Object on Cloudflare Workers Free; never select the paid Workers plan.
The website, provider gateway, browser sessions and Pi agent stay where they are.

1. Sign in to the intended Cloudflare account and deploy this Worker with Wrangler.
2. Set `REGISTRY_SECRET` via secret stdin to HMAC-SHA256 of the private
   `MODULATE_REMOTE_SECRET` over `modulate-discovery-registry-v1`, hex encoded. Do not put it in this directory, Git, logs or browser JS.
3. Configure Vercel `MODULATE_DISCOVERY_REGISTRY_URL` to the deployed HTTPS
   `workers.dev` origin and keep `MODULATE_DEVICE_DISCOVERY=1`; redeploy the site.
4. The Pi continues signing registrations to its existing Vercel URL. Registration
   proves the Pi's identity before storing its new origin. Verify a fresh rotation
   and an existing browser session after deployment.

The discovery object stores only hostname and timestamp. HMAC/short timestamp window authenticates
writes; reads require the derived registry credential. This credential cannot authenticate
to the Pi gateway. The gateway independently
proves the tunnel before sending credentials. Expiring sessions remain on the Pi.
The app has no Blob dependency or fallback. Still subject
to Workers Free limits; monitor request counts and use caching rather than removing
caps. Cloudflare daily limits reset at midnight UTC.

Deployment: `https://modulate-discovery.divyesh-thirukonda.workers.dev`.
The account uses Workers Free. New workers.dev subdomains can need HTTPS
provisioning time; require a successful authenticated registration and lookup
before treating deployment as healthy.


## Public demo allowance

A separate SQLite `DemoBudget` object stores anonymous HMAC identifiers, counters,
request IDs and microdollar accounting. It stores no prompts, generated code,
raw IP addresses or provider keys. `/demo-budget/*` is private and requires the
existing derived registry credential. No public browser receives this credential.
The v2 migration adds this object without changing the discovery object's data.

Enable only after reserving the funds from the **current Pi ledger**, never the
halted Mac backup. On the Pi, with its existing Python environment and checkout:

```sh
.venv/bin/python scripts/allocate_demo_budget.py --ledger /home/pi/modulate-product/brain/budget.json
```

This idempotently reserves $5 within the existing $50 ceiling, preserving all
previous charges and holds. It prints a reservation ID and amount, not secrets.
Then POST those exact `reservation` and `amount` fields to
`/demo-budget/allocate` using server-side Bearer registry authentication. The
allocation cannot subsequently be replaced or increased. Keep the Pi reservation
held while this public pool exists; do not settle or refund it independently.
Repeated allocation with the same values is idempotent.

The server calls `start`, `reserve`, `settle`, and `finish` for a generation.
A call holds 1,345,536 microdollars (full 1,048,576 input context at $1.25/M plus
8,192 output at $4.25/M). Validated provider usage refunds the difference; missing
usage or transport failures retain the hold. An overage halts the pool. Global
reservations are transactional, including concurrent server instances. Each
visitor gets up to six generations per UTC day, each network 24, with ten-second
spacing and one active request per session. Unknown-cost holds need operator
review; timeouts never refund them automatically.

Runtime model/price documentation verified November 3, 2026:
[Meta chat completions](https://dev.meta.ai/docs/protocols/chat-completions),
[Meta pricing](https://dev.meta.ai/docs/pricing-rate-limits).
