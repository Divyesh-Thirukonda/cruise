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

For website setup, finish in the customer's website, not the full local Studio. Treat companion readiness as an internal checkpoint. Use the narrow `http://127.0.0.1:8787/setup` page only for native comparison and the browser-code handoff, then return the same tab to the installation's public `/connect` form. Preserve a valid browser session; do not disconnect it just to replay setup.

Operate the Mac yourself: inspect and start services, open one relevant browser tab, fill authorized fields, submit supported actions and verify the result. Reserve handoffs for information you cannot observe, a physical gadget button, an OS dialog the user must handle, or a tool-required approval. If the user asks you to enter supplied setup details, adapt to that instruction instead of repeatedly asking them to fill the form. Follow your tool's permission rules and explain any concrete restriction accurately.

The agent runs on the Mac. A preloaded gadget uses the local enrollment helper and physical screen/buttons; it needs no Pi shell. Do not open Raspberry Pi Connect, use an existing developer browser login, or ask the user to paste commands into a Pi terminal. SSH is only a separately authorized developer-kit or maintenance path, never a fallback for normal gadget setup.

## Establish what already exists

Modulate has three distinct connections: the Pi's pinned enrollment to its Mac companion, the Pi-confirmed native Mac pairing, and an expiring browser session. Repair the failed layer; do not recreate the other two.

Find the user's existing Modulate checkout and running companion before installing a second copy. Read that checkout's `AGENTS.md`, `context/connect.md`, `context/product-runtime.md`, and `context/hardware.md`. If no checkout exists, use the public source at `https://github.com/Divyesh-Thirukonda/cruise`; record the checked-out revision before executing it. Do not overwrite an existing folder or reset unrelated changes.

The optional read-only probe is `scripts/inspect_setup.py --repo <checkout>` (relative to this skill). Add `--live` to inspect fixed local Studio/helper endpoints and print only connection booleans and known status/action codes; it omits credentials, pairing codes, prompts, app content and replies. It never changes settings or makes model calls. A listening port alone does not identify Modulate or prove that the Pi is connected.

Find the intended state directory even if the old service is stopped: inspect its saved launch configuration and the old checkout's state locations before creating any new state. If more than one app library exists, ask which one to retain rather than merging or choosing silently. Reuse that state and its launch settings. Before updating an old runtime or changing enrollment, make a verified private backup with restrictive permissions and retain the rollback path. Preserve saved apps, TLS keys, permissions, pairing, speech accounting, model spending and uncertain-cost holds. Do not print private config, enrollment tokens, pairing codes, or process environments. A failed or unreadable state file is a repair problem, not permission to reset it.

Honor an explicit fresh-start/reset note: empty apps and missing enrollment may be intentional. Keep the retained spending/speech ledgers and their limits; do not restore old games, sessions or enrollment to make setup pass. Do not mine recovery archives, historical logs or developer notes for IP addresses, tokens or access grants. Use current installation settings and user-provided access instead.

## Choose the shortest working path

- **An existing hub works locally:** retain its valid enrollment and pairing. A website-setup request includes completing that installation's browser connection. Restore its existing private gateway configuration and outbound connection when stopped, preserving secrets and state. Verify website reachability before creating a browser code. Do not change a shared Vercel project's gateway or secrets to point at another person's Mac.
- **A preloaded Modulate device:** follow [the local enrollment flow](references/native-setup.md). Use the current IPv4 or IPv6 address on its screen, start Studio with this Mac's route address and the exact device peer, then run `python -m modulate.enroll --device-address <screen-address> --state-dir <existing-state>`. Open its local page on port 8791. Default to private form entry for the identity/code; if the user supplies them and asks you to enter them, do that within the tool's rules. Physical confirmation still belongs to the user. Enrollment, native Mac access and the website's browser session are separate stages.
- **An older preloaded device only says “Enroll this Pi once”:** it lacks the new enrollment service and needs a factory/runtime update before this flow can work. Explain that concrete blocker; do not silently fall back to remote shell, expose services or claim the update is installed. Continue independent Mac preparation.
- **A blank Raspberry Pi/developer kit:** follow [native setup](references/native-setup.md). This needs initial OS/network provisioning and a supported installation channel. The agent can perform Pi software work over explicitly authorized SSH, but must not assume that channel exists. Offer the necessary physical SD-card preparation/access choice once; never promise a ready-to-flash Modulate image that is not supplied. Use a zero cloud-call ceiling until this user supplies provider access and chooses a spending ceiling.
- **This public site cannot reach the companion:** first distinguish a stopped or misrouted existing gateway from an independent new Mac. Repair the existing installation's configured route within the user's request. A separate Mac needs a gateway/deployment the user owns or a connection path supplied by their hub administrator; the download cannot enroll arbitrary computers into the shared demo. Preserve a working local link, but report the website blocker instead of treating localhost as the requested finish.
- **The browser rejects a code:** retain leading zeroes and use all eight digits. Check expiry, consumption and whether it came from this companion's browser-connection flow. Native Mac pairing uses a separate confirmation. Get one fresh code and retry; do not loop through guesses or weaken authentication.

## Finish through observable checks

Observe the current helper, companion and browser state immediately before a retry or handoff. If the user advances the flow, discard obsolete instructions. Reuse the current tab; after helper completion, open `http://127.0.0.1:8787/setup` and inspect its actual pending/native pairing state instead of submitting the old form or starting a second enrollment. Keep the full local Studio and service diagnostics behind the scenes. Prefer the safe status probe over printing entire API responses.

Verify the intended companion process, fresh Pi telemetry and native pairing separately. Saved pairing without current telemetry is not an online device. For a pending native pairing, show the matching code on the Mac before asking the user to compare it and press A; do not ask for blind or repeated A presses when the Mac comparison is missing. Ask for relevant macOS permission dialogs when reached; never synthesize physical approval or bypass it. Browser access alone does not grant control of a Mac or phone.

If the gadget cannot show its setup address/identity, finish independent Mac preparation and report whether network setup or a factory/runtime update remains. Start services only with verified configuration; do not invent a peer address to launch Studio. A pending local enrollment request is not success: wait for the helper's matching completion receipt, then verify fresh Pi telemetry and the separate native pairing.

Inspect current voice/hardware warnings before calling the whole gadget ready. A working connection does not prove the microphone or optional modules work. Report existing warnings separately and choose the next relevant physical check; do not reset a good pairing to repair peripherals.

Verify only features the user chooses. Prefer a state read or reversible check before an agent request. Ask before a first paid test if no spending approval exists. Do not play audio or change volume unnecessarily. A host preview is not proof that the physical screen works; ask for one concise physical check when needed.

Fresh Pi telemetry plus active native pairing proves the local link, not a website session or every OS permission. For website setup, verify this installation's public gateway, display a fresh one-use browser code on the narrow local setup page if needed, then return to the verified website's `/connect` form. There is no `/connect/pair` route. Keep codes out of URLs, logs and screenshots. Operate authorized browser steps within the tool's rules; otherwise leave the customer on the connection form with the single remaining action. After linking, let the user review access choices on the website. Keep an already valid browser session and its permissions.

Call the website connected only after this browser's actual session succeeds and fresh device state loads; a 200 HTML page, listening port or local-ready flag is insufficient. If the gateway is blocked, give its concrete next action without presenting local Studio as the customer destination. If the user explicitly requested only local operation, local readiness can finish that narrower task. Never claim a signed installer, public plugin-directory listing, automatic OS permission grants, or fresh-account model availability.
