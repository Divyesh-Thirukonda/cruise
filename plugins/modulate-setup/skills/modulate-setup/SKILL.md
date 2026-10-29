---
name: modulate-setup
description: Set up or repair Modulate's local Mac companion, Raspberry Pi runtime, and browser connection. Use for first installation, missing connection codes, offline companions, and native permission setup.
---

# Modulate setup

Help the user reach a working Modulate connection with as few manual steps as possible. Do the supported software work; explain the next physical or macOS action only when it is needed. Give short progress updates, not a list of every internal check.

## Establish what already exists

Modulate has three distinct connections: the Pi's pinned enrollment to its Mac companion, the Pi-confirmed native Mac pairing, and an expiring browser session. Repair the failed layer; do not recreate the other two.

Find the user's existing Modulate checkout and running companion before installing a second copy. Read that checkout's `AGENTS.md`, `context/connect.md`, `context/product-runtime.md`, and `context/hardware.md`. If no checkout exists, use the public source at `https://github.com/Divyesh-Thirukonda/cruise`; record the checked-out revision before executing it. Do not overwrite an existing folder or reset unrelated changes.

The optional read-only probe is `scripts/inspect_setup.py --repo <checkout>` (relative to this skill). It reports prerequisites, config-file presence, and loopback port reachability without reading credentials, changing settings, or making model calls. A listening port alone does not prove it is Modulate or that the Pi is connected.

Find the intended state directory even if the old service is stopped: inspect its saved launch configuration and the old checkout's state locations before creating any new state. If more than one app library exists, ask which one to retain rather than merging or choosing silently. Reuse that state and its launch settings. Before updating an old runtime or changing enrollment, make a verified private backup with restrictive permissions and retain the rollback path. Preserve saved apps, TLS keys, permissions, pairing, speech accounting, model spending and uncertain-cost holds. Do not print private config, enrollment tokens, pairing codes, or process environments. A failed or unreadable state file is a repair problem, not permission to reset it.

## Choose the shortest working path

- **An existing hub works locally:** restore its companion/tunnel if needed, then prepare a fresh single-use browser code in local Studio or the Pi's setup guide. Keep an unexpired browser session. Do not change a shared Vercel project's gateway or secrets to point at another person's Mac.
- **A new Mac and Pi:** follow [native setup](references/native-setup.md). Confirm actual local hardware and Pi access, prepare dependencies, enroll securely, and guide the matching-code confirmation on the Pi. Use a zero cloud-call ceiling until this user supplies their provider access and explicitly chooses a spending ceiling.
- **This public site cannot reach a new companion:** explain that `modulate-connect.vercel.app` currently serves one configured hub. A working local Studio is available first. For remote access, use a gateway/deployment the user owns or an enrollment path supplied by their hub administrator; the download does not enroll arbitrary computers into the shared deployment.
- **The browser rejects a code:** retain leading zeroes and use all eight digits. Check expiry, consumption and whether it came from this companion's browser-connection flow. Native Mac pairing uses a separate confirmation. Get one fresh code and retry; do not loop through guesses or weaken authentication.

## Finish through observable checks

Verify the intended companion process, Pi telemetry and native pairing separately. A browser says Connected only after its real session/state succeeds. Ask for the Pi's physical A-button confirmation and the relevant macOS permission dialogs when those steps are reached; never synthesize approval or bypass them. Browser access alone does not grant control of a Mac or phone.

Verify only features the user chooses. Prefer a state read or reversible check before an agent request. Ask before a first paid test if no spending approval exists. Do not play audio or change volume unnecessarily. A host preview is not proof that the physical screen works; ask for one concise physical check when needed.

Finish with the working URL, what was independently checked, and the one remaining human step if blocked. Never claim a signed installer, public plugin-directory listing, automatic OS permission grants, or fresh-account model availability.
