# Modulate

**Say what it should do. Give the same hardware a new job.**

Modulate is a modular-device project you program by speaking: a Meta-powered agent uses connected controls and devices as context to generate and check software for an on-device game or a controller for your computer. The user-requested extension adds browser computer tasks and spoken answers through the device.

Say “Hey Meta, make a kart-racing game,” and the target experience is a small original game appearing on the device's screen, playable with its physical controls. Then say “Make this knob control my computer's volume,” and the agent maps the knob to a computer you have paired. Follow-up requests can change the game, button behavior, or adjustment sensitivity.

The new behavior comes from generated code and mappings. Physical controls and game frames run locally after activation; generating a new experience is a separate, measured process.

## Status

Planning began October 27, 2026 for the Meta Global AI Developer Hackathon. The user renamed Cruise to **Modulate** and set this voice-first direction on October 28. **The first voice-to-number prototype runs on the physical Pi:** USB microphone → local Whisper transcription → local Meta Llama 3.2 generation → fixed code checks → PiTFT activation. A spoken trial displayed 1008 in blue from a newly generated program.

**Live generated games now run on the Pi.** The first typed Meta request produced **Pixel Kart Sprint**, with code and three original sprites, in about 49 seconds; the user confirmed steering and both large buttons. A later spoken “Make yourself” request produced **MODULATE: Self Assembly**, with four generated sprites, in about 38 seconds. Observed device rates were about 13 fps, not a sustained guarantee. See [exact revisions, costs, setup and limits](context/product-runtime.md#first-live-generated-game--october-28).

**The same knob now controls the paired Mac's actual system volume.** A typed mapping request completed in about 6.6 seconds; the user confirmed its direction and independent native reads confirmed the volume. A six-second push-to-talk request, “Make the knob less sensitive,” changed its scale from +2 to +1. The user then said “Hey Meta, reverse the knob” without pressing buttons, producing a checked −1 mapping. Those agent requests took about 5.9 and 4.5 seconds after transcription; they exclude recording/transcription time. [Live control and voice evidence](context/product-runtime.md#live-volume-and-spoken-refinements--october-28).

Another hands-free request increased the reversed step to −10. Two live UI rollbacks then restored −1 and returned to the original −10 revision, with zero model calls. [Rollback evidence](context/evidence/live-rollback.json) records Pi software acknowledgements, not optical readback.

The user confirmed the **Indie Developer** track and [owned hardware](context/hardware.md). This is a working hackathon prototype: early audio failures required resampling/buffering fixes, and a shutdown race caused unintended game fallback. The shutdown fix preserved the exact game revision across two verified restarts. These trials do not establish broad wake/noise or failure reliability; revocation and performance testing remain. The [number prototype guide](context/number-prototype.md) preserves its earlier evidence.

**A live Meta computer task and spoken reply now work in a local test.** From a typed request, the agent used Chrome screenshots and real cursor/keyboard actions to enter a phrase, click Verify and observe the confirmation in eight model calls. The resulting browser state was independently checked, the user heard the Pi's final reply, and Dodge Fall remained retained during that trial. The spoken Gmail attempt subsequently failed, so email reading is not demonstrated. Computer control uses a separate 15-minute Chrome-window grant, fresh observations and stop/revoke controls, without a Gmail API. [Exact trial, setup and privacy limits](context/product-runtime.md#computer-tasks-and-spoken-replies).

Later spoken game requests created **Metro Dash** and refined its collisions; the revised game is preserved. The latest update adds one-time focus of the granted Chrome window, spoken failure feedback and up to two repairs of malformed model responses within the existing call/budget limits. Validation ran 417 local tests with three Mac PyAV skips, plus 46 final Pi device checks after the earlier 92 speaker/device tests. The current $5 ceiling blocks the next reservation; a proposed $7 total ceiling and fresh Chrome trial await approval. [Ledger details](context/product-runtime.md#install-the-host).

## Run the product studio

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-product-host.txt
.venv/bin/python -m unittest discover -s tests -v
```

Then follow the [host/Pi setup guide](context/product-runtime.md) for private credentials, a selected spending ceiling, pinned TLS enrollment and device launch. The companion is served locally at `http://127.0.0.1:8787`; it shows the real preview, connected controls, agent activity, generated source and checks. It is a working control surface, not a promotional website. The macOS host bridge and Pi device are separate trusted processes; no model key belongs in the browser or on the Pi.

While processing, the Pi and companion show the actual stage. The user confirmed the Listening → processing transition; a later 60-sample trace showed processing throughout all sampled busy stages and then ready/game. The current program is retained and paused. [Processing and restart evidence](context/evidence/processing-and-restart.json) distinguishes software telemetry from optical confirmation.

The latest voice update keeps ambient transcription visually quiet. A wake-only check starts after a short pause while recording continues, so “Hey Meta” can acknowledge before the complete request finishes. Finish speaking with a three-second pause, then review the transcript in Studio during a separate three-second window. **Edit** pauses sending until **Send now**; **Discard** cancels the draft. During a build, “Hey Meta, cancel build” requests cancellation locally. If Meta needs a detail, its question appears on the Pi and in Studio, and your next reply includes that context. The update is installed: the user confirmed wake acknowledgement and hands-free cancellation of a held request; 164 focused tests passed on the Pi. A live Meta clarification and Studio edit/discard were also checked. Room-noise reliability remains unmeasured. See [voice behavior and limits](context/product-runtime.md#use-the-companion).

## Demonstration flow

1. **Ask and generate.** Show a real spoken game request and the agent/check/activation path. Pixel Kart Sprint was created through text; the later Self Assembly game came through the voice endpoint. Label the particular run accurately.
2. **Play on the device.** Show the original game on the PiTFT's 240×135 landscape canvas. Joystick steering and large green/red buttons are physically confirmed in the first game.
3. **Refine it.** Ask “Make steering less sensitive and make button B boost.” Show a fresh code or mapping change passing checks, then demonstrate its physical effect.
4. **Control the computer.** Link the Mac through the companion and trusted bridge. Show the knob changing actual OS volume, then the demonstrated spoken sensitivity and direction changes.
5. **Recover.** Show a rejected package, unavailable component, or failed activation leaving the previous working experience usable.

The typed local-form trial can demonstrate a browser task with permission shown, visible cursor actions and an audible reply. Label its typed input and test-page scope; do not present it as proof of spoken email access.

Voice is a core demo goal. Push-to-talk can establish it before wake-word detection; any host microphone or typed-input fallback must be identified. “Hey Meta” is a proposed activation phrase, not a claim that an official Meta voice-assistant integration exists. The user's “make Mario Kart” example is translated into an original small kart racer using our own or licensed assets.

## How it works in code

`Microphone → transcript + component/device context → Meta agent → generated package → checks and bounded repair → staged activation → local play/control`

The product generates **JavaScript application/game code on a stable device runtime**, with original sprite data. Firmware generation is a longer-term ambition; this build does not reflash the Pi or peripherals with model output. Generated code runs in a bounded QuickJS-NG worker with OS restrictions, separate from fixed hardware drivers and the allowlisted computer-action bridge. Verification is tied to the exact candidate and capability manifest; a model saying its code works is insufficient.

The local website handles pairing, preview, requests and status. Meta, Fireworks and Ollama adapters are implemented; `muse-spark-1.3` powered the live games and control changes. The current stack uses local Whisper speech recognition, a macOS host bridge and pinned TLS for the Pi connection. The wake phrase uses a local transcript matcher and is not an official Meta assistant integration. Evidence distinguishes typed and spoken runs.

Computer tasks use an independently implemented native Python helper, separate from generated packages and volume pairing. The agent receives temporary screenshots and chooses bounded actions. Existing Codex app services, credentials and proprietary computer-use runtime were not copied. Dependency attribution and the permission boundary are in the [architecture](context/architecture.md#computer-tasks-and-spoken-replies).

## Project context

| Document | Purpose |
| --- | --- |
| [Agent instructions](AGENTS.md) | How coding agents should work in this repository |
| [Product brief](context/product-brief.md) | Refined idea, target interactions, scope, and demo story |
| [Hardware](context/hardware.md) | Confirmed inventory, missing capabilities, and bring-up checks |
| [Hackathon facts](context/hackathon.md) | Source-backed rules, rubric, dates, and unresolved discrepancies |
| [Architecture](context/architecture.md) | Agent tools, generated packages, validation, pairing, and recovery |
| [Product runtime](context/product-runtime.md) | Host/Pi installation, runtime contracts, offline evidence and current limitations |
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

Read the product brief and build plan, then follow [CONTRIBUTING.md](CONTRIBUTING.md). The [product runtime guide](context/product-runtime.md) is the current setup entry point; the [number prototype guide](context/number-prototype.md) documents the earlier experiment. Run checks in the installed virtual environment.

The repository is public for judging. Keep API keys, private conversations, raw microphone recordings, account details, and raw participant materials out of commits. A project license has not yet been selected by the team.
