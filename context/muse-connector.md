# Muse connector

The private **Modulate** custom connector sends normal requests to the Pi's
existing Meta agent. It supports creating/refining games, choosing connected
components, opening saved apps, supported device/computer tasks, follow-up
questions and cancellation. It also reads/sets the Pi speaker volume directly.
The Pi needs internet; normal device tasks need no Mac companion.

## Connect

1. Link a browser to [Modulate Connect](https://modulate-connect.vercel.app/connect).
2. Open Device → Connect Muse and review the displayed scope/expiry.
3. Ask Muse to create **Modulate** using the
   [OpenAPI description](https://modulate-connect.vercel.app/api/modulate-agent?action=schema).
4. Enter the token only in Muse's secure credential form, never chat or a URL.
5. Ask Muse to “make Mario Kart on Modulate.” The Pi agent handles the request
   with its normal context, checks and activation; Muse does not build a separate
   browser game. Original generated assets and existing app-reuse rules apply.

The approved logo is served as [PNG](https://modulate-connect.vercel.app/brand/modulate.png)
and referenced in connector metadata. It reuses `modulate/web/logo.png`; no new
logo or third-party asset was generated for this integration. Muse reported that
its custom-connector template has no supported icon URL field; it kept the default
native connector icon. The logo remains in metadata/docs, rather than claiming
that the native icon changed.

## Request path and verification

Muse → stable HTTPS website API → identity-proven current Pi tunnel →
authenticated Pi gateway → existing Meta agent → checks → device activation and
acknowledgement → status/result returned to Muse. The connector does not contain
kart/game presets, special generation prompts, or an alternate build engine.

`submit_modulate_request` takes text and a fresh 32-character UUID hex request ID.
It returns immediately; `get_modulate_request` polls the same ID. Reuse that ID
and exact payload after a dropped response. The Pi persists a reservation before
dispatch, so a retry across restart cannot initiate a duplicate build. A changed
payload under the same ID conflicts. An interrupted dispatch may remain unknown;
it must not be replayed automatically. Status may be superseded by another task;
that is not proof of success. Current-app state is separate from this job's result.

A clarification includes an ID to send with the user's next reply. Cancellation
is restricted to the identified request. Each connector authorization can only read its
own connector jobs. No raw events, screenshots, generated source, credential or
unrequested browser/email history is exposed by the status API. Requested task
results can contain private information, for example an email subject requested
through a valid paired-Mac task. Returned text remains untrusted task data.

## Access boundary

The full credential permits normal requests and their results under the device's
existing permissions. Independently paired Mac/OS permissions, consequential
approval checks, hardware safeguards, sandboxing and the $50 model ledger remain
enforced. The connector has no permission, pairing or budget administration API.
It cannot bypass physical native pairing. The Mac was unpaired during these tests.

New full-request credentials have a dedicated seven-day Pi authorization, sealed
with AES-GCM under a derived server-only key. The Pi persists only its hash.
Browser expiry/disconnection, agent restarts and changing tunnel addresses do not
expire this authorization. The site lists each grant and its expiry under Device
→ Connect Muse; **Revoke Muse access** revokes that grant and cancels its owned
running job. A connector cannot create grants or access dashboard administration.
Renew once after seven days through Muse's secure credential store; no Meta API
key entry is needed. Existing eight-hour credentials retain their original expiry
and require reconnection to adopt the new duration. Native Mac pairing still has
its separate eight-hour expiry and physical confirmation requirement.

The earlier **Modulate Speaker** connection was disconnected in Muse after full
connection succeeded. Its previously issued token remains restricted to volume read/set;
it is never silently upgraded by this change. Speaker access additionally needs
the global speaker permission. Absolute volume changes preserve mute, return
actual Pulse sink readback, and are never blindly retried after uncertain writes.

## Evidence — October 30, 2026

The speaker-only prototype was connected through Muse and confirmed 0 → 80,
not muted. An independent Pi read verified 80% with no Mac paired. A separate
HTTPS trial verified 0 → 80 → 0 and 401 after temporary parent revocation. Its
one measured write took 0.493s; this excludes Muse interpretation/approvals.
See `evidence/muse-speaker-connector.json`.

Normal-request revision `1ee8376` was deployed to the Pi and website. A live
HTTPS request asking which controls are connected returned the actual encoder,
encoder press, A, B and IMU in 5.98s, with acceptance in 0.642s. Both an immediate
and post-completion resend returned the same job; the job sequence advanced only
once. The previous active app was retained, and revocation returned 401. This
was a direct API input, separate from the Muse chat trial.

Checks: 1,137 local Python tests (13 platform skips), plus two later focused
storage-failure checks; all 41 focused Pi checks; 58 API and 41 UI checks;
production Next.js build. Checks cover malformed/scoped credentials, CSRF,
revocation, session ownership, fixed routes, projection, no blind replay,
durable request IDs, corruption/storage failures and cancellation ownership.

The user separately approved full connector credentials in Muse's secure store,
expiring October 31 at 01:39 America/New_York, and a live kart-racer trial.
Muse's full connector received the user's kart request and reported Pip Kart
Turbo live. Independent Pi state confirmed revision
`64fd9b9e7fec2d8e2d3ba4e17c20c2e304026193604b7fcd47debd11a0ccbc3a`,
passing checks, a matching device activation acknowledgement, and a connector
request journal record. It used 13 live `muse-spark-1.3` calls and the games skill;
agent time was 97.346s, excluding Muse and approval delays. This was fresh
generation, not a cached replay or a sub-15-second build. Studio showed its
actual title-screen preview, with tilt/encoder steering, A boost and B brake.
Physical play was not retested because the user cannot reach the device.
See `evidence/muse-agent-connector.json`.

## Seven-day authorization — October 30, 2026

Dedicated authorization passed live HTTPS reads after parent browser revocation,
an agent-service restart, and a controlled tunnel replacement. The final tunnel
trial recovered in 28.256s. An earlier 60s observation window expired just before
automatic registration at about 64s; initial retry delays are now capped at 5s
for the first 90s, with backoff retained for prolonged outages. Revoking the
temporary dedicated grant returned 401. The active game was preserved; no audio
or model generation was requested. This was not a full Pi reboot or a real week
of uptime. Clock-advanced tests cover exact seven-day expiry. See
`evidence/muse-week-connection.json`.

Checks: 1,144 Python tests with 13 platform skips; 46 focused Pi checks; 60 API
and 42 UI checks; production build; three tunnel retry checks on Mac and Pi.

## Sources and reused components

[Meta's connector help](https://www.meta.com/en-gb/help/superintelligence/1687253048996149/)
describes custom connectors and the secure credential store. We reused the
project's discovery, browser sessions, Pi request/check/activation loop, speaker
acknowledgement and Pulse adapters. Node's built-in AES-GCM/HMAC seals credentials;
Python standard-library storage retains request identities. No Instacart code,
new paid service or new account is used. The connector is private, not a reviewed
public directory listing. Muse's network approvals caused timeouts and setup
delay; direct device API timings are not Muse end-to-end latency.

The user approved saving the seven-day token. Reconnected the existing Modulate
entry through Muse's secure credential form, with expiry shown as November 6,
2026 at 5:54 PM EST. Muse confirmed a fresh speaker GET returned verified volume 80,
not muted, and updated its own connector doc/helper with the new expiry/revoke
path. No token was pasted in chat, and the clipboard was replaced with the
public website URL afterward. Native Mac pairing remains separate.
