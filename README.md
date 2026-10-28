# Modulate

**Say what it should do. Give the same hardware a new job.**

Modulate is a proposed modular device you program by speaking: a Meta-powered agent uses its connected controls and devices as context to generate and check software, turning the same hardware into an on-device game or a controller for your computer.

Say “Hey Meta, make a kart-racing game,” and the target experience is a small original game appearing on the device's screen, playable with its physical controls. Then say “Make this knob control my computer's volume,” and the agent maps the knob to a computer you have paired. Follow-up requests can change the game, button behavior, or adjustment sensitivity.

The new behavior comes from generated code and mappings. Physical controls and game frames run locally after activation; generating a new experience is a separate, measured process.

## Status

Planning began October 27, 2026 for the Meta Global AI Developer Hackathon. The user renamed Cruise to **Modulate** and set this voice-first direction on October 28. **The first voice-to-number prototype now runs on the physical Pi:** USB microphone → local Whisper transcription → local Meta Llama3.2 generation → fixed code checks → PiTFT activation. A spoken trial displayed 1008 in blue from a newly generated program. Games, paired-computer control and wake-word detection remain unimplemented.

The user confirmed the **Indie Developer** track and [owned hardware](context/hardware.md). Pi5 identity, the Mini PiTFT, its A button, USB microphone capture and local model calls were tested October28. External controls and full game/display performance still need testing. See the [prototype setup, controls, evidence and limitations](context/number-prototype.md).

## First demo to build

1. **Ask and generate.** Speak a request for a simple kart racer. The Meta-powered agent reads the actual hardware capabilities, generates game code and bindings, and uses an independent test harness before activation.
2. **Play on the device.** Show the original game on the 135×240 PiTFT. Start with encoder steering and the existing buttons; add joystick control only if a joystick is confirmed and tested.
3. **Refine it.** Ask “Make steering less sensitive and make the green button boost.” Show a fresh code or mapping change passing checks, then demonstrate its physical effect.
4. **Control the computer.** Link one computer through a companion website and trusted local bridge. Ask for knob control of system volume, then show the actual OS volume changing.
5. **Recover.** Show a rejected package, unavailable component, or failed activation leaving the previous working experience usable.

Voice is a core demo goal. Push-to-talk can establish it before wake-word detection; any host microphone or typed-input fallback must be identified. “Hey Meta” is a proposed activation phrase, not a claim that an official Meta voice-assistant integration exists. The user's “make Mario Kart” example is translated into an original small kart racer using our own or licensed assets.

## How it is intended to work

`Microphone → transcript + component/device context → Meta agent → generated package → checks and bounded repair → staged activation → local play/control`

The first implementation proposal generates **application/game code on a stable device runtime**. Firmware generation is a longer-term ambition; the first build will not reflash the Pi or peripherals with unchecked model output. Generated code runs in a restricted environment, with fixed hardware drivers and an allowlisted bridge for computer actions. Verification must produce evidence tied to the exact package; a model saying its code works is insufficient.

The website handles pairing, preview, and status. System volume requires a tested host integration; changing a browser media element's volume is a different capability. Provider, runtime, speech recognition, host OS, and pairing transport remain choices to verify. Fireworks and Baseten are candidate inference providers, not completed integrations.

## Project context

| Document | Purpose |
| --- | --- |
| [Agent instructions](AGENTS.md) | How coding agents should work in this repository |
| [Product brief](context/product-brief.md) | Refined idea, target interactions, scope, and demo story |
| [Hardware](context/hardware.md) | Confirmed inventory, missing capabilities, and bring-up checks |
| [Hackathon facts](context/hackathon.md) | Source-backed rules, rubric, dates, and unresolved discrepancies |
| [Architecture](context/architecture.md) | Agent tools, generated packages, validation, pairing, and recovery |
| [Build plan](context/plan.md) | Priorities, milestones, and evidence to collect |
| [Decisions](context/decisions.md) | User-confirmed direction, engineering proposals, and open choices |
| [Build log](context/build-log.md) | What was actually created during the event |
| [Submission checklist](context/submission-checklist.md) | Public repo, three-minute video, and submission readiness |

The supplied participant guide weights **Impact 30%, Meta AI tooling 25%, Technical Depth & Execution 20%, Demo 25%**. These guide our priorities; they do not guarantee a placing.

## Collaborate

The product is now Modulate; the existing repository URL and workspace folder still use `cruise`.

```sh
git clone https://github.com/Divyesh-Thirukonda/cruise.git
cd cruise
git switch -c codex/short-description
```

Read the product brief and build plan, then follow [CONTRIBUTING.md](CONTRIBUTING.md). The [number prototype guide](context/number-prototype.md) contains installation and run commands. Run its focused checks with `python3 -m unittest discover -s tests -v`.

The repository is public for judging. Keep API keys, private conversations, raw microphone recordings, account details, and raw participant materials out of commits. A project license has not yet been selected by the team.
