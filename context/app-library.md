# App library

Modulate saves each successfully acknowledged app/game revision automatically.
Failed or merely generated candidates are not library entries. Existing successful
activations are imported from the active/rollback records and verified activation
trace; 27 apps/versions were recovered on the development hub on October 29.

## Use

- “Hey Meta, open my app library.”
- “What apps have you built?” / “Show my favorites.”
- “Open Pixel Kart Sprint.”
- “Favorite this.” / “Remove this from favorites.”
- “Delete this.” moves the selected app (or running app outside the menu) to Trash.
- “Show Trash.” / “Restore [title].”
- “Delete [title] forever.” prepares a named confirmation. Answer yes or no without
  repeating the wake phrase. Permanent deletion cannot be approved by the model.
- “Close the library.” returns to the existing app.
- With the library open: “Hey Meta, reverse the knob here.” changes menu scrolling.
  “Undo that” restores the previous direction from recent context; “Use the normal
  library knob direction” explicitly restores the original setting.

Inside the menu, the knob/joystick scroll, A selects and B goes back. The encoder
press and large buttons work when present; the small screen buttons also navigate.
The menu's first row selects All apps, Favorites or Trash. Selecting an app opens
its actions. No dedicated home control is taken away from a running game.
Voice remains usable, including while the menu is open. Both small buttons retain
push-to-talk. Input is neutralized for the game/host while navigating the library.

Both local Studio and Modulate Connect have library tabs and the same controls.
Browsing on the website alone does not change the device screen; Show on device
opens the physical menu. Existing linking is assumed complete during development.

## Persistence and boundaries

Private host storage: `<state-dir>/library/index.json` and `packages/<sha256>.json`.
Launcher preferences live separately in `library/preferences.json`. The trusted
`set_preferences` action accepts an absolute `encoder_direction` of `forward` or
`reversed`; retries do not flip it again. This changes only the library's encoder
input, preserving joystick/buttons, app bindings, source and drivers. Existing
installations default to `forward`. The model receives the current preference and
the saved before/after values for contextual changes and undo. A changed preference
invalidates stale menu actions and requires fresh button input on the device.
The Mac companion must be running for browsing or opening saved apps. This is
persistent local hub storage, not cloud synchronization or a Supabase account.
The current app remains available on the Pi when the companion is offline.

Each distinct source revision is a separate item; repeated titles can represent
refinements. Packages are immutable, bounded and checked against their hashes.
Opening a saved app runs current fixed checks, validates live capabilities and
uses the normal staged activation/device acknowledgement. It does not regenerate
source or bypass the isolated runtime. Unavailable or expired paired targets fail
without replacing the active app. Reopening the already-active revision leaves
the rollback slot intact.

Trash is reversible and does not interrupt an already-running copy. Permanent
deletion requires an expiring, one-use confirmation bound to the exact item. The
active, rollback and in-flight versions remain protected until no longer needed.
Purging removes the library package and exact historical candidate/check files;
diagnostic metadata and normal backups are not presented as erased. Durable
removal tombstones prevent historical migration from reviving deleted apps.

Corrupt storage is preserved and reported instead of reset. If archiving fails,
a confirmed activation remains authoritative and the error appears in Studio.
Maximum 512 saved revisions; there is no silent eviction. The menu transports only
bounded metadata. Changes use an exact menu ID/version so stale control input
cannot delete or launch a newly selected item.

## Verification

Synthetic tests cover atomic storage, migration provenance, corruption, Trash /
restore, one-use/expired confirmations, protected revisions, voice confirmations
without another model call, stale physical actions, fresh checks and staged
acknowledgement, lost input and overlay priorities. These are synthetic checks,
not proof that a human tried every voice phrase or module. Live deployment and
interaction evidence is recorded separately in `context/build-log.md`.
