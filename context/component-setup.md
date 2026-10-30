# Component discovery and setup — October 30, 2026

The Pi now refreshes its I²C inventory in the existing background hardware worker,
about every 15 seconds. It reopens known drivers outside the frame loop. Current
read-backed devices and observed unknown bus addresses enter a component inventory
in the model's request context, inspect_capabilities and the Device dashboard.
Unknown addresses are labeled `needs_identification`; they do not become usable
runtime inputs. Verified driver signals retain their actual names and units.

A new `component-setup` runtime skill coordinates identification, diagnostics,
supported driver installation, verified readings and capability refresh. A user's
request to use an unready component selects this skill through normal Meta tool
planning, then continues the original app request after successful setup. No
component name routes to a fixed game action. The model chooses mappings based on
current signals and the user's requested interaction.

At idle, an identified installable missing catalog driver or an unknown address
stable for five seconds schedules one automatic Meta setup request. Hardware
permission, active speech/listening, an existing task, repair workflow,
active library and activation staging gate scheduling. Attempts are recorded
before dispatch, survive restart and do not repeat for an unchanged problem.
Automatic requests have at most eight model calls within the same $50 ledger.
They can load skills, inspect capabilities, use diagnostic/reinitialization and
verified catalog installation, or ask for required information. They cannot
create/replace apps, operate the computer or change persistent addresses. A
subsequent explicit app request uses newly verified capabilities. Existing
missing-control adaptation remains a separate checked app-edit workflow.

The current installable pack is LSM6DS3TR-C. The installer verifies its identity,
hash-pinned vendor packages and actual readings. This implementation does not
browse the internet, synthesize arbitrary drivers or create new runtime signal
adapters for unknown boards. Such a board needs a model/markings and a compatible
trusted integration before it is usable. USB discovery is not added by this I²C
workflow. Address conflicts can require physical isolation/power cycling; those
confirmations are preserved. Do not rewire a powered assembly for this test.

## Live controlled trial

Deployed c400c7b to the actual Pi from a SHA256-verified repository archive. The Pi
passed 232 focused tests. The active app was already empty at the baseline; no
game-preservation claim is made for this trial.

Temporarily moved the active managed-driver pointer outside the import path and
restarted the services, leaving the sensor physically connected and keeping all
driver files as recoverable backups. No repair request was submitted. The Pi
reported missing IMU input, automatically invoked Meta, loaded setup skills,
restored the verified pack and reported live tilt/acceleration readiness.
Completion was observed after 18.34 seconds including service startup, five model
calls and $0.067437 charged/reserved. This reused the cached pinned pack; it does
not claim a new network download or a physical hot-plug trial. The existing
empty app state was unchanged. Physical tilt feel, visible display and audibility
were not rechecked.

A follow-up address-list deduplication is f5cd377. Validation and final restart
results are recorded in `evidence/component-setup.json`. Unknown-board behavior,
permission gating, stale/failed attempt journals, automatic tool restrictions and
periodic new-address discovery are synthetic tests, distinct from this sensor trial.

After the final update, an agent restart retained IMU readiness and produced zero
additional model calls during a 20-second observation. The Pi passed 38 final
focused checks. Final host suite: 1130 tests, 13 skips; website: 45 API tests,
40 UI tests and a production build.
