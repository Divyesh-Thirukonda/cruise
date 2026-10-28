# Voice-to-number prototype

Built October 28, 2026. This is the first small implementation, separate from the larger game/pairing plan. It generates and activates **application source**, not boot firmware or peripheral firmware. The Pi runs Raspberry Pi OS/Debian 12, Python 3.11, a 135×240 Mini PiTFT and a USB PnP microphone.

## Use the installed Pi

The installed directory is `/home/pi/modulate-prototype`. The running user service is `modulate-prototype.service`.

1. Press the small **A / GPIO23** button on the PiTFT board itself. External red/green Qwiic buttons are not used by this prototype.
2. Wait for **Listening**, then speak within six seconds: “Show a random number between one and one hundred in green.”
3. The display shows transcription/generation status, then the number and source-hash prefix. The default speech model is **Whisper tiny.en**, running locally. **Meta Llama 3.2 1B**, through the Pi's existing Ollama installation, generates the program locally.
4. Press A again for a fresh request, such as “Now make the range 1000 to 2000 and use blue.” Previous source is provided as context.
5. **B / GPIO24** restores the previous committed program and its previously displayed number. It is a rollback, not a fresh model call.

Recording begins only after A is pressed. Temporary WAV files are deleted after reading; recording bytes are discarded after transcription. A private local transcript is kept in `state/last-request.txt` for debugging. Code candidates, active source, driver preview and sanitized events are also private local state, excluded from Git. No wake phrase or continuous ambient recording is implemented.

From Raspberry Pi Connect's remote shell:

```sh
systemctl --user status modulate-prototype
systemctl --user stop modulate-prototype
systemctl --user start modulate-prototype
journalctl --user -u modulate-prototype -n 30 --no-pager
```

This is a transient user service, not boot-enabled. After a reboot, start it again:

```sh
systemd-run --user --unit=modulate-prototype \
  --working-directory=/home/pi/modulate-prototype \
  /home/pi/modulate-prototype/.venv/bin/python -m modulate \
  --state-dir /home/pi/modulate-prototype/state --trigger button
```

## How regeneration works

Each deliberate request makes a live model call. The model writes a new Python-subset program using integer assignments, arithmetic, comparisons, `randint`, and one final `show` call. This is not preset selection: the generated source determines the range, calculation, label and colors. The trusted runtime's random-number capability supplies the random draw; the language model writes the program rather than being treated as a uniform random-number generator.

The source is parsed and interpreted by our own small interpreter. It is **never passed to Python `exec`, `eval`, imports, a shell, or a firmware flasher**. Imports, arbitrary functions, attributes, loops, file/network access and direct GPIO access are rejected. Static and dynamic limits cap source length, syntax depth, operations and integer/output sizes. This deliberately limited language is not a sandbox for arbitrary Python applications.

There are at most two generation attempts. Failed checks go back to the model once for repair. Valid source is hashed, saved as an immutable `.py` revision, executed to produce a bounded frame, and sent through the trusted display driver. Only a matching driver acknowledgement commits `active.json` with an atomic file replacement. The previous committed revision survives rejected programs, failed activation and interruptions. That acknowledgement establishes driver completion; the TFT has no optical readback. A physical screen check is separate evidence.

`state/candidate-*.json` contains actual model responses, including rejected ones. `state/<sha256>.py` contains activated source. `state/events.jsonl` records provider/model, checks, revision, result and timing without credentials or full transcripts. `state/screen.png` is a software preview of the latest frame, not a photograph.

## Reproduce setup

Use an existing Pi OS installation; do not reimage the SD card. Enable SPI and I2C if not already enabled, following the official Raspberry Pi/Adafruit instructions. This prototype only uses SPI and the TFT's own GPIO buttons; it does not change the Qwiic bus or resolve the two external buttons' address collision.

```sh
sudo apt install python3-venv python3-pil python3-lgpio alsa-utils
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements-pi.txt
ollama pull llama3.2:1b
.venv/bin/python -c 'from faster_whisper import WhisperModel; WhisperModel("tiny.en", device="cpu", compute_type="int8", cpu_threads=2)'
arecord -l
.venv/bin/python -m modulate --display-test
.venv/bin/python -m modulate --state-dir context/private/runtime --trigger button
```

Ollama was already installed on the tested Pi. For a fresh device, use its [official installation instructions](https://docs.ollama.com/linux) and [Meta model page](https://ollama.com/library/llama3.2:1b). Review the applicable model license. Models are downloaded during setup, not hidden behind a live request. Once cached, the default capture/transcription/generation path requires no external API call.

The tested microphone is ALSA `plughw:CARD=Device,DEV=0` (card 3 during bring-up). Select the actual device using `--audio-device` if its stable card name differs. Capture is mono, signed 16-bit PCM at 16 kHz. `--seconds` accepts 1–10. The display uses hardware SPI0 CE0, DC GPIO25 and backlight GPIO22, with offsets 53/40 and landscape rotation90. On this Pi, Linux owns CE0: the Adafruit driver uses `cs=None` so hardware SPI toggles CE0. No custom GPIO5 wire or boot-configuration change was needed. Do not copy the older lab's GPIO5 assumption to stock wiring.

For typed debugging (clearly distinct from voice):

```sh
.venv/bin/python -m modulate --prompt 'Show a random number from 1 to 100 in green'
```

For a preview without GPIO, add `--simulate`; an actual model provider is still required. For one immediate microphone recording, use `--once`. Stop the service first so only one process uses the screen/state directory.

## Optional Google development path

The Google adapter targets the documented `gemini-3.8-flash` Interactions API. Key authentication/model listing succeeded during setup, but live generation returned HTTP503/high-demand errors (and a generateContent probe timed out). **Google audio transcription is not verified.** There is no automatic provider fallback.

To explicitly select it later, supply `GEMINI_API_KEY` on the trusted Pi process or in an owner-readable `chmod 600` environment file, then use `--provider google --speech google --env-file /private/path`. The API key is never included in generated code. The default working path uses local speech and Meta generation, with no Google credential required.

## Verification and limits

```sh
python3 -m unittest discover -s tests -v
```

The tests cover forbidden code and inactive branches, resource/output bounds, malformed provider responses, secret-safe errors, stale revisions and acknowledgements, failed display/pointer writes, source tampering, rollback and interruptions before/after commit.

Verified during bring-up: actual Pi 5 identification, USB capture-device detection, successful display driver writes and user confirmation of the display test. Two live local Meta generation probes passed the interpreter (1–100, then blue 1000–2000). A typed request produced and activated number 24 on the TFT in 4.69 s with source hash `3fe6729a8499c0f48084a7192a5933af4af7ce1db4dbae0fd729ff2215df2b6c`.

The physical voice trial then produced **1008 in blue**, confirmed by the user, with a different source hash `516799652c2fbb52dfdd9e5b173cc09fe381ae0086f11c8a5cece2fe75b15675`. It took 12.65 s including 6 s recording; transcription completed about 1 s after capture, and generation/check/activation took about 5.6 s. One preceding voice attempt exhausted the model-output limit and preserved number 24. That is **one successful activation out of two observed voice attempts**, not a reliability claim. Earlier untuned model prompts also failed checks. The successful model additionally chose a green background; the user confirmed the requested blue number, but exact preservation of unspecified styling is not guaranteed. See [sanitized evidence](evidence/number-prototype-2026-10-28.json).

This prototype does not implement a generated game, host-volume pairing, joystick/encoder controls, automatic component discovery, arbitrary Python, firmware flashing, guaranteed semantic correctness, or wake-word detection. A successful bounded program check does not prove the model interpreted every spoken instruction correctly. Whisper tiny.en and Llama 1B are intentionally small; failures remain visible and preserve the last working revision.

## Prior work and dependencies

Hardware/capture parameters were checked against [Viktor Radev / LaboriouslyExquisite's prior lab work](https://github.com/LaboriouslyExquisite/Interactive-Lab-Hub/tree/3ef4fa566cd6881db97dc44d36090905f650b0ee), a fork of IRL-CT/Interactive-Lab-Hub. No repository-wide license was identified there, so the small adapters were independently written rather than copying its application code. That repository and Adafruit's examples are pre-event references, not new hackathon contributions.

Dependencies: [Adafruit Blinka](https://github.com/adafruit/Adafruit_Blinka) and [RGB display driver](https://github.com/adafruit/Adafruit_CircuitPython_RGB_Display) (MIT), [Pillow](https://github.com/python-pillow/Pillow) (HPND), [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT), [Ollama](https://github.com/ollama/ollama) (MIT) and Meta Llama 3.2 weights (Llama 3.2 Community License). Whisper model weights and their upstream license are distinct from Meta's generation model. No third-party photo, game asset or private chat was added to the repository.
