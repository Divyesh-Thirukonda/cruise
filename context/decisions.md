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

## October 29 — Expressive Muse state screens

The user requested Meta's cuddly Muse character across wake/listening,
instruction processing, spoken replies, building, error explanation and success,
without removing other screens. Use a custom local Pillow illustration based
on the official cream/peach mascot reference. Keep guidance readable and retain
the existing screen/control priorities. Talking follows real speaker playback;
celebration follows a matching durable device activation, never a model claim.
Animation is presentation only and adds no model calls. Setup, library and the
actual generated applications remain functional. [Visual provenance and state
mapping](muse-screens.md).

## October 29 — Include connection source in the submission repo

The user requested a clearly named folder containing only the connection webapp
code previously developed/deployed in the portfolio. Place it in
`webapp/connect-app-code`, with the complete UI, two Vercel routes, shared HTTP
helpers, existing tests and minimal standalone build files. Record source commit
and file hashes; leave the current portfolio deployment intact. Exclude personal
portfolio pages/assets, credentials and runtime state. Link the folder from the
main README so judges can inspect the complete connection implementation.

## October 29 — Quiet wake onsets and launcher control preferences

Treat reversing launcher scrolling as an ordinary saved preference, not a reason
to regenerate an app or edit drivers. Add a bounded trusted library operation and
expose its current value and observed before/after values to the agent. When the
library is open, an unqualified knob-direction request targets that menu; explicit
game or host-control targets still win. Preserve the active package and controls
outside the library, as well as stale-action and deletion safeguards.

For missed wake phrases, increase local pre-roll from 250 to 600 ms and lower
Silero speech onset/end thresholds from .50/.35 to .35/.20. Keep explicit anchored
Hey Meta matching, recognizer silence rejection, the three-second request pause,
speaker guards and cancellation. Microphone capture was already enabled at 75%
with automatic gain control; do not increase gain blindly. Synthetic recovery of
a delayed quiet onset is evidence for the capture fix, not measured wake accuracy.

## October 29 — Dedicated connection deployment

The user requested that Modulate leave the personal portfolio and deploy directly
from this GitHub repository. Use Vercel project `modulate-connect`, production
branch `main`, root `webapp/connect-app-code`, at
`https://modulate-connect.vercel.app/connect`. Preserve the same dashboard and
server routes. Keep the provider destination explicitly pinned, update host/Pi
setup links together, and retain the existing companion, tunnel, app library,
pairing state and spending ledgers. The new hostname needs a new host-only browser
cookie; it does not require re-enrolling the Pi or resetting native permissions.

Preserve original portfolio source hashes as provenance alongside current hashes.
After validating the standalone production path, revert only the portfolio's
Modulate feature commits and redeploy its main branch. Do not reset shared Git
history or discard unrelated portfolio work.

## October 29 — Guided connection flow and portable setup skill

The user requested a simpler React/Next.js experience that exposes one useful
step at a time. Use a minimal first-visit introduction and connection-code form,
then a separate access review, then Studio. Do not show workspace navigation or
permission switches before the browser connects. Returning valid sessions open
Studio. Put native connections, hardware and sound in **Device**, choices in
**Access**, saved apps in **App library**, and detailed activity/source under a
**Developer tools** disclosure. Keep active cancellation/stop controls reachable
even outside Studio.

Browser linking must preserve the device's current access settings. The access
step reads those settings and saves only changed values; keeping current access
does not send a permission update. Changes still apply device-wide and do not
substitute for macOS permissions. Reorganizing these screens does not justify
re-enrollment, new native pairing or resetting existing libraries/ledgers.

Replace the Create React App shell with Next.js 16.4.3 and React 19.3.1, retaining
the current authenticated server gateway behind Next.js route adapters. Preserve
original portfolio source hashes alongside current hashes. This remains the
dedicated Modulate deployment, with no portfolio dependency.

Put initial installation instructions on a separate setup page with a copyable
coding-agent prompt and optional downloadable skill package. The skill discovers and
repairs existing setup before creating replacements, preserves private state,
and guides human hardware/OS steps. Downloading a plugin does not automatically
install native services or grant access. The public site serves one configured
hub; a different user's Mac/Pi needs its own runtime and remote deployment.
Do not imply a signed installer, automatic permission grants or self-service
multi-tenant enrollment.

The user clarified that setup should work with their choice of coding agent.
Use portable Markdown instructions as the default path: open the folder, read
`skills/modulate-setup/SKILL.md`, and follow it with local file/command tools.
Optionally install through the agent's own skill mechanism. Keep the existing
Codex manifest/catalog installer as a separately documented optional adapter;
do not represent it as universally compatible or require it for setup.

## October 29 — Preloaded gadget setup without customer shell access

The user confirmed that customer setup assumes factory-loaded Modulate software.
The customer and their coding agent work on the Mac and use the device screen;
Raspberry Pi Connect, developer accounts, historical IPs and SSH-key installation
are not onboarding dependencies. Add a narrow enrollment service with a physical
certificate identity, expiring setup code and separate fresh button confirmation.
Keep native Mac pairing and browser sessions distinct, preserve all saved state
and spending, and report older device software as a factory-update requirement.
Initial network provisioning and a finished OS image remain separate work.
The user authorized a one-time developer-shell update of this test gadget only.

## October 29 — Agent-owned Mac setup with observable completion

The user's setup-chat report is evidence to verify, not an instruction set.
Agents should perform authorized Mac/browser setup, recheck live state before
retries or handoffs, and reserve physical button/required OS interactions for
the customer. Preserve valid enrollment and pairing when diagnosing another
layer. Local online pairing is a valid connection finish; a remote browser code
is needed only for requested, configured remote access. Report feature warnings
separately rather than declaring a connected gadget fully ready.

Display device-initiated native comparison codes only through an authenticated
local Studio read, never normal state, model context or remote gateway output.
Explain bounded error causes where available; legacy missing reasons remain
uncertain. A reported identity typo requires physical verification and never
automatic trust in the network certificate.

## October 29 — Website is the customer destination

The user superseded the earlier default of finishing customer setup in local
Studio. Keep that console as a developer tool, while customer setup uses the
minimal Mac `/setup` comparison/handoff screen and returns to the installation's
website `/connect` form. An explicitly local-only use can still stop locally;
the website journey is not complete until its own session and device state work.
Preserve valid sessions and native pairing rather than replaying onboarding.

Handle remote transport configuration through the setup agent and existing
private installation settings. Do not redirect arbitrary new Macs to an
unrelated shared hub, claim connection from configuration alone, or pass codes
in URLs. Show one next action, recover in place after restart/expiry/clipboard
failure, and keep genuine physical/OS confirmation requirements visible.


## Website cube identity and triad palette — October 29, 2026

- Keep a rounded isometric cube around the impossible-triangle logo. The mark
  remains monochrome; red `#F01E27`, blue `#1DAAF0` and yellow `#F0EB1D` apply
  only to local/public web UI. Generated programs and Pi character screens retain
  their colors.
- Use blue for primary controls, yellow sparingly for highlights/warnings and
  red for destructive/error accents, on neutral readable surfaces. The selected
  generated raster and its provenance/prompt are documented in `branding.md`.
- Keep customer flow, pairing, permissions and all runtime budgets unchanged.


## Programmatic logo direction — October 29, 2026

The user requested simple programmatic logo construction instead of further image
generation. Use editable SVG geometry with identical repeated sections. The new
`assets/brand/` study is a draft; the deployed identity remains unchanged.

## Approved production logo — October 29, 2026

The user selected programmatic revision 16 as Modulate's logo. Use its exact
three identical filled cube modules on the public website and local web
surfaces. Prefer the transparent SVG for wordmarks and a dark tile behind the
same geometry for favicons. This supersedes the earlier generated logo choice;
the website-only red/blue/yellow palette remains unchanged.

## Later means leaving connection setup — October 29, 2026

A user may decline setup without being sent into another connecting screen.
Dismiss the whole episode until explicit setup reopening (hold-A or a local
setup voice command) or a later boot; an
ordinary wake/request is not setup intent. Return to the current local app or
neutral idle state. Distinguish optional native Mac control from the prototype's
current companion-hosted AI; do not imply that hiding setup adds standalone AI.


## 2026-10-29 — Pi owns normal AI operation

The user asked to remove the running-Mac dependency and use the Pi's Wi-Fi plus
the existing Vercel deployment. Run the trusted agent/library/speech coordinator
on the Pi with loopback pinned TLS to the device runtime; keep Meta/ElevenLabs
API keys in the existing Vercel gateway. Browser linking is optional. Move both
cumulative ledgers intact, freeze the stopped Mac's old copies, and refuse
missing/malformed/migrated accounting on standalone startup. Preserve the $50
total model ceiling and unknown holds. The user explicitly approved a 10,000
cumulative speech-character ceiling; the separate provider cap is unchanged.

The current installation supports local apps, replies and speaker control without
Mac pairing. A separate native Mac bridge is not yet connected. The dashboard
still uses a development Quick Tunnel with a hostname that changes on restart;
direct Pi AI is independent of it. Do not claim either limitation is solved.
[Deployment, trials and safeguards](standalone.md).


## 2026-10-30 — Increase cumulative speech allowance to one million

The user explicitly requested 1,000,000 speech characters. Applied
`MODULATE_TTS_CHARACTER_LIMIT=1000000` to the Pi's private service configuration,
retaining the existing 5,011 reserved characters and all five uncertain requests.
This is a persistent installation-wide allowance across replies/restarts, not a
per-request or API-key quota. Provider key/account limits and the $50 model
ceiling were not changed. Repeated-operation failure feedback now distinguishes
an unsuccessful attempt from a usage quota; bounded repair loops remain intact.


## 2026-10-30 — Pi-owned AI with optional native Mac access

The Pi remains sole AI/speech accounting owner. Native computer controls use an
optional Mac helper with no model credentials or ledgers. The helper connects
outbound over pinned local TLS; a fresh physical comparison-code confirmation
creates the revocable eight-hour grant. Temporary reconnects preserve its original
expiry. Commands consume persisted sequences before execution and uncertain
outcomes are not replayed. Browser linking remains separate and optional.

Use the existing scoped gateway secret for signed tunnel registration and endpoint
identity proof, storing only one origin/timestamp in private Vercel Blob. Never put
Vercel admin access on the device. A changing development tunnel may cause a brief
website outage (121.738 seconds to registration in the recorded trial); device AI
and native LAN controls do not depend on it. This registry serves one demo Pi.

Code comparison and pairing do not replace native OS permissions. Brightness was
verified through the Pi agent; the background helper still needs Screen Recording
and Accessibility for desktop actions. Camera/audio and physical knob brightness
across this link are not yet live-validated. See [scope and evidence](optional-mac.md).


## 2026-10-30 — Local MMS and website-managed native Mac access

Use the pinned official Meta MMS English VITS checkpoint on the Pi as the active
speech provider, following the user's explicit choice. Keep the ElevenLabs ledger
unchanged for rollback; MMS makes no paid TTS requests or cumulative reservations.
Keep bounded per-reply resources, cancellation and the separate $50 Meta ceiling.
The offline speech subprocess receives no provider credentials. The checkpoint's
CC-BY-NC-4.0 license is recorded in [the operating note](meta-mms.md).

Use Modulate.app as the stable responsible macOS app for the native helper and
permission prompts. The user enabled Screen Recording, Accessibility and Camera.
Use the authenticated Vercel setup page for native comparison/status; expose the
comparison code only to the linked browser, and retain physical small-A approval,
revocation and the original eight-hour expiry. The localhost page is diagnostic.
The user does not need a Mac for Pi generation or speech. Native Mac actions need
the paired helper running with OS grants. Camera frames remain outside model input.

The earlier unverified camera/audio note above is superseded by fresh capture and
stop telemetry in [the new evidence](evidence/mms-native-runtime.json). That trial
does not establish physical camera-display/audio-playback quality or broad desktop
reliability. No physical brightness-knob trial was performed in this session.

## October 30 — capabilities determine app controls

The user's product intent is standalone operation that adapts to connected hardware. A package's controls are its dependencies, not a fixed product inventory. Preserve a disconnected app while permitting an independently checked replacement. A suspended local game may trigger one debounced Meta adaptation per revision/control set, persisted before dispatch, with no privileged tools and existing ledger limits. A user request can always explicitly refine the interaction.

Trusted drivers identify supported modules and expose bounded signals/units; Meta chooses the game's mapping from current capabilities and intent. No fixed joystick/encoder/IMU preference order. New module discovery makes capabilities available without silently redesigning a healthy app. LSM6DS3TR-C now exposes acceleration, angular velocity and gravity tilt; live samples remain outside manifest hashes. Unidentified hardware still needs a trusted driver/contract, and no absolute position/heading is implied. [Implementation and physical evidence](adaptive-controls.md).

## October 30 — supported driver installation belongs to the Pi agent

The user authorized closing the missing-driver setup gap. Expose a fixed installer through hardware-debugger, separate from generated apps and computer-shell tools. Begin with the owned LSM6DS3TR-C: independently read chip identity, install hash-pinned official Adafruit wheels into a private pack, require real samples before commit and verify the pack on startup. Preserve base dependencies, existing app revisions, cancellation and the $50 ledger. An ordinary requested setup/repair needs no extra installation question for a verified catalog entry.

Meta chooses whether installation serves the request and chooses app mappings afterward. Unknown modules still need identification, a reviewed driver pack and an input contract; do not describe this as arbitrary driver synthesis. Automatic app adaptation retains only local app tools. Button-address repair still requires its physical isolation/power-cycle confirmations. The user is currently away from the device: complete remote verification while recording physical checks as unperformed. [Verified scope and live trial](driver-setup.md).

## October 30 — layout cleanup and preserving an existing Mac session

The UI review keeps the existing information architecture and product behavior. Setup cards have explicit spacing, quiet actions retain padding without acquiring a hover border, Device action rows align at the bottom, and the Studio preview must shrink within its card. Route changes reset the workspace scroll container.

A network-address change can reconnect the installed Mac helper within an existing valid grant after independently matching the Pi certificate to its saved pin. Change the address only; preserve token, sequence, OS permissions, expiry and revocation. This session's reconnection used that path. It did not implement automatic Mac address discovery or remove the physical check for a fresh/expired pairing.


## 2026-10-30 — Bound demo recovery and replace quota-exhausted discovery

- Use a shared 32-call agent budget with parent completion reserve, partial specialist handoffs and at most two cancellable transient inference retries. The million-character historical speech allowance is unrelated to agent turns. Do not remove spending or effect-replay protections.
- Replace the single-address Vercel Blob discovery record with Cloudflare Workers Free plus a SQLite Durable Object. Store only hostname/timestamp; derive a registry-only HMAC credential from the existing gateway secret. Preserve independent Pi identity proofs and expiring sessions. Deployment is pending explicit Wrangler authorization; do not label the migration live until verified.
- During the Blob quota outage, use the already-supported direct, identity-verified tunnel configuration as a temporary website recovery. Re-enable dynamic discovery after Cloudflare registration and session continuity are tested. No paid plan, new model provider or device-agent relocation is needed.


## 2026-10-30 — Reuse real creations for repeated requests

- Meta decides semantic reuse from bounded saved-app metadata before generation; a saved launch retains trusted verification, capability checks and activation acknowledgement. Explicit new versions generate; edits refine. Report reuse honestly rather than fresh generation.
- Present the latest saved revision per title by default while retaining all source, favorites, Trash and rollback history. Expose older versions explicitly on the website; do not destructively merge same-title packages.
- Optimize computer-task round trips generically, retaining fresh observations and current access. Do not cache private answers or hardcode the demo script. The under-15-second target applies to measured runs, not a blanket performance claim.


### Cloudflare activation

- Wrangler authorization and live rotation succeeded. Dynamic Cloudflare discovery is active; the temporary direct-address mode is no longer used. Remove the legacy Blob dependency/fallback to prevent accidental future quota use. Temporary tunnel changes still take roughly a minute to recover in this trial.
