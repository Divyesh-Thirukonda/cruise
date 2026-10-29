# Modulate Connect

`https://divy.live/connect` is the remote Studio for the existing Modulate hub. It is served by the existing portfolio project. The Mac companion remains the trusted runtime for the paired Pi, the agent, native computer tools, private state, and spending ledgers.

## Connect a browser

1. Keep the Mac companion and its outbound connection running.
2. On that Mac, open `http://127.0.0.1:8787` and create a browser connection code.
3. On a phone or computer, visit `https://divy.live/connect`, enter the single-use eight-digit code, and choose the device's access switches.
4. Use the dashboard to send requests, inspect the running program and checks, answer follow-up questions, edit voice drafts, cancel work, manage hardware, and control the existing paired Mac.

The browser connection expires after eight hours and can be disconnected independently of the Pi's native Mac pairing. Local Studio can revoke every remote browser. A paired browser is a trusted administrator for this one Modulate hub. The access switches apply to the device as a whole, including its microphone requests; they are not separate per-browser sandboxes.

Page reloads and companion restarts retain an unexpired browser session. During a companion outage the dashboard disables actions and retries automatically. Disconnect immediately clears the browser's private view; older polling responses cannot restore it. Reconnecting requires a fresh code because the original code was consumed.

## On-device setup

The maintained Pi runtime displays setup locally if enrollment is missing/invalid, the companion cannot be reached after an eight-second startup grace, or the reachable Mac is not paired. This card needs no model/API connection. A healthy paired boot goes straight to the retained app. A missing browser dashboard alone does not interrupt working Mac/voice controls.

- Small PiTFT **A** advances local instructions, prepares a one-use browser code when the public gateway is available, or starts native Mac pairing when a browser is already connected. The card tells you which action will happen.
- Small PiTFT **B** dismisses setup and preserves the saved app. Dismissal stays in memory for the current process/boot. On a later restart it can remind you again; while disconnected, hold small A for one second to reopen it. A locally recognized wake phrase also reopens a dismissed reminder where wake listening is enabled.
- **Both** screen buttons retain push-to-talk. Setup actions need a fresh release and press. Preparing native pairing does not approve it: the separate matching-code card still needs another fresh small-A press.
- Once enrolled and able to reach the companion, say **“Hey Meta, help me connect”** or **“show setup.”** Meta chooses the `connection-setup` skill and trusted `connection_setup` tools to inspect state and prepare the next step. Computer use is not required for these tools. The agent cannot operate the Mac before native pairing or grant its own macOS permissions.

Browser codes appear only in authenticated device setup offers, never the model's results, normal dashboard state or spoken reply. They expire after five minutes and disappear when consumed, replaced or revoked. A fresh matching Pi display telemetry report can confirm that an offered guide is visible; queued work is not reported as physical display success.

This does **not** replace the initial Raspberry Pi OS/Wi-Fi configuration, installation of the companion/runtime, pinned Pi enrollment, or the user's macOS permission dialogs. The setup page and local card explain those remaining human steps. The current public site connects to this configured hub; a signed installer and self-service enrollment for arbitrary computers remain unimplemented.

## What the switches mean

- **Computer control:** native screenshots, cursor, keyboard and app actions on the companion Mac. macOS Screen Recording and Accessibility permission must also be enabled for the companion's Python/native process.
- **System controls:** supported Mac volume and brightness actions, including generated knob bindings.
- **Camera:** the Mac camera feed used by the Pi's generated application. macOS Camera permission is still required.
- **Computer audio:** capture the Mac's system audio and play it through the Pi. Native Screen Recording permission and the existing audio adapter are required.
- **Voice:** requests from the Pi microphone, including wake and push-to-talk paths.
- **Speaker:** generated spoken replies and Pi speaker adjustments. Stop actions remain available.
- **Hardware setup:** trusted hardware diagnostics and guided supported address repair. Physical wiring confirmations remain necessary.
- **Share camera preview:** separately allow a camera-containing screen preview to travel through the cloud connection to paired browsers. Off by default. It does not grant camera capture or enable the computer-use screenshot tool.

A phone can operate this dashboard remotely. Browser pairing does not grant control of the phone's own system volume, apps, or cursor. Another Mac would need a configured native companion and Pi enrollment; this release is one configured hub, not a self-service multi-tenant fleet or a signed one-click native installer.

## Data and secrets

The public browser calls same-origin Vercel functions. These forward only a fixed list of Studio operations to a dedicated companion gateway. The ordinary localhost Studio and Pi TLS endpoint are not published. Browser sessions use HttpOnly, Secure, SameSite cookies, origin/CSRF checks, expiry, and companion-side revocation. The gateway requires an independent server credential before accepting any route; pairing attempts are bounded and the code is single-use.

The Meta and ElevenLabs keys are production-only Vercel secrets. A separate companion credential authorizes fixed provider operations; it is never sent to browser JavaScript. The local agent reserves against the existing $50 ledger before Meta calls. ElevenLabs retains the existing durable 5,000-character application ceiling and provider key restrictions. Migration must not recreate/reset either ledger or release uncertain reservations. Provider failures do not silently fall back to local keys or another model.

Requests, dashboard state, and permitted previews pass through Vercel and the outbound tunnel. Computer-task screenshots requested by the user go to Meta; spoken reply text goes to ElevenLabs. Camera previews pass through the remote connection only when the separate sharing switch is enabled. Service logging must not include keys, request bodies, screenshots, audio, pairing codes, or browser session tokens.

## Run and recover

The host accepts `--connect-env-file` in addition to the existing provider configuration. Store the connection file with mode 600 under ignored `context/private/`; use a different random value for `MODULATE_REMOTE_SECRET` and `MODULATE_CLOUD_KEY`. `MODULATE_CLOUD_URL` is the fixed provider gateway `https://divy.live/api/modulate-provider`.

The remote gateway binds to `127.0.0.1:8789`, separate from Studio on 8787 and the enrolled Pi endpoint on 8788. Start the companion using its normal state directory and existing host/device addresses, with `--connect-env-file context/private/connect.env`. Do not create another state directory just to enable remote access; doing so would discard pairing and spending history.

The current development connection uses the already-installed `cloudflared`:

```sh
cloudflared tunnel --url http://127.0.0.1:8789 --no-autoupdate --protocol http2
```

Set the resulting HTTPS origin as the portfolio project's production `MODULATE_COMPANION_URL`, and use the same `MODULATE_REMOTE_SECRET` in the companion and Vercel. The production provider function uses `MODULATE_CLOUD_KEY`, `MODULATE_META_API_KEY`, and `MODULATE_ELEVENLABS_API_KEY`. Changes to Vercel environment variables require a new deployment. None of these values use a browser-exposed prefix.

Keep the companion, tunnel, Mac and Pi running. This development tunnel has no uptime guarantee and gets a different hostname after it is recreated; update the Vercel origin and redeploy then. A stable named tunnel is the next operational step. An offline companion produces an explicit offline state rather than a simulated dashboard or successful action.

Sources: [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/), [Vercel environment variables](https://vercel.com/docs/environment-variables), [sensitive environment variables](https://vercel.com/docs/environment-variables/sensitive-environment-variables). Native computer/camera/audio dependencies and their limitations are documented in [architecture](architecture.md).
