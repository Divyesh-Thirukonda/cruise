# Optional Mac controls with a Pi-owned agent

The Pi owns AI, speech, apps and existing cost ledgers. Wi-Fi is required for
new Meta requests and ElevenLabs replies; saved games run locally. This prototype
assumes configured Wi-Fi; factory network provisioning is not implemented.

## The two connections

1. Browser: hold small A for one second, release, then follow the browser-code
guide. Enter its one-use eight-digit code at the website /connect form.
2. Mac: copy the website's Mac setup prompt into a coding agent on the computer
to control. Keep the Pi agent running; never restart the legacy Mac AI studio.
The optional helper and Pi show a matching eight-digit comparison code. Compare
both, then press small PiTFT A. Do not enter that code into the website.
3. Native access lasts up to eight hours. Temporary disconnects/restarts reconnect
within that session. Expiry or Revoke Mac pairing requires fresh confirmation.
macOS permissions still apply. Closing the browser does not revoke the Mac.

## Helper

Use this trusted checkout and its existing Mac Python environment/native dependencies.
Obtain the current Pi address and fingerprint from the physical setup display or
an existing authenticated connection. Never silently trust a changed fingerprint.

Run `.venv/bin/python -m modulate.mac_companion --pair --device ADDRESS --fingerprint IDENTITY`
and open http://127.0.0.1:8787/setup for comparison. After confirmation, the same
command without --pair reconnects owner-only state in ~/.local/share/modulate-mac.
A per-user LaunchAgent can keep it running at login. Stop that helper before
running --revoke, or revoke from the website's Device page while it is running.
The helper has no model keys, app generator or AI/speech accounting ledger.

## Brightness path

Pi microphone → local transcription → Pi agent → Meta reads current encoder and
paired Mac capabilities → generated bounded brightness mapping → fixed checks
→ staged activation → acknowledgement from Pi controller.

Then each physical knob delta travels through the fixed Pi driver and trusted
Pi bridge, over pinned local TLS to the Mac helper. The helper changes native
brightness and returns native readback. Turning the knob makes no model calls.
Generated packages cannot run shell commands or obtain bridge credentials.

The Mac connects outbound to Pi port 8790. Certificate pinning precedes credentials.
Only fresh physical confirmation activates the separate native session. Commands
have persisted sequences, single delivery and short deadlines; uncertain actions
are never replayed. A Mac watchdog stops computer/media access after connection
loss. Camera/audio stay on the local link, outside website storage and model input.

## Website reconnect

modulate.connect_tunnel supervises cloudflared. On hostname changes it signs a
registration to the fixed website with the existing scoped gateway secret. The
website proves endpoint identity before storing one origin/timestamp record in
private Vercel Blob. There is no Vercel administrator credential on the Pi.
After successful registration, discovery refreshes within 30 seconds per function
instance; browser polling keeps its existing session. In the live restart trial,
new-host identity checks initially failed and retries registered the hostname after
121.738 seconds. The public session endpoint was confirmed online at 141 seconds
without another deployment or environment change. Direct provider calls remain
independent of tunnels.
Quick Tunnels still have development availability limits; this is not a production SLA.

## Verified scope — October 30

The user compared matching codes and pressed small A. A typed live Pi Meta request
changed native Mac brightness 47 → 48 → 47 in six model calls, with independent
native final readback. Orbit Catch retained its exact revision. The helper was
restarted as a per-user LaunchAgent and reconnected within the same eight-hour
session. No physical brightness mapping was activated or knob trial claimed.

The background helper currently reports Screen Recording and Accessibility as
ungranted. Native brightness works; desktop actions stay blocked until macOS grants
those permissions to the helper. Camera and audio over this new network link are
not live-validated. Pairing alone is not proof of every capability.

See [sanitized runtime evidence](evidence/optional-mac-runtime.json). Discovery is
for the single configured demo Pi; multi-customer identity/routing is future work.
