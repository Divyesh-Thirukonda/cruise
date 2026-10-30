# Optional Mac controls with a Pi-owned agent

The Pi owns AI, speech, apps and existing cost ledgers. Wi-Fi is required for
new Meta requests; [Meta MMS speech](meta-mms.md) and saved games run locally. This prototype
assumes configured Wi-Fi; factory network provisioning is not implemented.

## The two connections

1. Browser: hold small A for one second, release, then follow the browser-code
guide. Enter its one-use eight-digit code at the website /connect form.
2. Mac: copy the website's Mac setup prompt into a coding agent on the computer
to control. Keep the Pi agent running; never restart the legacy Mac AI studio.
After linking the browser, the Vercel setup page and Pi show a matching eight-digit
Mac comparison code. Compare both, then press small PiTFT A. Do not type this
second code into a form. Only the physical press grants native access.
3. Native access lasts up to eight hours. Temporary disconnects/restarts reconnect
within that session. Expiry or Revoke Mac pairing requires fresh confirmation.
macOS permissions still apply. Closing the browser does not revoke the Mac.

## Helper

Use this trusted checkout and its existing Mac Python environment/native dependencies.
Obtain the current Pi address and fingerprint from the physical setup display or
an existing authenticated connection. Never silently trust a changed fingerprint.

Build the trusted native app with `.venv/bin/python scripts/install_mac_app.py`.
It installs `~/Applications/Modulate.app` with a stable bundle identifier. Reuse an
existing valid app to preserve macOS grants. Stop a running helper before starting
a new pairing. Run `.venv/bin/python -m modulate.mac_companion --pair --pair-only
--device ADDRESS --fingerprint IDENTITY`, then open Modulate.app promptly. This
prepares a 120-second pending request; it does not authorize the Mac.

Open https://modulate-connect.vercel.app/connect/setup in the linked browser and
compare its code with the Pi. Press small A only when they match. The website
shows current native permissions and the pairing expiry once connected. The
legacy localhost comparison endpoint remains for diagnostics; it is no longer
required by the normal setup flow.

In Modulate.app, the user grants Screen & audio recording, Keyboard & mouse access,
and optionally Camera. The native app supplies the responsible macOS identity for
its trusted Python child. Restart the app after an OS-required quit. Closing its
window keeps the helper running; quitting the app stops it. Enable login launch
with `.venv/bin/python scripts/install_mac_app.py --skip-build --login`. The app
restarts a failed child, and reconnects the saved owner-only state in
`~/.local/share/modulate-mac` while its eight-hour session remains valid.

The helper has no model keys, app generator or AI/speech accounting ledger.
Revoke from the website Device page, or stop the helper and use `--revoke`.
Rebuilding an ad-hoc-signed app can require granting macOS permissions again;
this is a development app, not a notarized distribution.

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

The user subsequently enabled all three permissions for Modulate.app. Fresh Pi
state reported Screen Recording and Accessibility granted, with computer control
enabled. A typed Pi Meta request opened Gmail, selected the newest primary-inbox
message, and produced a spoken summary in eight model calls (39.523 seconds to
agent completion, excluding later synthesis/playback). The selected message was
independently checked in the browser. The native task recovered from an initial
URL typing focus miss before opening Gmail; this is one successful trial, not a
reliability benchmark. Orbit Catch retained its revision. MMS playback was
reported delivered. Email contents are excluded from published evidence.

See [sanitized runtime evidence](evidence/optional-mac-runtime.json). Discovery is
for the single configured demo Pi; multi-customer identity/routing is future work.


## Final native and local-speech validation — October 30

After the native grants, live typed Pi Meta requests captured fresh Mac camera
frames and system-audio packets, then verified both streams stopped. One audio
action returned a helper-busy result; a subsequent observation confirmed stopped
with zero buffered audio. This trial verifies capture/transport telemetry, not a
renewed human check of the camera image or audible system audio on the Pi.

A second typed request changed brightness 47 → 48 → 47 and volume 31 → 32 → 31,
preserving unmuted state. Independent native readback confirmed both final values.
No physical knob mapping was activated in these tests. The existing game revision
remained unchanged. The deployed website setup view showed Browser connected,
Mac connected and both desktop permissions allowed, preserving the existing
eight-hour expiry. The native app is configured to launch at login.

The Pi remains on Wi-Fi, with agent/device/connect services active after the final
agent restart. Local Meta MMS speech is active; the user confirmed clear speaker
output and the old ElevenLabs ledger stayed unchanged. The total Meta ledger is
$11.734172 charged/reserved of $50 after these trials. See
[sanitized evidence](evidence/mms-native-runtime.json) and [MMS details](meta-mms.md).
