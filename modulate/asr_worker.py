"""Trusted offline Meta wav2vec 2.0 worker. No remote code or pickle weights."""
import hashlib
import json
from pathlib import Path
import struct
import sys

MODEL = "facebook/wav2vec2-base-960h"
REVISION = "22aad52d435eb6dbaf354bdad9b0da84ce7d6156"
MODEL_SHA256 = "8aa76ab2243c81747a1f832954586bc566090c83a0ac167df6f31f0fa917d74a"
MAX_PCM = 16000 * 2 * 25


def decode_logits(logits, processor, blank_id):
    """Greedy CTC with a conservative emission-confidence gate; no prompt bias."""
    import torch
    if logits.ndim != 3 or logits.shape[0] != 1 or not torch.isfinite(logits).all():
        raise ValueError("Invalid recognition logits")
    probabilities, ids = logits.float().softmax(-1).max(-1)
    emitted = ids != blank_id
    if int(emitted.sum()) < 3 or float(probabilities[emitted].mean()) < .5:
        return ""
    text = processor.batch_decode(ids)[0].strip()
    if type(text) is not str or len(text) > 2000 or any(ord(c) < 32 for c in text):
        raise ValueError("Invalid transcript")
    return text


def main():
    import numpy as np
    import torch
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
    directory = Path(sys.argv[1])
    with (directory / "model.safetensors").open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != MODEL_SHA256:
            raise ValueError("Meta speech weights do not match the pinned revision")
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    model = Wav2Vec2ForCTC.from_pretrained(directory, local_files_only=True, use_safetensors=True).eval()
    processor = Wav2Vec2Processor.from_pretrained(directory, local_files_only=True)
    while header := sys.stdin.buffer.read(4):
        if len(header) != 4:
            break
        size = struct.unpack("!I", header)[0]
        if not 2 <= size <= MAX_PCM or size % 2:
            break
        pcm = sys.stdin.buffer.read(size)
        if len(pcm) != size:
            break
        try:
            samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
            if len(samples) < 400 or float(np.sqrt(np.mean(samples * samples))) < .0002:
                text = ""
            else:
                inputs = processor(samples, sampling_rate=16000, return_tensors="pt")
                with torch.inference_mode():
                    text = decode_logits(model(**inputs).logits, processor, model.config.pad_token_id)
            output = json.dumps(text).encode()
            sys.stdout.buffer.write(struct.pack("!I", len(output)) + output)
            sys.stdout.buffer.flush()
        except Exception:
            sys.stdout.buffer.write(struct.pack("!I", 0))
            sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
