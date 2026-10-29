"""Synthetic receiver/player tests; no network, sound device or audio files."""
import base64
import queue
import subprocess
import threading
import time
import unittest
from unittest.mock import Mock, patch

from modulate.audio_receiver import (AudioReceiver, AudioReceiverError, FORMAT,
                                     MAX_CHUNK_BYTES, _packet, _PulsePlayer)


SESSION = "a" * 32
PCM = b"\x01\x00\x02\x00" * 48


def packet(sequence, pcm=PCM, session=SESSION, **extra):
    return {"session": session, "sequence": sequence,
            "pcm": base64.b64encode(pcm).decode("ascii"), **extra}


def wait_until(condition):
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("Synthetic audio worker did not reach the expected state")


class FakePlayer:
    def __init__(self, sink, failure=None):
        self.sink, self.failure = sink, failure
        self.writes = []
        self.closed = threading.Event()

    def write(self, pcm, cancel):
        if cancel.is_set():
            return False
        if self.failure:
            raise self.failure
        self.writes.append(pcm)
        return True

    def close(self):
        self.closed.set()


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.packets = queue.Queue()
        self.fetches, self.players, self.statuses = [], [], []
        self.receiver = AudioReceiver(self.fetch, self.statuses.append, "synthetic-usb",
                                      player_factory=self.player)
        self.addCleanup(self.receiver.stop)

    def fetch(self, session, after, cancel):
        self.fetches.append((session, after))
        try:
            value = self.packets.get(timeout=0.01)
            if cancel.is_set():
                self.packets.put(value)  # Host ring retains data across cancelled reads.
                return None
            return value
        except queue.Empty:
            return None

    def player(self, sink):
        result = FakePlayer(sink)
        self.players.append(result)
        return result

    def start(self):
        self.receiver.set_enabled(True, SESSION)
        self.receiver.start()

    def test_contiguous_audio_reuses_one_explicit_sink_and_reports_sample_frames(self):
        self.packets.put(packet(1))
        self.packets.put(packet(3, PCM * 2))  # A batch's last sequence may jump.
        self.start()
        wait_until(lambda: self.receiver.snapshot()["frames_written"] == 144)
        self.assertEqual(len(self.players), 1)
        self.assertEqual(self.players[0].sink, "synthetic-usb")
        self.assertEqual(self.players[0].writes, [PCM, PCM * 2])
        self.assertEqual(self.fetches[:2], [(SESSION, None), (SESSION, 1)])
        state = self.receiver.snapshot()
        self.assertEqual(state["chunks_received"], 2)
        self.assertEqual(state["frames_received"], 144)
        self.assertNotIn("pcm", state)
        self.assertNotIn(base64.b64encode(PCM).decode(), repr(self.statuses))

    def test_replay_cannot_play_again_or_flush_existing_player(self):
        self.packets.put(packet(1))
        self.packets.put(packet(1, reset=True))
        self.start()
        wait_until(lambda: self.receiver.snapshot()["chunks_dropped"] == 1)
        self.assertEqual(self.players[0].writes, [PCM])
        self.assertFalse(self.players[0].closed.is_set())
        self.assertEqual(self.receiver.snapshot()["frames_received"], 48)

    def test_wrong_session_rejects_audio_closes_player_and_does_not_advance_cursor(self):
        self.packets.put(packet(1))
        self.packets.put(packet(999, session="b" * 32))
        self.start()
        wait_until(lambda: self.receiver.snapshot()["state"] == "error")
        self.assertTrue(self.players[0].closed.is_set())
        self.assertEqual(self.receiver.snapshot()["sequence"], 1)
        self.assertEqual(self.players[0].writes, [PCM])

    def test_duck_discards_and_advances_then_resumes_from_live_edge(self):
        self.packets.put(packet(1))
        self.start()
        wait_until(lambda: self.receiver.snapshot()["frames_written"] == 48)
        self.receiver.set_ducked(True)
        self.assertTrue(self.players[0].closed.is_set())
        self.packets.put(packet(2))
        wait_until(lambda: self.receiver.snapshot()["sequence"] == 2)
        self.assertEqual(self.receiver.snapshot()["state"], "ducked")
        self.assertEqual(len(self.players), 1)
        self.receiver.set_ducked(False)
        self.packets.put(packet(3, reset=True))
        wait_until(lambda: self.receiver.snapshot()["frames_written"] == 96)
        self.assertEqual(len(self.players), 2)
        self.assertEqual(self.players[1].writes, [PCM])
        self.assertGreaterEqual(self.fetches.count((SESSION, None)), 3)

    def test_late_fetch_from_old_session_never_enters_new_player(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def fetch(session, after, cancel):
            if session == SESSION:
                entered.set()
                release.wait(1)
                return packet(1)
            return self.fetch(session, after, cancel)
        self.receiver.fetch = fetch
        self.start()
        self.assertTrue(entered.wait(1))
        self.receiver.set_enabled(True, "b" * 32)
        self.packets.put(packet(1, pcm=PCM * 2, session="b" * 32))
        release.set()
        wait_until(lambda: self.receiver.snapshot()["frames_written"] == 96)
        self.assertEqual(self.players[0].writes, [PCM * 2])
        self.assertEqual(self.receiver.snapshot()["session"], "b" * 32)

    def test_disable_closes_player_without_waiting_for_blocked_fetch(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def fetch(session, after, cancel):
            if after is None:
                return packet(1)
            entered.set()
            release.wait(1)
            return packet(2)
        self.receiver.fetch = fetch
        self.start()
        self.assertTrue(entered.wait(1))
        before = time.monotonic()
        self.receiver.set_enabled(False)
        self.assertLess(time.monotonic() - before, 0.2)
        self.assertTrue(self.players[0].closed.is_set())
        release.set()
        wait_until(lambda: not self.receiver.snapshot()["enabled"])
        self.assertEqual(self.players[0].writes, [PCM])
        self.assertFalse(self.receiver.snapshot()["playing"])

    def test_host_reset_flushes_old_player_before_new_live_packet(self):
        self.packets.put(packet(1))
        self.packets.put(packet(20, reset=True))
        self.start()
        wait_until(lambda: self.receiver.snapshot()["frames_written"] == 96)
        self.assertEqual(len(self.players), 2)
        self.assertTrue(self.players[0].closed.is_set())
        self.assertEqual(self.players[1].writes, [PCM])

    def test_overrun_closes_pipe_and_next_fetch_requests_live_edge(self):
        def factory(sink):
            result = self.player(sink)
            if len(self.players) == 1:
                result.failure = AudioReceiverError("overrun")
            return result
        self.receiver._factory = factory
        self.packets.put(packet(1))
        self.start()
        wait_until(lambda: self.receiver.snapshot()["state"] == "error")
        self.assertTrue(self.players[0].closed.is_set())
        self.packets.put(packet(50, reset=True))
        wait_until(lambda: self.receiver.snapshot()["frames_written"] == 48)
        self.assertEqual(self.fetches[:2], [(SESSION, None), (SESSION, None)])
        self.assertEqual(self.receiver.snapshot()["sequence"], 50)

    def test_transport_errors_are_content_free_and_close_the_player(self):
        def fetch(session, after, cancel):
            if after is None:
                return packet(1)
            raise RuntimeError("Private endpoint or payload must never be emitted")
        self.receiver.fetch = fetch
        self.start()
        wait_until(lambda: self.receiver.snapshot()["state"] == "error")
        self.assertTrue(self.players[0].closed.is_set())
        self.assertNotIn("Private", repr(self.statuses))

    def test_delayed_response_beyond_transport_bound_is_not_played(self):
        now = [0.0]
        self.receiver._clock = lambda: now[0]
        def fetch(session, after, cancel):
            now[0] += 3.1
            return packet(1)
        self.receiver.fetch = fetch
        self.start()
        wait_until(lambda: self.receiver.snapshot()["state"] == "error")
        self.assertIn("stale", self.receiver.snapshot()["error"])
        self.assertEqual(self.players, [])

    def test_same_session_offer_does_not_reset_sequence_or_active_player(self):
        self.packets.put(packet(1))
        self.start()
        wait_until(lambda: self.receiver.snapshot()["frames_written"] == 48)
        self.receiver.set_enabled(True, SESSION)
        self.packets.put(packet(2))
        wait_until(lambda: self.receiver.snapshot()["frames_written"] == 96)
        self.assertEqual(len(self.players), 1)
        self.assertFalse(self.players[0].closed.is_set())

    def test_unknown_sink_never_fetches_or_selects_a_default(self):
        receiver = AudioReceiver(Mock(), sink=None, player_factory=self.player)
        self.addCleanup(receiver.stop)
        receiver.set_enabled(True, SESSION)
        receiver.start()
        wait_until(lambda: receiver.snapshot()["state"] == "unavailable")
        receiver.fetch.assert_not_called()
        self.assertEqual(self.players, [])

    def test_invalid_enable_or_sink_has_no_side_effects(self):
        for session in (None, "", "A" * 32, "a" * 31, True):
            with self.subTest(session=session), self.assertRaises(ValueError):
                self.receiver.set_enabled(True, session)
        for sink in ("", "with space", "sink;command", True):
            with self.subTest(sink=sink), self.assertRaises(ValueError):
                AudioReceiver(self.fetch, sink=sink)
        self.assertFalse(self.receiver.snapshot()["enabled"])
        self.assertEqual(self.players, [])

    def test_late_sink_discovery_recovers_but_never_redirects_known_output(self):
        receiver = AudioReceiver(self.fetch, sink=None, player_factory=self.player)
        self.addCleanup(receiver.stop)
        receiver.set_enabled(True, SESSION)
        receiver.start()
        wait_until(lambda: receiver.snapshot()["state"] == "unavailable")
        self.packets.put(packet(1))
        self.assertTrue(receiver.set_sink("synthetic-usb"))
        wait_until(lambda: receiver.snapshot()["frames_written"] == 48)
        self.assertFalse(receiver.set_sink("synthetic-usb"))
        with self.assertRaises(ValueError):
            receiver.set_sink("other-output")
        for sink in (None, "", "invalid sink", True):
            with self.subTest(sink=sink), self.assertRaises(ValueError):
                receiver.set_sink(sink)
        self.assertEqual(receiver.snapshot()["output"], "synthetic-usb")
        self.assertEqual(len(self.players), 1)


class PacketTests(unittest.TestCase):
    def test_fixed_format_complete_frames_and_exact_size_bound(self):
        result = _packet(packet(1, b"\0" * MAX_CHUNK_BYTES, format=FORMAT), SESSION)
        self.assertEqual(len(result[1]), MAX_CHUNK_BYTES)
        cases = [None, [], {}, packet(True), packet(-1), packet(2 ** 63),
                 packet(1, b""), packet(1, b"\0" * 3), packet(1, b"\0" * (MAX_CHUNK_BYTES + 4)),
                 packet(1, reset=1), packet(1, format="wav"), packet(1, file="untrusted"),
                 {**packet(1), "pcm": "%%%%"}, {**packet(1), "pcm": "é"},
                 packet(1, session="b" * 32)]
        for value in cases:
            with self.subTest(value=repr(value)[:70]), self.assertRaises(AudioReceiverError):
                _packet(value, SESSION)


class PulsePlayerTests(unittest.TestCase):
    def make_player(self):
        process = Mock()
        process.stdin.fileno.return_value = 7
        process.poll.return_value = None
        with patch("modulate.audio_receiver.shutil.which", return_value="/usr/bin/paplay"), \
             patch("modulate.audio_receiver.subprocess.Popen", return_value=process) as spawn, \
             patch("modulate.audio_receiver.os.set_blocking") as blocking:
            player = _PulsePlayer("synthetic-usb")
        blocking.assert_called_once_with(7, False)
        self.addCleanup(player.close)
        return player, process, spawn

    def test_player_pins_raw_stereo_format_and_writes_partial_nonblocking_pipe(self):
        player, process, spawn = self.make_player()
        args = spawn.call_args.args[0]
        for option in ("--device=synthetic-usb", "--raw", "--format=s16le", "--rate=48000", "--channels=2"):
            self.assertIn(option, args)
        self.assertNotIn("shell", spawn.call_args.kwargs)
        with patch("modulate.audio_receiver.os.write", side_effect=[4, 4]) as write:
            self.assertTrue(player.write(b"12345678", threading.Event()))
        self.assertEqual([call.args[1] for call in write.call_args_list], [b"12345678", b"5678"])

    def test_cancel_prevents_writes_and_close_terminates_without_drain(self):
        player, process, _ = self.make_player()
        cancel = threading.Event()
        cancel.set()
        with patch("modulate.audio_receiver.os.write") as write:
            self.assertFalse(player.write(PCM, cancel))
        write.assert_not_called()
        process.wait.side_effect = [subprocess.TimeoutExpired("paplay", .2), None]
        player.close()
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        process.stdin.close.assert_called_once()

    def test_blocked_pipe_is_bounded_and_reports_overrun(self):
        player, _, _ = self.make_player()
        with patch("modulate.audio_receiver.os.write", side_effect=BlockingIOError), \
             patch("modulate.audio_receiver.time.monotonic", side_effect=[0, 0, 1]):
            with self.assertRaises(AudioReceiverError) as failure:
                player.write(PCM, threading.Event())
        self.assertEqual(failure.exception.category, "overrun")

    def test_missing_player_never_starts_an_alternate_output(self):
        with patch("modulate.audio_receiver.shutil.which", return_value=None), \
             patch("modulate.audio_receiver.subprocess.Popen") as spawn:
            with self.assertRaises(AudioReceiverError):
                _PulsePlayer("synthetic-usb")
        spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
