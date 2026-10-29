# Modulate customer-flow review — plugin 0.4.0

## Verdict

No remaining blocking finding in the reviewed customer flow for the existing configured hub. The revised skill, helper, narrow localhost setup page and public entry flow consistently send customers through enrollment when needed → `/setup` for native comparison and browser-code handoff → the verified public `/connect` page. No inspected customer CTA or automatic transition points to the full localhost developer Studio. Public `/connect/studio` remains the intended connected workspace.

This was a source review and synthetic rehearsal, not live onboarding. No device, service, private configuration, real browser session, gateway, authentication, provider or model was accessed. All requests and mutations in the tests were isolated fixture calls. This reviewer made no repository edits or live state changes.

## Four rehearsals

### 1. Fresh preloaded gadget; user wants the website

The skill prepares/reuses the Mac installation, asks only for unavailable physical information, and uses the local enrollment helper if enrollment is missing. Matching completion navigates to `http://127.0.0.1:8787/setup`. Native comparison and fresh physical approval remain a separate step. Opening `/setup` alone creates no request or grant; the synthetic initial page showed “Let Modulate use this Mac.” with zero POSTs.

Local telemetry plus active native pairing is an intermediate checkpoint. The agent must verify the installation's public API reaches this companion before the browser-code handoff. Browser linking leads to access review, preserving current settings until the user changes them. Actual browser session success and fresh device state finish website setup.

A separate customer's hub requires its own owned configuration/admin path. The skill forbids repointing the shared demo or borrowing its secrets. This is not multi-tenant provisioning.

### 2. Enrollment complete; native pairing active; gateway off

The workflow skips both enrollment and native re-pairing. Synthetic `/setup` showed “One more connection step.”, hid browser-code creation and made zero POSTs. It keeps the verified local link while the agent repairs the existing installation's remote route or explains the independent-hub blocker.

Appropriate response: “Your gadget and Mac are already linked. The website connection still needs to be restored; I’ll keep the pairing and finish that step.” This states the next action, not completed remote access. Localhost is not presented as the requested finish.

### 3. Current browser already has a valid session

The agent retains the session and reads fresh device state. Public `/connect` routes directly to `/connect/studio`; no new code, revocation or permission write occurs. The focused public test explicitly asserts read-only API calls and this navigation.

A global local browser count is not treated as this browser's authentication: the separate local fixture with one existing session did not claim current-browser readiness or perform a POST. `Keep current access` writes nothing; saving access sends only explicit changes.

### 4. Expired or replaced code

Expired native/browser codes disappear without auto-approval, automatic regeneration or success claims. Valid pending offers are reused. A fresh read precedes code preparation and clipboard handoff. A new code needs a deliberate action and, for native pairing, a new physical comparison.

The local page's handoff now says: “A browser connection was added. The website will check this browser’s session.” It cannot authenticate the current browser itself. Actual public session/device checks remain authoritative.

## Reproduced issue and verified correction

The initial actual-JavaScript rehearsal displayed offer A, then supplied a poll with no offer and unchanged browser count, then an unrelated browser-count increase. The old `seenWebsite` survived offer invalidation and misleadingly announced completion.

The owner cleared remembered evidence when an offer disappears without an immediate qualifying count increase and added a regression. An independent rerun of the exact sequence stayed at “Bring it to Modulate.” with no completion claim and zero synthetic mutations. Neutral handoff text also removes the unsupported claim that the exact displayed code/current browser was authenticated; replacement and claim can occur between polls.

## Checks independently run

- `node --test tests/customer-setup.test.cjs`: **11/11 passed** after the final correction.
- Focused `EntryScreens.test.js` and `Connect.test.js`: **20/20 passed** with mocked APIs.
- Separate JSDOM rehearsal ran the shipped setup JavaScript against fixtures for initial load, gateway-off, existing global browser count and the stale-offer sequence.
- Source tracing confirmed fresh-state guards, active pairing reuse, bounded setup routes, separate physical confirmation, and no default permission payload during browser claim.

## Limits

`remote_enabled` is local configuration, not proof of public reachability or correct-hub routing. The revised skill requires independent public-API verification; public failures remain visible. The current URL contract is a fixed reviewed deployment, so an unrelated new Mac still needs an owned configured connection path. No live Pi revision, physical display, native grant, public deployment, browser redemption, model access or uptime was verified here. The 31 passing tests are synthetic behavioral evidence only.
