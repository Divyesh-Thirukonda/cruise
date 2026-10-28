# Contributing to Modulate

Read the [product brief](context/product-brief.md) and pick the next unfinished milestone in the [build plan](context/plan.md). Coordinate ownership before editing the same hardware interface or configuration contract.

Use a short task branch and open a pull request explaining the user-visible outcome, how it was verified, and any hardware or provider dependencies. Keep changes small enough for a teammate to run and review. Document exact setup and test commands when code is added; there are none yet.

For model or device changes, include one successful example and relevant failure evidence. Generated game/application code needs independent checks tied to its exact package, a tested isolation boundary, and activation/recovery evidence. Keep physical drivers and the privileged computer bridge outside generated code. See the [architecture](context/architecture.md) before changing these contracts.

Clearly distinguish live hardware, simulator, recorded output, and mock inference; identify microphone source, wake/push-to-talk/typed input, and device-screen vs host-preview output. Redact credentials, raw recordings, and private prompt data. A browser audio-volume demo is not evidence of computer system-volume control.

Add a dated entry to [the build log](context/build-log.md). Identify reused libraries, assets, and earlier code so judges can separate our event work from dependencies. Agree on licensing before including third-party code or assets whose reuse is unclear.
