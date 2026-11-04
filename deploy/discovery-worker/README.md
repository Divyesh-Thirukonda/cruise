# Cloudflare discovery and independent demo budget

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

The public demo has its own **$25 total budget**, explicitly authorized by the
user November 3, 2026. It is independent of the physical Pi and its $50 ledger.
Initialize the cloud ledger once by POSTing `{"budgetId":"<fresh UUID hex>",
"amount":25000000}` to `/demo-budget/initialize` with server-side Bearer registry
authentication. Persist the initialization ID for retries. Identical retries are
idempotent; changing the ID/amount or exceeding $25 is rejected. No Pi connection,
ledger reservation, tunnel or native service is involved. Existing accrued usage
and unknown-cost holds are never reset by initialization.

The server calls `start`, `reserve`, `settle`, and `finish` for a generation.
A call holds 1,345,536 microdollars (full 1,048,576 input context at $1.25/M plus
8,192 output at $4.25/M). Validated provider usage refunds the difference; missing
usage or transport failures retain the hold. An overage halts the pool. Global
reservations are transactional, including concurrent server instances. Each
visitor gets up to 15 requests per UTC day, each network 60, with five-second
spacing and one active request per session (raised November 3 so one visitor can
follow all ten video scenes; the $25 total is unchanged). Unknown-cost holds need operator
review; timeouts never refund them automatically.

Runtime model/price documentation verified November 3, 2026:
[Meta chat completions](https://dev.meta.ai/docs/protocols/chat-completions),
[Meta pricing](https://dev.meta.ai/docs/pricing-rate-limits).
