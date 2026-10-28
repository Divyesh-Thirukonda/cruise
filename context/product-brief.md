# Modulate: speak an idea into a physical experience

Status: user-directed concept revision, October 28, 2026. Modulate replaces the working name Cruise. The broader scope is spoken creation of games on the device and control of paired computers. The first [voice-to-number prototype](number-prototype.md) is working with local Meta generation; the broader game/paired-computer experiences below remain targets.

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

## Two concrete experiences

| Request | Intended behavior | Evidence required |
| --- | --- | --- |
| “Hey Meta, make a kart-racing game.” | Generate a small game for the connected display and controls; test it and activate it on the device | Actual Meta response, generated source/package, independent check results, physical input moving the kart on the PiTFT |
| “Make steering less sensitive and make the green button boost.” | Revise the existing code or bindings using the current program and hardware context | A new revision, fresh checks, and a visible effect beyond switching a stored preset |
| “Make this knob control my computer's volume.” | Select the paired computer's supported volume action and bind encoder movement with bounded steps | Explicit pairing, a working host bridge, observed OS volume change, and correct behavior after disconnect |

With the confirmed inventory, use the encoder to steer and buttons for game actions. A joystick is part of the desired interaction but is not in the confirmed inventory; do not silently assume it exists. The tiny 135×240 screen makes a simple readable game the first target. Display refresh and input timing must be measured on the actual Pi.

## Voice is part of the product

The intended entry point is a microphone. Test capture from the owned Bluetooth speaker/microphone before treating it as supported. A permissioned host microphone and push-to-talk are disclosed development steps; typed text is a debug fallback. A successful typed demo alone does not prove the voice experience.

“Hey Meta” is the user's proposed wake phrase. Wake detection, speech recognition, and Meta reasoning are separate pieces to select and test; the phrase does not establish access to an official Meta assistant or speech SDK. Show listening, transcription, generation, and ready/error states, provide mute/cancel, and make a misheard request correctable before it changes behavior. Do not keep raw recordings by default.

## What the agent actually builds

The first engineering proposal is to generate bounded game/application code and a versioned binding configuration for a fixed runtime. This preserves the user's code-generation ambition while keeping the physical drivers and recovery mechanism stable. The user's broader firmware-generation ambition remains recorded, but actual firmware rewriting is outside the first prototype and requires its own isolation, flashing, and recovery design.

The agent's meaningful loop is **inspect capabilities → generate → run checks → inspect failures → repair within a limit → stage activation**. The verification harness and permission boundary belong to the runtime, not to generated code. Model-generated tests can supplement those checks but cannot be the only proof. Passing a smoke test is evidence of the behaviors tested, not proof of arbitrary code correctness.

Once a revision is active, the game loop and controls execute locally. “Generate live” means the response is produced for the request during the session; it is not a claim of instant generation, guaranteed latency, or a model call per frame. A failed generation leaves the last working revision usable.

## Linking a computer

The companion website is a functional pairing and preview surface. The user links a specific device to a specific computer and grants a small action set. The proposed host bridge exposes system-volume control and state through a revocable session. The agent receives those granted actions as context and generates bindings to them; it does not install arbitrary generated host programs.

A webpage's media-volume control affects its media element; it does not prove OS system-volume control. The first computer OS and bridge implementation remain open. See the [architecture](architecture.md) for this distinction and the activation contract.

## Why Meta and an inference provider matter

A Meta model must contribute at runtime to interpreting intent, selecting feasible controls, writing a fresh program, and using verification feedback. The host/server calls the model with the request, actual capabilities, current revision, and bounded check results. This is the substantive integration to demonstrate.

Fireworks and Baseten have been discussed as candidate providers for serving Meta models. The initial build needs one verified provider adapter, not both. Exact model identifiers, account access, tool-call behavior, structured responses, latency, and spending controls must be checked before selection. Speech-model access is a separate question. No provider integration or credits have been established.

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

Defer arbitrary commercial games, phone-game integration, generated low-level drivers, firmware flashing, broad desktop automation, custom hardware fabrication, and additional modes. Build the real microphone-to-device loop, one original game, one trusted computer action, and one fresh refinement first. See the [build plan](plan.md) for dependencies and explicitly labeled fallbacks.
