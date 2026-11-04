# Optional Baseten and Modal integrations

Implemented November 4, 2026. **Code integration and local tests only:** no
Baseten inference request, Modal cloud execution, or physical-device trial was
performed for this change. Neither service is part of the demonstrated live path.
No cloud configuration, deployment, provider default, or existing ledger changed.

## Baseten: optional Meta model transport

`modulate.agent_provider.AgentProvider` accepts `provider="baseten"` and uses
Baseten Model APIs at `https://inference.baseten.co/v1/chat/completions` with a
server-side `BASETEN_API_KEY`. It reuses bounded requests/responses, tool-name
validation, sanitized errors, redirect rejection, and normalized usage metadata.
The Studio CLI and private credential loader recognize the optional provider.

The model must be supplied explicitly as a Meta-family slug from the operator's
account. The prefix check is a naming restriction, not proof of model identity,
availability, tool support, or account access. No default Baseten model is selected;
verify those properties before use. Model-specific reasoning options and screenshot
input remain disabled for this adapter. There is no provider fallback.

A network-free configuration check, after setting `BASETEN_MODEL` to the verified
slug, is:

```python
import os
from modulate.agent_provider import AgentProvider, ProviderConfig

provider = AgentProvider(ProviderConfig("baseten", os.environ["BASETEN_MODEL"]))
print(provider.request_budget([{"role": "user", "content": "Make a game."}], []))
```

**Budget gate:** Baseten pricing is intentionally unknown (`None`), not zero.
The existing agent ledger refuses dispatch until verified price accounting is
implemented. Do not bypass that gate with a direct `complete()` call to run the
product. Mock transport tests demonstrate the wire adapter, not billable usage.

## Modal: explicit package-verification job

`integrations/modal_verify.py` registers a Modal Function that calls the existing
fixed QuickJS verifier. Its image installs the pinned QuickJS engine and
`libseccomp2`; only four explicitly named runtime Python files are mounted.
Credentials, private state, camera frames and the rest of the checkout are excluded.
The job has a 60-second timeout, one-container maximum, and no automatic retries.

For a separately authorized future cloud trial, install the optional SDK and use
an already authenticated Modal account:

```sh
python -m pip install -r requirements-modal.txt
python -m modal run integrations/modal_verify.py --package-path /path/to/app.json
```

This is an explicit cloud invocation and can incur Modal charges outside the
product's model ledger; it is never invoked automatically by the Pi or agent.
Local package validation runs before upload. Invalid packages fail before dispatch;
a failed verification produces a nonzero exit code. The report identifies its
backend target, simulated-check scope, and lack of activation authority. It contains
the verifier's package hash and diagnostics. The normal local capability checks,
matching revision verification and device acknowledgement still gate activation.

The checks use simulated inputs, not actual sensors. Cloud timings would not be
Pi performance measurements. This wrapper does not add new test scenarios to the
existing harness. Modal's Linux image and syscall restrictions still need a remote
trial; local SDK tests execute the function body on macOS through `.local()`.

## Reproducing local validation

```sh
python -m pip install -r requirements-product-host.txt -r requirements-modal.txt
python -m unittest tests.test_agent_provider tests.test_agent_provider_errors tests.test_modal_verify tests.test_game_runtime tests.test_studio -q
```

Tests use synthetic Baseten replies and real local game-worker execution. Modal
SDK tests skip when the optional SDK is absent. No account credentials are needed.

## Sources and attribution

- [Baseten Chat Completions](https://docs.baseten.co/reference/inference-api/chat-completions): HTTP contract, bearer authentication, model slug and tool-call transport.
- [Modal Functions](https://modal.com/docs/guide/functions) and [Image API](https://modal.com/docs/reference/modal.Image): function registration and explicit source/image configuration.
- Modal Python SDK 1.6.3 is an optional third-party dependency. The wrapper is original project code; it reuses Modulate's existing QuickJS-NG verifier rather than claiming a new execution engine.
