# Modulate build plan

Proposed schedule, revised October 28, 2026 in America/New_York. The [product](product-runtime.md) demonstrates typed/spoken Meta-to-game creation, physical controls, paired native Mac volume, PTT/hands-free refinements and UI rollback. Initial audio failures and fixes remain recorded. The user has added browser computer tasks through actual cursor control and spoken replies; those paths are implemented but await native/physical validation. Repeated recovery/revocation, noise/performance trials, unfamiliar refinements, user-impact validation and demo evidence remain. The [number prototype](number-prototype.md) retains separate evidence.

## Build order

1. **Prove physical input and display.** Bring up the PiTFT, encoder, and buttons, resolving the button address collision first. A handwritten original game fixture can prove input and rendering; label it as a fixture, not generated output.
2. **Prove voice capture and a Meta call.** Test the owned microphone, then a clearly identified permissioned host microphone if necessary. Start with push-to-talk. Verify one real Meta provider call, transcribed request handling, and failure behavior before adding the wake phrase.
3. **Define the runtime and package contract.** Freeze a small game API, capability manifest, bindings, and independent verification harness. Select and test isolation and resource limits before running model-produced code. Preserve a known working revision.
4. **Complete the generation loop.** A Meta-powered agent reads capabilities, produces original game code and bindings, invokes checks, inspects failures, and makes bounded repairs. Stage the exact checked package, activate with acknowledgement, and play it on the PiTFT.
5. **Connect one computer action.** Select one host OS and implement a trusted system-volume bridge. Pair through a functional companion website, expose only granted capabilities, and verify revocation and disconnect. Then let the agent map the knob to this action.
6. **Refine and recover.** Show a fresh spoken game or binding change, rejected unsupported requests, failed verification, failed activation, and recovery. Add wake detection only after capture/transcription and the main loop are dependable.
7. **Validate computer tasks and spoken replies.** User consent now covers the native helper and screenshots sent to Meta; both required Mac permissions report granted. Test a 15-minute Chrome-window grant, an actual screenshot-to-Meta/cursor loop, interruption and revocation. Start with a read-only browser task; use no Gmail API. Standalone USB speech is audible by user confirmation; next verify an integrated reply, microphone pause and physical PiTFT B interruption. Mocked action tests and playback-process success are not substitutes for these checks.

The [architecture](architecture.md) records implemented contracts and remaining checks. The build order above is now a repeatable verification sequence; successful live trials do not establish reliability. A model success message cannot replace independent checks.

## Milestones

| Target | Deliverable | Exit evidence |
| --- | --- | --- |
| Oct 28–29 | Input/display fixture, microphone trial, first Meta call; choose one runtime and host OS | Physical steering on screen; recorded capture/transcript outcome; sanitized real response; decisions recorded |
| Oct 29–30 | Isolated execution, fixed check harness, package validation and staged activation | Invalid API, nonterminating program, malformed bindings, and stale revision rejected; previous revision retained |
| Oct 30–31 | Spoken request generates a playable original game on the device; bounded repair | Source/package hash, independent verification report, active revision acknowledgement, physical play footage, timing |
| Oct 31 | Fresh spoken refinement and one paired PC-volume action | New checked revision; actual OS volume changes; pairing target and scope visible; reconnect/revocation outcomes |
| Nov 1 | Recovery and user validation; wake phrase if feasible | Failure/rollback recording; feedback from at least three target users if available; clearly recorded voice path |
| Nov 2 | Feature freeze and rehearsal | Consecutive activation trials, recorded failures, game rendering/input measurements, clear device footage |
| Nov 3 | Three-minute video and submission draft | Accessible video/repo, original-contribution summary, clean-clone instructions for actual code |
| Nov 4 | Final checks and submission | Team target: submit by 7 PM Eastern; supplied organizer deadline: 9 PM Eastern |

These are planning targets, not guarantees. Reassess scope at each unproven dependency rather than describing future work as completed.

## Scope cuts and disclosed fallbacks

- Use the physically confirmed joystick/buttons for the game and encoder for volume. Do not buy hardware to satisfy the sketch without instruction.
- Reduce game complexity to a readable small 2D racer before dropping play on the actual device screen. A host preview does not prove the on-device claim.
- Use push-to-talk before wake detection. A host microphone is acceptable as a visibly identified prototype input; typed text is a debug path and does not fulfill the voice target.
- Keep one primary provider, one game runtime and macOS as the host target. The user's added computer-task scope starts with one Chrome window plus local spoken replies. Defer unrestricted desktop/app control, phone-game integration, training, generated drivers and firmware flashing.
- If the system-volume bridge is blocked, report that gap. A browser-audio demonstration must be called browser volume and does not fulfill system-volume control.
- Use a simulator or cached package for development or disclosed recovery only. Do not replace failed live inference with an unlabeled preset.

## Suggested ownership, pending team agreement

Split by deliverable: hardware/display/voice capture; Meta agent/package verification; runtime/activation and paired-computer bridge. These are proposed responsibilities, not named team members. Agree on integration ownership and the submission representative; the guide allows at most four participants.

## Evidence tied to the rubric

| Criterion | What to collect |
| --- | --- |
| Impact — 30% | A target user's setup problem, observed manual baseline, and actual outcome with Modulate; label small samples |
| Meta AI tooling — 25% | Sanitized live model identity, generated code, fresh request, tool checks and any repair, capability-aware rejection |
| Technical depth — 20% | Isolation/permission failures, independent harness results, pairing scope, package/revision consistency, activation and rollback |
| Demo — 25% | Voice-to-game footage with physical input; same knob changing paired-computer volume; an unfamiliar refinement and failure recovery |

For the computer/speaker extension, collect a separate consent-to-task-to-audible-reply trial, including stop/revoke behavior. Keep email contents, screenshots and derived private answers out of public traces or demo footage unless the user explicitly supplies content for publication.

## Measurement template

Record date, commit, device/host, model/provider, capability manifest version, package hash, active revision, prompt category, microphone source, wake/push-to-talk/typed path, live/replay/mock status, check outcomes, repair count, acknowledgement, and success/failure. Keep secrets and raw audio out of public traces.

Measure capture/transcription, generation, verification/repair, activation, and total request-to-ready separately. Measure game frame timing, physical-input-to-effect, and knob-to-volume acknowledgement after activation. Preserve failures in the denominator. Numeric latency targets should follow the first baseline, not precede it as advertised performance.

Use at least 10 consecutive activation/mode-switch trials as a proposed rehearsal gate, followed by an unfamiliar spoken prompt and an unavailable capability request. This is an internal evidence target, not an organizer rule or statistical reliability claim.
