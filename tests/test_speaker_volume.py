"""Synthetic speaker-volume protocol tests; no actual sound or Pulse changes."""
from types import SimpleNamespace
import subprocess
import threading
import time
import unittest
from unittest.mock import patch

from modulate.speaker_volume import (PulseVolumeBackend, SpeakerVolume,
                                     SpeakerVolumeDevice, SpeakerVolumeError)

SESSION = "a" * 32
SINK = "alsa_output.synthetic.analog-stereo"


def wait_for(predicate):
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.001)
    raise AssertionError("Synthetic volume worker did not reach the expected state")


class Backend:
    def __init__(self):
        self.volume, self.muted = 75, False
        self.writes = []
        self.uncertain = False
        self.block = False
        self.entered, self.release = threading.Event(), threading.Event()

    def get(self, sink):
        if self.block:
            self.entered.set()
            self.release.wait(1)
        return {"volume": self.volume, "muted": self.muted}

    def set_volume(self, sink, value):
        self.writes.append(("volume", sink, value))
        self.volume = value
        if self.uncertain:
            raise RuntimeError("private native failure after applying")

    def set_muted(self, sink, value):
        self.writes.append(("mute", sink, value))
        self.muted = value


class VolumeProtocolTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.output = {"available": True, "pcm_backend": "paplay", "output": SINK}
        self.device = SpeakerVolumeDevice(lambda: dict(self.output), SESSION, self.backend)
        self.host = SpeakerVolume()
        self.device.start()
        self.addCleanup(self.device.stop)
        wait_for(lambda: self.device.snapshot()["available"])
        self.host.observe(self.device.snapshot(), SESSION)

    def begin(self, action, value=None, timeout=.5):
        result = []

        def run():
            try:
                result.append(self.host.control(action, value, timeout))
            except Exception as error:
                result.append(error)

        thread = threading.Thread(target=run)
        thread.start()
        wait_for(lambda: self.host.offer(SESSION) is not None or result)
        return thread, result, self.host.offer(SESSION)

    def finish(self, thread, result, command):
        self.assertTrue(self.device.offer(command))
        wait_for(lambda: (self.device.snapshot().get("ack") or {}).get("id") == command["id"])
        self.host.observe(self.device.snapshot(), SESSION)
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(result), 1)
        return result[0]

    def test_revoked_access_never_offers_a_queued_change(self):
        access = threading.Event()
        access.set()
        result = []
        def run():
            try:
                result.append(self.host.control("set", 80, .5, allowed=access.is_set))
            except SpeakerVolumeError as error:
                result.append(error)
        thread = threading.Thread(target=run)
        thread.start()
        wait_for(lambda: self.host.status()["pending"])
        access.clear()
        self.assertIsNone(self.host.offer(SESSION))
        thread.join(1)
        self.assertIsInstance(result[0], SpeakerVolumeError)
        self.assertFalse(self.host.status()["pending"])
        self.assertEqual(self.backend.writes, [])
        with self.assertRaises(SpeakerVolumeError):
            self.host.control("set", 80, allowed=access.is_set)
        self.assertIsNone(self.host.offer(SESSION))

    def test_initial_level_is_read_only_and_delta_is_applied_once_with_actual_readback(self):
        self.assertEqual(self.backend.writes, [])
        thread, result, command = self.begin("delta", 10)
        # An external volume change after the heartbeat must be included in the
        # delta's actual pre-write read, rather than stale host telemetry.
        self.backend.volume = 61
        response = self.finish(thread, result, command)
        self.assertEqual(response["before"], {"volume": 61, "muted": False})
        self.assertEqual(response["after"], {"volume": 71, "muted": False})
        self.assertTrue(response["verified"])
        for _ in range(3):
            self.assertFalse(self.device.offer(command))
        self.assertEqual(self.backend.writes, [("volume", SINK, 71)])
        self.assertIsNone(self.host.offer(SESSION))

    def test_get_set_delta_clamp_and_mute_share_sink_and_preserve_other_setting(self):
        for action, value, expected in [("get", None, (75, False)), ("set", 98, (98, False)),
                                         ("delta", 10, (100, False)), ("mute", True, (100, True)),
                                         ("set", 0, (0, True)), ("delta", -10, (0, True))]:
            with self.subTest(action=action, value=value):
                result = self.finish(*self.begin(action, value))
                self.assertEqual((result["volume"], result["muted"]), expected)
                self.assertTrue(result["verified"])
        self.assertTrue(all(write[1] == SINK for write in self.backend.writes))

    def test_device_restart_reads_current_volume_without_reset(self):
        self.backend.volume, self.backend.muted = 42, True
        self.device.stop()
        replacement = SpeakerVolumeDevice(lambda: dict(self.output), "b" * 32, self.backend)
        self.addCleanup(replacement.stop)
        replacement.start()
        wait_for(lambda: replacement.snapshot()["available"])
        self.assertEqual(replacement.snapshot()["volume"], 42)
        self.assertTrue(replacement.snapshot()["muted"])
        self.assertEqual(self.backend.writes, [])

    def test_host_rejects_wrong_ack_identity_and_unverified_after_state(self):
        thread, result, command = self.begin("set", 55)
        actual = self.device.snapshot()
        ack = {key: command[key] for key in ("id", "epoch", "revision")}
        ack.update(status="applied", before={"volume": 75, "muted": False},
                   after={"volume": 55, "muted": False})
        self.host.observe({**actual, "ack": {**ack, "id": "f" * 32}}, SESSION)
        self.assertEqual(result, [])
        self.host.observe({**actual, "ack": {**ack, "after": {"volume": 54, "muted": False}}}, SESSION)
        thread.join(1)
        self.assertIsInstance(result[0], SpeakerVolumeError)
        self.assertEqual(self.backend.writes, [])

    def test_disconnect_wakes_host_waiter_and_old_session_cannot_receive_command(self):
        thread, result, command = self.begin("set", 50)
        self.assertIsNone(self.host.offer("b" * 32))
        self.host.disconnect()
        thread.join(1)
        self.assertIsInstance(result[0], SpeakerVolumeError)
        self.assertIsNone(self.host.offer(SESSION))

    def test_device_disconnect_between_read_and_write_does_not_change_volume(self):
        self.backend.block = True
        thread, result, command = self.begin("set", 50)
        self.device.offer(command)
        self.assertTrue(self.backend.entered.wait(1))
        self.device.disconnect()
        self.backend.release.set()
        wait_for(lambda: self.device.snapshot().get("ack") is not None)
        self.host.observe(self.device.snapshot(), SESSION)
        thread.join(1)
        self.assertIsInstance(result[0], SpeakerVolumeError)
        self.assertEqual(self.backend.writes, [])

    def test_uncertain_write_fails_without_reapplying_duplicate_delta(self):
        self.backend.uncertain = True
        thread, result, command = self.begin("delta", 10)
        response = self.finish(thread, result, command)
        self.assertIsInstance(response, SpeakerVolumeError)
        self.assertEqual(self.backend.volume, 85)
        self.assertFalse(self.device.offer(command))
        self.assertEqual(len(self.backend.writes), 1)
        self.assertNotIn("private", str(response))

    def test_withdrawn_offer_invalidates_inflight_write_and_duplicate_cannot_rearm_it(self):
        self.backend.block = True
        thread, result, command = self.begin("set", 50)
        self.device.offer(command)
        self.assertTrue(self.backend.entered.wait(1))
        self.assertFalse(self.device.offer(None))
        self.assertFalse(self.device.offer(None), "Repeated withdrawal is idempotent")
        self.assertFalse(self.device.offer(command), "A withdrawn revision cannot rearm")
        self.backend.release.set()
        wait_for(lambda: self.device.snapshot().get("ack") is not None)
        self.host.observe(self.device.snapshot(), SESSION)
        thread.join(1)
        self.assertIsInstance(result[0], SpeakerVolumeError)
        self.assertEqual(self.backend.writes, [])
        self.assertEqual(self.backend.volume, 75)

    def test_timeout_has_unknown_outcome_and_stale_ack_does_not_confirm_next_request(self):
        thread, result, old = self.begin("set", 35, timeout=.04)
        thread.join(1)
        self.assertIn("unknown", str(result[0]))
        self.assertIsNone(self.host.offer(SESSION))
        thread, result, current = self.begin("set", 45)
        stale = {key: old[key] for key in ("id", "epoch", "revision")}
        stale.update(status="applied", before={"volume": 75, "muted": False},
                     after={"volume": 35, "muted": False})
        self.host.observe({**self.device.snapshot(), "ack": stale}, SESSION)
        self.assertEqual(result, [])
        self.assertEqual(self.finish(thread, result, current)["volume"], 45)

    def test_invalid_actions_sinks_sessions_expiry_and_retired_epochs_never_write(self):
        for action, value in [("set", True), ("set", 101), ("set", -1), ("delta", 11),
                              ("delta", 0), ("mute", 1), ("get", 1), ("shell", "anything")]:
            with self.subTest(action=action, value=value), self.assertRaises(SpeakerVolumeError):
                self.host.control(action, value)
        command = {"id": "c" * 32, "epoch": "d" * 32, "revision": 1,
                   "device_session": SESSION, "sink": SINK, "action": "get", "value": None,
                   "expires_at": time.time() + 5}
        for changes in ({"sink": "other-sink"}, {"device_session": "b" * 32},
                        {"expires_at": time.time() - 1}, {"expires_at": time.time() + 50},
                        {"revision": True}, {"action": "set", "value": 101}):
            self.assertFalse(self.device.offer({**command, **changes}))
        self.assertTrue(self.device.offer(command))
        second = {**command, "epoch": "e" * 32, "id": "f" * 32}
        self.assertTrue(self.device.offer(second))
        self.assertFalse(self.device.offer({**command, "revision": 999}))
        self.assertEqual(self.backend.writes, [])


class PulseBackendTests(unittest.TestCase):
    def test_native_arguments_pin_sink_use_percent_and_parse_readback(self):
        backend = PulseVolumeBackend()
        responses = [SimpleNamespace(stdout=b"Volume: front-left: 49152 / 75% / -7dB, front-right: 49152 / 75% / -7dB\n"),
                     SimpleNamespace(stdout=b"Mute: no\n"), SimpleNamespace(stdout=b""), SimpleNamespace(stdout=b"")]
        with patch("modulate.speaker_volume.shutil.which", return_value="/usr/bin/pactl"), \
                patch("modulate.speaker_volume.subprocess.run", side_effect=responses) as run:
            self.assertEqual(backend.get(SINK), {"volume": 75, "muted": False})
            backend.set_volume(SINK, 85)
            backend.set_muted(SINK, True)
        calls = [call.args[0] for call in run.call_args_list]
        self.assertEqual(calls, [["/usr/bin/pactl", "get-sink-volume", SINK],
                                 ["/usr/bin/pactl", "get-sink-mute", SINK],
                                 ["/usr/bin/pactl", "set-sink-volume", SINK, "85%"],
                                 ["/usr/bin/pactl", "set-sink-mute", SINK, "1"]])
        self.assertTrue(all(call.kwargs["timeout"] == .7 and not call.kwargs.get("shell")
                            for call in run.call_args_list))

    def test_overamplification_invalid_sink_missing_player_and_native_error_fail_closed(self):
        backend = PulseVolumeBackend()
        for sink in ("@DEFAULT_SINK@", "-other", "sink;command", "sink\nother"):
            with self.subTest(sink=sink), self.assertRaises(SpeakerVolumeError):
                backend.get(sink)
        for value in (-1, 101, True):
            with self.assertRaises(SpeakerVolumeError):
                backend.set_volume(SINK, value)
        with patch("modulate.speaker_volume.shutil.which", return_value=None), self.assertRaises(SpeakerVolumeError):
            backend.get(SINK)
        with patch("modulate.speaker_volume.shutil.which", return_value="/usr/bin/pactl"), \
                patch("modulate.speaker_volume.subprocess.run", side_effect=subprocess.TimeoutExpired("private", .7)):
            with self.assertRaises(SpeakerVolumeError) as caught:
                backend.get(SINK)
            self.assertNotIn("private", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
