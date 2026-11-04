"""Optional Modal job for the existing verifier; never activates a device app.

Run explicitly: modal run integrations/modal_verify.py --package-path app.json
Remote execution has not been validated. The default product does not call this.
"""
import json
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
app = modal.App("modulate-package-verifier")
image = (modal.Image.debian_slim(python_version="3.12")
         .apt_install("libseccomp2")
         .pip_install("quickjs-ng==0.17.0.2"))
# Explicit source allowlist: never upload the checkout, credentials or state.
for filename in ("__init__.py", "game_runtime.py", "game_worker.py", "imu.py"):
    image = image.add_local_file(ROOT / "modulate" / filename,
                                 "/root/modulate/" + filename)


@app.function(image=image, cpu=1, memory=512, timeout=60, retries=0,
              max_containers=1)
def verify_package(package: dict) -> dict:
    from modulate.game_runtime import verify
    return {"backend_target": "modal", "scope": "simulated-package-checks",
            "activation_authorized": False, "report": verify(package)}


@app.local_entrypoint()
def main(package_path: str):
    from modulate.game_runtime import MAX_PACKAGE_BYTES, validate_package
    # Reject oversized/invalid packages before uploading anything.
    with Path(package_path).open("rb") as stream:
        raw = stream.read(MAX_PACKAGE_BYTES + 1)
    if len(raw) > MAX_PACKAGE_BYTES:
        raise ValueError("Package exceeds the upload size limit")
    package = validate_package(json.loads(raw))
    result = verify_package.remote(package)
    print(json.dumps(result, indent=2))
    if not result["report"]["passed"]:
        raise SystemExit(1)
