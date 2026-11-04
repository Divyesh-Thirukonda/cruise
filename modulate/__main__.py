"""Run with python -m modulate. No generated code is passed to Python exec."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import time
from pathlib import Path

from .activation import Store
from .hardware import Screen, record
from .provider import ProviderError, generate
from .runtime import ValidationError, run


def main():
    parser = argparse.ArgumentParser(description="Voice -> generated screen program; application hot reload, not firmware flashing")
    parser.add_argument("--state-dir", default="context/private/runtime")
    parser.add_argument("--provider", choices=["ollama"], default="ollama")
    parser.add_argument("--model", help="Local Meta Llama model; defaults to llama3.2:1b")
    parser.add_argument("--speech", choices=["local"], default="local")
    parser.add_argument("--audio-device", default="plughw:CARD=Device,DEV=0")
    parser.add_argument("--seconds", type=int, choices=range(1, 11), default=6)
    parser.add_argument("--trigger", choices=["button", "enter"], default="button")
    parser.add_argument("--prompt", help="Explicit typed debugging path; makes one live generation")
    parser.add_argument("--once", action="store_true", help="Record immediately and exit after one request")
    parser.add_argument("--simulate", action="store_true", help="PNG preview only; no physical display")
    parser.add_argument("--display-test", action="store_true", help="Driver diagnostic only; no model request")
    args = parser.parse_args()
    os.umask(0o077)
    store = Store(args.state_dir)
    lock = (store.directory / "service.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error("Another Modulate process owns this state directory")
    screen = Screen(store.directory / "screen.png", simulate=args.simulate)
    model = args.model or "llama3.2:1b"
    speech = None
    if args.speech == "local" and not args.prompt and not args.display_test:
        from .speech import LocalSpeech
        screen.status("Loading speech...", "Meta wav2vec 2.0 / local")
        speech = LocalSpeech()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))

    def event(kind, **values):
        # Deliberately excludes audio, secrets, full transcripts and generated text.
        payload = {"event": kind, "time": time.time(), "device": "simulator" if args.simulate else "pi-tft", **values}
        print(json.dumps(payload), flush=True)
        with (store.directory / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(payload) + "\n")

    def ready():
        if store.active:
            store.restore(screen)
        else:
            screen.status("Ready to listen", f"Press TFT button A (23)\nSpeak for {args.seconds} seconds\nB (24): previous program")

    def request(prompt=None):
        started = time.monotonic()
        base = store.revision
        try:
            if prompt is None:
                screen.status("Listening...", f"Speak now: {args.seconds} seconds\nUSB microphone")
                event("recording", seconds=args.seconds)
                wav = record(args.seconds, args.audio_device)
                screen.status("Transcribing...", "Meta wav2vec 2.0 / local")
                prompt = speech.transcribe(wav)
                del wav
                if not prompt.strip():
                    raise ValueError("No intelligible speech")
                event("transcribed", characters=len(prompt), speech=args.speech)
            else:
                event("typed_debug_request", characters=len(prompt))
            # Private local evidence only; this directory is ignored by Git.
            (store.directory / "last-request.txt").write_text(prompt)
            current = store.current_code()
            feedback = ""
            for attempt in range(2):
                screen.status("Generating..." if not attempt else "Repairing...", f"Meta Llama / local\n{model[:30]}")
                event("generating", provider=args.provider, model=model, attempt=attempt + 1)
                candidate = generate(prompt, provider=args.provider, model=model,
                                     previous_code=current, feedback=feedback)
                (store.directory / f"candidate-{time.time_ns()}.json").write_text(json.dumps(candidate, indent=2))
                try:
                    run(candidate["code"])
                    break
                except ValidationError as error:
                    event("verification_rejected", attempt=attempt + 1, reason=str(error)[:160])
                    if attempt:
                        raise
                    feedback = str(error)[:300]
                    current = candidate["code"]
            screen.status("Checked. Activating", "New application revision")
            active = store.activate(candidate, screen, base_revision=base)
            event("activated", provider=active["provider"], model=active["model"],
                  revision=active["revision"], number=active["frame"]["number"],
                  seconds=round(time.monotonic() - started, 2), attempts=attempt + 1)
            return True
        except Exception as error:
            # Do not leak network exceptions that may contain credentials/payloads.
            detail = str(error)[:120] if isinstance(error, (ProviderError, ValidationError)) else type(error).__name__
            event("request_failed", error_type=type(error).__name__, detail=detail)
            screen.status("Request failed", "Previous program preserved\nSee local event log\nTry TFT A again")
            time.sleep(2)
            ready()
            return False

    try:
        if args.display_test:
            screen.status("Display connected", "MODULATE / driver test\nNo model used")
            event("display_driver_test")
            return 0
        ready()
        event("ready", provider=args.provider, model=model, trigger=args.trigger)
        if args.prompt is not None or args.once:
            return 0 if request(args.prompt) else 1
        if args.trigger == "button" and args.simulate:
            parser.error("Simulator requires --trigger enter, --once or --prompt")
        while True:
            if args.trigger == "enter":
                input("Press Enter, then speak. Ctrl-C quits. ")
                request()
            elif screen.pressed(0):
                # Capture begins on press; no automatic ambient recording.
                request()
                while screen.pressed(0):
                    time.sleep(0.05)
            elif screen.pressed(1):
                try:
                    previous = store.rollback(screen)
                    event("rolled_back", revision=previous["revision"])
                except Exception as error:
                    event("rollback_unavailable", error_type=type(error).__name__)
                while screen.pressed(1):
                    time.sleep(0.05)
            time.sleep(0.05)
    except (KeyboardInterrupt, EOFError):
        event("stopped")
        return 0
    finally:
        if speech is not None:
            speech.close()
        screen.close()
        lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
