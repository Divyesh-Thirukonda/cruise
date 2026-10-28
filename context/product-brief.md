# Cruise: a controller you can describe

Status: proposed product direction, 2026-10-27. Cruise is a working name from the repository folder. No hardware, model integration, or working product is claimed by this brief.

## The idea, sharpened

**Tell one physical controller what you are trying to do. It maps its available controls to that job, explains the layout, and lets you refine it in plain language.**

Start with independent creators who move between making music and producing video. The initial problem is time spent mapping controls, remembering shortcuts, and rebuilding layouts when a workflow changes. Validate that problem with creators before describing it as established demand.

The gadget changes its behavior and labels; its physical parts remain the same. A knob can control a mix in one mode and scrub a timeline in another. A button can trigger a sound or an editing action. It becomes a speaker only if audio hardware exists: prompts cannot create missing capabilities.

The strongest demonstration is a new, useful mapping produced from an unfamiliar request, then used immediately on real hardware. A menu of three prerecorded presets would leave the central reinvention claim unproven.

## Why this could stand out

The proposed theme is **Push the Frontier**: a Meta model translates human intent into a usable interface for a physical system. The model has a substantive job: reconcile a request with the device's actual controls, available host actions, and the user's preferences.

Do not pitch it as the first programmable controller or assume it replaces every specialized device. The differentiator to demonstrate is the whole loop: describe a job, receive a feasible mapping, use it, then revise it conversationally without opening a mapping editor.

| Judging category | What we should prove |
| --- | --- |
| Impact — 30% | A creator completes a concrete task with less setup effort; show a measured comparison with manual mapping and a user's own feedback. |
| Meta AI tooling — 25% | A real Meta model produces a novel, capability-aware configuration and handles a follow-up request or missing capability. Show the actual call and resulting configuration. |
| Technical depth and execution — 20% | Invalid configurations cannot activate; switching preserves a usable previous state; hardware events reach the intended host action. |
| Demo — 25% | The same visible device performs two useful jobs, responds to an unrehearsed refinement, and recovers from a rejected request. |

Weights are taken from the supplied participant guide; see [hackathon context](hackathon.md). These are proposed evidence targets, not a forecast of judging results or a guarantee of a prize.

## A finishable first version

Commit to one controller, one host computer, and two transformations:

1. **Music mode:** a small performance or mixing surface with a few real actions supported by the chosen music application or a locally built audio demo.
2. **Video mode:** the same controls operate a small set of real editing or playback actions supported by the chosen video application or a locally built timeline demo.

Choose the exact applications and actions only after proving the host integration. If a demo application is our own, say so clearly; do not imply integration with a commercial editor. Prefer a few actions that work reliably over a large catalog of claimed integrations.

The minimum interaction is typed text. Voice, image understanding, more hardware modules, and a third mode are optional once the core loop works. The best stretch feature is a grounded follow-up such as, “Keep the transport buttons, make this knob move one frame at a time, and label the controls for a beginner.”

Use parts already available. Record the actual board, controls, transport, display capabilities, and any output hardware before choosing the firmware stack. An on-screen layout can label controls if there is no device display. A browser simulator is a useful development tool and an explicitly labeled fallback; it does not establish the physical-device claim by itself.

## Why the model matters

The proposed Meta integration turns a request, the current mapping, and real device/host capabilities into a new configuration. A deterministic validator checks it before activation; physical events then run locally without inference. A follow-up request must produce a useful change beyond selecting a saved preset.

The [architecture](architecture.md) defines the proposed contract, capability checks, activation acknowledgement, and rollback. Verify actual model access and provider behavior before implementing that adapter. The [build plan](plan.md) defines the evidence to collect, including failures, measured latency, user feedback, and a manual-mapping comparison. Do not present planned targets as observed results.

## Three-minute demo spine

| Time | What the viewer sees |
| --- | --- |
| 0:00–0:20 | One creator's concrete mapping problem, the actual device, and the promise: describe the job, then use the controls. |
| 0:20–0:55 | A typed music request, visible generation and preview, activation, then a physical control producing an audible or visible result. |
| 0:55–1:30 | A video-workflow request; the same device switches behavior and completes a real task. Keep device, layout, and resulting application action in view. |
| 1:30–2:05 | A new follow-up changes one mapping or accommodates a constraint. Show the actual model-produced change and use it immediately. |
| 2:05–2:30 | An unavailable or invalid action is rejected while the existing configuration continues working; show recovery or rollback. |
| 2:30–2:50 | A concise architecture view and genuine measurements. Identify where Meta inference is used and what the team built during the event. |
| 2:50–3:00 | The practical benefit, public repository, and working demo entry point. |

This is a target script, not a claim that any segment exists. Record a clean backup take, and distinguish recorded evidence from live operation. Keep the story centered on the device; a polished campaign or website can support it once the core demo is dependable.

## Scope cuts and immediate decisions

Defer a module marketplace, custom PCB, custom enclosure, mobile application, broad operating-system automation, continuous autonomous remapping, model training, and a full DJ workstation. None is required to prove the core idea in this event.

Before expanding implementation, settle these decisions:

1. Inventory hardware already on hand and prove one physical input reaches one host action.
2. Choose the primary creator workflow and two small action sets the team can demonstrate end to end.
3. Verify access to an eligible Meta model and test one real structured configuration response.
4. Freeze the first configuration contract, then implement preview, activation, and recovery around it.
5. Confirm the team, track, and submission representative; assign hardware/runtime, model/compiler, and demo/evaluation work according to actual availability.

If the first physical input or provider call stalls, resolve that bottleneck before spending time on branding or additional modes.
