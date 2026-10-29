# Modulate submission checklist

Deadline: **November 4, 2026 at 9:00 PM America/New_York** (`2026-11-04T21:00:00-05:00`). Team target: finish and submit earlier that day, with November 3 reserved for unresolved submission questions. This target is a team recommendation, not an organizer requirement.

See [hackathon context](hackathon.md) for sources, the rubric, and unresolved source discrepancies. Nothing below is marked complete until there is evidence.

## Entry and project eligibility

- [ ] Confirm participant acceptance and review/accept the final Official Rules through the organizer's process.
- [x] Choose the competition track: **Indie Developer**, confirmed by the user on October 28, 2026.
- [ ] Confirm the organizer's registration/submission reflects the selected track.
- [ ] Confirm the roster has no more than four participants and designate one representative.
- [ ] State the selected theme and explain how the working product fits it.
- [ ] Verify a real Meta model integration; record provider, exact tested model identifier, and the model's substantive role.
- [ ] Record pre-existing components and newly created hackathon contributions separately.
- [ ] Check rights and attribution for dependencies, hardware designs, audio, imagery, and demo assets.

## Evidence for judging

| Criterion | Evidence to complete |
| --- | --- |
| Impact — 30% | Identify a target user making a small game or personal device control; capture the problem and compare with manual setup without invented savings |
| Meta tooling — 25% | Show a live spoken request producing original game/application code and mappings, independent checks and any bounded repair, and one unfamiliar refinement grounded in actual capabilities |
| Technical execution — 20% | Demonstrate isolated execution, independent verification, scoped pairing/actions, acknowledged activation, rollback, and reproducible setup; report observed timings and success/failure counts |
| Demo — 25% | Show voice input, a generated game on the device screen with physical play, a fresh change, and the same knob changing paired-computer system volume |

Measurements are project evidence goals, not extra organizer requirements. Publish observed results and limitations, including whether a run uses hardware, a simulator, a live model, or a cached configuration.

## Code and live product

- [x] Include the connection dashboard and server routes in this repository: [webapp/connect-app-code](../webapp/connect-app-code), with source manifest, standalone build, 20 UI/client tests and 30 API tests verified on October 29.
- [ ] Repository is public and can be opened while signed out.
- [ ] README states what exists, what is planned, how to run it, required hardware, and which parts require API access.
- [ ] A new teammate can reproduce the setup from the README.
- [ ] Required checks pass on the exact revision used for the submission.
- [ ] Verification is tied to the exact generated package hash, runtime/harness version, and capability manifest; model self-review or generated tests alone are not the evidence.
- [ ] Generated application code cannot bypass the runtime's hardware/action API or isolation; verify resource exhaustion, crash, and forbidden-access outcomes.
- [ ] Distinguish generated application/game code from firmware; claim firmware generation/flashing only if separately implemented and demonstrated.
- [ ] Demonstrate real microphone capture/transcription; identify device vs host microphone and wake phrase vs push-to-talk. Typed text alone does not fulfill voice.
- [ ] Demonstrate a playable original game on the actual PiTFT. A browser preview alone does not fulfill on-device play.
- [ ] Confirm any joystick before advertising it; describe encoder steering accurately when using the owned controls.
- [ ] Pair the intended computer with scoped, revocable permissions; prove real OS volume change and reject stale or revoked sessions. Browser media volume must be labeled separately.
- [ ] Hardware connection, reconnect, invalid model output, and loss of network have a tested outcome.
- [ ] No credentials, private conversation exports, raw microphone recordings, personal data, or unlicensed game/audio assets are accidentally published.
- [ ] Choose a license deliberately; include required third-party notices.
- [ ] Record the submitted commit SHA and preserve the version shown in the video.
- [ ] Confirm the actual submission form's live-product requirements and access instructions; test any supplied URL while signed out.

## Three-minute video

- [ ] Video is three minutes and focuses on working functionality built during this event.
- [ ] First seconds establish who benefits and show the physical product doing something useful.
- [ ] Demonstrate the same hardware changing roles through a prompt, with visible or audible effects.
- [ ] Show what the Meta agent generated and what the independent verification actually checked; label any repair loop and its outcome.
- [ ] Make the Meta model's contribution clear without exposing API keys or private data.
- [ ] Show at least one change that proves the system can adapt beyond fixed role presets.
- [ ] Explain how constraints and recovery keep the device usable when generation fails.
- [ ] Clearly label pre-existing code/assets and newly built functionality.
- [ ] Label simulations, prerecorded sequences, cached responses, and fallback modes honestly.
- [ ] Label time compression around generation and preserve an uncut timing run; do not imply guaranteed instant generation.
- [ ] Use owned or properly licensed audio and other assets.
- [ ] Check legibility, audio, pacing, captions, and the final video link while signed out.

## Submit and preserve

- [ ] Complete one team submission via the Cerebral Valley platform.
- [ ] Use the product name Modulate, list every contributor, and verify repository URL, video URL, track, and theme; the existing repository slug remains `cruise` unless separately renamed.
- [ ] Confirm public access to all judging artifacts from a separate browser session.
- [ ] Submit before the deadline and save the confirmation/receipt privately.
- [ ] Record any later edits and keep the final submitted artifact versions identifiable.
- [ ] Rehearse the live-final demonstration if selected; finals use the same rubric.

Optional bonus submissions, public promotion, credit claims, and community-vote activity are separate from the core submission.
