"""Synthetic TTS process/queue tests; no speech, player or hardware is opened."""

import os
import hashlib
import subprocess
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modulate.speaker import LocalSpeechBackend, Speaker, SpeakerError, MAX_TEXT_CHARACTERS
from modulate.device_transport import SPEECH_FORMAT, MAX_SPEECH_BYTES, TransportError


def audio_descriptor(payload, identifier="a" * 32):
    return {"id": identifier, "format": SPEECH_FORMAT, "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest()}


def wait_until(condition):
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("Synthetic speech worker did not finish")


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.cancel_seen = threading.Event()
        self.failure = None
        self.available = True

    def info(self):
        return {"available": self.available, "backend": "synthetic", "output": "synthetic-sink", "error": None}

    def play(self, text, cancel):
        self.calls.append(text)
        self.started.set()
        if self.failure:
            raise self.failure
        while not self.release.is_set():
            if cancel.wait(0.005):
                self.cancel_seen.set()
                # Keep cancellation pending for deterministic latest-wins tests.
                self.release.wait(1)
                return False
        return not cancel.is_set()

    def play_pcm(self, audio, cancel):
        return self.play(audio, cancel)


class SpeakerTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.statuses = []
        self.speaker = Speaker(self.statuses.append, self.backend)
        self.addCleanup(self.backend.release.set)
        self.addCleanup(self.speaker.stop)

    def test_unavailable_backend_never_claims_playback(self):
        self.backend.available = False
        speaker = Speaker(backend=self.backend)
        self.addCleanup(speaker.stop)
        self.assertFalse(speaker.start())
        pause = Mock()
        self.assertFalse(speaker.speak("Synthetic request", before_playback=pause))
        pause.assert_not_called()
        self.assertEqual(speaker.snapshot()["state"], "unavailable")
        self.assertIsNone(speaker.snapshot()["last_delivery"])
        self.assertEqual(self.backend.calls, [])

    def test_capture_pause_hook_only_runs_for_accepted_speech_before_playback(self):
        pause = Mock()
        self.assertFalse(self.speaker.speak("Stopped", before_playback=pause))
        self.speaker.start()
        for text in ("", "bad\0text", "x" * (MAX_TEXT_CHARACTERS + 1)):
            with self.assertRaises(ValueError):
                self.speaker.speak(text, before_playback=pause)
        pause.assert_not_called()
        play = self.backend.play
        def checked_play(text, cancel):
            pause.assert_called_once_with()
            return play(text, cancel)
        self.backend.release.set()
        with patch.object(self.backend, "play", side_effect=checked_play):
            self.assertTrue(self.speaker.speak("Accepted", before_playback=pause))
            wait_until(lambda: self.speaker.snapshot()["last_delivery"] == "delivered")
        self.assertEqual(self.backend.calls, ["Accepted"])

    def test_delayed_active_status_cannot_overwrite_new_idle_status(self):
        entered, release, second_done = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        delivered = []
        def callback(status):
            if status["state"] == "queued":
                entered.set()
                release.wait(1)
            delivered.append(status["state"])
        self.speaker.on_status = callback
        # Force the callback scheduling that previously left the controller's
        # cache queued after playback was already idle, permanently muting wake.
        self.speaker._state = "queued"
        first = threading.Thread(target=self.speaker._notify)
        first.start()
        self.assertTrue(entered.wait(1))
        with self.speaker._changed:
            self.speaker._state = "idle"
        def idle_notification():
            self.speaker._notify()
            second_done.set()
        second = threading.Thread(target=idle_notification)
        second.start()
        try:
            self.assertFalse(second_done.wait(0.05))
        finally:
            release.set()
            first.join(1)
            second.join(1)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(delivered, ["queued", "idle"])

    def test_latest_request_replaces_active_and_single_pending_without_content_in_status(self):
        self.speaker.start()
        self.speaker.speak("PRIVATE_FIRST")
        self.assertTrue(self.backend.started.wait(1))
        self.speaker.speak("PRIVATE_DROPPED")
        self.assertTrue(self.backend.cancel_seen.wait(1))
        self.speaker.speak("PRIVATE_LATEST")
        latest = self.speaker.snapshot()["request_id"]
        self.backend.release.set()
        wait_until(lambda: self.speaker.snapshot()["last_delivery"] == "delivered")
        self.assertEqual(self.backend.calls, ["PRIVATE_FIRST", "PRIVATE_LATEST"])
        self.assertEqual(self.speaker.snapshot()["request_id"], latest)
        self.assertNotIn("PRIVATE", str(self.statuses) + str(self.speaker.snapshot()))
        self.assertIsNone(self.speaker._pending)

    def test_cancel_discards_pending_and_stops_active(self):
        self.speaker.start()
        self.speaker.speak("first")
        self.assertTrue(self.backend.started.wait(1))
        self.speaker.speak("pending")
        self.speaker.cancel()
        self.assertTrue(self.backend.cancel_seen.wait(1))
        self.backend.release.set()
        wait_until(lambda: self.speaker.snapshot()["state"] == "idle")
        self.assertEqual(self.backend.calls, ["first"])
        self.assertEqual(self.speaker.snapshot()["last_delivery"], "cancelled")

    def test_stop_prevents_new_work_and_cancels_active_audio(self):
        self.speaker.start()
        self.speaker.speak("first")
        self.assertTrue(self.backend.started.wait(1))
        self.backend.release.set()
        self.assertTrue(self.speaker.stop())
        self.assertFalse(self.speaker.speak("late"))
        self.assertEqual(self.speaker.snapshot()["state"], "stopped")

    def test_failure_reports_generic_error_without_raw_content(self):
        self.backend.failure = RuntimeError("PRIVATE_REQUEST_DETAILS")
        self.speaker.start()
        self.speaker.speak("private request")
        wait_until(lambda: self.speaker.snapshot()["state"] == "error")
        self.assertEqual(self.speaker.snapshot()["last_delivery"], "failed")
        self.assertNotIn("PRIVATE", str(self.statuses))
        self.assertIn("rejected playback", self.speaker.snapshot()["error"])

    def test_size_limit_rejects_instead_of_silently_truncating(self):
        self.speaker.start()
        for text in ("", " ", None, "a" * (MAX_TEXT_CHARACTERS + 1), "bad\0text"):
            with self.subTest(text_type=type(text).__name__), self.assertRaises(ValueError):
                self.speaker.speak(text)
        self.assertEqual(self.backend.calls, [])

    def test_status_callback_failure_does_not_kill_worker(self):
        self.speaker.on_status = Mock(side_effect=RuntimeError("UI failure"))
        self.backend.release.set()
        self.assertTrue(self.speaker.start())
        self.assertTrue(self.speaker.speak("one request"))
        wait_until(lambda: self.speaker.snapshot()["last_delivery"] == "delivered")

    def test_unavailable_audio_recovers_on_background_worker_without_blocking_request_thread(self):
        self.backend.available = False
        entered, restore = threading.Event(), threading.Event()
        def refresh():
            entered.set()
            self.assertTrue(restore.wait(1))
            self.backend.available = True
            return self.backend.info()
        self.backend.refresh = refresh
        speaker = Speaker(backend=self.backend)
        self.addCleanup(speaker.stop)
        self.addCleanup(restore.set)
        self.assertFalse(speaker.start())
        self.assertTrue(entered.wait(1))
        self.assertFalse(speaker.speak("not yet"))
        self.assertFalse(speaker.snapshot()["available"])
        restore.set()
        wait_until(lambda: speaker.snapshot()["available"])
        self.backend.release.set()
        self.assertTrue(speaker.speak("Recovered"))
        wait_until(lambda: speaker.snapshot()["last_delivery"] == "delivered")
        self.assertEqual(self.backend.calls, ["Recovered"])

    def test_recovery_retry_is_spaced_and_stop_interrupts_the_retry_wait(self):
        self.backend.available = False
        self.backend.refresh = Mock(side_effect=self.backend.info)
        speaker = Speaker(backend=self.backend)
        self.addCleanup(speaker.stop)
        with patch("modulate.speaker.RECOVERY_SECONDS", 0.05):
            speaker.start()
            wait_until(lambda: self.backend.refresh.call_count >= 1)
            first = self.backend.refresh.call_count
            time.sleep(0.01)
            self.assertEqual(self.backend.refresh.call_count, first)
            wait_until(lambda: self.backend.refresh.call_count >= 2)
            self.assertTrue(speaker.stop())

    def test_remote_audio_fetch_runs_on_worker_then_pcm_with_provider_label(self):
        payload = b"\x01\x00" * 200
        descriptor = audio_descriptor(payload)
        pause = Mock()
        caller = threading.get_ident()
        def fetch(audio, cancel):
            pause.assert_called_once_with()
            self.assertNotEqual(threading.get_ident(), caller)
            self.assertEqual(audio, descriptor)
            self.assertFalse(cancel.is_set())
            return payload
        self.speaker.audio_fetch = fetch
        self.backend.release.set()
        self.speaker.start()
        self.assertTrue(self.speaker.speak("PRIVATE_DISPLAY_ONLY", descriptor, before_playback=pause))
        wait_until(lambda: self.speaker.snapshot()["last_delivery"] == "delivered")
        self.assertEqual(self.backend.calls, [payload])
        self.assertEqual(self.speaker.snapshot()["provider"], "elevenlabs")
        self.assertTrue(self.speaker.snapshot()["backend"].startswith("elevenlabs/"))
        self.assertIn("fetching", [status["state"] for status in self.statuses])
        self.assertNotIn("PRIVATE", str(self.statuses))
        self.assertIsNone(self.speaker._pending)

    def test_invalid_remote_descriptor_does_not_pause_capture_or_fetch(self):
        self.speaker.audio_fetch = Mock()
        self.speaker.start()
        pause = Mock()
        valid = audio_descriptor(b"\x01\x00")
        for changes in ({"bytes": 3}, {"bytes": MAX_SPEECH_BYTES + 2}, {"format": "mp3"},
                        {"url": "https://elsewhere.invalid"}, {"sha256": "bad"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.speaker.speak("Synthetic reply", {**valid, **changes}, before_playback=pause)
        pause.assert_not_called()
        self.speaker.audio_fetch.assert_not_called()
        self.assertEqual(self.backend.calls, [])

    def test_remote_fetch_failure_or_bad_bytes_never_fall_back_to_local_text(self):
        valid = audio_descriptor(b"\x01\x00" * 100)
        for failure in (TransportError("PRIVATE_AUTH_ERROR"), b"wrong", b"\x02\x00" * 100,
                        b"\x00" * (MAX_SPEECH_BYTES + 2)):
            with self.subTest(result_type=type(failure).__name__):
                self.speaker.audio_fetch = Mock(side_effect=failure) if isinstance(failure, Exception) else Mock(return_value=failure)
                self.speaker.start()
                self.speaker.speak("PRIVATE_NEVER_LOCAL_FALLBACK", valid)
                wait_until(lambda: self.speaker.snapshot()["last_delivery"] == "failed")
                self.assertIn("Speech audio", self.speaker.snapshot()["error"])
                self.assertEqual(self.backend.calls, [])
                self.assertNotIn("PRIVATE", str(self.statuses))

    def test_new_remote_reply_cancels_old_fetch_and_only_latest_pcm_is_played(self):
        first, latest = b"\x01\x00" * 100, b"\x02\x00" * 100
        entered = threading.Event()
        def fetch(descriptor, cancel):
            if descriptor["id"] == "a" * 32:
                entered.set()
                self.assertTrue(cancel.wait(1))
                return first
            return latest
        self.speaker.audio_fetch = fetch
        self.backend.release.set()
        self.speaker.start()
        self.speaker.speak("Old", audio_descriptor(first))
        self.assertTrue(entered.wait(1))
        self.assertEqual(self.speaker.snapshot()["state"], "fetching")
        self.speaker.speak("New", audio_descriptor(latest, "b" * 32))
        wait_until(lambda: self.speaker.snapshot()["last_delivery"] == "delivered")
        self.assertEqual(self.backend.calls, [latest])

    def test_cancel_during_remote_fetch_never_starts_player(self):
        entered = threading.Event()
        def fetch(descriptor, cancel):
            entered.set()
            self.assertTrue(cancel.wait(1))
            raise TransportError("Synthetic cancellation")
        self.speaker.audio_fetch = fetch
        self.speaker.start()
        self.speaker.speak("Reply", audio_descriptor(b"\x01\x00"))
        self.assertTrue(entered.wait(1))
        self.speaker.cancel()
        wait_until(lambda: self.speaker.snapshot()["state"] == "idle")
        self.assertEqual(self.speaker.snapshot()["last_delivery"], "cancelled")
        self.assertEqual(self.backend.calls, [])


class BackendTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        lookup = patch("modulate.speaker.shutil.which", side_effect=lambda name: "/usr/bin/" + name)
        lookup.start()
        self.addCleanup(lookup.stop)
        query = patch("modulate.speaker.subprocess.run", return_value=SimpleNamespace(stdout=b"42\tusb-speaker\tPipeWire\ts16le\tSUSPENDED\n"))
        self.query = query.start()
        self.addCleanup(query.stop)

    def test_detects_and_pins_one_output_without_changing_volume(self):
        backend = LocalSpeechBackend()
        self.assertEqual(backend.info()["output"], "usb-speaker")
        self.assertEqual(backend.info()["output_selection"], "detected_single_sink")
        self.assertTrue(backend.info()["available"])
        self.assertEqual(self.query.call_args.args[0], ["/usr/bin/pactl", "list", "short", "sinks"])
        backend.info()
        self.query.assert_called_once()

    def test_multiple_or_missing_outputs_are_unavailable_without_fallback(self):
        for output in (b"", b"1 first pipewire\n2 second pipewire\n"):
            self.query.return_value.stdout = output
            self.assertFalse(LocalSpeechBackend().info()["available"])
        self.query.return_value.stdout = b"1 first pipewire\n2 second pipewire\n"
        self.assertTrue(LocalSpeechBackend(pulse_sink="second").info()["available"])
        self.assertFalse(LocalSpeechBackend(pulse_sink="absent").info()["available"])

    def test_recovery_preserves_sink_pin_until_original_output_returns(self):
        backend = LocalSpeechBackend()
        self.assertEqual(backend.output, "usb-speaker")
        self.query.return_value.stdout = b"8 another-speaker PipeWire\n"
        self.assertFalse(backend.refresh()["available"])
        self.assertEqual(backend.output, "usb-speaker")
        self.query.return_value.stdout = b"9 usb-speaker PipeWire\n"
        self.assertTrue(backend.refresh()["available"])
        self.assertEqual(backend.output, "usb-speaker")

    def test_startup_before_pulse_session_can_discover_first_sink_later(self):
        self.query.side_effect = subprocess.TimeoutExpired("pactl", 2)
        backend = LocalSpeechBackend()
        self.assertFalse(backend.info()["available"])
        self.query.side_effect = None
        self.assertTrue(backend.refresh()["available"])
        self.assertEqual(backend.output, "usb-speaker")

    def test_environment_output_is_explicit_and_alsa_requires_configuration(self):
        with patch.dict(os.environ, {"MODULATE_SPEAKER_SINK": "usb-speaker"}):
            self.assertEqual(LocalSpeechBackend().info()["output_selection"], "configured")
        backend = LocalSpeechBackend(alsa_device="plughw:CARD=UACDemoV10,DEV=0")
        self.assertEqual(backend.info()["backend"], "espeak-ng/aplay")
        for value in ("bad\noutput", "--option", "", "sink;rm"):
            # A leading dash is harmless as an option value, but still a valid
            # explicit identifier only if pactl lists it; never a shell string.
            if value == "--option":
                self.assertFalse(LocalSpeechBackend(pulse_sink=value).info()["available"])
            else:
                with self.assertRaises(ValueError):
                    LocalSpeechBackend(pulse_sink=value)

    def test_missing_synth_or_failed_discovery_reports_unavailable(self):
        with patch("modulate.speaker.shutil.which", return_value=None):
            self.assertFalse(LocalSpeechBackend().info()["available"])
        self.query.side_effect = subprocess.TimeoutExpired("pactl", 2)
        self.assertFalse(LocalSpeechBackend().info()["available"])

    def pipeline(self, *, synth_code=0, player_code=0, hang=False):
        written = bytearray()
        processes = []
        class Stream:
            closed = False
            def fileno(self):
                return 100
            def close(self):
                self.closed = True
        class Process:
            def __init__(self, code):
                self.stdin, self.stdout = Stream(), Stream()
                self.pid = 100 + len(processes)
                self.code = code
                self.finished = False
            def poll(self):
                if self.code:
                    return self.code
                return 0 if self.finished or (written and not hang) else None
            def wait(self, timeout):
                self.finished = True
                return self.code
        def create(arguments, **kwargs):
            process = Process(synth_code if not processes else player_code)
            processes.append(process)
            return process
        def write(descriptor, data):
            written.extend(data)
            return len(data)
        return processes, written, create, write

    def test_pipeline_keeps_text_on_stdin_and_uses_fixed_argv_and_no_files(self):
        backend = LocalSpeechBackend()
        processes, written, create, write = self.pipeline()
        content = 'PRIVATE; $(touch forbidden) --output=file'
        with patch("modulate.speaker.subprocess.Popen", side_effect=create) as launch, \
                patch("modulate.speaker.os.set_blocking"), patch("modulate.speaker.os.write", side_effect=write), \
                patch("modulate.speaker.os.killpg"):
            self.assertTrue(backend.play(content, threading.Event()))
        self.assertEqual(bytes(written), content.encode())
        self.assertNotIn("PRIVATE", str(launch.call_args_list))
        self.assertEqual(launch.call_args_list[0].args[0],
                         ["/usr/bin/espeak-ng", "--stdin", "--stdout", "-v", "en-us", "-s", "170"])
        self.assertIn("--device=usb-speaker", launch.call_args_list[1].args[0])
        for call in launch.call_args_list:
            self.assertNotIn("shell", call.kwargs)
            self.assertEqual(call.kwargs["stderr"], subprocess.DEVNULL)
        self.assertTrue(all(process.stdin.closed and process.stdout.closed for process in processes))

    def test_player_failure_never_reports_success_or_switches_outputs(self):
        backend = LocalSpeechBackend()
        processes, _, create, write = self.pipeline(player_code=1)
        with patch("modulate.speaker.subprocess.Popen", side_effect=create) as launch, \
                patch("modulate.speaker.os.set_blocking"), patch("modulate.speaker.os.write", side_effect=write), \
                patch("modulate.speaker.os.killpg"):
            with self.assertRaisesRegex(SpeakerError, "rejected playback"):
                backend.play("private", threading.Event())
        self.assertFalse(backend.info()["available"])
        self.assertEqual(launch.call_count, 2)
        self.assertEqual(backend.output, "usb-speaker")

    def test_timeout_terminates_both_process_groups(self):
        backend = LocalSpeechBackend()
        processes, _, create, write = self.pipeline(hang=True)
        with patch("modulate.speaker.subprocess.Popen", side_effect=create), \
                patch("modulate.speaker.os.set_blocking"), patch("modulate.speaker.os.write", side_effect=write), \
                patch("modulate.speaker.os.killpg") as terminate, \
                patch("modulate.speaker.time.monotonic", side_effect=[0, 91]):
            with self.assertRaisesRegex(SpeakerError, "time limit"):
                backend.play("private", threading.Event())
        self.assertEqual(terminate.call_count, 2)
        self.assertTrue(all(process.finished for process in processes))

    def test_cancel_before_playback_starts_creates_no_process(self):
        backend = LocalSpeechBackend()
        cancel = threading.Event()
        cancel.set()
        with patch("modulate.speaker.subprocess.Popen") as launch:
            self.assertFalse(backend.play("private", cancel))
        launch.assert_not_called()

    def test_raw_pcm_uses_pinned_output_fixed_format_stdin_and_no_synth(self):
        payload = b"\x01\x00" * 100
        for mode in ("pulse", "alsa"):
            with self.subTest(mode=mode):
                backend = LocalSpeechBackend(alsa_device="plughw:2,0") if mode == "alsa" else LocalSpeechBackend()
                processes, written, create, write = self.pipeline()
                with patch("modulate.speaker.subprocess.Popen", side_effect=create) as launch, \
                        patch("modulate.speaker.os.set_blocking"), patch("modulate.speaker.os.write", side_effect=write), \
                        patch("modulate.speaker.os.killpg"):
                    self.assertTrue(backend.play_pcm(payload, threading.Event()))
                self.assertEqual(launch.call_count, 1)
                arguments = launch.call_args.args[0]
                if mode == "pulse":
                    for flag in ("--device=usb-speaker", "--raw", "--format=s16le", "--rate=24000", "--channels=1"):
                        self.assertIn(flag, arguments)
                else:
                    self.assertEqual(arguments, ["/usr/bin/aplay", "-q", "-D", "plughw:2,0", "-t", "raw",
                                                 "-f", "S16_LE", "-r", "24000", "-c", "1"])
                self.assertEqual(bytes(written), payload)
                self.assertNotIn("shell", launch.call_args.kwargs)
                self.assertTrue(all(process.stdin.closed for process in processes))

    def test_raw_pcm_timeout_terminates_player_and_invalid_audio_never_launches(self):
        backend = LocalSpeechBackend()
        processes, _, create, write = self.pipeline(hang=True)
        with patch("modulate.speaker.subprocess.Popen", side_effect=create), \
                patch("modulate.speaker.os.set_blocking"), patch("modulate.speaker.os.write", side_effect=write), \
                patch("modulate.speaker.os.killpg") as terminate, \
                patch("modulate.speaker.time.monotonic", side_effect=[0, 91]):
            with self.assertRaisesRegex(SpeakerError, "time limit"):
                backend.play_pcm(b"\x01\x00", threading.Event())
        terminate.assert_called_once()
        self.assertTrue(processes[0].finished)
        with patch("modulate.speaker.subprocess.Popen") as launch:
            for audio in (b"", b"x", b"x" * (MAX_SPEECH_BYTES + 2), "text"):
                with self.assertRaises(ValueError):
                    backend.play_pcm(audio, threading.Event())
            cancelled = threading.Event()
            cancelled.set()
            self.assertFalse(backend.play_pcm(b"\x01\x00", cancelled))
        launch.assert_not_called()

    def test_raw_pcm_cancellation_during_playback_terminates_process_group(self):
        backend = LocalSpeechBackend()
        cancel = threading.Event()
        processes, written, create, write = self.pipeline(hang=True)
        def interrupt(descriptor, data):
            size = write(descriptor, data)
            cancel.set()
            return size
        with patch("modulate.speaker.subprocess.Popen", side_effect=create), \
                patch("modulate.speaker.os.set_blocking"), patch("modulate.speaker.os.write", side_effect=interrupt), \
                patch("modulate.speaker.os.killpg") as terminate:
            self.assertFalse(backend.play_pcm(b"\x01\x00" * 100, cancel))
        terminate.assert_called_once()
        self.assertTrue(processes[0].finished)
        self.assertEqual(len(written), 200)
        self.assertEqual(backend.output, "usb-speaker")
        self.assertTrue(backend.info()["available"])


if __name__ == "__main__":
    unittest.main()
