# Muse Voice Transcribe for invoked requests

The integration uses `muse-voice-transcribe-1.0` for command recognition through
Meta's recording endpoint. It is speech recognition, separate from the Meta
agent reasoning/generation and local Meta MMS spoken replies.

## Audio path

The Pi keeps native 48 kHz capture, local 16 kHz resampling, Silero activity
checks and cached Whisper `tiny.en` wake recognition. A confirmed wake command,
explicit push-to-talk recording, or active clarification answer may use Muse
ASR. Ambient wake checks, computer-media rolling wake checks and busy voice
cancellation stay local. Late recognition cannot deliver a command after an
epoch change, stop, mute or replacement. A locally recognized cancellation does
not wait for cloud transcription.

Invoked PCM goes through the existing enrolled, pinned-TLS device connection to
the trusted Pi agent. It checks voice permission, reserves estimated audio cost
in the existing shared ledger, wraps at most 25 seconds of mono 16-bit 16 kHz
PCM in a canonical WAV, and calls the fixed provider gateway. Vercel converts the
bounded payload to Meta's documented multipart `request` + `audio` form and sends
it to `https://api.meta.ai/v1/asr/transcribe` in `PUSH_TO_TALK` mode. This mode also
fits hands-free utterances because local capture already establishes the end.
The provider key remains in Vercel; no new key is installed in device firmware,
browser code, generated apps or Muse chat. The ASR adapter does not log or save audio/transcripts; accepted requests follow
the existing command-history policy. Meta's own data handling still applies.

Muse receives product-name vocabulary hints only (`Modulate`, `Meta`), with no
preset demo commands or game outputs. The transcript enters the same existing
review, agent, check and activation path. No new app is executed by ASR alone.
The current three-second capture silence and transcript-review windows remain;
this is not yet a realtime endpointing integration or a wake reliability claim.

## Selection, cost and failure behavior

Set `MODULATE_ASR_PROVIDER=meta_muse` in the trusted agent's existing private
provider file and restart the agent. The authenticated heartbeat selects the
command recognizer on the device; an absent setting selects `local`. Rolling
back to `local` does not change stored apps, pairing, Muse authorization or any
ledger. No additional dependency or permanent credential is introduced.

Verified pricing is $0.18 per processed audio hour, metered in whole seconds.
We reserve 50 microdollars per rounded-up input second under the existing $50
total ceiling, settling from the validated returned duration rounded down to
whole seconds. The response may include up to one 80 ms processing frame of
padding; the input-second reservation still covers its whole-second cost. An
uncertain call retains its reservation. Audio time is separate
from text tokens and the historical ElevenLabs character ledger. No cap is reset
or raised. Calls do not automatically retry or silently switch to local ASR.
A failed request reports a generic transcription error and is discarded so a
late or duplicate request cannot unexpectedly operate the device. Wake detection
continues locally afterward; typing in Studio remains available.

A live 1,000 ms fixture initially returned 1,040 ms from Meta and exposed an
overly strict duration check; the final adapter accepts one bounded 80 ms frame
and keeps billing reservations conservative. The multipart JSON part follows
the official no-filename contract, and decimal integer duration strings are
normalized before validation.

Provider processing times out after 10 seconds in the gateway, 12 seconds in the
agent and 15 seconds in the pinned device client. Bounds, fixed destinations,
response projection, no retries, late-result rejection and permission checks
have focused synthetic coverage; physical room recognition remains separate.

## Live comparison on the Pi — October 30

The existing account accepted live `muse-voice-transcribe-1.0` requests. Three
in-memory Meta MMS synthetic clips (3.488s, 2.704s and 3.008s) were sent directly
to ASR, never played or executed. Muse took 1.448s, 1.000s and 1.100s including
the gateway network round trip; cached local Whisper took 0.955s, 0.895s and
0.939s excluding model loading. Synthesis/capture/silence/review/agent time is
excluded from both. These samples added $0.000400 to the existing ledger.

Muse was slower in this small sample, and both recognizers misheard the MMS
voice's synthesized wake phrase. This does not establish improved accuracy,
physical wake recognition, room-noise robustness or end-to-end task speed.
The useful integration boundary is invoked command transcription while wake
remains local. The sample text and measurements are in
[evidence/muse-voice-transcribe.json](evidence/muse-voice-transcribe.json).

The local Python suite passed 1,156 tests with 13 platform skips before the
additional focused late-result/transport/padding checks, which also passed.
The Pi passed 199 focused checks and all 13 final ASR checks. The website passed
63 API checks, 42 UI checks and its production build.

The Pi's existing private provider configuration now selects `meta_muse` for
invoked commands. After agent restart, the complete VoiceListener → pinned
Companion TLS → agent/gateway → live Muse path returned a synthetic PTT command
in 1.182s and delivered it to an isolated callback. No device command was
executed, audio was not played, and the current game and speaker volume were
unchanged. The shared ledger retained its $50 ceiling and was not halted.
The separate native Mac and seven-day Muse connector grants were unchanged.
A person speaking through the physical room microphone remains untested for
this new ASR path.

## Sources and reused work

- [Meta speech API guide](https://dev.meta.ai/docs/speech-to-text)
- [Meta model list](https://dev.meta.ai/docs/models)
- [Meta pricing and rate limits](https://dev.meta.ai/docs/pricing-rate-limits)
- [Meta reference cookbook](https://github.com/meta-models/meta-model-cookbook/tree/main/06_muse_voice/01_voice_api_fundamentals)

This project adds the ASR adapter, bounded device/gateway transport and invocation,
permission and ledger integration. It reuses Meta's hosted recognition model,
existing local Whisper/Silero and MMS models, and the project's existing TLS,
credential gateway and durable ledger. No model training is claimed. The adapter
was implemented independently from the official API documentation; no cookbook
source was copied into production.
