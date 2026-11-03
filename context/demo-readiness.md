# Demo readiness — November 2–3, 2026

The target is fast independent commands in any order. Fifteen seconds remains a
performance target, not a measured bound for every fresh generation or native
computer task. Timing below starts with typed website submission and ends when
the Pi agent stops running. It excludes microphone capture/transcription and
speech playback. Follow-ups such as “reverse it” necessarily use the latest
relevant successful action; they cannot specify a target without context.

## Runtime changes

- The generic `edit_package` tool accepts exact revision, existing JSON-field
  paths and expected old/new values, or exact substring edits with an expected
  occurrence count. It copies the current package, applies all edits atomically,
  and runs the same independent verifier. No generated code or match heuristic
  selects a requested color, game, device or binding.
- `write_package(verify=true)` returns independent checks in the writing call.
  Meta must inspect the report before asking to activate its exact candidate.
  This saves a model round trip; validation and device acknowledgement remain.
- Optional Mac initialization now happens at the first actual desktop observation,
  rather than before every local request. A busy helper no longer prevents local
  jobs from starting or leaves their running flag stuck. A new computer task
  must observe afresh before acting; failed initialization remains retryable.
- Initial context includes the actual capability snapshot. Changed capabilities,
  stale revisions, private computer context and automatic setup still gate edits.
- Successful app selection ends speaker mode so the stream overlay cannot hide
  the new app. Reopening the already-active saved app also exits speaker mode.
  A rejected activation leaves the previous speaker route untouched.
- Schema failures identify the failing package/sprite/drawing structure and the
  missing/unsupported fields, without returning values. The previous generic
  message caused three repeated full rewrites in a failed live game trial.

These changes contain no named-game source, demo prompt routing, stored email
answers, reduced checks or artificial thinking delay. ElevenLabs remains a
private temporary demo setting; no provider configuration or credential is part
of these repository changes.

## Script claims and prerequisites

| Scene | Current implementation and limits |
| --- | --- |
| Original first-person game | Live Meta generates original code/art for the bounded runtime. Fresh generation can exceed 15 seconds or fail checks; a saved compatible creation may be reopened faster and must be described as saved reuse. Physical gameplay needs a filmed check. |
| Bubbles / input edit | A model-generated package edit uses the existing game as its base, fresh verification and device acknowledgement. Only connected ready controls are available. |
| Brightness / reverse | Requires the optional Mac session and an attached encoder. The earlier November 2 trial physically confirmed both directions at two percentage points per step. The current rehearsal detects joystick and A/B only. |
| YouTube | Native screenshot/cursor/keyboard tools operate the paired Mac; page load, dialogs and model latency affect timing. Selecting and playing a video is distinct from understanding its content. |
| Computer speaker | Existing paired-Mac audio capture/transport; prior human playback confirmation. Mode changes now relinquish the stream after a new app succeeds. |
| Halloween mirror | Actual local Mac camera stream plus generated overlays; frames stay outside model input. A mirror effect does not establish face tracking. |
| Hardware debugger | Supported identity-gated driver packs and guided address repair. Isolation, rewiring and power cycling still require a human. An I²C address alone does not identify arbitrary hardware. |
| App library | Saved local creations, favorites, Trash/restore; joystick/encoder navigation when connected. Permanent deletion uses the existing physical/human confirmation. |
| Voice switches harness to local Llama | Not implemented. `llama3.2:1b` was used by the first local prototype; that fact does not establish voice-driven harness replacement. |
| RFID guardrails | Package isolation and bounded host actions exist. A dedicated tested RFID abuse classifier/block has not been demonstrated; do not claim one. |
| Purchased modules / IR TV remote | Future scenario until actual hardware, driver, permissions and physical behavior are available. No component store or IR capability is established by the current demo. |
| Muse step tracker | Muse can submit normal agent requests. A step-tracker app requires a ready IMU; the current assembly does not advertise one. Walking use also needs portable power/internet. Generating an app does not validate step-count accuracy. |

Speech narration must identify the actual provider for the take: ElevenLabs is
currently selected; Meta MMS remains installed. Subagents are available to the
runtime, but simple tasks need not delegate and should not be narrated as if
every request always does.

## Live rehearsal evidence

| Typed website request | Seconds | Outcome |
| --- | ---: | --- |
| Open library before generation | 7.557 | Opened |
| Fresh original first-person game, first attempt | 76.773 | Rejected repeated malformed fields; previous app retained |
| Fresh original first-person game, after diagnostic repair | 148.457 | Generated Rust Pit 2.5D, checked and acknowledged |
| Change enemies to bubbles | 27.285 | `edit_package`, checks and acknowledgement; other controls retained |
| Open library after edit | 6.470 | Opened |
| Repeat the first-person-game request | 13.082 | Reopened the exact edited saved revision |
| Become computer speaker | 5.639 | Route started; no new physical audibility check |

The next reopen attempt was rejected with HTTP 400 before a new job was accepted.
It exposed the eager optional-Mac initialization bug described above, leaving
`running=true` against the preceding completed job. The fix was installed after
clearing that exact stale job. After the initialization fix, speaker → saved game passed in 13.333 seconds;
speaker start took 10.769 seconds. Halloween mirror generation took 33.198 seconds,
and reopening the saved game afterward took 9.924 seconds. Native YouTube work
ended after 74.507 seconds, then a playback-recovery request ended after 58.249
seconds. Independent native UI inspection found a paused pre-roll ad after both;
target playback is not confirmed and must not be presented as a verified success.
The fixed package boundary and app activation do not verify website playback.
Final state: agent idle, Mac paired with both native permissions, audio stopped,
Rust Pit's bubble revision retained, no runtime error, ElevenLabs without a speech
error. These are telemetry and a game-preview observation, not a physical retest.
These timings do not demonstrate a universal 15-second bound or 75% reliability.

See `evidence/demo-rehearsal-nov2.json` for measured trials, including failures.
No successful software acknowledgement here substitutes for optical gameplay,
physical knob effects, audibility, hot-plug safety or step-count accuracy.
