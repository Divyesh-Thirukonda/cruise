"""Synthetic TTS process/queue tests; no speech, player or hardware is opened."""

import os
import subprocess
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modulate.speaker import LocalSpeechBackend, Speaker, SpeakerError, MAX_TEXT_CHARACTERS


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
        self.assertFalse(speaker.speak("Synthetic request"))
        self.assertEqual(speaker.snapshot()["state"], "unavailable")
        self.assertIsNone(speaker.snapshot()["last_delivery"])
        self.assertEqual(self.backend.calls, [])

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


if __name__ == "__main__":
    unittest.main()
