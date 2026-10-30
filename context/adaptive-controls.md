# Adaptive connected controls — October 30, 2026

The joystick was physically disconnected. Saved **Orbit Catch** still declared `joystick` and `button_a`, and the device suspended it. A second bug prevented a checked replacement from activating over that suspended predecessor. Both were application/runtime issues; no Mac or particular peripheral is required for local app generation.

The device now preserves the saved revision while allowing a verified replacement, with rollback restoring the suspended predecessor if needed. The card says **Controls changed** and offers “Adapt this app.” When a local game remains suspended with a stable missing control for five seconds, the Pi schedules one live Meta edit per app/control combination. It waits for listening, transcription, user requests, speech, setup and library navigation. Attempts persist across service restarts; automatic edits have only local package tools, no computer, camera or hardware mutation tools. The existing $50 ledger and independent verification/activation checks remain.

## Live evidence

- **Automatic hardware-change request:** Meta changed Orbit Catch from joystick + A to encoder + A in 14.316 seconds, 7 model calls, $0.099571 charged/reserved. Artwork was unchanged. The user confirmed the knob works. An agent restart preserved the new revision without additional model calls.
- **Typed motion request on the user's behalf:** after installing the missing trusted IMU driver/input contract, the Pi advertised the LSM6DS3TR-C at `0x6A`, with WHO_AM_I `0x6A` and actual reads. Meta inspected capabilities, runtime API and the current package, then generated, checked and activated a version using **IMU + A** in 20.487 seconds, 6 model calls, $0.115248 charged/reserved. Artwork was unchanged. The user confirmed: “Yes, tilt controls the ship.” This was not a spoken generation trial.
- Meta chose `tilt_x`, neutral calibration on A start/retry, a 0.05 dead zone and 0.25 smoothing fraction. Trusted drivers do not contain game-control preferences or a joystick→encoder→IMU fallback order.
- Final revision: `15ec238a3ac61c887db52a9a5a4466475c6227c83d4a5836bc9a7a8f6083ee29`. Pi reports the game active, no missing controls/error, all three services active and Meta MMS speech delivered. Total ledger: 642 calls, $11.948991 charged/reserved of $50.

[Sanitized trace and measurements](evidence/adaptive-controls.json) keep live model/device evidence separate from synthetic replay. The generated package replay held the ship at X=112 at calibrated neutral, moved left to 111.458 and right to 117.779 with controlled samples. Host suite: 1,089 tests, 13 skipped. Pi focused suite: 208 passed. Coverage includes malformed/partial sensor samples, missing controls, stable manifest hashes, failed activation, suspended rollback and restart-safe scheduling.

## Discovery and model boundary

The trusted runtime identifies supported hardware and reports capabilities only after successful reads. LSM6DS3TR-C exposes sensor-axis acceleration in m/s², angular velocity in radians/s, and bounded gravity inclination `tilt_x/tilt_y` (±45° full scale). Read failures neutralize every motion field and withdraw `imu` availability. Fast acceleration affects gravity-based tilt; there is no magnetometer, absolute heading or position claim.

A background worker reopens missing/failed supported drivers every five seconds, outside game frames, without consuming encoder/button events or writing EEPROM addresses. Physical unplug/replug for the new IMU driver remains unverified; synthetic discovery/failure checks pass. Unknown I²C responders are not universal plug-and-play: a trusted driver and bounded input contract are still needed. Adding a module makes it available to the next model request; it does not silently replace a healthy app.

The model receives identity, signals, units, sensor limitations and a live input sample. The changing sample is separate from the capability manifest hash so ordinary motion cannot invalidate a checked activation. The model chooses appropriate mappings for the requested experience and generates the app. Local physical input and rendering then run without model calls.

## Reused dependencies

- [Adafruit LSM6DS driver 4.6.3](https://github.com/adafruit/Adafruit_CircuitPython_LSM6DS/tree/4.6.3), MIT; [documented acceleration/gyro API](https://docs.circuitpython.org/projects/lsm6dsox/en/latest/api.html).
- [Adafruit Register 1.13.0](https://pypi.org/project/adafruit-circuitpython-register/1.13.0/), MIT, required by the sensor driver. The initial `--no-deps` sensor install exposed this missing dependency; it was installed before the successful live reading.

Our work adds the read-backed capability/input path, bounded motion normalization, independent verification samples, model context, missing-control adaptation and transactional suspended-app replacement. The sensor driver is reused, not claimed as original work.
