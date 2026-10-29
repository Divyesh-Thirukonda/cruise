"""Synthetic mute-ownership tests; no native audio or output changes."""
import unittest

from modulate.audio_route import MacAudioRoute


class Backend:
    def __init__(self, muted=False):
        self.device, self.muted, self.volume = (1, "private-device-id"), muted, 37
        self.writes = []
        self.failure = False
        self.uncertain = False

    def get(self):
        if self.failure:
            raise RuntimeError("private details")
        return {"device": self.device, "muted": self.muted}

    def set_muted(self, device, value):
        if self.failure or device != self.device:
            raise RuntimeError("private details")
        self.writes.append((device, value))
        self.muted = value
        if self.uncertain:
            raise RuntimeError("the write happened before the error")


class AudioRouteTests(unittest.TestCase):
    def test_no_implicit_mutation_then_mute_restore_preserves_volume(self):
        backend = Backend()
        route = MacAudioRoute(backend)
        self.assertEqual(route.status()["state"], "stopped")
        self.assertEqual(backend.writes, [])
        state = route.start()
        self.assertEqual(state["state"], "muted")
        self.assertTrue(state["owns_mute"])
        self.assertTrue(backend.muted)
        self.assertNotIn("private-device-id", str(state))
        route.start()
        self.assertEqual(len(backend.writes), 1)
        state = route.stop()
        self.assertFalse(backend.muted)
        self.assertTrue(state["restored"])
        route.stop()
        self.assertEqual(len(backend.writes), 2)
        self.assertEqual(backend.volume, 37)

    def test_existing_mute_is_preserved_without_acquiring_write_ownership(self):
        backend = Backend(muted=True)
        route = MacAudioRoute(backend)
        self.assertEqual(route.start()["state"], "already_muted")
        self.assertFalse(route.status()["owns_mute"])
        route.stop()
        self.assertTrue(backend.muted)
        self.assertEqual(backend.writes, [])

    def test_switching_output_releases_ownership_without_unmuting_other_device(self):
        backend = Backend()
        route = MacAudioRoute(backend)
        route.start()
        backend.device = (2, "new-output")
        state = route.stop()
        self.assertEqual(state["state"], "output_changed")
        self.assertFalse(state["owns_mute"])
        self.assertTrue(backend.muted)
        self.assertEqual(len(backend.writes), 1)

    def test_same_native_object_id_different_uid_is_an_output_change(self):
        backend = Backend()
        route = MacAudioRoute(backend)
        route.start()
        backend.device = (1, "replacement-device")
        self.assertEqual(route.stop()["state"], "output_changed")
        self.assertEqual(len(backend.writes), 1)

    def test_external_unmute_is_respected_and_volume_adjustment_is_not_undone(self):
        backend = Backend()
        route = MacAudioRoute(backend)
        route.start()
        backend.muted, backend.volume = False, 71
        self.assertEqual(route.stop()["state"], "mute_changed")
        self.assertEqual(len(backend.writes), 1)
        self.assertEqual(backend.volume, 71)

    def test_failed_restore_retains_ownership_for_retry_without_private_error(self):
        backend = Backend()
        route = MacAudioRoute(backend)
        route.start()
        backend.failure = True
        failed = route.stop()
        self.assertEqual(failed["state"], "error")
        self.assertTrue(failed["owns_mute"])
        self.assertNotIn("private", str(failed))
        backend.failure = False
        self.assertTrue(route.stop()["restored"])
        self.assertFalse(backend.muted)

    def test_uncertain_start_write_can_still_be_restored(self):
        backend = Backend()
        backend.uncertain = True
        route = MacAudioRoute(backend)
        self.assertEqual(route.start()["state"], "error")
        self.assertTrue(backend.muted)
        self.assertTrue(route.status()["owns_mute"])
        backend.uncertain = False
        self.assertTrue(route.stop()["restored"])
        self.assertFalse(backend.muted)

    def test_read_failure_never_writes_or_claims_ownership(self):
        backend = Backend()
        backend.failure = True
        route = MacAudioRoute(backend)
        status = route.start()
        self.assertEqual(status["state"], "error")
        self.assertFalse(status["active"])
        self.assertFalse(status["owns_mute"])
        self.assertEqual(backend.writes, [])


if __name__ == "__main__":
    unittest.main()
