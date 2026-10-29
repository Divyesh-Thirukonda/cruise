# Portable setup skill forward trial

Decision/workflow simulation only. Read the skill, native-setup reference, safe probe source, and the public enrollment implementation's identity-position logic. No live endpoints, browser, services, private files, devices, or paid calls were used. No repository files were modified.

## Case A — already complete local installation

Observed input: current helper complete; Studio device connected, pairing true, remote disabled; required native permissions true. The user's two A presses are history, not the success evidence.

Chosen actions: inspect the current helper and Studio state; use the same relevant tab to show local Studio; retain enrollment and pairing; finish. Do not request another A press, reopen enrollment, create a browser code, configure remote access, or run a paid/physical feature test.

Exact customer response after those simulated actions:

> Your local setup is complete. Studio sees the gadget online, Mac pairing is active, and the required Mac permissions are granted. You can use [Modulate Studio](http://127.0.0.1:8787).

## Case B — private entry, delegated entry, mismatch, then completion

### 1. Initial request for private entry

Chosen actions: keep/reuse the local helper tab and let the user enter the device identity and setup code directly. Do not request that they paste the values into chat. Do not claim the request is already enrolled.

Exact customer response after showing the ready helper:

> Enter the gadget identity and eight-digit setup code directly in the local helper, keeping any leading zeroes, then submit. I’ll check what the helper needs next.

### 2. User supplies current details and asks the agent to enter and submit

Chosen actions: refresh the helper and Studio state. Given the helper is still ready and the form tools support the authorized action, fill and submit the supplied values in the existing tab. Do not hand the browser work back to the user. Do not echo either value. Inspect the resulting status.

Exact customer progress response:

> I’ll enter those details in the local helper, submit them, and check the result.

### 3. Current error is identity_mismatch / check_identity; user says it does not work

Chosen actions: inspect current helper and Studio immediately before the handoff. If the reported mismatch still exists, ask only for the physical character at group 2, character 8. No enrollment was sent. Do not replace the identity from the network certificate, assume expiry, ask for a whole new code, retry guesses, or ask for A.

Exact customer response for the supplied current error:

> The helper found an identity mismatch and sent no enrollment request. Please check group 2, character 8 on the gadget’s screen and tell me that character.

### 4. User physically confirms the corrected character and authorizes its use

Chosen actions: inspect fresh helper and Studio state before editing or retrying. Because helper is now complete and Studio is online with pairing active, discard the stale form/correction plan, show Studio in the same tab, and finish. Do not apply the corrected character, submit again, or ask for another physical confirmation. No additional feature permissions or physical output have been established by this case.

Exact customer response:

> Setup is complete now. Studio sees the gadget online and Mac pairing is active. You can use [Modulate Studio](http://127.0.0.1:8787).

## Behavioral evidence and ambiguities

- Mocked execution of the shipped live_status function accepts Case A's raw connection booleans and reports local_connection_ready true while remote_gateway_configured is false. This is fixture-backed parser evidence, not a real onboarding result.
- A separate injected error fixture preserves identity_mismatch and check_identity but deliberately drops the free-text message. Its Studio booleans were synthetic parser scaffolding, not facts inferred about Case B. The group/character hint must come from the fresh helper UI or other allowed targeted read; the probe alone does not carry it.
- Public enrollment source defines two groups of ten characters, so group 2, character 8 is unambiguous. A mismatch location does not authorize a replacement character.
- No blocking ambiguity in either supplied case. Case A's supplied statuses are treated as current observations. Case B must refresh state after the user's correction; its final state supersedes the earlier error even if this agent never made the correction itself.
- The Case B final fixture does not establish additional native permission grants, model/provider access, physical screen behavior, or feature reliability; the response claims only the observed local connection and pairing.
