# Demo speed and script notes — October 30

Installed agent revision `8f9e2e4` and website deployment
`dpl_Gaqs8aBF3SkBNfmTTV6viv64NdDC`. Meta now receives a bounded catalog of actual
saved app titles/IDs before planning. It decides semantic suitability; there is
no demo-command router, prewritten game or cached email answer. A repeat can
launch a saved package through the existing verification and device acknowledgement
path. A request for a fresh/different version still generates. An edit refines the
active app. Failed launches cannot bypass current hardware/permission checks.

Same-title revisions now show one latest entry in the Pi's All apps menu and
website by default. Website “Show earlier saved versions” reveals retained
revisions. Favorites and Trash retain their individual revision semantics;
trashing the latest version can reveal an older saved version. No old packages
were deleted or merged. Distinct app titles remain separate.

Generic instructions encourage batching skill loading and fresh observations in
one model response, avoiding needless delegation and stopping once the requested
information is visible. Computer tasks still use real screenshots/native input.
No Gmail API or replay of a previous subject was added.

## Live measurements

Typed requests through the actual authenticated Pi tunnel, measured submission to
agent ready. Polling adds up to roughly 1.2 seconds. Excludes capture/transcription,
spoken playback and human physical verification. Not a 75%-success benchmark.

| Request | Seconds | Model calls | Result |
| --- | ---: | ---: | --- |
| Make Orbit Catch | 8.8 | 3 | Exact stored revision reopened; no duplicate |
| Make Mario Kart, first trial | 42.7 | 8 | Newly generated original Pixel Kart; check failure repaired |
| Make Mario Kart, repeated | 6.6 | 3 | Exact Pixel Kart revision reopened; no duplicate |
| Open the app library | 4.1 | 3 | Library opened |
| Reverse it, while library open | 5.3 | 3 | Library direction saved reversed |
| Make the coins red in the kart game | 18.3 | 6 | New checked Pixel Kart revision activated |
| Make Mario Kart, after edit | 9.1 | 4 | Latest red-coin revision reopened; no duplicate |

Five of seven trials were under 15 seconds. Fresh generation and editing exceeded
the target. Real Meta planning/checking kept the Muse processing display active
for several seconds; no artificial thinking delay or false inference label was
added. The first racer was generated live during this authorized test and remains
saved. When reopening it during a demo, describe it as reuse rather than claiming
fresh generation. Exact revisions/costs are in [demo-speed.json](evidence/demo-speed.json).

The previous Orbit Catch and library knob preference were restored after testing.
The new racer and its edit remain in the library. Speaker stayed at its existing
0%; audibility was not tested. Mac pairing was expired, so no new Gmail, YouTube,
brightness-binding, camera or computer-audio timing is claimed. A fresh physical
comparison-code confirmation is required before those trials. Earlier brightness
read/set/restore and camera/audio successes remain historical evidence.

## Corrections for the supplied narration

- Say **Meta MMS speech on the Pi**, rather than ElevenLabs, for the current setup.
- Brightness uses **a Meta-generated control binding, capability checks and an
  authenticated native macOS bridge**. Reverse changes the declarative mapping;
  it does not rewrite the macOS driver. Physical knob-to-brightness still needs
  a filmed check on the current session.
- The joystick is currently disconnected; the live racer chose IMU tilt. Describe
  the controls that the current capability manifest actually reports.
- Supported I²C diagnosis/address repair includes guided physical isolation,
  power cycling and reconnection. Do not claim fully autonomous physical repair,
  a collision inferred from scanning alone, or a newly completed repair trial.
- Library navigation currently supports knob/joystick and A/B, with a persistent
  direction preference. Arbitrarily rebinding it to any peripheral is not yet
  established. An IMU game mapping does not prove IMU library navigation.
- Voice cannot rewrite the agent harness or switch the configured provider.
  Development-time provider adapters do not establish voice-driven self-modification.
  Do not claim a specifically demonstrated RFID blocking feature.
- Purchased modules/casings and an infrared TV remote are future scenarios until
  the components, integration and physical behavior are actually demonstrated.
- For “watch an interesting video,” show an actual observed selection/playback;
  do not imply it understands video content without a demonstrated input path.

Fresh Mac observations and a valid native session are necessary to measure the
remaining computer tasks. Do not use a private inbox in public footage without
choosing safe content. Automatic tunnel discovery is still awaiting the separate
Cloudflare deployment authorization; the website currently uses the temporary
identity-verified direct tunnel configured during the Blob outage.
