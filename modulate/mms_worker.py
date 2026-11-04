"""Isolated trusted worker; dependencies come from requirements-tts-mms.txt."""
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

MODEL_SHA256 = "69cf8b651c1493f1801dfd2311c298d694a38357bc9a1e41f410491ea6f0e1be"
REVISION = "c71de0fe7204c83f1c10820a7d696d0b450048ba"


def spoken_number(value):
    ones = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
    tens = "zero ten twenty thirty forty fifty sixty seventy eighty ninety".split()
    n = int(value)
    if n < 20: return ones[n]
    if n < 100: return tens[n//10] + (" " + ones[n%10] if n%10 else "")
    for size, name in ((1_000_000_000, "billion"), (1_000_000, "million"), (1000, "thousand"), (100, "hundred")):
        if n >= size:
            return spoken_number(str(n//size)) + " " + name + (" " + spoken_number(str(n%size)) if n%size else "")


def normalize(text):
    text = text.replace("%", " percent").replace("&", " and ")
    return re.sub(r"\d+(?:\.\d+)?", lambda m: spoken_number(m[0].split(".")[0]) +
                  (" point " + " ".join(spoken_number(x) for x in m[0].split(".")[1]) if "." in m[0] else ""), text)


def chunks(text):
    words, result, current = normalize(text).split(), [], ""
    for word in words:
        if len(current) + len(word) > 220 and current:
            result.append(current); current = ""
        current += (" " if current else "") + word
    if current: result.append(current)
    return result


def main():
    import numpy as np
    import torch
    from transformers import VitsModel, VitsTokenizer
    directory = Path(sys.argv[1])
    with (directory / "model.safetensors").open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != MODEL_SHA256:
            raise ValueError("MMS weights do not match the pinned revision")
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    model = VitsModel.from_pretrained(directory, local_files_only=True, use_safetensors=True).eval()
    tokenizer = VitsTokenizer.from_pretrained(directory, local_files_only=True)
    for line in sys.stdin.buffer:
        try:
            if len(line) > 10_000: raise ValueError("Oversized request")
            text = json.loads(line)["text"]
            if not isinstance(text, str) or not 1 <= len(text) <= 1200: raise ValueError("Invalid text")
            audio = []
            total = 0
            for phrase in chunks(text):
                inputs = tokenizer(phrase, return_tensors="pt")
                if inputs.input_ids.shape[-1] > 800: raise ValueError("Oversized phrase")
                with torch.inference_mode(): waveform = model(**inputs).waveform[0].cpu().numpy()
                if not np.isfinite(waveform).all(): raise ValueError("Invalid samples")
                count = round(len(waveform) * 24000 / model.config.sampling_rate)
                total += count
                if total > 24000*90: raise ValueError("Oversized audio")
                samples = np.interp(np.arange(count) * model.config.sampling_rate/24000, np.arange(len(waveform)), waveform)
                audio.append((np.clip(samples, -1, 1)*32767).astype("<i2").tobytes())
            pcm = b"".join(audio)
            sys.stdout.buffer.write(struct.pack("!I", len(pcm)) + pcm)
            sys.stdout.buffer.flush()
        except Exception:
            # Never echo text or library diagnostics to the parent/logs.
            sys.stdout.buffer.write(struct.pack("!I", 0)); sys.stdout.buffer.flush()


if __name__ == "__main__": main()
