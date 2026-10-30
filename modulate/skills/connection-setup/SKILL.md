---
name: connection-setup
description: Guide pairing, reconnecting and permission setup for Modulate's Mac companion and browser dashboard. Use when connecting a computer or phone, opening setup, or diagnosing missing access; use hardware-debugger for physical modules.
---

# Connection setup

Use `connection_setup` to inspect the actual connection and present the next useful step on Modulate's screen. Read `ai_host` from current capabilities/status. When it is `pi`, the agent runs on Modulate using Wi-Fi and the existing cloud provider gateway; apps, speech and the Pi speaker do not need Mac pairing. When it is `mac`, the legacy Mac companion must be reachable. An unavailable agent leaves deterministic local guidance; it cannot call Meta or control an unpaired computer. Do not describe a local setup card as an AI-generated result.

Distinguish these connections before deciding what to do:

- **Enrolled Pi ↔ running agent:** loopback in standalone mode, or the legacy Mac companion; carries requests and the device runtime's authenticated connection. Missing enrollment, unavailable network and a stopped companion need the displayed installation/reconnection instructions. There is no self-service Wi-Fi setup or signed companion installer in this release.
- **Pi ↔ paired Mac:** an optional native Mac helper connects to the Pi agent over pinned local TLS. Browser linking does not grant Mac access. Direct the user to the website setup prompt for the optional helper; never restart the legacy Mac AI agent for standalone setup. In legacy Mac-hosted mode, an expiring native session authorizes supported computer controls. Creating an offer is not pairing; the user confirms the matching offer with the small PiTFT A button. Native macOS permissions still apply.
- **Browser ↔ existing Modulate hub:** `https://modulate-connect.vercel.app/connect` accepts a one-use code and the user's permission choices. A phone becomes a remote dashboard for this hub, not a controllable phone OS or a native computer bridge. Browser disconnection does not revoke the native Mac pairing.

Choose from the trusted tool's supported actions according to current state:

- `status` reads pairing/expiry, browser connection status and enabled permissions, and safe native-access metadata. Use it to avoid reinstalling or re-pairing a healthy connection.
- `show` opens the guide on the physical screen, retaining the current app. Use it for “show setup” or when the user needs the connection instructions again.
- `start_pairing` creates the native Mac offer when that connection is missing or expired. Explain the physical confirmation; never treat an offer or a spoken “yes” as proof that pairing completed.
- `create_browser_code` puts the one-use browser code on the Pi for the user to enter at `modulate-connect.vercel.app/connect`. Codes stay out of model results and spoken replies. Do not create repeated codes while the user is entering one, invent a code, or ask them to paste a token/API key into the conversation.

Perform supported preparation without asking the user to approve routine design choices. Then give one concise current instruction. Use `ask_user` only when a real human step blocks progress, such as confirming the displayed pairing offer or granting the companion a native OS permission. End that turn and wait; do not keep polling, assume “done,” simulate a button press, or use computer actions to grant the very access they require. After the user's response, inspect the new state and continue from that point instead of starting over.

The guide can be dismissed for the current boot so the saved app remains usable; dismissal is not pairing or a permission grant. Hold the small A button for one second to reopen it when disconnected; ordinary voice requests leave dismissed setup closed. Missing access should explain the concrete next step, not trigger generated replacement code, clearing saved apps, resetting credentials or spending ledgers, or sending the user to Codex for a supported setup step.

If the companion is present but a requested capability is unavailable, distinguish a disabled device permission, an expired native pair and a missing macOS grant from unsupported hardware. Preserve the user's existing permission choices; do not broaden them merely to make a status check pass. When setup succeeds, confirm the observed connection briefly and continue the original requested task if it is still relevant. Do not promise that a successful pairing proves every camera, microphone, speaker or computer action works.

Customer setup stays on the focused Mac pairing page (`http://127.0.0.1:8787/setup`) and the website connection screen. The local root Studio is a developer surface, not an onboarding destination. A healthy local link is one completed step; when the user is connecting the website, finish its actual browser pairing. If the website transport is not configured/reachable, explain that remaining step and let the setup agent repair the existing installation. Never claim a browser is connected from a configured gateway alone.
