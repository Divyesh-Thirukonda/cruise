# Native setup reference

Use the current checked-out runtime documentation and CLI `--help` as the source of truth. The commands below describe the supported shape, not credentials or a fixed machine address.

## Mac companion

The native bridge targets macOS. Check Python 3.11+, Git and OpenSSL. Create a dedicated virtual environment only when an appropriate one does not already exist. Install the checkout's pinned `requirements-product-host.txt`. Add its computer/camera requirements only for features the user enables. Preserve the current environment and service configuration when repairing an installation.

Studio is started from the repository root with `python -m modulate.studio`. It accepts a literal reachable `--host-address`, the intended Pi's literal `--device-address`, `--state-dir`, optional private `--env-file` and `--connect-env-file`, and an explicit `--budget`. The default budget is zero. Never copy a developer's historical budget into a new user's installation.

Read existing configuration without displaying its values. Keep credentials in ignored private files with mode 0600 or an appropriate server secret store. The model and ElevenLabs keys belong to the host/server, never the Pi or browser. Verify current provider endpoint/model access rather than assuming the sample model is available to a new account.

Local Studio listens on `http://127.0.0.1:8787`; the Pi controller uses a separate TLS endpoint on port 8788. The server creates private enrollment and certificate files in the selected state directory. A changed host IP can require a coordinated certificate/enrollment update, not a reset of the app library or ledgers.

## Raspberry Pi

Use the user's existing Pi OS and files. Inspect the actual board, SPI/I2C configuration, permissions, screen, microphone and audio output. Only install missing prerequisites. The tested Pi uses OS packages `python3-venv`, `python3-pil`, `python3-lgpio`, `libseccomp2` and `libportaudio2`, a virtual environment with system packages, and `requirements-product-pi.txt`. Prepare faster-whisper's `tiny.en` CPU/int8 cache under the same device user when absent. Do not silently download a different model during a spoken request.

Transfer only `device-enrollment.json` and its public `device-cert.pem` through an authorized authenticated channel. Keep the relative certificate path valid; do not transfer the host TLS private key or provider credentials. Use the existing device state directory with `python -m modulate.device --state-dir … --enrollment …`. The repository includes a systemd template at `deploy/modulate-device.service`; adapt paths and user to the installation and avoid two owners of the display/microphone.

If this Mac already serves another Pi, determine whether the user is replacing it or wants an additional device before changing the peer address or enrollment. The current host has one exact Pi peer allowlist; do not claim it supports two simultaneous devices. A replacement can retain the host's app library and spending ledgers while updating enrollment separately. Back up the intended existing state privately before making that change.

Do not rewrite peripheral addresses during generic connection setup. If two Qwiic buttons collide, use the runtime's hardware debugger workflow and require isolation/power-cycle confirmation before a supported address write. Power down before changing physical wiring.

## Pair and open the dashboard

Local Studio's native Pair flow displays a matching code on the Pi. The user confirms with the small PiTFT A button; B declines. Do not use the development `--pair-code` shortcut as an undisclosed substitute for that confirmation. macOS Screen Recording, Accessibility, Camera and audio permissions still require the user's system dialogs when needed.

Browser linking is separate. The Pi setup guide or local Studio can display a one-use browser code. It expires after five minutes; the resulting browser session lasts up to eight hours. Never share the code in a public log, URL, artifact, or speech response.

For a user-owned remote deployment, the dedicated gateway binds to loopback port 8789. Use a maintained outbound HTTPS tunnel or equivalent user-owned deployment. The fixed gateway origin and strong independent secrets must match across companion and web server. Never expose ordinary Studio or the Pi endpoint directly. See the repository's `context/connect.md` for the server-only environment names and production-origin configuration.

The shared public demo is currently a single configured hub. No plugin action silently changes that hub to a new user's computer or lends them its provider credentials. A phone can operate the remote dashboard; it cannot grant system-wide control over its own mobile OS.
