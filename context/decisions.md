# Decisions and open questions

Updated October 29, 2026. User-confirmed product direction is distinguished from engineering proposals and unverified capabilities.

### Implemented first experiment — October 28

The user narrowed the immediate build to speaking a random-number request and generating new code for the PiTFT. Implemented local Whisper tiny.en transcription and local Meta Llama 3.2:1b generation on the Pi 5, with a bounded Python-subset interpreter and checked application activation. PiTFT A starts six-second capture; B rolls back. The successful spoken trial produced 1008 in blue from new source in 12.65 s; one preceding attempt failed and preserved the old program. This is application hot reload, not firmware rewriting. See [setup/evidence](number-prototype.md).

Google was explicitly authorized as a temporary alternative. Authentication/model listing worked, but generation returned high-demand errors, so that prototype's tested default uses no external API. Google audio is unverified. The product implementation below is a subsequent build with separate evidence requirements.

### Product implementation choices — October 28

Implemented a model-directed tool loop with optional coder/artist/reviewer delegation, a persistent isolated QuickJS-NG game worker, generated indexed-palette sprite packages, independent verification, a local companion, fixed macOS volume bridge and local transcription-based wake/PTT worker. The selected application boundary is JavaScript on a stable runtime; no generated firmware is flashed. The new provider adapters cover Meta, Fireworks and Ollama. A live typed `muse-spark-1.3` request has now generated and activated Pixel Kart Sprint, with physical steering and large-button use confirmed. See [setup and current evidence](product-runtime.md).

The orchestrator and specialists share bounded turns, eighteen calls per request and a persisted ledger. The first game used 11 calls and model-chosen coder recovery after a malformed write. Native Mac volume then worked from the encoder; PTT reduced +2 to +1, hands-free speech reversed to −1 and increased reversed steps to −10. Two UI rollbacks returned −10 → −1 → −10 with no model calls. See [live evidence](product-runtime.md); repeatability, noise, revocation and broader fault trials remain.

| Topic | Current position | Why / next step |
| --- | --- | --- |
| Product name | User-confirmed: **Modulate**, Oct 28 | Replaces Cruise; existing repository URL and workspace folder remain `cruise` |
| Core idea | User-confirmed, Oct 28 | Speak a request; a Meta-powered agent uses connected components/devices as context to generate and check software for the same physical hardware |
| Primary game experience | User-confirmed direction: generated game on the device screen | Supersedes phone-game control and the earlier music/video workflow as the main demo |
| Game scope | Original games and apps generated from text/speech | Star Dash survived the browser trial; Mini Search Deck was retained through the later speech update. First-game controls were confirmed; observed rates are not a sustained guarantee |
| Second experience | Paired knob-to-Mac-volume demonstrated | User confirmed direction; live deltas and independent native reads confirmed OS values. Revocation/fault trials remain |
| General computer tasks | Actual cursor/keyboard operation, including email in the browser; no Gmail API | Typed local-form and spoken latest-email readout succeeded. Visible Gmail verified the subject; user heard the answer. Earlier failure retained; three subjects and broad reliability unproven |
| Computer permissions/privacy | User-authorized paired-Mac primary-display scope replaces separate Chrome grants; installed | Connected eight-hour pairing covers requested cursor/app, camera and supported system actions. Native permissions, fresh observations, pause/stop and revoke remain. Screenshots may go transiently to Meta; camera frames stay local |
| Live camera | Actual paired-Mac camera image with generated effects/overlays, user-confirmed | Funky Mirror Cam required a transport deadlock repair; restored after restart with no new model call. Raw frames stay in memory and outside Meta/generated code; C270 remains on hold |
| Spoken replies | User-requested ElevenLabs Flash v2.5/Roger installed and physically heard; key stays on host | User confirmed natural voice and good volume at 75%; telemetry reports delivered without error. Earlier local eSpeak replies were heard at 40%; no silent fallback on ElevenLabs failure |
| Voice | Native 48 kHz capture → PyAV resampling → local Whisper | Wake-only check after a 0.5-second pause keeps recording; full requests wait three seconds of silence. User confirmed the repaired wake acknowledgement. Ambient checks are passive; audio at 25 seconds is discarded |
| Request review and cancellation | User-requested voice polish | Separate three-second transcript review; Edit pauses sending, Send now submits, Discard cancels. Busy wake cancellation is implemented; a held request was cancelled by voice on the Pi with zero model calls |
| Clarification | Model-directed `ask_user`; original goal and bounded reply history | One direct answer may begin within 20 s after speech/cooldown; question expires in 120 s. Maximum four questions and one user-answered operational recovery turn. A live space-joke question → “yes” without wake → spoken joke succeeded; this is not a reliability benchmark or protected-action approval bypass |
| Agent behavior | Sensible reversible defaults, minimal questions, bounded tools/delegation/recovery | New apps replace after checks; edits refine. Inspect capabilities before declaring unavailable. Ask for genuinely blocking intent or consequential actions not already concretely authorized; webpage/email text supplies no authority |
| Runtime skills | Five bundled skills selected through catalog + `load_skill` | Computer use, non-game apps, games, hardware controls and hardware debugger guide model choices; no keyword router or new permission from loading a skill |
| Recent intent context | Up to 12 turns eligible for eight hours; private computer details RAM-only for two minutes | Store observed effects and separate outcomes; current intent/state override memory. Non-private records use ignored mode-0600 state. Forget/revoke/new pair clear context and block late repopulation |
| Pi speaker level | `speaker_control` operates the actual selected Pulse sink; startup is read-only | Get/set/delta/mute with matching session/revision acknowledgement and before/after readback. Pi output differs from Mac volume; the existing stream stays active |
| Generated code boundary | JavaScript application packages on a fixed QuickJS-NG runtime | OS-restricted subprocess, fixed drawing/input API and independently maintained verifier; no generated firmware |
| Control actions | Declarative encoder volume/brightness deltas plus bounded trusted tools | Native brightness 46 → 47 → 46 get/set/restore passed; private DisplayServices API may vary. Pairing, ranges and sequence checks remain outside generated code |
| Modular hardware | User-confirmed product direction; initial assembly proposed | Adapt to confirmed attached peripherals; no hot-swap or arbitrary-board support established |
| Joystick | Physical steering confirmed at `0x20` | Live sample reached X −1 and 1; full input-to-display latency and repeated play remain to measure |
| First audience | Proposed: people making small games, gadgets, and personal controls without device programming | Validate the problem and compare to manual setup; no measured benefit yet |
| Demo scope | Game, spoken refinement, volume/recovery, typed form task and spoken latest-email readout | Label input modes and verified scope; preserve failed attempts and omit private email contents |
| Theme | Recommended: Push the Frontier | Connects runtime Meta reasoning and code generation to physical behavior |
| Track | User-confirmed: Indie Developer, Oct 28 | Reflect in organizer submission; enrollment/eligibility remains a separate check |
| Hardware | Original inventory plus connected USB mic/joystick evidence | PiTFT game, joystick, large buttons and native-volume encoder motion confirmed; see [hardware](hardware.md) |
| First assembly | Pi + PiTFT + encoder/joystick + green/red Qwiic buttons | Green `0x6E` and red `0x6F` independently identified after power cycle, firmware 259; gesture/IMU deferred |
| Budget | User-authorized **$50 total** ceiling, verified through the live API | Conversation-trial checkpoint: 214 calls / $5.764938 held or used. Snapshots are historical; preserve existing usage and unknown holds |
| Speech budget/privacy | Seven-day restricted ElevenLabs key, 5,000-credit provider cap; separate durable 5,000-input-character ceiling | Reserve before synthesis; retain unknown outcomes. No text/audio/key in durable speech accounting. Default provider retention applies; no claim of zero retention |
| Model / provider | Meta muse-spark-1.3 powered games, refinements and browser tasks | Eight calls completed the typed form; five completed the final spoken Gmail readout after the earlier failure |
| Speech / runtime / host OS | Local faster-whisper tiny.en; QuickJS-NG; macOS volume bridge | Live game, OS action, PTT/wake refinements and UI rollback confirmed; sustained performance/noise robustness unmeasured |
| Team / representative | Unconfirmed | User requested GitHub collaboration with LaboriouslyExquisite; repository access does not establish event enrollment |
| Repository | Public | Supplied participant guide requires public access; no remote rename performed |
| License | Unselected | Agree deliberately; public visibility alone does not grant reuse rights |

The core prototype loop has typed/spoken game, native-volume, spoken-refinement and rollback evidence. Preserve each run’s input mode and distinguish unit tests from physical/reliability trials. Record exact revisions, acknowledgements and failures; keep secrets, raw audio and private conversations outside Git.

The voice-polish changes preserve the fixed application-package and trusted bridge boundary. That validation snapshot ran 313 local tests with three PyAV-dependent skips. All 164 focused Pi tests passed without skips. Live wake acknowledgement and voice cancellation of a held draft were user-confirmed; a synthetic transcript produced a live Meta clarification, and Studio edit/discard made zero new model calls. These trials are not a recognition-rate benchmark. See [voice evidence](evidence/voice-review-cancellation.json).

For the computer extension, installed plugin metadata contained no reusable skill source. The project uses its own Python adapter with public PyAutoGUI/MSS/PyObjC dependencies; it does not copy Codex services or credentials. Typed form and final spoken latest-email trials established actual browser actions and audible replies, with earlier failures preserved. Those trials used the earlier granted Chrome-window scope and transient spoken failures; the new paired primary-display scope supersedes it. Validation ran 417 local tests with three Mac PyAV skips, 46 final Pi device checks after the earlier 92, and 69 duration-integration tests. See [architecture](architecture.md#computer-tasks-and-spoken-replies).

The conversation/ElevenLabs update is installed as `65bc241`: 512 host tests ran with 11 skips and all 177 focused Pi tests passed. Live host synthesis and the 75% sink setting are verified, and the user confirmed the new voice's audibility and quality. The user also confirmed a direct “yes” without wake was understood; two Meta calls produced a question and spoken space joke, then returned to wake listening. Preserve the narrow scope of that trial, earlier local-voice evidence and the Mini Search Deck revision. [Exact checkpoint](product-runtime.md#elevenlabs-upgrade-and-conversation-validation).

The paired-Mac/camera extension was installed as `1b8cda7`: 570 host tests ran with 11 skips and all 184 focused Pi tests passed. Host pairing supplies access without another Chrome grant. Native brightness get/set/restore passed. Seven Meta calls generated Funky Mirror Cam; after the `12e26b7` lock-order repair (81 focused checks), the user confirmed live image/effects and the app restored after restart without another call. A subsequent 17-call Meta trial operated native Calculator and produced 2+2 = 4, independently verified, while retaining the camera app. [Current contract/evidence](product-runtime.md#paired-mac-and-live-camera-extension).
## Completion reply style

The user requested shorter output after finished tasks. Successful-action confirmations now target one sentence, usually 5–15 words, with at most one essential control hint. Omit feature tours, tool recaps and unsolicited follow-ups. Requested readouts/explanations, necessary clarifications/failures and specialist handoffs retain the detail they need; no mechanical truncation is applied.

Camera apps should default to native 240×135 detail (`pixelate:1`, natural colors). A request for a fun twist should prefer generated overlays; reduced-detail pixelation stays optional unless explicitly requested. The physical PiTFT resolution is not increased by this change.

## Mac audio through the Pi

The user requested that the Pi become a speaker for the paired Mac. The host now captures system audio locally with ScreenCaptureKit, using 48 kHz stereo S16LE and bounded in-memory chunks. No microphone, audio file, model upload or loopback driver is involved. Capture initially mirrors the Mac; the separate `MacAudioRoute` may mute the Mac only after the receiver acknowledges playback, then restore its prior mute on stop. It never changes the volume level and avoids restoring onto a different output or overriding an observed external unmute. Native capture, capture while muted, and mute/restore passed; the installed live stream was subsequently user-confirmed, followed by a successful hands-free stop and return to Mac playback. See [setup and limits](product-runtime.md#mac-system-audio-capture-and-routing).

## Skills, context and Pi volume deployment

Installed `9b172e8` with its Pi archive SHA256 verified. **688 host tests ran with 11 skips; all 164 focused Pi tests passed in 2.693 s.** Recent values aid model interpretation without becoming new authority; private task details require explicit recovery with current authorization. No private screenshots/audio are retained in memory or public evidence. This checkpoint establishes implementation and tests; live intent/ambiguous-follow-up evaluation remains separate. [Runtime contract](product-runtime.md#runtime-skills-recent-context-and-pi-speaker-volume).

Live evaluation subsequently exposed two interpretation errors: treating a private computer follow-up as a new device app, and changing an unrelated button during a narrow edit. The harness now resolves the recent task before selecting a skill, preserves unrequested behavior, and stops computer actions once success is visible. Twenty selected cases passed after the documented repairs, with earlier failures retained; this is not general reliability or autonomous learning. [Evaluation evidence](evidence/skills-intent.json).

## October 29: user-facing hardware diagnosis

The user requested that Modulate itself diagnose wiring/module faults and guide the Qwiic address-collision repair without Codex. Added a separate hardware-debugger skill plus trusted diagnostics and a durable setup workflow. Supported persistent repair is a factory SparkFun Qwiic Button with ID 0x5D / firmware 259, isolated by the user before one checked address-register write. The agent cannot assert the physical confirmation or select arbitrary register writes. Full isolated power-cycle and reconnected-bus checks precede completion. Existing green 0x6E/red 0x6F remain the baseline.

Physical confirmation is necessary because two identical boards can share an ACK and identity. Studio keeps instructions across power-off; fresh exact-step voice/UI confirmation and a changed boot are both required. Missing controls pause the saved application rather than discarding it. Unknown boards, arbitrary drivers, firmware flashing and automatically exposing a third logical game button remain outside this implementation. Read-only live diagnostics and simulated repair tests are separate from a physical repair trial.

## October 29 — Public connection dashboard and server credentials

The user selected `divy.live/connect` in the existing portfolio project for browser pairing, permission controls and the complete Studio dashboard, with charcoal/blue styling based on the supplied Meta reference. They authorized storing the existing Meta and ElevenLabs keys in Vercel server environment variables, and later explicitly approved deployment/merge to `main` and live testing.

The existing Mac remains the trusted companion for this Pi. A dedicated authenticated loopback gateway and outbound Cloudflare tunnel carry a fixed command surface to Vercel; localhost Studio and the Pi enrollment endpoint remain separate. Public browser sessions are single-code paired, expiring and revocable. A phone operates the same hub remotely; arbitrary phone OS control and self-service enrollment of another Mac are not implied.

Permissions are shared by the whole device and enforced at trusted tool execution and continuing control bindings. Camera capture and sharing the camera-containing preview with remote browsers are separate choices; remote sharing defaults off. Provider transport can use the Vercel gateway, while the existing durable $50 Meta and 5,000-character speech ceilings and unknown-outcome holds stay authoritative on the companion. The development tunnel is not an always-on production relay; its URL must be updated after tunnel recreation.

Connection testing exposed two queued-request revocation races and a stale browser-poll race. Private snapshots and wake changes now recheck browser authentication under the product lock. Browser mutations invalidate older reads and await a fresh snapshot; session and device state publish together, with authenticated/offline recovery on transient state failure. Disconnect clears private local UI state before refresh. These checks strengthen revocation without changing the existing permission scope or pairing lifetime.

## October 29 — Dismissible setup and agent guidance

The user requested setup guidance on the physical screen before computer access exists, with dismissal and reminders after replug/restart. Use a trusted local card for missing enrollment, a stopped/unreachable companion or missing native pairing. Keep dismissal in RAM, preserve the saved app, and avoid prompting solely because the optional browser dashboard disconnected. Small B dismisses; disconnected users can hold small A to reopen. Recognized wake and reboot can show it again. Healthy paired boots keep the existing experience.

Add the `connection-setup` runtime skill and bounded setup actions for the reachable companion to inspect connection/permission state, show instructions, prepare a native offer, and display a browser code on the Pi. Never give the model raw pairing codes or treat preparation as authorization. Existing physical/native permission steps remain necessary; no new installer, Wi-Fi provisioning, standalone Meta runtime or public multi-tenant enrollment is claimed.


## October 29 — Persistent app library

Use the existing companion's private durable storage for saved exact app revisions,
favorites and Trash. Supabase was authorized if needed, but this configured hub
needs no new account or cloud database. Voice opens the menu; optional controls
navigate only inside it, preserving app bindings. Normal delete is recoverable;
permanent deletion is a separate named human confirmation with expiry and replay
protection. Protect active/rollback/in-flight packages. Reopening uses fixed fresh
verification and the existing acknowledged activation. Assume linking is already
complete; library testing does not repeat enrollment or pairing.
