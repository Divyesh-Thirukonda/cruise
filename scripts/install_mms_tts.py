#!/usr/bin/env python3
"""Install public Meta MMS weights in a separate Pi CPU environment.

Weights: facebook/mms-tts-eng, CC-BY-NC-4.0; see context/meta-mms.md.
Does not change the running provider or touch any cost ledger.
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    environment = ROOT / ".venv-mms"
    subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    python = str(environment / "bin/python")
    subprocess.run([python, "-m", "pip", "install", "--only-binary=:all:", "-r", str(ROOT / "requirements-tts-mms.txt")], check=True)
    script = """from huggingface_hub import snapshot_download
from pathlib import Path
import hashlib,sys
p=Path(snapshot_download('facebook/mms-tts-eng', revision='c71de0fe7204c83f1c10820a7d696d0b450048ba', allow_patterns=['*.json','model.safetensors','README.md'], local_dir=sys.argv[1]))
with (p/'model.safetensors').open('rb') as f:
    assert hashlib.file_digest(f,'sha256').hexdigest()=='69cf8b651c1493f1801dfd2311c298d694a38357bc9a1e41f410491ea6f0e1be'
print('Pinned MMS weights verified')
"""
    subprocess.run([python, "-c", script, str(ROOT / "brain/models/mms-tts-eng")], check=True)

if __name__ == "__main__": main()
