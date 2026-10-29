# Native setup reference

Use the current checked-out runtime documentation and CLI `--help` as the source of truth. Commands below describe agent-operated setup through supported access, not terminal instructions for the customer. Do not use Raspberry Pi Connect or a developer's browser/account as an implicit setup dependency.

## Mac companion

The native bridge targets macOS. Check Python 3.11+, Git and OpenSSL. Create a dedicated virtual environment only when an appropriate one does not already exist. Install the checkout's pinned `requirements-product-host.txt`. Add its computer/camera requirements only for features the user enables. Preserve the current environment and service configuration when repairing an installation.

Studio is started from the repository root with `python -m modulate.studio`. It accepts a literal reachable `--host-address`, the intended Pi's literal `--device-address`, `--state-dir`, optional private `--env-file` and `--connect-env-file`, and an explicit `--budget`. A new installation uses zero until the user authorizes spending; an existing installation retains its actual authorized ceiling and usage/unknown-cost holds. Never copy a developer's historical budget into a new user's installation.

Read existing configuration without displaying its values. Keep credentials in ignored private files with mode 0600 or an appropriate server secret store. The model and ElevenLabs keys belong to the host/server, never the Pi or browser. Verify current provider endpoint/model access rather than assuming the sample model is available to a new account.

Local Studio listens on `http://127.0.0.1:8787` and must be checked on the Mac. It deliberately cannot be reached from the Pi at the Mac's network address; a failed Pi-to-Mac HTTP request on 8787 is not a connectivity diagnosis. The Pi uses a separate certificate-pinned HTTPS endpoint on 8788, with a device credential and exact peer-address check. Verify that path through enrolled telemetry; do not disable TLS checks or authentication to probe it.

The server creates private enrollment and certificate files in the selected state directory. A changed host IP can require a coordinated enrollment update, not a reset of apps or ledgers. Obtain current addresses from the user's supported setup/access path; never recover old addresses or tokens from development logs or backup archives. Complete dependency/configuration preparation while device access is unresolved; do not claim Studio and Pi are connected just because local Studio starts.

## Preloaded gadget: enroll from this Mac

Keep the gadget and Mac on a network that allows them to reach each other. Use the current IPv4 address on the gadget's setup screen; no device browser login or SSH is required. If the screen has no address, resolve its network connection first. Do not guess from historical development IPs.

1. On the Mac, run `python -m modulate.enroll --device-address <current-screen-IPv4> --print-host-address`. This reads the OS route's source address without sending a network payload.
2. Start Studio using that output as `--host-address`, the gadget's exact address as `--device-address`, and the intended existing state directory, credentials and spending ceiling. Preserve prior state and ledgers; do not create a second installation to avoid an error. If its existing certificate does not match the current Mac address, repair the enrollment/certificate together after a private backup.
3. Run `python -m modulate.enroll --device-address <current-screen-IPv4> --state-dir <existing-state>`, using the same Python environment. Open the helper's `http://127.0.0.1:8791` page on the Mac. The helper reads only the companion's device enrollment and public certificate; it never sends provider credentials or the companion's TLS private key.
4. Ask the user to press the small A button to open device setup, then enter the full 20-character gadget identity and eight-digit setup code directly into this local page. Keep these out of chat, logs and screenshots. The code expires after five minutes. This code is not the later website connection code.
5. The helper pins the device's TLS certificate identity before sending enrollment. It stages a request; the user checks the Mac address shown on the gadget and presses A freshly to accept, or B to reject. Do not simulate this button press. Wait for the helper's matching completion receipt, then verify fresh Pi telemetry in Studio. Never call “awaiting confirmation” a completed link.

The gadget setup service is a narrow, temporary enrollment path on TLS port 8790; it does not accept shell commands, runtime updates or caller-chosen file paths. It will not overwrite an existing enrollment. Native Mac pairing still requires another fresh physical confirmation, followed by a separate browser code as described below.

An older device whose screen only says **“Enroll this Pi once”** does not have this service. That is a genuine factory/runtime-update blocker, not a code-entry or permission error. Finish Mac preparation, explain that the device needs that update, and stop before claiming a working link. Do not substitute Raspberry Pi Connect, customer shell commands or archived credentials. This source implementation does not prove any particular physical device has been updated or tested.

## Blank Pi / developer-kit installation

This is separate from normal preloaded-gadget setup. Initial Raspberry Pi OS, Wi-Fi and installation access must be provisioned first. Explain the physical SD-card preparation step and establish a supported access method, such as SSH explicitly configured for this user's Mac. Do not erase an existing card without authorization or claim this repository provides a finished Modulate OS image. The agent performs commands once access exists; the customer should not need to edit a Pi remote shell.

Use only an explicitly authorized SSH target/identity or another documented authenticated installation channel. Do not search browser tabs for a logged-in Pi account, silently add SSH keys, reuse revoked access, or ask for remote-terminal command output. Existing OS files and an intentional fresh reset must be respected; missing enrollment after that reset is expected, and old enrollment/pairing must not be restored from backups.

Once authorized access exists, inspect the actual board, SPI/I2C configuration, permissions, screen, microphone and audio output. Only install missing prerequisites. The tested Pi uses OS packages `python3-venv`, `python3-pil`, `python3-lgpio`, `libseccomp2` and `libportaudio2`, a virtual environment with system packages, and `requirements-product-pi.txt`. Prepare faster-whisper's `tiny.en` CPU/int8 cache under the same device user when absent. Do not silently download a different model during a spoken request.

Install the maintained runtime with `python -m modulate.device --state-dir … --enrollment …` using the intended device state directory. The repository includes a systemd template at `deploy/modulate-device.service`; adapt paths and user and avoid two owners of the display/microphone. Once the updated un-enrolled runtime is running, use the physical enrollment flow above. Never transfer the host TLS private key or provider credentials to the Pi.

If this Mac already serves another Pi, determine whether the user is replacing it or wants an additional device before changing the peer address or enrollment. The current host has one exact Pi peer allowlist; do not claim it supports two simultaneous devices. A replacement can retain the host's app library and spending ledgers while updating enrollment separately. Back up the intended existing state privately before making that change.

Do not rewrite peripheral addresses during generic connection setup. If two Qwiic buttons collide, use the runtime's hardware debugger workflow and require isolation/power-cycle confirmation before a supported address write. Power down before changing physical wiring.

## Pair and open the dashboard

Local Studio's native Pair flow displays a matching code on the Pi. The user confirms with the small PiTFT A button; B declines. Do not use the development `--pair-code` shortcut as an undisclosed substitute for that confirmation. macOS Screen Recording, Accessibility, Camera and audio permissions still require the user's system dialogs when needed.

Browser linking is separate. The Pi setup guide or local Studio can display a one-use browser code. It expires after five minutes; the resulting browser session lasts up to eight hours. Never share the code in a public log, URL, artifact, or speech response.

For a user-owned remote deployment, the dedicated gateway binds to loopback port 8789. Use a maintained outbound HTTPS tunnel or equivalent user-owned deployment. The fixed gateway origin and strong independent secrets must match across companion and web server. Never expose ordinary Studio or the Pi endpoint directly. See the repository's `context/connect.md` for the server-only environment names and production-origin configuration.

The shared public demo is currently a single configured hub. No plugin action silently changes that hub to a new user's computer or lends them its provider credentials. A phone can operate the remote dashboard; it cannot grant system-wide control over its own mobile OS.
