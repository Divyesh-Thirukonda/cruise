---
name: modulate-setup
description: Set up or repair Modulate's local Mac companion, Raspberry Pi runtime, and browser connection. Use for first installation, missing connection codes, offline companions, and native permission setup.
---

# Modulate setup

These instructions are portable: read this file in any coding agent with local
file and command tools and follow the linked reference. No vendor-specific
plugin installation is needed. If the user wants to keep the skill, use their
agent's supported skill mechanism; do not assume the optional adapter in this
package works with every agent.

Help the user reach a working Modulate connection with as few manual steps as possible. Do the supported software work; explain the next physical or macOS action only when it is needed. Give short progress updates, not a list of every internal check.

The agent runs on the Mac. A preloaded gadget uses the local enrollment helper and physical screen/buttons; it needs no Pi shell. Do not open Raspberry Pi Connect, use an existing developer browser login, or ask the user to paste commands into a Pi terminal. SSH is only a separately authorized developer-kit or maintenance path, never a fallback for normal gadget setup.

## Establish what already exists

Modulate has three distinct connections: the Pi's pinned enrollment to its Mac companion, the Pi-confirmed native Mac pairing, and an expiring browser session. Repair the failed layer; do not recreate the other two.

Find the user's existing Modulate checkout and running companion before installing a second copy. Read that checkout's `AGENTS.md`, `context/connect.md`, `context/product-runtime.md`, and `context/hardware.md`. If no checkout exists, use the public source at `https://github.com/Divyesh-Thirukonda/cruise`; record the checked-out revision before executing it. Do not overwrite an existing folder or reset unrelated changes.

The optional read-only probe is `scripts/inspect_setup.py --repo <checkout>` (relative to this skill). It reports prerequisites, config-file presence, and loopback port reachability without reading credentials, changing settings, or making model calls. A listening port alone does not prove it is Modulate or that the Pi is connected.

Find the intended state directory even if the old service is stopped: inspect its saved launch configuration and the old checkout's state locations before creating any new state. If more than one app library exists, ask which one to retain rather than merging or choosing silently. Reuse that state and its launch settings. Before updating an old runtime or changing enrollment, make a verified private backup with restrictive permissions and retain the rollback path. Preserve saved apps, TLS keys, permissions, pairing, speech accounting, model spending and uncertain-cost holds. Do not print private config, enrollment tokens, pairing codes, or process environments. A failed or unreadable state file is a repair problem, not permission to reset it.

Honor an explicit fresh-start/reset note: empty apps and missing enrollment may be intentional. Keep the retained spending/speech ledgers and their limits; do not restore old games, sessions or enrollment to make setup pass. Do not mine recovery archives, historical logs or developer notes for IP addresses, tokens or access grants. Use current installation settings and user-provided access instead.

## Choose the shortest working path

- **An existing hub works locally:** restore its companion/tunnel if needed, then prepare a fresh single-use browser code in local Studio or the Pi's setup guide. Keep an unexpired browser session. Do not change a shared Vercel project's gateway or secrets to point at another person's Mac.
- **A preloaded Modulate device:** follow [the local enrollment flow](references/native-setup.md). Use the current IPv4 address on its screen, start Studio with this Mac's route address and the exact device peer, then run `python -m modulate.enroll --device-address <screen-address> --state-dir <existing-state>`. Open its local page on port 8791. The user enters the device's 20-character identity and eight-digit setup code directly there, then confirms on the gadget with a fresh A press. Never request those values in chat. Enrollment, native Mac access and the website code are separate steps.
- **An older preloaded device only says “Enroll this Pi once”:** it lacks the new enrollment service and needs a factory/runtime update before this flow can work. Explain that concrete blocker; do not silently fall back to remote shell, expose services or claim the update is installed. Continue independent Mac preparation.
- **A blank Raspberry Pi/developer kit:** follow [native setup](references/native-setup.md). This needs initial OS/network provisioning and a supported installation channel. The agent can perform Pi software work over explicitly authorized SSH, but must not assume that channel exists. Offer the necessary physical SD-card preparation/access choice once; never promise a ready-to-flash Modulate image that is not supplied. Use a zero cloud-call ceiling until this user supplies provider access and chooses a spending ceiling.
- **This public site cannot reach a new companion:** explain that `modulate-connect.vercel.app` currently serves one configured hub. A working local Studio is available first. For remote access, use a gateway/deployment the user owns or an enrollment path supplied by their hub administrator; the download does not enroll arbitrary computers into the shared deployment.
- **The browser rejects a code:** retain leading zeroes and use all eight digits. Check expiry, consumption and whether it came from this companion's browser-connection flow. Native Mac pairing uses a separate confirmation. Get one fresh code and retry; do not loop through guesses or weaken authentication.

## Finish through observable checks

Verify the intended companion process, Pi telemetry and native pairing separately. A browser says Connected only after its real session/state succeeds. Ask for the Pi's physical A-button confirmation and the relevant macOS permission dialogs when those steps are reached; never synthesize approval or bypass them. Browser access alone does not grant control of a Mac or phone.

If the gadget cannot show its setup address/identity, finish independent Mac preparation and report whether network setup or a factory/runtime update remains. Start services only with verified configuration; do not invent a peer address to launch Studio. A pending local enrollment request is not success: wait for the helper's matching completion receipt, then verify fresh Pi telemetry and the separate native pairing.

Verify only features the user chooses. Prefer a state read or reversible check before an agent request. Ask before a first paid test if no spending approval exists. Do not play audio or change volume unnecessarily. A host preview is not proof that the physical screen works; ask for one concise physical check when needed.

Finish with the working URL, what was independently checked, and the one remaining human step if blocked. Never claim a signed installer, public plugin-directory listing, automatic OS permission grants, or fresh-account model availability.
