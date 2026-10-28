# Decisions and open questions

Updated October 28, 2026. User-confirmed product direction is distinguished from engineering proposals and unverified capabilities.

### Implemented first experiment — October 28

The user narrowed the immediate build to speaking a random-number request and generating new code for the PiTFT. Implemented local Whisper tiny.en transcription and local Meta Llama 3.2:1b generation on the Pi 5, with a bounded Python-subset interpreter and checked application activation. PiTFT A starts six-second capture; B rolls back. The successful spoken trial produced 1008 in blue from new source in 12.65 s; one preceding attempt failed and preserved the old program. This is application hot reload, not firmware rewriting. See [setup/evidence](number-prototype.md).

Google was explicitly authorized as a temporary alternative. Authentication/model listing worked, but generation returned high-demand errors, so the tested default uses no external API. Google audio is unverified. The full game/host-pairing architecture below remains a proposal.

| Topic | Current position | Why / next step |
| --- | --- | --- |
| Product name | User-confirmed: **Modulate**, Oct 28 | Replaces Cruise; existing repository URL and workspace folder remain `cruise` |
| Core idea | User-confirmed, Oct 28 | Speak a request; a Meta-powered agent uses connected components/devices as context to generate and check software for the same physical hardware |
| Primary game experience | User-confirmed direction: generated game on the device screen | Supersedes phone-game control and the earlier music/video workflow as the main demo |
| Game scope | Proposed: original small 2D kart racer | Refines “make Mario Kart” to a finishable original game; actual rendering and gameplay untested |
| Second experience | User-confirmed direction: knob controls linked computer's volume | Website pairing plus a trusted host bridge proposed; OS, transport, and actual system-volume capability unverified |
| Voice | User-confirmed target: microphone with “Hey Meta” activation | Capture, speech recognition, and wake detection are separate unverified components; push-to-talk first, host mic/typed debug fallback explicitly labeled |
| Agent behavior | User-requested generation and verification; bounded tool loop proposed | Inspect capabilities, generate, run independent checks, repair within a limit, stage, activate; no successful execution yet |
| Generated code boundary | Engineering proposal: sandboxed game/application code on a fixed runtime | Preserves the code-generation goal; actual firmware rewriting remains a later ambition with no flashing/recovery design yet |
| Control actions | Proposed: versioned declarative bindings and allowlisted host bridge | Generated code gets no direct privileged host, driver, filesystem, or network access; exact isolation implementation still to select and test |
| Modular hardware | User-confirmed product direction; initial assembly proposed | Adapt to confirmed attached peripherals; no hot-swap or arbitrary-board support established |
| Joystick | Desired interaction, not confirmed inventory | Start with encoder steering; confirm any joystick before planning drivers or claiming support |
| First audience | Proposed: people making small games, gadgets, and personal controls without device programming | Validate the problem and compare to manual setup; no measured benefit yet |
| Demo scope | Proposed: on-device game, fresh spoken refinement, paired PC volume, recovery | Keep one complete physical loop; exact actions depend on tested hardware and host capabilities |
| Theme | Recommended: Push the Frontier | Connects runtime Meta reasoning and code generation to physical behavior |
| Track | User-confirmed: Indie Developer, Oct 28 | Reflect in organizer submission; enrollment/eligibility remains a separate check |
| Hardware | User-confirmed, Oct 28 | Pi 5 (8 GB), PiTFT, encoder, two buttons, sensors, speaker/mic, supporting parts; see [inventory](hardware.md). None bench-tested here |
| First assembly | Proposed: Pi + PiTFT + encoder + two Qwiic buttons | Resolve duplicate button addresses; defer gesture/IMU until basic input/display work |
| Budget | Unspecified; use owned parts first | No purchases or new spending authorized |
| Model / provider | Unconfirmed; Fireworks and Baseten discussed as candidates | Earlier application wording did not select or integrate either; verify one real call and exact model/API capabilities before choosing |
| Speech model / runtime / host OS | Unconfirmed | Verify capture, transcription, code isolation, display performance, and one real OS volume action before freezing the stack |
| Team / representative | Unconfirmed | User requested GitHub collaboration with LaboriouslyExquisite; repository access does not establish event enrollment |
| Repository | Public | Supplied participant guide requires public access; no remote rename performed |
| License | Unselected | Agree deliberately; public visibility alone does not grant reuse rights |

The October 28 revision changes product scope, not implementation status. No generated game, voice assistant, firmware, host bridge, provider integration, or measured performance has been demonstrated. Future decisions should record date, rationale, and evidence here; keep secrets, billing details, raw audio, and private conversations outside Git.
