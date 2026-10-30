# Local Meta MMS speech

Modulate uses Meta's public English `facebook/mms-tts-eng` VITS checkpoint on the
Pi CPU. It runs in a separate `.venv-mms` environment, using PyTorch 2.9.1,
Transformers 4.57.6 and NumPy 2.2.6. No ElevenLabs call or character reservation
is made by this provider. Existing ElevenLabs accounting is retained unchanged;
the separate $50 Meta request ceiling still applies.

## Installation and contract

Run `python3 scripts/install_mms_tts.py` on the Pi. The script downloads only JSON,
README and safetensors files at revision
`c71de0fe7204c83f1c10820a7d696d0b450048ba`. The safetensors SHA-256 is
`69cf8b651c1493f1801dfd2311c298d694a38357bc9a1e41f410491ea6f0e1be`;
the worker checks it before loading. Runtime loading is offline, local-only and
uses safetensors, with two CPU threads. No remote model code is loaded.

Configure the private Pi provider file with `MODULATE_TTS_PROVIDER=meta_mms`,
`MODULATE_MMS_PYTHON=/home/pi/modulate-product/.venv-mms/bin/python` and
`MODULATE_MMS_MODEL_DIR=/home/pi/modulate-product/brain/models/mms-tts-eng`.
Restart the agent and device after installing the updated modules. Existing
`elevenlabs` and `local` providers remain explicit rollback choices; errors never
silently switch voice providers.

The persistent isolated worker produces native 16 kHz speech and resamples it to
the existing authenticated 24 kHz mono PCM transport. Text/audio stay in memory.
Replies retain the existing 1,200-character and 90-second per-reply bounds to
prevent resource exhaustion. There is no cumulative MMS character allowance.
Cancellation kills the active worker and discards late results; the next reply
loads a fresh worker. Ordinary replies reuse the loaded model. Numbers are
expanded before the English tokenizer so brightness values are not dropped.

## Physical evidence, October 30

On the user's Wi-Fi-connected Pi 5, cold synthesis took 8.265 seconds for
3.600 seconds of PCM. A second sentence took 5.887 seconds for 5.920 seconds of
PCM. These are two synthesis measurements, not full voice latency or a benchmark.
The user confirmed clear speech from the product's speaker test. Subsequent
Gmail-task speech reported `meta_mms/paplay`, `delivered`, with no speech error.
The historical character ledger retained its exact SHA-256 across both replies.

## Reused work and license

[Meta MMS English model](https://huggingface.co/facebook/mms-tts-eng) and its
[VITS integration](https://huggingface.co/docs/transformers/model_doc/vits) are
third-party work. The checkpoint is **CC-BY-NC-4.0**, a noncommercial license;
it is not a commercially unrestricted replacement. This project supplies the
isolated worker, PCM transport integration, cancellation, provider selection,
number normalization, installation and device validation. No voice training or
model architecture is claimed as project work.


The final worker environment contains only fixed locale/path and offline flags;
provider credentials are not inherited. A real Pi synthesis with this environment
returned 47,616 PCM bytes, followed by a successful agent restart.
See [sanitized deployment and native tests](evidence/mms-native-runtime.json).
