---
name: hardware-controls
description: Adjust or remap the Pi's speaker and physical controls or the paired Mac's advertised volume and brightness. Resolve which device or current activity a short request such as louder refers to; also manage Mac-to-Pi audio streaming.
---

# Hardware controls

Distinguish the action's target before choosing the tool. Use the latest relevant request, successful result and active mode to interpret “louder,” “quieter,” “again,” “reverse it” or “less sensitive.” Reuse the recent relevant target and step when available; an explicit device name wins. Current observations override remembered settings. Avoid a clarification when the context identifies the target; inspect state if needed. If two materially different targets remain plausible, ask one short question.

- `speaker_control` operates the Pi's selected physical speaker, shared by spoken replies and computer-audio playback; changing its level does not stop the stream. Use it for “your speaker,” “speak louder,” or the Pi's current output volume. Its get/set/delta/mute actions adjust this sink, not Mac volume.
- `system_control` operates advertised settings on the paired Mac, including native volume and supported brightness. A successful read establishes the actual target/state; do not assume every display supports brightness.
- `computer_audio` starts, stops or inspects the Mac-to-Pi live audio route. Capturing system audio is separate from selecting a macOS output device. Mac system-volume changes are not evidence of Pi speaker-level changes.
- Launcher/menu knob scrolling is an `app-library` preference. When the library is open, "reverse the knob" defaults to that menu unless the user names another target. Use `app_library set_preferences` with an explicit direction; do not regenerate the saved app, rewrite drivers, or change other control mappings.

Use current tool schemas and capabilities for supported actions and ranges. Choose modest reversible steps when no amount is specified. Apply the requested change and verify its returned or acknowledged state. A queued Pi command is not yet an applied volume, and software playback is not proof the user heard it. Never silently redirect to a different output after failure.

For a physical remapping, read the active package and current runtime contract. Generate declarative bindings using only advertised controls, supported actions and their real target identity. Preserve unrelated mappings for a refinement; a new control app may replace the active app after checks. Do not invent a local-speaker binding merely because immediate speaker adjustment exists: use only the mapping actions the runtime actually advertises. Use the normal exact-revision verification and activation path.

Keep driver work and credentials outside generated code. Respect stop/revoke/disconnect and treat model output as untrusted. Give a brief result naming the affected device or control, so a correct action cannot be mistaken for a change on the other machine.
