# Runtime driver setup — October 30, 2026

Modulate's Pi agent can now diagnose and install a supported missing driver through its hardware-debugger skill. The first pack is the owned **LSM6DS3TR-C IMU**. This closes the installation gap for that sensor; it does not create arbitrary drivers or infer a chip from its I²C address.

## Request path

Say “Hey Meta, use hardware-debugger to fix my motion sensor,” or submit the same request in Studio. Meta inspects current evidence, chooses `hardware_debug(action="install_driver", driver="lsm6ds3trc")` when appropriate, receives verified readings and continues the original request. The trusted runtime refreshes its capability manifest and invalidates earlier candidates after installation. A compatible saved game can resume without being rewritten. Meta still chooses control mappings when generating an app; the driver contains no game preference or steering preset.

The physical Pi runs the installer and agent. A Mac is unnecessary. An initial download and the Meta model request require internet; local input handling and rendering remain independent of model calls.

## Trusted installation boundary

- Read WHO_AM_I register `0x0F` at supported addresses `0x6A`/`0x6B` using base I²C support; require value `0x6A` for this catalog entry.
- Download fixed, hash-pinned pure-Python wheels from the official PyPI file host. Accept no model-supplied URL, version, shell command, package source build or driver code. Reject oversized archives, path escapes, symlinks and executable import hooks/native libraries.
- Stage files in the private device directory outside base packages. Downloads never hold the physical-input lock.
- Under that lock, check chip identity again, open the maintained driver and require three finite acceleration/gyro samples with usable gravity. Commit the active pack pointer atomically under the cancellation lock. Restore previous imports and sensor handles on failure.
- On service startup, verify the saved pack's file hashes before making it importable. Partial downloads remain inactive. Existing session/boot/command identity, cancellation, expiry, button-repair exclusion and the $50 model ceiling apply.

Blinka, BusDevice and base I²C support remain prerequisites supplied by the device runtime. This mechanism installs catalog packs into an existing supported input contract. Adding another chip still requires a reviewed identity probe, package pack and bounded input adapter. Generated apps and automatic missing-control adaptation have no installer or shell access. The physical Qwiic-address repair retains its user-confirmed isolation/power-cycle steps.

## Live controlled trial

Installed code `e3de9d3` on the Pi from its SHA256-verified repository archive. Preserved the working optional IMU package as a private backup outside the import path, restarted the services and submitted a **typed** repair request to the normal Pi API. This deliberately induced a missing-driver condition; no cable was unplugged and no spontaneous hardware fault is claimed.

The runtime Meta agent loaded hardware-debugger and made two successful hardware tool calls. The installed pack reported verified WHO_AM_I/address `0x6A`, actual acceleration/gyro readings, `managed=true` and `input_ready=true`. Agent trace duration was **7.578 seconds**; the half-second polling wrapper observed completion at **7.76 seconds**. Four model calls added **$0.051106** charged/reserved. The tool performing installation took **1.731 seconds**.

Orbit Catch retained revision `03130009c50e9e5cf4affbac4e55461a1b53b770bfeb8073ac720b3200c7edf7`. A subsequent device-service restart loaded the managed pack and retained that revision with no additional model calls. Agent, device and connection services were active. MMS reported no pending speech or error. These are remote software/sensor observations: the user no longer has physical access, so tilt steering, visible display and audibility were not retested after installation. Earlier user-confirmed tilt play remains separate [evidence](adaptive-controls.md).

[Sanitized measurements](evidence/driver-setup.json) exclude private identifiers, network details, raw transcripts and credentials. Total ledger after the trial: **655 calls / $12.144861** charged/reserved under the unchanged $50 ceiling.

## Validation and attribution

The host suite ran **1,106 tests successfully, 13 skipped**. The deployed Pi passed **242 focused tests** in 17.582 seconds. Focused failure tests cover incorrect identity, changed chip during download, unknown catalog ID, checksum/partial-download failure, archive path escapes, invalid samples, cancellation before commit, persistent-pointer failure, import/handle rollback, duplicate/stale commands, repair-workflow exclusion and restart integrity. These synthetic tests are distinct from the live sensor trial.

An initial deployment-wrapper indentation error stopped before any device mutation; it was corrected and syntax-checked before deployment. The broader host run also caught an outdated tool-schema expectation, which was updated before the passing run. Neither failure was silently represented as a successful trial.

Reused packages, both MIT, verified against version-specific PyPI metadata and official driver documentation:

- [Adafruit CircuitPython LSM6DS 4.6.3](https://pypi.org/project/adafruit-circuitpython-lsm6ds/4.6.3/), wheel SHA256 `079351c8ef3ce9a375ad617664a59aad276a16c3891844d7ee30f9583147d6b2`.
- [Adafruit CircuitPython Register 1.13.0](https://pypi.org/project/adafruit-circuitpython-register/1.13.0/), wheel SHA256 `fba55bf5d2cde3af77b7a8f9d7d97a6dc08697cff0d5977edadf83b90745066d`.
- [Adafruit acceleration/gyro API documentation](https://docs.circuitpython.org/projects/lsm6dsox/en/latest/api.html).

Our contribution is the catalog, identity-gated transactional installer, runtime tool integration, cancellation/recovery behavior, capability refresh and evidence. We did not author the underlying sensor driver.
