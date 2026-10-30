# Muse speaker connector

Modulate exposes a private custom connector for Meta Muse, rather than a public
connector-directory listing. It needs the Pi online and the existing website
provider gateway; it does not need a Mac companion.

## Setup

1. Link a browser to [Modulate Connect](https://modulate-connect.vercel.app/connect).
2. Open Device → Connect Muse. Speaker access must already be enabled.
3. Ask Muse to create a custom connector using the
   [OpenAPI description](https://modulate-connect.vercel.app/api/modulate-muse?action=schema).
4. Enter the generated speaker token only in Muse's secure credential form.
   Never paste it in chat or put it in a URL. Keep action approvals enabled.
5. Ask Muse to “raise speaker volume to 80%”. Successful responses contain
   verified device readback, not a model's prediction of the result.

The credential authorizes two operations: read the Pi speaker volume/mute state,
and set an absolute integer level from 0 to 100. It cannot play audio, unmute,
change apps, use the microphone/camera, read email, or control the Mac.

## Access and request path

Muse → fixed HTTPS website speaker endpoint → identity-proven current Pi tunnel
→ authenticated Pi gateway → speaker command/acknowledgement → selected Pulse
sink read/write/read → verified response. No extra Modulate model call is needed.
The optional Mac session is independent.

The opaque credential encrypts a parent browser token under a derived server-only
key. Its audience is the fixed speaker endpoint; generic dashboard endpoints do
not accept it. It expires with that parent browser session, at most eight hours.
Disconnect the parent browser or disable speaker access to block it immediately.
After parent expiry/revocation, create a new credential and update Muse's secure
store. Hiding/copying a token does not revoke it. There is no permanent connector
authorization or independent per-token revocation control in this prototype.

Commands are not retried automatically after an uncertain response. Read the
actual state before retrying. Revocation is rechecked before command offers and
while waiting for acknowledgement; a write already applied cannot be undone by
revocation. Global speaker access continues to govern spoken replies as well.

## Verified on October 30, 2026

Revision 717b38a was deployed to the production website and the two changed Pi
modules. A live HTTPS test confirmed 0 → 80 → 0, a separate fresh read of 80, and
401 after revoking the temporary test browser. Read latency was 0.778 seconds;
set-to-80 latency was 0.493 seconds in that single trial. Those times exclude
Muse interpretation and approval UI. No sound was played and no Mac was paired.
The Pi retained its prior empty active-app state.

Validation: 1,133 local Python tests, 13 platform skips; all 35 focused Pi checks;
52 website API checks and 41 UI checks; production Next.js build passed. Synthetic
checks cover altered/expired credentials, fixed operation scope, parent
revocation, queued access withdrawal, malformed levels, unverified readback and
no blind write replay. They are separate from the live volume trial.

Muse has prepared the custom connector and the user authorized secure credential
storage and an 80% test. Completion of the Muse-side flow is recorded separately
once independently verified.

## Sources and reused components

[Meta's custom connector help](https://www.meta.com/en-gb/help/superintelligence/1687253048996149/)
describes creating custom connectors through Muse and using its secure credential
store. The connector uses the project's existing authenticated discovery,
speaker acknowledgement and PulseAudio adapters; no Instacart code is reused.
Node's built-in AES-GCM/HMAC provides credential sealing. No new paid service or
account was created.
