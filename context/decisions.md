# Decisions and open questions

Updated October 28, 2026. User-confirmed product direction is distinguished from engineering proposals and unverified capabilities.

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
| Game scope | Pixel Kart Sprint from text; MODULATE: Self Assembly from speech | First-game controls confirmed; observed device rates about 13 fps. Further gameplay/performance testing remains |
| Second experience | Paired knob-to-Mac-volume demonstrated | User confirmed direction; live deltas and independent native reads confirmed OS values. Revocation/fault trials remain |
| General computer tasks | User-confirmed extension: actual cursor/keyboard operation, including email in the browser; no Gmail API | Native helper and Meta screenshot/action tools implemented; dependencies installed and permissions report granted. User authorized the native/screenshot trial; full operation awaits validation |
| Computer permissions/privacy | Separate explicit 15-minute grant, fresh observation per action and transient screen-derived answers | Volume pairing grants no cursor access. Model-requested consequential actions use Studio confirmation; semantic classification is not a jailbreak-proof boundary |
| Spoken replies | Local Pi eSpeak NG/paplay path implemented; standalone USB sentence heard by the user | Initial silent attempt preceded setting 40% and correcting a manual sink-name typo. Physical PiTFT B interruption and mic pause are implemented; integrated agent reply still to test |
| Voice | Native 48 kHz capture → PyAV resampling → local Whisper | Wake-only check after a 0.5-second pause keeps recording; full requests wait three seconds of silence. User confirmed the repaired wake acknowledgement. Ambient checks are passive; audio at 25 seconds is discarded |
| Request review and cancellation | User-requested voice polish | Separate three-second transcript review; Edit pauses sending, Send now submits, Discard cancels. Busy wake cancellation is implemented; a held request was cancelled by voice on the Pi with zero model calls |
| Clarification | Model-directed `ask_user` with next-reply context | One short question ends the agent turn; the next reply includes the original request and question. Preserve valid short answers; do not claim a numeric confidence threshold |
| Agent behavior | Live tools, bounded delegation and recovery demonstrated once | First game used 11 calls and coder delegation chosen after a malformed write; repeatability remains to measure |
| Generated code boundary | JavaScript application packages on a fixed QuickJS-NG runtime | OS-restricted subprocess, fixed drawing/input API and independently maintained verifier; no generated firmware |
| Control actions | Declarative encoder-to-volume binding plus allowlisted bridge | Generated code has no privileged host/driver access; fixed macOS actions validate values and sequence numbers |
| Modular hardware | User-confirmed product direction; initial assembly proposed | Adapt to confirmed attached peripherals; no hot-swap or arbitrary-board support established |
| Joystick | Physical steering confirmed at `0x20` | Live sample reached X −1 and 1; full input-to-display latency and repeated play remain to measure |
| First audience | Proposed: people making small games, gadgets, and personal controls without device programming | Validate the problem and compare to manual setup; no measured benefit yet |
| Demo scope | On-device game, fresh spoken refinement, paired PC volume and recovery; requested computer task/speaker extension next | Preserve established evidence. Add browser interaction and audible reply only after separate live validation |
| Theme | Recommended: Push the Frontier | Connects runtime Meta reasoning and code generation to physical behavior |
| Track | User-confirmed: Indie Developer, Oct 28 | Reflect in organizer submission; enrollment/eligibility remains a separate check |
| Hardware | Original inventory plus connected USB mic/joystick evidence | PiTFT game, joystick, large buttons and native-volume encoder motion confirmed; see [hardware](hardware.md) |
| First assembly | Pi + PiTFT + encoder/joystick + green/red Qwiic buttons | Green `0x6E` and red `0x6F` independently identified after power cycle, firmware 259; gesture/IMU deferred |
| Budget | Current product development ceiling: $5 for the local model-call ledger | Default zero; preserve reservations and require explicit authorization before raising the ceiling. No hardware purchase implied |
| Model / provider | Meta muse-spark-1.3 powered typed/spoken games and control refinements | Snapshot after typed Dodge Fall: 60 calls / $0.497411; later activity may change it. A cursor request was declined before the new computer adapter existed; its live path remains unvalidated |
| Speech / runtime / host OS | Local faster-whisper tiny.en; QuickJS-NG; macOS volume bridge | Live game, OS action, PTT/wake refinements and UI rollback confirmed; sustained performance/noise robustness unmeasured |
| Team / representative | Unconfirmed | User requested GitHub collaboration with LaboriouslyExquisite; repository access does not establish event enrollment |
| Repository | Public | Supplied participant guide requires public access; no remote rename performed |
| License | Unselected | Agree deliberately; public visibility alone does not grant reuse rights |

The core prototype loop has typed/spoken game, native-volume, spoken-refinement and rollback evidence. Preserve each run’s input mode and distinguish unit tests from physical/reliability trials. Record exact revisions, acknowledgements and failures; keep secrets, raw audio and private conversations outside Git.

The voice-polish changes preserve the fixed application-package and trusted bridge boundary. That validation snapshot ran 313 local tests with three PyAV-dependent skips. All 164 focused Pi tests passed without skips. Live wake acknowledgement and voice cancellation of a held draft were user-confirmed; a synthetic transcript produced a live Meta clarification, and Studio edit/discard made zero new model calls. These trials are not a recognition-rate benchmark. See [voice evidence](evidence/voice-review-cancellation.json).

For the computer extension, installed plugin metadata contained no reusable skill source. The project therefore uses its own Python adapter with public PyAutoGUI/MSS/PyObjC dependencies; it does not copy Codex services or credentials. Computer action tests are mocked; native permission status and standalone USB audibility are now confirmed, while full agent/browser/speech integration awaits testing. Dependency sources and limits are recorded in the [architecture](architecture.md#computer-tasks-and-spoken-replies).
