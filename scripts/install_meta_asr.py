#!/usr/bin/env python3
"""Install pinned Meta recognition and standalone speech gating with Python 3.11.

No microphone capture, provider calls, service changes or ledger modifications.
Install requirements-product-pi.txt in the device venv too.
"""
import hashlib
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    environment = ROOT / ".venv-asr"
    subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    python = str(environment / "bin/python")
    subprocess.run([python, "-m", "pip", "install", "--only-binary=:all:", "-r", str(ROOT / "requirements-speech-meta.txt")], check=True)
    script = """from huggingface_hub import snapshot_download
from pathlib import Path
import hashlib,sys
p=Path(snapshot_download('facebook/wav2vec2-base-960h', revision='22aad52d435eb6dbaf354bdad9b0da84ce7d6156', allow_patterns=['*.json','model.safetensors','README.md'], local_dir=sys.argv[1]))
with (p/'model.safetensors').open('rb') as f:
    if hashlib.file_digest(f,'sha256').hexdigest()!='8aa76ab2243c81747a1f832954586bc566090c83a0ac167df6f31f0fa917d74a': raise ValueError('Model checksum mismatch')
print('Pinned Meta speech weights verified')
"""
    subprocess.run([python, "-c", script, str(ROOT / "brain/models/wav2vec2-base-960h")], check=True)
    # Recognition is Meta; this existing non-Meta activity detector remains an
    # explicit exception, described and attributed in context/meta-speech.md.
    base = "https://raw.githubusercontent.com/snakers4/silero-vad/be95df9152c0d7618fa1edfeb296fc3dae32376f/"
    with urllib.request.urlopen(base + "src/silero_vad/data/silero_vad_16k_op15.onnx", timeout=30) as response:
        model = response.read(2_000_001)
    if hashlib.sha256(model).hexdigest() != "7ed98ddbad84ccac4cd0aeb3099049280713df825c610a8ed34543318f1b2c49":
        raise ValueError("Speech detector checksum mismatch")
    target = ROOT / "brain/models/silero-vad.onnx"
    target.write_bytes(model)
    with urllib.request.urlopen(base + "LICENSE", timeout=30) as response:
        target.with_suffix(".LICENSE").write_bytes(response.read(16384))
    print("Local speech assets installed; runtime stays offline")


if __name__ == "__main__":
    main()
