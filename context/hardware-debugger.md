# Modulate hardware debugger

Implemented and installed October 29, 2026. Live Meta diagnosis, guided setup preparation and cancellation passed against the physical Pi. Full address repair and fault recovery were tested with a simulated bus; no new board was physically rewired or repaired in this trial. See [test and deployment evidence](evidence/hardware-debugger.json). The previously verified green `0x6E` / red `0x6F` assembly remains the baseline to preserve; see the [hardware inventory](hardware.md).

The debugger lets the user ask Modulate about missing inputs, a suspected I2C problem, a wiring step or voice/speaker/display status. Once deployed, supported work uses the product's voice or Studio interface without needing Codex or a terminal. The model chooses the [hardware-debugger skill](../modulate/skills/hardware-debugger/SKILL.md) and trusted tools; it does not generate a privileged driver.

## Tool and evidence boundary

`hardware_debug(action, label?)` supports `inspect`, `scan`, `reinitialize`, `begin_button_repair`, `continue` and `cancel`. Label is optional only when beginning a repair. Inspection combines driver-read status, bus addresses, supported button identity, voice/speaker/transport/display health, known wiring context and the saved workflow. Scan and driver reinitialization do not authorize arbitrary persistent writes.

Use observations to narrow the cause. A scan cannot prove an address collision, count boards sharing an address, identify their color or establish working presses. A generic I2C address does not identify an unknown module. Ask for the manufacturer's model or board markings when needed; do not apply the Qwiic Button procedure to another board. Software display/playback success remains distinct from a visible frame or audible sound.

The supported persistent change is a new, physically isolated factory-address SparkFun Qwiic Button at `0x6F`. The fixed tool checks device ID `0x5D` and the supported firmware value 259, then changes only its I2C-address register `0x1F`. Firmware 259 is this implementation's supported/previously observed variant, not a claim about every shipped board. The trusted address pool starts with `0x6E`, then `0x6D`, and avoids known/reserved and observed addresses; an existing healthy `0x6E` remains reserved. There is no arbitrary register API or firmware flashing. SparkFun documents the [register map](https://learn.sparkfun.com/tutorials/sparkfun-qwiic-button-hookup-guide/register-map) and [Python identity/address methods](https://github.com/sparkfun/qwiic_button_py/blob/main/qwiic_button.py).

The scanner follows i2cdetect's default address-dependent receive-byte/quick-probe policy over `0x08–0x77`; it does not issue register data writes during discovery. This is not a guarantee that probing arbitrary unknown peripherals is harmless. The debugger targets the documented assembly and supported Qwiic Button family; identify another board and consult its manufacturer before treating it as supported. See the [i2c-tools probe limitations](https://manpages.debian.org/bookworm/i2c-tools/i2cdetect.8.en.html).

## Guided repair through voice or Studio

Start with a concrete request such as “Hey Meta, help me connect this new SparkFun Qwiic Button.” Modulate inspects the current hardware and reports the next physical step. A general healthy-hardware check must not rewrite the existing pair. Starting the supported repair is authorized by the repair request; advancing it also requires the user to have performed each physical step.

| Step | User action | Exact confirmation after boot |
| --- | --- | --- |
| Isolate the new button | Cleanly shut down and unplug the Pi. Disconnect the original Qwiic chain. Connect only the new button directly to the Mini PiTFT's QT port using a keyed QT-to-QT cable. Boot and wait for Modulate to reconnect. | `isolated button ready` |
| Verify persistence | After Modulate reports the address write, shut down and unplug again. Leave the new button isolated, then reconnect power and boot. | `button power cycled` |
| Verify the complete assembly | After isolated verification, shut down and unplug. Reconnect the original chain plus the new button, then boot. | `modules reconnected` |

Say the current phrase after “Hey Meta,” or use Studio's exact-step confirmation. The trusted workflow checks the physical confirmation and reboot evidence; neither a model assertion nor elapsed time substitutes for the user. At a waiting phase the agent uses `ask_user` for the necessary hands-on help and ends its turn instead of consuming model calls by polling. A reboot may outlast the conversational question: the separate durable workflow preserves its phase, so ask Modulate to continue rather than beginning another repair.

Use the **Pi 5 board's power button**, not the screen's A/B buttons or a Qwiic button. On Raspberry Pi OS Lite, one short press initiates shutdown; on Desktop, two short presses do so. Wait for shutdown to finish and unplug power before changing wiring. Reconnect power to boot. These are the manufacturer's [power-button instructions](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#power-button); holding the button is a different hard-shutdown action.

The Mini PiTFT stays seated directly over GPIO physical pins 1–24; use its QT port rather than dangling Dupont leads. Its orientation is covered by [Adafruit's pinout guide](https://learn.adafruit.com/adafruit-mini-pitft-135x240-color-tft-add-on-for-raspberry-pi/pinouts). Preserve the USB microphone/speaker needed for voice while isolating the Qwiic chain. If microphone or transport failure prevents voice, use Studio where available and restore the connection first; the device cannot guide a live step while powered off.

## Completion and limits

Successful repair requires identity/address readback after the isolated power cycle, then verification after reconnection. Do not treat the return value of an address setter as proof: SparkFun's [address-change example](https://github.com/sparkfun/qwiic_button_py/blob/main/examples/qwiic_button_ex6_changeI2CAddress.py) is source guidance, while the runtime supplies the fixed checked workflow. Preserve the healthy `0x6E`/`0x6F` buttons throughout.

A third button can have a unique address without becoming a third game input. The current runtime exposes `button_a` and `button_b`; new logical input support is separate work. Cancellation stops the workflow, but an already-written address must not be assumed undone. Inspect the saved phase/address before resuming. Unknown identity, unexpected firmware, missing physical confirmation or failed readback should produce a concrete explanation and stop before another speculative write.

Record deployment/tests, actual scan/identity observations, each user-confirmed physical step and final input behavior separately. Synthetic tests can establish refusal/recovery behavior; they cannot prove how the user wired the board. No raw conversation, audio, credential or private screenshot belongs in public repair evidence.

## Validation checkpoint

Installed `982cff6` on the Pi after archive SHA256 verification. All 238 focused Pi tests passed without skips; the host suite ran 778 tests with 11 platform skips, followed by 79 focused checks after final Studio-cancellation and speech refinements. Live diagnostics identified joystick 0x20, encoder 0x36 and buttons 0x6E/0x6F with firmware 259. Meta selected hardware-debugger, prepared an additional-button setup at unused 0x6D, requested physical isolation and stopped. Cancellation retained the original addresses and app; no address write was performed. The final healthy check returned one short sentence.

Fresh camera telemetry, wake listening, pairing, Pi volume 70% and the original active revision were retained after host/Pi updates. Trial memory was removed while preserving the real speaker preference. The total ledger was 462 calls / $9.706706 held or used under the existing $50 ceiling; it includes an unconfirmed follow-up while waiting. This does not establish broad hardware or voice-recognition reliability.
