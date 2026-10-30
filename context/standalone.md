# Standalone Pi AI — October 29, 2026

The Pi owns the agent, app library, conversation state and speaker coordinator.
Wi-Fi connects it to the existing Modulate Vercel provider gateway for live Meta
and ElevenLabs requests. A Mac is no longer required for normal device AI.
Inference still needs internet; installed games run in the isolated local runtime.

## Installed layout

- `/home/pi/modulate-product/brain`: private agent state, both cumulative ledgers,
  provider gateway configuration and local TLS enrollment; owned by `pi`.
- `/home/pi/modulate-product/state`: retained physical runtime and device state.
- `modulate-agent.service`: starts `modulate.studio --standalone` at boot.
  Studio is loopback port 8787, pinned device HTTPS is loopback 8788, and the
  authenticated remote gateway is loopback 8789. LAN listener overrides are
  rejected for that controller transport in standalone mode. The optional Mac
  helper has a separate pinned LAN TLS listener on port 8790.
- The `standalone.conf` drop-in for `modulate-device.service` selects the local
  agent enrollment and disables legacy Mac enrollment bootstrap. It Wants the
  agent, so a failing AI service does not stop an installed local game.
- `modulate-connect.service`: optional cloudflared process on the Pi for the
  website's existing authenticated dashboard gateway. Device AI calls the fixed
  provider URL directly and does not depend on this tunnel.

These service files assume the existing provisioned Pi environment and paths.
They are not a fresh-image installer. Preserve the existing audio session,
Whisper model, hardware dependencies and fixed isolated runtime.

## Accounting and migration

The Mac agent was stopped before moving ownership. Both private ledgers were
copied without resets, including pending/unknown reservations. Initial transferred
snapshot: 570 model calls / $11.120607 charged or held; speech 4,829 reserved
characters / 4,611 settled / 69 requests / 5 uncertain requests. The old Mac model
ledger is halted and marked migrated; the old speech ledger is marked migrated.
Historical private backups must not become a second active spending owner.

Standalone startup refuses absent, public-readable, symlinked, malformed or
migrated ledgers. There is no fallback to fresh ledgers or a raw provider key.
Private gateway credentials were encrypted to the Pi's independently confirmed
existing TLS certificate before transfer. No SSH key was added. Provider API
keys remain in Vercel; generated packages and browser code receive none.

The total model ceiling stays **$50**. The user explicitly approved increasing
the local speech ceiling from 5,000 to 10,000, then explicitly requested
**1,000,000 cumulative input characters** on October 30.
`MODULATE_TTS_CHARACTER_LIMIT=1000000` is loaded from the
private service env file; old reservations remain. The separately configured
provider key's 5,000-credit cap and expiry are unchanged. Characters and provider
credits are different accounting units. The local allowance is per persistent
installation ledger across all replies and restarts, not per request or API key;
it has no automatic monthly reset. Changing keys does not reset it. Individual
spoken replies retain a separate 1,200-character input bound. Never reset or raise either limit to
work around a failure.

Before another migration, stop the sole current owner, preserve both ledgers,
transfer them securely, and freeze the old copy. Do not run the legacy Mac agent
using its historical backup. Moving back requires the latest Pi ledger state and
an explicit ownership handoff.

## Verification

The live trials used the Pi agent with no paired Mac and the Mac AI process
stopped. They are separate from synthetic unit tests:

1. A typed live request returned “Modulate is running on its own.” in one Meta
   call. Device telemetry reported ElevenLabs/paplay playback without error, and
   the user confirmed **“Yes, I heard it.”**
2. A separate speaker-volume request (input mode not independently recorded) failed because the controller's
   existing speaker-volume dispatch still required a Mac pairing. The typed game
   probe initially received HTTP 400 because that request was already running;
   no game request was dispatched by that rejected submission. The volume gate
   now accepts the authenticated local Pi agent in standalone mode, retaining
   its session/sink/epoch/revision, expiry and native readback checks. The legacy
   unpaired Mac path is still rejected. Failure evidence is preserved.
3. A typed live game request generated original **Orbit Catch** code and ship/star
   sprites, inspected actual hardware, repaired a malformed package tool call,
   passed independent package/runtime guards, and activated with matching Pi
   acknowledgement in **13 Meta calls**, about **37.37 seconds** after typed submission
   (one-second completion polling; excludes voice capture/transcription). Revision:
   `491f6971e962eff1495c40374430d8d27004fdba49742c49e31787cfb10046b8`.
   The Pi reported the game display. After reboot the user confirmed
   **“Yes, the game and controls work.”** Cumulative model snapshot: **592 calls / $11.363438**.

4. A full Pi reboot changed the boot identity, automatically restarted all three
   services, retained the exact game revision and returned to wake listening.
   Model calls remained 592: no inference was used to restore the app.
5. A typed speaker readback completed in three Meta calls after reboot. The
   authenticated device acknowledged the actual level at 30%, unchanged, and
   ElevenLabs playback completed. Cumulative snapshot: **595 calls / $11.390532**;
   speech **5,011 reserved / 4,793 settled / 73 requests / 5 uncertain**.
6. The user reported an audible answer to the suggested spoken check, “Hey Meta,
   what game is running?” The final collected trace had no new matching request,
   so this is recorded as user confirmation without an attributed model trace.

See [sanitized machine evidence and confirmation boundaries](evidence/standalone-runtime.json).
The production dashboard was deployed from `995c160`; its session endpoint
reported an online Linux agent and the rendered setup page said “Just Modulate
and Wi-Fi.” No fresh browser or native Mac permission was granted during testing.

Automated validation: 1,056 host tests passed with 13 platform skips; 196 staged
Pi checks passed, followed by 13 final standalone/speaker checks. The website
source verification, API tests, 29 UI tests and production build passed. These
checks do not establish wake/noise reliability or provider uptime.

## Website and remaining boundaries

Hold small screen A for one second, release, then press A to show the one-use
browser code. Browser linking is optional for speaking to the device. Linking a
browser grants no native computer access. The optional native Mac helper is now
connected to the Pi agent. Physical comparison-code approval and a live typed
brightness request were verified; existing desktop/camera/audio adapters are
connected but have not been revalidated across this new link. See
[optional Mac setup and transport boundaries](optional-mac.md).

The optional website transport still uses a development Quick Tunnel. Its
supervisor registers hostname changes with the fixed website using a scoped HMAC
and an endpoint identity challenge. Private Vercel Blob stores only the current
origin and timestamp; no administrator token is installed on the Pi. Deployment
requires the discovery flag and Blob connection. The existing fixed-URL path is
preserved for legacy installations. Direct Pi AI requests do not use this tunnel.

Sources checked during implementation: [Meta Chat Completions](https://dev.meta.ai/docs/protocols/chat-completions),
[ElevenLabs streaming TTS](https://elevenlabs.io/docs/api-reference/text-to-speech/stream),
[Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).
Existing dependencies are reused; cloudflared 2026.10.6 Linux ARM64 was downloaded
from Cloudflare's official release and its published SHA256 verified. No new
account, hardware purchase or provider credit purchase was made.
