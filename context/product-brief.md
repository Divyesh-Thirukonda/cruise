# Modulate: speak an idea into a physical experience

Status: October 28, 2026. Modulate replaces Cruise. The live prototype has typed and spoken generated Pi games, physical controls, paired native Mac volume, PTT/wake refinements and UI rollback. The first kart used text; Self Assembly came through voice. Wake reliability and broader fault/performance trials remain unmeasured. See [current evidence](product-runtime.md) and the separate [number prototype](number-prototype.md).

The user has extended the product to general computer tasks through actual cursor/keyboard interaction and spoken responses. The Chrome-window adapter and Pi speech path are implemented. Standalone USB speech is user-confirmed and Mac permissions report granted; the full model-driven browser/spoken-reply loop remains untested.

## Project one-liner

**Modulate is a modular device you program by speaking: a Meta-powered agent generates and checks software that turns its connected controls into playable games and tools for your other devices.**

## The idea, refined

Describe what you want the device to do. Modulate gives a Meta-powered agent the connected components, screen, supported device actions, and current program as context. The agent writes the code and control mappings, checks the result with tools, repairs failures within a limit, and stages a new experience for the same physical hardware.

The user should be able to move from “Hey Meta, make a kart-racing game” to playing that game on the device's own screen, then say “Make this knob control my computer's volume” after linking their computer. A later instruction such as “Make the steering less sensitive” should modify the current experience without requiring the user to open an editor.

“Modular” means software adapts to the components actually connected. The initial assembly uses owned plug-in peripherals. Hot swapping, automatic discovery of arbitrary boards, a custom enclosure, and a module marketplace are not established capabilities.

The user's “make Mario Kart” phrasing communicates a familiar game mechanic. The demo target is an original, small 2D kart racer with original or licensed assets. It does not promise Nintendo's game, characters, tracks, or a full commercial game engine.

## Who it is for

Start with people who want to make small interactive gadgets, games, and personal controls without writing device code or manually mapping every input. The initial hypothesis is that spoken programming can shorten the path from an idea to a useful physical interaction. Validate that with actual users and an observed baseline; demand and time savings have not been established.

The earlier music/video creator workflow and phone-game controller examples are superseded as the primary demo. The current game runs on the device's screen. Phone support can be a later extension after this loop works.

## Target interactions

| Request | Intended behavior | Evidence required |
| --- | --- | --- |
| “Hey Meta, make a kart-racing game.” | Generate a small game for the connected display and controls; test it and activate it on the device | Actual Meta response, generated source/package, independent check results, physical input moving the kart on the PiTFT |
| “Make steering less sensitive and make button B boost.” | Revise the existing code or bindings using the current program and hardware context | A new revision, fresh checks, and a visible effect beyond switching a stored preset |
| “Make this knob control my computer's volume.” | Select the paired computer's supported volume action and bind encoder movement with bounded steps | Explicit pairing, a working host bridge, observed OS volume change, and correct behavior after disconnect |
| “Hey Meta, read my email.” | With a separate grant, use the visible Chrome browser through screenshots and cursor/keyboard actions, then speak a concise answer | Actual permission grant, visible browser interaction and user-confirmed speaker output; no Gmail API. This end-to-end path is not yet validated |

The first game uses the joystick and large green/red buttons, physically confirmed by the user. Distinct button addresses were verified after a power cycle. A 240-sample game window reached joystick X −1 and 1 and included both buttons; later volume traces captured encoder motion. The 240×135 display showed 13.4 fps in the first run; sustained performance and input-to-display timing remain to measure.

## Voice is part of the product

The intended entry point is a microphone. The attached USB microphone and local Whisper transcription worked in the number prototype; the owned Bluetooth speaker/microphone remains untested. The new product voice worker uses the Pi microphone and local recognition, with push-to-talk and optional transcript-based wake matching. Typed text is a debug fallback; the companion does not capture browser microphone audio. A successful typed demo alone does not prove the voice experience.

“Hey Meta” is the chosen wake phrase, matched in local transcripts with a listening gap during inference. Native 16 kHz capture and early stream-overflow attempts failed; 48 kHz resampling plus buffering/retry fixes preceded successful PTT and hands-free refinements. The user explicitly confirmed no buttons for the wake reversal. These successes are not a reliability benchmark or official Meta assistant integration. Show actual voice/error states, provide mute/cancel and keep recordings out of saved artifacts.

Replies now have a local eSpeak NG/USB playback path. The microphone pauses while speech plays; physical PiTFT B stops speech and holding both screen buttons invokes PTT. The user confirmed hearing a standalone sentence through the USB Jieli output at 40% after the initial silent attempt and a corrected manual sink name. Integrated agent replies and room echo behavior remain to test. This is separate from the untested Bluetooth audio device.

## What the agent actually builds

The implementation generates bounded JavaScript game/application packages with sprite data and separate declarative control bindings for a fixed runtime. This preserves the user's code-generation ambition while keeping physical drivers and recovery stable. The user's broader firmware-generation ambition remains recorded, but actual firmware rewriting is outside this build and requires its own isolation, flashing, and recovery design.

The agent's meaningful loop is **inspect capabilities → generate → run checks → inspect failures → repair within a limit → stage activation**. The verification harness and permission boundary belong to the runtime, not to generated code. Model-generated tests can supplement those checks but cannot be the only proof. Passing a smoke test is evidence of the behaviors tested, not proof of arbitrary code correctness.

Once a revision is active, the game loop and controls execute locally. “Generate live” means the response is produced for the request during the session; it is not a claim of instant generation, guaranteed latency, or a model call per frame. A failed generation leaves the last working revision usable.

## Linking a computer

The local companion website is a pairing and preview surface. The user links the enrolled Pi to the Mac and grants a small action set. The implemented native host bridge exposes system-volume control and state through a revocable session. The agent receives those granted actions as context and generates bindings to them; it does not install arbitrary generated host programs.

A webpage's media-volume control does not prove OS volume control. The selected macOS bridge uses fixed trusted OS calls; knob motion now changes native volume, corroborated by independent OS reads. Revocation and broader fault tests remain. See the [architecture](architecture.md).

Computer tasks use a separate 15-minute grant for one frontmost Chrome window on the primary display. Meta sees temporary screenshots and chooses visible actions through a fixed native helper; the model cannot select arbitrary applications or write host scripts. Volume pairing does not grant this access. The user explicitly chose browser interaction over a Gmail API and authorized the native/screenshot-to-Meta trial. The current app remains intact during these tasks, and screen-derived answers use a transient display/speech path. Native permissions report granted; actual model-driven cursor operation still needs validation.

## Why Meta and an inference provider matter

A Meta model must contribute at runtime to interpreting intent, selecting feasible controls, writing a fresh program, and using verification feedback. The host/server calls the model with the request, actual capabilities, current revision, and bounded check results. This is the substantive integration to demonstrate.

The current product uses `muse-spark-1.3`. The first live game used 11 model calls, including coder delegation chosen after a malformed tool call, then checked activation in about 49 seconds. It generated source and three original sprites for the actual Pi controls. Fireworks and local Ollama adapters are also implemented; Baseten remains a candidate. Provider credits are not assumed. Speech recognition is local and separate from the generation model.

## Three-minute demo spine

| Time | What the viewer sees |
| --- | --- |
| 0:00–0:20 | The physical device and a user speaking an idea; explain the setup work Modulate aims to remove |
| 0:20–1:00 | A game request, actual generation and checks, then a physical control moving the kart on the device screen |
| 1:00–1:30 | A fresh spoken refinement, the changed revision, and its effect in play |
| 1:30–2:05 | Pairing state, a spoken request to bind volume, and the same knob changing the computer's OS volume |
| 2:05–2:30 | An unsupported input or failing package is rejected; demonstrate the previous working mode or recovery |
| 2:30–2:50 | Where Meta inference runs, how verification gates activation, and observed timings with limitations |
| 2:50–3:00 | What was built during the event, the practical benefit, and repository/demo entry points |

This is a target script, not existing footage. If generation takes longer, label edits or time compression and preserve an uncut timing run. A host preview, cached program, or prerecorded response must not stand in for live device/model evidence without disclosure.

## Evidence and scope

| Judging category | What we should prove |
| --- | --- |
| Impact — 30% | A target user gets from spoken idea to working game/control with an observed comparison to manual setup |
| Meta AI tooling — 25% | A live Meta-powered generation and bounded repair loop produces a novel program or refinement grounded in capabilities |
| Technical depth and execution — 20% | Independent verification, isolated code execution, trusted pairing/actions, acknowledged activation, and rollback work under failure |
| Demo — 25% | One visible device plays a generated game, changes through speech, and becomes a useful paired-computer control |

Weights are organizer facts from the supplied guide; these evidence targets are team recommendations. Do not promise a score or prize.

Keep the demonstrated game, volume and spoken-refinement loop as the core evidence. Validate the newly requested Chrome computer task and spoken response next; include them in the video only with separate live evidence. Defer arbitrary commercial games, phone-game integration, generated low-level drivers, firmware flashing, unrestricted desktop/app access and custom hardware fabrication. See the [build plan](plan.md) for dependencies and explicitly labeled fallbacks.
