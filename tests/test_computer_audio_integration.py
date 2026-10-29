"""Synthetic paired audio authority, transport and Pi voice arbitration."""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modulate.agent import AgentError, Ledger, Orchestrator
from modulate.device import Controller
from modulate.device_transport import Companion, save_private
from modulate.product import Product
from tests.test_agent import FakeService, ScriptedProvider, reply
from tests.test_assistant_io import FakeComputer, SyntheticProvider
from tests.test_product import FakeBackend


FORMAT = "pcm_s16le_48000_stereo"
STREAM = "a" * 32


class FakeAudio:
    def __init__(self):
        self.running, self.session = False, None
        self.starts = self.stops = 0
        self.on_chunk = None
        self.chunks = []

    def status(self):
        return {"supported": True, "state": "running" if self.running else "stopped",
                "running": self.running, "session": self.session, "format": FORMAT, "error": None}

    def start(self):
        self.starts += 1
        self.running, self.session = True, ("a" if self.starts == 1 else "b") * 32
        return self.status()

    def stop(self):
        self.stops += 1
        self.running, self.session = False, None
        return self.status()

    def chunk(self, *, after, session, timeout):
        self.chunks.append((after, session, timeout))
        if self.on_chunk:
            return self.on_chunk()
        return {"session": session, "sequence": 3, "pcm": b"\x01\0\x02\0" * 48,
                "reset": after is None}


class HostAudioAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.product = Product(Path(self.temp.name), SyntheticProvider([]),
                               backend=FakeBackend(), computer=FakeComputer())
        self.audio = self.product.system_audio = FakeAudio()
        self.product.audio_guard = SimpleNamespace(is_alive=lambda: True)
        self.product.telemetry["speaker"] = {"available": True}
        self.now = 1000
        self.product.bridge.clock = lambda: self.now
        self.addCleanup(self.product.cancel)

    def pair(self):
        self.product.last_seen = time.monotonic()
        code = self.product.create_pairing()["code"]
        return self.product.pair(code, "Synthetic controller")

    def start(self):
        self.pair()
        return self.product.computer_audio("start")["session"]

    def test_start_requires_connected_pair_and_actual_speaker_before_capture(self):
        for action in ("start", "status"):
            with self.assertRaises(AgentError):
                self.product.computer_audio(action)
        self.assertEqual(self.audio.starts, 0)
        self.pair()
        self.product.telemetry["speaker"]["available"] = False
        with self.assertRaisesRegex(AgentError, "speaker"):
            self.product.computer_audio("start")
        self.assertEqual(self.audio.starts, 0)

    def test_pair_pause_revoke_and_expiry_remove_offer_and_packets(self):
        for reason in ("pause", "revoke", "expiry", "disconnect"):
            with self.subTest(reason=reason):
                self.product.computer_paused = False
                session = self.start()
                self.assertEqual(self.product.audio_offer()["session"], session)
                if reason == "pause":
                    self.product.computer_session("revoke")
                elif reason == "revoke":
                    self.product.revoke()
                elif reason == "expiry":
                    self.now += 8 * 60 * 60
                else:
                    self.product.last_seen = None
                self.assertIsNone(self.product.audio_offer())
                with self.assertRaises(AgentError):
                    self.product.audio_packet(session, None)
                if reason in {"pause", "revoke"}:
                    self.assertFalse(self.audio.running)

    def test_disconnect_guard_stops_capture_without_another_request(self):
        self.start()
        self.product.last_seen = None
        guard = threading.Thread(target=self.product._guard_audio)
        guard.start()
        guard.join(1)
        self.assertFalse(guard.is_alive())
        self.assertFalse(self.audio.running)

    def test_old_stream_cannot_read_or_stop_new_stream(self):
        old = self.start()
        self.product.stop_computer_audio(old)
        fresh = self.product.computer_audio("start")["session"]
        self.assertNotEqual(old, fresh)
        self.assertFalse(self.product.stop_computer_audio(old)["stopped"])
        self.assertTrue(self.audio.running)
        with self.assertRaises(AgentError):
            self.product.audio_packet(old, 0)
        self.assertEqual(self.audio.chunks, [])

    def test_none_cursor_requests_live_edge_and_audio_never_enters_state_or_disk(self):
        session = self.start()
        response = self.product.audio_packet(session, None)["packet"]
        self.assertEqual(self.audio.chunks, [(None, session, .5)])
        self.assertTrue(response["reset"])
        self.assertEqual(base64.b64decode(response["pcm"]), b"\x01\0\x02\0" * 48)
        self.assertNotIn("pcm", self.product.audio_status())
        for path in Path(self.temp.name).rglob("*"):
            if path.is_file():
                self.assertNotIn(response["pcm"].encode(), path.read_bytes())
        self.audio.on_chunk = lambda: None
        self.assertEqual(self.product.audio_packet(session, 3), {"packet": None})

    def test_invalid_cursors_and_unknown_actions_never_reach_capture(self):
        session = self.start()
        for after in (-1, True, "3", 2 ** 63):
            with self.subTest(after=after), self.assertRaises(AgentError):
                self.product.audio_packet(session, after)
        with self.assertRaises(AgentError):
            self.product.computer_audio("execute")
        self.assertEqual(self.audio.chunks, [])

    def test_revocation_during_long_poll_drops_result_and_does_not_hold_product_lock(self):
        session = self.start()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def chunk():
            self.assertFalse(self.product.lock._is_owned())
            entered.set()
            self.assertTrue(release.wait(1))
            return {"session": session, "sequence": 1, "pcm": b"\0" * 4, "reset": False}
        self.audio.on_chunk = chunk
        with ThreadPoolExecutor(max_workers=2) as pool:
            fetch = pool.submit(self.product.audio_packet, session, None)
            self.assertTrue(entered.wait(1))
            pool.submit(self.product.revoke).result(1)
            release.set()
            with self.assertRaises(AgentError):
                fetch.result(1)


class DeviceAudioArbitrationTests(unittest.TestCase):
    def setUp(self):
        self.controller = Controller.__new__(Controller)
        self.controller.lock = threading.RLock()
        self.controller.computer_audio = Mock()
        self.audio_state = {"enabled": True, "playing": True, "ducked": False, "session": STREAM}
        self.controller.computer_audio.snapshot.side_effect = lambda: dict(self.audio_state)
        def enabled(value, session=None):
            self.audio_state["enabled"] = value
            if value:
                self.audio_state["session"] = session
        self.controller.computer_audio.set_enabled.side_effect = enabled
        self.controller.computer_audio.set_ducked.side_effect = lambda value: self.audio_state.update(ducked=value)
        self.controller.voice = Mock()
        self.controller.voice_state = {"state": "wake_listening", "message": "Listening for Hey Meta"}
        self.controller.speaker_state = {"state": "idle", "available": True}
        self.controller.speech_cooldown = 0
        self.controller.speech_seen = set()
        self.controller.build = None
        self.controller.request_in_flight = False
        self.controller.audio_blocked = None
        self.controller.last_response = time.monotonic()
        self.controller.host = {"wake": True, "computer_audio": {"session": STREAM, "format": FORMAT}}

    def test_streaming_does_not_mute_ambient_wake_or_claim_tts_active(self):
        self.controller._sync_voice()
        self.controller.voice.set_enabled.assert_called_with(True)
        self.controller.voice.set_playback_active.assert_called_with(True)
        self.controller.computer_audio.set_enabled.assert_called_with(True, STREAM)
        self.controller.computer_audio.set_ducked.assert_called_with(False)
        self.assertFalse(self.controller._speaker_active())

    def test_confirmed_voice_tts_pending_and_busy_duck_without_latching_stop(self):
        cases = [("voice", {"state": "listening", "message": "Wake phrase heard; speak now"}),
                 ("voice", {"state": "listening", "message": "Push-to-talk recording"}),
                 ("voice", {"state": "listening", "message": "Listening for your answer"}),
                 ("voice", {"state": "transcribing"}), ("speaker", {"state": "speaking"}),
                 ("pending", True), ("busy", True)]
        for kind, value in cases:
            with self.subTest(kind=kind, value=value):
                self.controller.voice_state = {"state": "wake_listening"}
                self.controller.speaker_state = {"state": "idle"}
                self.controller.host.pop("speech_pending", None)
                self.controller.build = None
                if kind == "voice": self.controller.voice_state = value
                elif kind == "speaker": self.controller.speaker_state = value
                elif kind == "pending": self.controller.host["speech_pending"] = True
                else: self.controller.build = {"job_id": "b" * 32}
                self.controller._sync_computer_audio()
                self.controller.computer_audio.set_ducked.assert_called_with(True)
                self.controller.voice.set_playback_active.assert_called_with(False)
                self.assertIsNone(self.controller.audio_blocked)

    def test_physical_stop_latch_survives_old_offer_but_allows_new_explicit_stream(self):
        self.assertTrue(self.controller._stop_computer_audio())
        self.assertEqual(self.controller.audio_blocked, STREAM)
        for _ in range(3):
            self.controller._sync_computer_audio()
            self.controller.computer_audio.set_enabled.assert_called_with(False, STREAM)
        self.controller.host["computer_audio"]["session"] = "b" * 32
        self.controller._sync_computer_audio()
        self.controller.computer_audio.set_enabled.assert_called_with(True, "b" * 32)

    def test_stale_link_wrong_format_or_no_offer_disables_receiver(self):
        self.controller.last_response = time.monotonic() - 5
        self.controller._sync_computer_audio()
        self.controller.computer_audio.set_enabled.assert_called_with(False, STREAM)
        self.controller.last_response = time.monotonic()
        self.controller.host["computer_audio"]["format"] = "unexpected"
        self.controller._sync_computer_audio()
        self.controller.computer_audio.set_enabled.assert_called_with(False, STREAM)
        self.controller.host["computer_audio"] = None
        self.controller._sync_computer_audio()
        self.controller.computer_audio.set_enabled.assert_called_with(False, None)

    def test_fetch_preserves_none_cursor_and_discards_result_cancelled_in_flight(self):
        self.controller.companion = Mock()
        cancel = threading.Event()
        self.controller.companion.post.return_value = {"packet": {"sequence": 1}}
        self.assertEqual(self.controller._fetch_computer_audio(STREAM, None, cancel), {"sequence": 1})
        self.controller.companion.post.assert_called_with("audio", {"session": STREAM, "after": None})
        def cancelled(*args):
            cancel.set()
            return {"packet": {"sequence": 2}}
        self.controller.companion.post.side_effect = cancelled
        self.assertIsNone(self.controller._fetch_computer_audio(STREAM, 1, cancel))
        calls = self.controller.companion.post.call_count
        self.assertIsNone(self.controller._fetch_computer_audio(STREAM, 2, cancel))
        self.assertEqual(self.controller.companion.post.call_count, calls)


class AudioToolAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name)
        self.service = FakeService()
        self.service.computer_audio = Mock(return_value={"state": "running", "session": STREAM})
        provider = ScriptedProvider([reply(content="Synthetic ready")])
        self.agent = Orchestrator(provider, self.service, path / "agent", Ledger(path / "ledger.json", limit_dollars=0))
        self.agent.run("Synthetic test")

    def test_only_orchestrator_can_start_and_no_arbitrary_tool_arguments(self):
        for role in ("coder", "reviewer"):
            with self.subTest(role=role), self.assertRaises(AgentError):
                self.agent.dispatch("computer_audio", {"action": "start"}, role)
        for arguments in ({"action": "shell"}, {"action": "start", "command": "untrusted"}, {}, {"action": True}):
            with self.subTest(arguments=arguments), self.assertRaises(AgentError):
                self.agent.dispatch("computer_audio", arguments, "orchestrator")
        self.service.computer_audio.assert_not_called()
        self.agent.dispatch("computer_audio", {"action": "start"}, "orchestrator")
        self.service.computer_audio.assert_called_once_with("start")
        self.assertFalse(self.agent.private_request)
        self.assertEqual(self.service.activations, [])

    def test_waiting_clarification_or_cancelled_request_cannot_start_audio(self):
        self.agent.clarification = "Synthetic question"
        with self.assertRaises(AgentError):
            self.agent.dispatch("computer_audio", {"action": "start"}, "orchestrator")
        self.agent.clarification = None
        self.agent.cancelled.set()
        with self.assertRaises(AgentError):
            self.agent.dispatch("computer_audio", {"action": "start"}, "orchestrator")
        self.service.computer_audio.assert_not_called()


class AudioTransportTests(unittest.TestCase):
    def test_audio_routes_keep_enrolled_origin_auth_timeout_and_none_cursor(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "enrollment.json"
            save_private(path, {"host_url": "https://127.0.0.1:8788", "device_key": "x" * 40, "ca_file": "cert.pem"})
            with patch("modulate.device_transport.ssl.SSLContext"), patch("modulate.device_transport.urllib.request.build_opener"):
                client = Companion(path)
            response = client.opener.open.return_value.__enter__.return_value
            response.read.return_value = b'{"packet":null}'
            self.assertEqual(client.post("audio", {"session": STREAM, "after": None}), {"packet": None})
            request = client.opener.open.call_args.args[0]
            self.assertEqual(request.full_url, client.origin + "/device/audio")
            self.assertEqual(json.loads(request.data), {"session": STREAM, "after": None})
            self.assertEqual(request.get_header("Authorization"), "Bearer " + "x" * 40)
            self.assertEqual(client.opener.open.call_args.kwargs, {"timeout": 3})
            client.post("audio/stop", {"session": STREAM})
            self.assertEqual(client.opener.open.call_args.args[0].full_url, client.origin + "/device/audio/stop")


if __name__ == "__main__":
    unittest.main()
