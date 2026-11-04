# Meta speech recognition

Current source uses Meta's public English `facebook/wav2vec2-base-960h` for
local wake recognition, voice cancellation, and explicitly selected local command
transcription. The existing `muse-voice-transcribe-1.0` gateway remains available
for invoked requests. Ambient audio stays local; this change does not upload
continuous microphone audio or increase either spending ceiling.

## Installation

From the repository root on the Pi, using Python 3.11:

```sh
python3.11 scripts/install_meta_asr.py
.venv/bin/python -m pip install -r requirements-product-pi.txt
python3.11 scripts/install_mms_tts.py
```

The first script creates `.venv-asr`, downloads the pinned recognition weights
and the standalone activity detector, and checks their SHA-256 digests. The last
script installs Meta MMS for spoken replies, now the default. Installation is an
explicit online operation; inference only loads local assets. Stop the services
before changing their dependencies, then restart them after installation.
No script changes private credentials, pairing, active games or cost ledgers.

Recognition uses revision `22aad52d435eb6dbaf354bdad9b0da84ce7d6156` and
`model.safetensors` SHA-256
`8aa76ab2243c81747a1f832954586bc566090c83a0ac167df6f31f0fa917d74a`.
Default paths are `.venv-asr/bin/python` and `brain/models/wav2vec2-base-960h`.
An explicitly configured device process may override them with
`MODULATE_ASR_PYTHON` and `MODULATE_ASR_MODEL_DIR`. No provider key is needed.

## Runtime boundaries

A persistent CPU subprocess owns the model, with two inference threads and one
interop thread. Its environment contains only fixed path/locale and offline
flags. It receives bounded mono 16 kHz PCM through pipes and returns bounded JSON
text. No remote code, pickle weights, prompt bias or alternate provider is used.
Loading and inference share a 30-second deadline; cancellation interrupts blocked
pipe writes and reads, terminates the worker and discards the result. A later
request starts a fresh worker after failure. A missing model fails visibly.

Native 48 kHz capture, PyAV resampling, 600 ms pre-roll, three-second end silence,
25-second discard, anchored wake matching, exact cancellation phrases and epoch
checks remain. Greedy CTC rejects blank/low-confidence output; digital silence is
rejected before waveform normalization. These are defensive checks, not a
measured false-trigger rate. Model calls remain outside the game's input loop.

## Explicit non-Meta exception

Silero 6.2 remains the local speech-activity detector. It classifies speech
boundaries and does not generate or transcribe content. The previous simple
energy detector failed in the physical prototype; no comparable small Meta
streaming detector was verified for this device. Retaining this component avoids
claiming that an untested energy threshold is an equivalent replacement.

It is installed independently from the pinned upstream commit
`be95df9152c0d7618fa1edfeb296fc3dae32376f`, file
`src/silero_vad/data/silero_vad_16k_op15.onnx`, SHA-256
`7ed98ddbad84ccac4cd0aeb3099049280713df825c610a8ed34543318f1b2c49`.
ONNX Runtime uses one CPU thread and caller-owned recurrent state. Model loading
and malformed output fail closed; no automatic energy-based replacement exists.

## Verification and deployment status

[Development-host evidence](evidence/meta-speech.json) records actual local Meta
inference on clips synthesized by Meta MMS, plus silence and noise controls.
Command words were recognized, but synthesized “Hey Meta” was misheard. A larger
Meta checkpoint was also tried and did not resolve that issue, so the smaller
checkpoint remains selected. The historical Muse comparison already showed this
synthetic wake problem; it is not evidence about a person speaking in the room.

The new recognizer has **not been installed or tested on the physical Pi**.
Physical wake recognition, cancellation, CPU latency and room-noise behavior need
fresh trials. Prior physical timings and success records describe the earlier
speech stack, not this replacement. Push-to-talk avoids wake-word detection but
still requires a physical end-to-end retest. No audio was captured or played in
the development verification, and no paid API calls were made.

The legacy number prototype now only supports local Meta Llama generation and
this Meta speech worker. The Gemini implementation was removed. Product voice
output defaults to Meta MMS and rejects the retired external provider selection;
explicit OS speech remains a diagnostic option. Historical speech billing code
and ledgers remain for migration/accounting, without resetting their values.
Ollama and partner agent adapters accept only the configured Meta model families;
their presence does not imply every model identifier has live account access.

## Reused models and libraries

- [Meta wav2vec 2.0 checkpoint](https://huggingface.co/facebook/wav2vec2-base-960h): Apache-2.0, 94.4 million parameters, English 16 kHz ASR.
- [Meta MMS spoken replies](meta-mms.md): separate model and noncommercial license.
- [Silero VAD](https://github.com/snakers4/silero-vad/tree/v6.2): MIT; the installer saves its license with the asset.
- PyTorch 2.9.1, Transformers 4.57.6, NumPy 2.2.6, ONNX Runtime 1.23.2 and PyAV 12.3.0 are reused libraries, not new event contributions.

The project contributes the bounded worker protocol, lifecycle integration,
installation/checksum checks and tests. It does not claim model training.
