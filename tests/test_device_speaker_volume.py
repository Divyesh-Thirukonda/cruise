"""Synthetic controller wiring for Pulse volume; no hardware or native I/O."""
import unittest
from unittest.mock import Mock

from modulate.device_transport import TransportError
from tests import test_device_speaker as speaker_fixture


class DeviceSpeakerVolumeTests(unittest.TestCase):
    def setUp(self):
        speaker_fixture.DeviceSpeakerTests.setUp(self)
        self.volume = Mock()
        self.volume.snapshot.return_value = {"available": True, "sink": "synthetic-sink",
                                             "volume": 75, "muted": False, "ack": None}
        self.controller.speaker_volume = self.volume

    def test_only_paired_heartbeat_offers_command_to_background_worker(self):
        command = {"synthetic": "command validated by volume worker"}
        self.controller.responses.put({"paired": True, "speaker_volume": command})
        self.controller._apply_responses()
        self.volume.offer.assert_called_once_with(command)
        self.volume.disconnect.assert_not_called()
        self.controller.responses.put({"paired": False, "speaker_volume": command})
        self.controller._apply_responses()
        self.volume.disconnect.assert_called_once()
        self.assertEqual(self.volume.offer.call_count, 1)

    def test_heartbeat_reports_verified_volume_metadata(self):
        self.Companion.post.return_value = {}
        self.controller._network_step()
        packet = self.Companion.post.call_args.args[1]
        self.assertEqual(packet["telemetry"]["speaker_volume"], self.volume.snapshot.return_value)

    def test_standalone_local_agent_controls_pi_speaker_without_mac_grant(self):
        command = {"synthetic": "validated by worker"}
        self.controller.standalone = True
        self.controller.responses.put({"paired": False, "speaker_volume": command,
                                       "setup_status": {"ai_host": "pi"}})
        self.controller._apply_responses()
        self.volume.offer.assert_called_once_with(command)
        self.volume.disconnect.assert_not_called()

    def test_standalone_flag_does_not_authorize_unpaired_mac_agent(self):
        self.controller.standalone = True
        self.controller.responses.put({"paired": False, "speaker_volume": {},
                                       "setup_status": {"ai_host": "mac"}})
        self.controller._apply_responses()
        self.volume.offer.assert_not_called()
        self.volume.disconnect.assert_called_once()

    def test_network_failure_invalidates_pending_volume_authority(self):
        self.Companion.post.side_effect = TransportError("Synthetic unavailable link")
        self.controller._network_step()
        self.volume.disconnect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
