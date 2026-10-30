# Live demo reliability audit — October 30, 2026

The agent runs on the Pi. Meta inference requires internet; installed apps keep
running locally. The optional Mac helper is required only for Mac actions. These
checks used typed requests through the authenticated Pi tunnel, not microphone
input or a person holding the controls.

## Changes installed

- The shared work budget is 32 model calls per request, previously 18. Specialists
  leave capacity for the parent to verify, activate and finish. A specialist that
  uses its five calls returns partial findings and candidate IDs instead of losing
  the handoff. Every turn receives its remaining budget. Exhaustion reports
  incomplete work and distinguishes acknowledged app activation from full success.
- Transient inference transport failures and HTTP 429/502/503/504 get at most two
  cancellable retries, inside the same call/spending budgets. Each retry reserves
  its own cost; unknown-cost holds remain. Authentication failures are not retried.
  Dispatched computer actions are never automatically replayed.
- Tunnel registration retries after 2, 4, 8, 15, then 30 seconds instead of waiting
  30 seconds after every early failure. Failed registration clears stale success
  status. Website GETs can refresh discovery and retry once against a changed,
  identity-verified tunnel. Mutating commands are not replayed.
- Connect warns about zero/muted Pi audio and browser/Mac sessions with less than
  30 minutes remaining. No volume setting or session expiry is silently changed.
- `python -m modulate.demo_preflight` provides a read-only telemetry check without
  model calls. Add `--mac` when demonstrating computer controls; a standalone demo
  does not require Mac pairing. `--state-file PATH` checks state retrieved through
  an authenticated tunnel. It reports faults, busy state, spending headroom,
  silent/unavailable speech, wake readiness and expiring sessions.

## Different limits

The historical 1,000,000-character allowance is the cumulative local ElevenLabs
speech ledger. Current Meta MMS speech runs on the Pi and does not use that ledger.
It never changed the agent's work budget. The separate $50 cumulative model
ceiling, unknown-cost holds, bounded generated code, per-response speech bounds,
physical confirmation and eight-hour native sessions remain.

## Measured live checks

| Check | Observed result |
| --- | --- |
| Agent update/restart | Pi reconnected; current app and Mac pairing preserved; 142 focused tests passed on Pi |
| Fresh game generation | Demo Circuit verified and activated in 36.3 s, 8 model calls; selected IMU tilt steering from current hardware |
| Follow-up refinement | Smoother steering and larger score activated in 21.2 s, 6 calls |
| Concurrent submission | Second request rejected while first request ran |
| Cancel during inference | Cancelled in 2.6 s; one billed call, no app replacement |
| Mac and Pi readback | Mac brightness 38%, Mac volume 31%, Pi speaker 0%; 5.1 s, 3 calls |
| Mac brightness round trip | Observed 38 → 39 → 38, with final readback; 10.9 s, 6 calls |
| Rollback | Exact previous Demo Circuit revision acknowledged in 1.60 s, zero model calls |
| Restore saved app | Original Orbit Catch revision restored in 2.82 s, zero model calls |
| Local MMS | Device telemetry reported `meta_mms/paplay`, delivered, no error, and return to wake listening; speaker remained at its existing 0% |
| Initial tunnel rotation | New origin registered automatically after 65.3 s; the same browser session worked through Vercel without re-pairing |

A second rotation recovered website access at 97.49 s from polling start, with
last success at 24.11 s and first failure at 26.28 s. It preserved the same session,
but did not demonstrate a shorter outage. Temporary-tunnel DNS and registry
availability remain dependencies.

The 65-second trial exposed the registration backoff and motivated the tunnel
changes above. Final results and exact revisions are in
[evidence/demo-reliability.json](evidence/demo-reliability.json).

## Before recording

Run `.venv/bin/python -m modulate.demo_preflight --mac` on the Pi. Check Connect's
warnings and confirm the Mac session extends beyond the recording. A fresh native
pairing requires the physical button; a browser confirmation cannot replace it.
The audited speaker was at 0%, so set an audible volume when ready to record.

Try one short spoken request in the actual room and test the physical controls.
The remote audit cannot verify wake accuracy in room noise, audibility, optical
screen output, cabling during movement, or feel of steering. Internet/provider
outages and temporary-tunnel DNS propagation remain external dependencies. Keep
Orbit Catch available in App library as an honestly labeled saved-app fallback;
restoring it does not require another model call.

## Blob quota migration completed

After the user reported paused Vercel Blob access and authorized Wrangler,
deployed the address registry to Cloudflare Workers Free with a SQLite Durable
Object. Vercel still hosts the website/provider gateway; the Pi owns the agent.
Cloudflare stores only a tunnel origin/timestamp and uses a derived credential
that cannot authenticate to the Pi. Removed the Blob dependency and fallback.

A deliberate tunnel restart automatically registered the replacement after
64.1 seconds. Website polling recovered after 58.93 seconds from its later watch
start, retaining the same browser session and current Demo Circuit revision.
This verifies automatic recovery, not uninterrupted service. No model call was
needed. At the migration check the Mac session was expired; it needs physical
confirmation before native computer actions. Physical voice/control checks were
not repeated.

## Reconnect follow-up

Continued the interrupted audit after Cloudflare migration. Fixed a preview
error that could persist after reconnection when the saved app revision did not
change. The connection transition now permits a new preview request.
Command network failures, gateway failures and timeouts now warn that the action
may already have run and direct the user to inspect activity/state before
resending. No automatic command replay was added. Already-cancelled transport
requests do not fetch or submit commands.

Validation: 45 API tests, 39 UI/transport tests and production build passed.
The reconnect preview test retains the exact app revision; transport tests
verify no duplicate dispatch for network/gateway failures and timeout.

Cancellation while loading session credentials is also checked before command
dispatch (175e559). The test verifies that only the session read is sent.
