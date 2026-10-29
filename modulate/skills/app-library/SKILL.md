---
name: app-library
description: Browse saved apps or games, favorites, Trash and restore; navigate the on-device library and adjust launcher-only knob scrolling preferences by voice.
---

Use `app_library` for saved creations. Every successfully acknowledged activation
is saved automatically on the companion, including each distinct revision. Failed
candidates are not apps. Storage survives restarts; it is not account cloud sync.

`list` returns metadata and exact IDs, never executable source. `open` shows the
library on the Pi, optionally with tab `all`, `favorites`, or `trash`. Use `select`
with the exact entry ID to highlight an item. Titles can repeat; use current
selection, most recent requested revision and conversation context to choose.
Ask only when the intended app cannot reasonably be resolved. "What have you
built?" should open the menu and briefly name a few recent apps; avoid a long
spoken catalogue. No home button is reserved during ordinary gameplay.

For "this app", use the selected entry while the library is open, otherwise the
active app. `favorite` takes an explicit boolean. `trash` is reversible and does
not interrupt a currently running copy. `restore` returns an item to All apps.
"Delete this" means Trash, not permanent deletion. After browsing Trash, use its
exact selected ID for restore or deletion. `close` returns to the current app.

The launcher is configurable through trusted preferences, not generated code.
For "reverse the knob in this menu", "scroll the other way", or an unqualified
knob reversal while the library is open, inspect `library.preferences` in current
context or `list`, then call `set_preferences` with `encoder_direction` set to
the explicit `forward` or `reversed` value. The tool saves it across restarts.
Repeated assignment is safe; do not blindly toggle by repeating a tool call.
`forward` restores the original driver direction; `reversed` changes only the
library's knob navigation, not joystick, buttons, games, volume or brightness.
No app generation, replacement or confirmation is needed. Keep the menu open
and the current selection. To undo, restore the recorded before-value; explicit
requests about a game or system-volume binding still use their normal skill.
Say "Reversed the library knob." after the saved preference is returned; do not
claim a physical effect before device feedback or user observation establishes it.

`launch` rechecks and atomically activates the exact stored source through the
trusted runtime. Do not write_package to fake reopening. If required controls
or the paired camera/host are unavailable, explain that concrete result; keep
the current app. The saved package has no permission to modify infrastructure.
To edit a saved app, launch it then use the appropriate app/game skill.

Only use `purge` when the user explicitly asks to delete forever. It prepares a
named confirmation and ends the turn. The user can answer yes without Hey Meta;
the trusted host verifies the reply. Never call another tool to simulate approval.
`cancel_purge` abandons the confirmation. Active and rollback versions cannot be
permanently deleted while needed for recovery; Trash remains available.

Keep success replies brief: "Favorited Pixel Kart." or "Moved it to Trash."
The library menu also supports knob/joystick navigation and A/select, B/back when
those modules are connected. Voice remains sufficient for every operation.
