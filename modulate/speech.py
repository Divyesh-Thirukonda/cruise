"""Local speech recognition; no network request once weights are cached."""
import io


class LocalSpeech:
    def __init__(self, model="tiny.en"):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=2)

    def transcribe(self, wav_bytes):
        segments, _ = self.model.transcribe(
            io.BytesIO(wav_bytes), language="en", beam_size=1,
            condition_on_previous_text=False, vad_filter=True,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        if len(text) > 2000:
            raise ValueError("Transcript is too long")
        return text
