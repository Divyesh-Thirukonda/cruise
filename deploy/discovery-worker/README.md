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
   and an existing browser session before removing the old Blob configuration.

Only hostname and timestamp are stored. HMAC/short timestamp window authenticates
writes; reads require the derived registry credential. This credential cannot authenticate
to the Pi gateway. The gateway independently
proves the tunnel before sending credentials. Expiring sessions remain on the Pi.
No requests should go to Blob when the registry URL is configured. Still subject
to Workers Free limits; monitor request counts and use caching rather than removing
caps. Cloudflare daily limits reset at midnight UTC.
