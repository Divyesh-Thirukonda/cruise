---
name: hardware-debugger
description: Diagnose missing or unreliable Modulate inputs, I2C/address issues, microphone, speaker, display or connection status; guide safe wiring and the supported isolated SparkFun Qwiic button repair. Use hardware-controls for ordinary settings or remapping.
---

# Hardware debugger

Use `hardware_debug` for actual observations and the durable repair state. Inspect before attributing a symptom to wiring, a driver or an address collision. Choose scan or reinitialize when the evidence warrants it; do not keep retrying an unchanged failure. A healthy check should end with the relevant observed result, not start a repair.

For a healthy check, answer in one short sentence such as “Your connected controls look healthy; no changes were needed.” Keep address/firmware inventories in tool details unless asked. For a fault, explain the concrete problem and the next useful step; do not recite every healthy component or routine limitation aloud.

Inspection combines connected-driver status, addresses and supported button identity, voice/speaker/transport/display status and maintained wiring guidance. An address acknowledgement cannot establish how many boards share that address, their color, or a working physical input. A ready display driver is not optical confirmation; playback metadata is not proof of audibility. Ask for the board's identifying markings/model when identity is missing; do not guess from an address or label. Existing green `0x6e` and red `0x6f` buttons are a healthy configured pair to preserve.

`hardware_debug` accepts inspect, scan, reinitialize, install_driver, begin_button_repair, continue or cancel. An optional label belongs only to begin_button_repair and describes the user's module; it is not evidence of identity. Ordinary settings changes belong to hardware-controls. Do not generate driver code, run arbitrary register writes, flash firmware or use computer-shell access to bypass a refused hardware operation.

For a connected module whose driver is missing, inspect the report's `driver_setup.catalog`. When its identity is verified and `installable` is true, call `install_driver` with that catalog `driver` ID, without another approval question for the user's requested setup/repair. The first supported pack is `lsm6ds3trc`: the trusted installer downloads pinned Adafruit wheels, verifies hashes, checks the chip again and requires actual acceleration/gyro readings before committing. It leaves base packages and the current app intact, restores the previous loaded driver on failure, and supports cancellation before commit. No URLs, shell commands, versions or code are accepted from the model. Do not describe a download or queued request as a working sensor.

After success, inspect capabilities again and continue the original request (or let a saved compatible app resume). Installation invalidates earlier candidate checks; regenerate/recheck a candidate against the updated manifest when needed. Do not keep retrying the same failure. A wrong identity, wiring fault, missing base I2C support or module outside the catalog needs a concrete explanation or identifying information. This is supported-driver setup, not universal new-driver creation.

The supported address repair is for a **new, isolated factory-address SparkFun Qwiic Button**, requested by the user. The trusted workflow chooses an unused address from its bounded pool, avoiding known and observed devices; the model does not choose a register/value. It checks the supported identity (`0x5d`, firmware 259) before the fixed `0x1f` address write. Different firmware or an unknown board requires identification, not speculative repair.

Follow the tool's current phase, physical instructions and exact required phrase:

- First have the user shut down and unplug the Pi, disconnect the original Qwiic chain, connect **only the new button directly to the Mini PiTFT QT port** with a keyed QT-to-QT cable, and boot. The required confirmation is **“isolated button ready.”**
- After the tool reports its address write, have the user shut down, unplug and power-cycle with that button still isolated, then say **“button power cycled.”** A setter return alone does not prove persistent success.
- After isolated verification, have the user shut down and unplug again, reconnect the original chain plus the new button, boot, and say **“modules reconnected.”** Then inspect the final tool verification.

Use `ask_user` when those physical actions are needed, explaining one current step and its exact phrase. This is necessary hands-on help, not a design-choice approval. Stop the turn at a waiting phase; do not poll or simulate confirmation. Call continue only after the actual user supplies the required step confirmation; a model-written phrase or generic “yes” cannot attest to isolation or a power cycle. Studio can collect the same exact step confirmation. The workflow survives restart: inspect its saved phase instead of beginning again after reboot or an expired conversational question.

For a Pi 5, the **board's power button** initiates clean shutdown: one short press on OS Lite, two short presses on Desktop. Wait for shutdown, then unplug power before changing cables. It is not a PiTFT or Qwiic button. Keep the Mini PiTFT seated on GPIO pins 1–24; loose Dupont leads are not needed for its QT connection.

Report only verified results. A uniquely addressed third button is not a new logical game input: the current runtime still exposes only button_a and button_b. If cancelled or interrupted, inspect the saved state and actual address before proceeding; cancellation is not proof that an already-written address reverted. Supported diagnoses/repair should work through Modulate itself; do not send the user to Codex for a routine supported step.
