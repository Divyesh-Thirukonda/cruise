---
name: games
description: Generate or refine a playable original game for the PiTFT and connected physical controls, with fresh game logic and pixel artwork. Use device-apps for camera effects or useful visual tools without gameplay.
---

# Games

Turn the request into an original, compact game that reads well at 240×135. Choose a coherent mechanic, clear goal and feedback, responsive controls, a manageable challenge, and restart. Familiar commercial-game references suggest mechanics, not a promise to reproduce proprietary characters or assets. Generate the logic and sprite artwork fresh; no bundled game or preset should substitute for a failed model attempt.

Inspect the actual inputs and maintained runtime API. Design around connected controls, avoiding invisible dependencies on a touchscreen, keyboard, browser or an untested sensor. Use readable high-contrast shapes and purposeful sprites. Start with a title and short control hints, then wait for a deliberate available button press so the player cannot lose while generation completes.

Use recent context and the current package to interpret refinements such as “make it faster” or “make that button jump.” Preserve the rest of the working game unless the request implies a replacement. Choose reversible design details without repeatedly asking the user to choose colors, layouts, buttons or difficulty. Ask only when the desired outcome is genuinely blocked.

The isolated runtime and its inputs/drawing commands are the contract. Frame logic must remain local, bounded and independent of model calls. Do not change trusted services, install libraries or invent privileged APIs to implement gameplay.

Check the candidate independently and inspect its rendering and input behavior where useful. Repair the actual reported failure; a visually attractive preview alone does not prove playable rules or physical latency. Activation must match the exact checked revision and live acknowledgement. If work fails, preserve the previous app and explain the concrete limit without claiming success. End with a brief description of how to play.
