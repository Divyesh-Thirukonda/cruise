"""Telemetry checks must distinguish local operation and optional Mac access."""
import unittest
from modulate.demo_preflight import assess


class DemoPreflightTests(unittest.TestCase):
    def state(self):
        return {"device": {"connected": True, "telemetry": {"app": {},
                "speaker_volume": {"available": True, "volume": 60, "muted": False},
                "voice": {"state": "wake_listening"}}}, "agent": {"running": False},
                "budget": {"limit_dollars": 50, "charged_or_reserved_dollars": 12},
                "speech": {"provider": "meta_mms"}, "wake": True}

    def test_local_demo_does_not_require_mac(self):
        self.assertEqual(assess(self.state())["status"], "pass")
        self.assertEqual(assess(self.state(), mac=True)["status"], "fail")

    def test_connected_but_silent_speaker_is_not_ready(self):
        state = self.state()
        state["device"]["telemetry"]["speaker_volume"]["volume"] = 0
        self.assertEqual(assess(state)["status"], "warn")
        state["device"]["telemetry"]["app"]["suspended"] = True
        self.assertEqual(assess(state)["status"], "fail")

    def test_session_expiring_during_demo_is_flagged(self):
        state = self.state()
        state["remote"] = {"connected": True, "expires_at": 1600}
        self.assertEqual(assess(state, now=1000)["status"], "warn")
        self.assertEqual(assess(state, now=1601)["status"], "fail")

    def test_exhausted_budget_blocks_without_modifying_it(self):
        state = self.state()
        state["budget"]["charged_or_reserved_dollars"] = 50
        self.assertEqual(assess(state)["status"], "fail")
        self.assertEqual(state["budget"]["limit_dollars"], 50)
