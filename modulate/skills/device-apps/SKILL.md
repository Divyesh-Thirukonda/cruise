---
name: device-apps
description: Create or refine a useful non-game experience on the Pi's mini display, including live camera effects, visual tools and interactive gadgets. Use games for playable challenges, or hardware-controls for direct settings and remapping.
---

# Device apps

Design a small useful experience for the actual 240×135 display and connected controls. Resolve “it,” “that effect” and similar refinements from the active app and recent request/results. Choose readable layouts, appealing effects and sensible controls yourself. A new-app request replaces the current app after successful checks; an edit preserves its intent and changes what was requested. For a narrow edit, verify both the requested behavior and an unaffected behavior. Changing one control is not permission to swap another control's action, even when the resulting controls are redundant.

Treat the current hardware as design context, not a required kit. Use available controls or a useful automatic visual experience when no controls are present. Declare only controls the app actually needs. Local apps need no Mac pairing; only a specifically requested Mac feature needs that target. Adapt a paused app to available controls through the normal checked replacement flow, retaining its purpose and artwork.

The maintained package API uses `kind:game` for visual applications as well as games. That name does not require adding a score, opponents, a start menu or a game objective. A camera or utility should show its useful output immediately. Read the current runtime contract rather than inventing browser, clock, sensor or network APIs. Retain its original-sprite requirement with purposeful visual design.

For a live-camera request, use metadata-only `camera_control` and the actual paired target, then generate the camera layer with original overlays and meaningful controls. The trusted renderer supplies pixels locally; generated code and the model never receive camera frames. Start can be asynchronous; check readiness when needed while developing the app. Do not call `computer_observe` merely to make a camera effect. A placeholder candidate preview checks layout, not a live image.

To turn the device into a speaker for the Mac, use `computer_audio`; this is a trusted stream route, not a fake animation or generated audio driver. Preserve the current app for return. Load hardware-controls when the task also changes playback volume or physical bindings.

Use the independent checker and preview to improve the actual package. Fix the observed problem without replacing checks or rewriting listening, transport or drivers. Activate only the exact passing revision, and distinguish acknowledgement from physical user confirmation. Summarize the result and controls, not the internal construction process.
