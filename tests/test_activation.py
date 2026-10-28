"""Activation failures use temporary state and a fake software display acknowledgment."""

import hashlib
import json
import os
from collections import deque
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modulate.activation import ActivationError, Store
from modulate.runtime import ValidationError


ACK = object()


def candidate(number):
    return {"code": f"show({number}, label='Test')", "provider": "test", "model": "test-model"}


class Display:
    def __init__(self):
        self.calls = []
        self.responses = deque()
        self.visible = None

    def render(self, frame, revision, provider):
        self.calls.append((frame, revision, provider))
        response = self.responses.popleft() if self.responses else ACK
        if isinstance(response, Exception):
            raise response
        self.visible = (frame, revision, provider)
        return revision if response is ACK else response


class ActivationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(directory.name)
        self.display = Display()

    def activate(self, number):
        return self.store.activate(candidate(number), self.display, base_revision=self.store.revision)

    def assert_preserved(self, expected):
        self.assertEqual(self.store.active, expected)
        self.assertEqual(json.loads(self.store.pointer.read_text()), expected)
        self.assertEqual(Store(self.store.directory).active, expected)

    def test_pointer_is_committed_only_after_matching_software_ack(self):
        original_render = self.display.render

        def render(*args):
            self.assertIsNone(self.store.revision)
            self.assertFalse(self.store.pointer.exists())
            return original_render(*args)

        with patch.object(self.display, "render", side_effect=render):
            record = self.activate(7)
        self.assertEqual(record["revision"], hashlib.sha256(candidate(7)["code"].encode()).hexdigest())
        self.assertEqual(self.store.current_code(), candidate(7)["code"])
        self.assertEqual(self.display.visible[1], record["revision"])
        self.assert_preserved(record)

    def test_malformed_or_failing_program_preserves_active_without_render(self):
        active = self.activate(7)
        for source in ("show(", "import os\nshow(0)", "show(1 // 0)", "show(1000000)"):
            with self.subTest(source=source):
                self.display.calls.clear()
                with self.assertRaises(ValidationError):
                    self.store.activate({**candidate(8), "code": source}, self.display,
                                        base_revision=active["revision"])
                self.assertEqual(self.display.calls, [])
                self.assert_preserved(active)

    def test_stale_base_cannot_overwrite_newer_program(self):
        older = self.activate(7)
        newer = self.activate(8)
        self.display.calls.clear()
        with self.assertRaisesRegex(ActivationError, "Stale base"):
            self.store.activate(candidate(9), self.display, base_revision=older["revision"])
        self.assertEqual(self.display.calls, [])
        self.assert_preserved(newer)

    def test_driver_failure_restores_previous_frame_and_pointer(self):
        active = self.activate(7)
        self.display.calls.clear()
        self.display.responses.append(OSError("test driver failure"))
        with self.assertRaisesRegex(OSError, "test driver failure"):
            self.activate(8)
        self.assertEqual([frame.number for frame, _, _ in self.display.calls], [8, 7])
        self.assertEqual(self.display.visible[1], active["revision"])
        self.assert_preserved(active)

    def test_first_driver_failure_does_not_create_active_pointer(self):
        self.display.responses.append(OSError("test driver failure"))
        with self.assertRaises(OSError):
            self.activate(7)
        self.assertIsNone(self.store.active)
        self.assertFalse(self.store.pointer.exists())

    def test_stale_or_missing_ack_cannot_commit_candidate(self):
        active = self.activate(7)
        for acknowledgment in (active["revision"], None, "unrelated-revision"):
            with self.subTest(acknowledgment=acknowledgment):
                self.display.responses.append(acknowledgment)
                with self.assertRaisesRegex(ActivationError, "Display acknowledgement mismatch"):
                    self.activate(8)
                self.assertEqual(self.display.visible[1], active["revision"])
                self.assert_preserved(active)

    def test_pointer_replace_failure_restores_previous_display_and_disk_pointer(self):
        active = self.activate(7)
        replace = os.replace

        def fail_pointer(source, destination):
            if Path(destination) == self.store.pointer:
                raise OSError("test pointer write failure")
            return replace(source, destination)

        with patch("modulate.activation.os.replace", side_effect=fail_pointer):
            with self.assertRaisesRegex(OSError, "test pointer write failure"):
                self.activate(8)
        self.assertEqual(self.display.visible[1], active["revision"])
        self.assert_preserved(active)
        # A leftover pending file must not prevent the next successful activation.
        self.assertEqual(self.activate(9)["frame"]["number"], 9)

    def test_interrupt_after_render_restores_previous_revision(self):
        active = self.activate(7)
        render = self.display.render

        def interrupted_render(frame, revision, provider):
            result = render(frame, revision, provider)
            if revision != active["revision"]:
                raise KeyboardInterrupt()
            return result

        with patch.object(self.display, "render", side_effect=interrupted_render):
            with self.assertRaises(KeyboardInterrupt):
                self.activate(8)
        self.assertEqual(self.display.visible[1], active["revision"])
        self.assert_preserved(active)

    def test_interrupt_after_pointer_commit_recovers_committed_revision(self):
        self.activate(7)
        write_pointer = self.store._write_pointer

        def interrupted_write(record):
            write_pointer(record)
            raise KeyboardInterrupt()

        with patch.object(self.store, "_write_pointer", side_effect=interrupted_write):
            with self.assertRaises(KeyboardInterrupt):
                self.activate(8)
        committed = json.loads(self.store.pointer.read_text())
        self.assertEqual(committed["frame"]["number"], 8)
        self.assertEqual(self.display.visible[1], committed["revision"])
        self.assert_preserved(committed)

    def test_rollback_after_restart_restores_exact_saved_frame_without_rerun(self):
        source = {**candidate(7), "code": "show(randint(1, 20))"}
        with patch("modulate.runtime._RNG") as rng:
            rng.randint.return_value = 7
            previous = self.store.activate(source, self.display, base_revision=None)
        self.activate(8)
        self.store = Store(self.store.directory)
        with patch("modulate.activation.run", side_effect=AssertionError("must not rerun")):
            restored = self.store.rollback(self.display)
        self.assertEqual(restored, previous)
        self.assertEqual(self.display.visible[0].number, 7)
        self.assert_preserved(previous)
        with self.assertRaisesRegex(ActivationError, "No previous revision"):
            self.store.rollback(self.display)

    def test_rollback_bad_ack_restores_current_revision(self):
        self.activate(7)
        current = self.activate(8)
        self.display.responses.append(current["revision"])
        with self.assertRaisesRegex(ActivationError, "Rollback acknowledgement mismatch"):
            self.store.rollback(self.display)
        self.assertEqual(self.display.visible[1], current["revision"])
        self.assert_preserved(current)

    def test_rollback_pointer_failure_restores_current_revision(self):
        self.activate(7)
        current = self.activate(8)
        with patch.object(self.store, "_write_pointer", side_effect=OSError("test disk full")):
            with self.assertRaisesRegex(OSError, "test disk full"):
                self.store.rollback(self.display)
        self.assertEqual(self.display.visible[1], current["revision"])
        self.assert_preserved(current)

    def test_interrupt_during_rollback_restores_current_revision(self):
        self.activate(7)
        current = self.activate(8)
        with patch.object(self.store, "_write_pointer", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.store.rollback(self.display)
        self.assertEqual(self.display.visible[1], current["revision"])
        self.assert_preserved(current)

    def test_interrupt_after_rollback_commit_recovers_committed_previous_revision(self):
        previous = self.activate(7)
        self.activate(8)
        write_pointer = self.store._write_pointer

        def interrupted_write(record):
            write_pointer(record)
            raise KeyboardInterrupt()

        with patch.object(self.store, "_write_pointer", side_effect=interrupted_write):
            with self.assertRaises(KeyboardInterrupt):
                self.store.rollback(self.display)
        self.assertEqual(self.display.visible[1], previous["revision"])
        self.assert_preserved(previous)

    def test_modified_active_source_is_not_restored(self):
        active = self.activate(7)
        (self.store.directory / active["source"]).write_text(candidate(9)["code"])
        self.display.calls.clear()
        with self.assertRaisesRegex(ActivationError, "Active source hash mismatch"):
            self.store.current_code()
        with self.assertRaisesRegex(ActivationError, "Active source hash mismatch"):
            self.store.restore(self.display)
        self.assertEqual(self.display.calls, [])
        self.assert_preserved(active)

    def test_modified_previous_source_cannot_be_rolled_back_to(self):
        previous = self.activate(7)
        current = self.activate(8)
        (self.store.directory / previous["source"]).write_text(candidate(9)["code"])
        self.display.calls.clear()
        with self.assertRaisesRegex(ActivationError, "Previous source hash mismatch"):
            self.store.rollback(self.display)
        self.assertEqual([revision for _, revision, _ in self.display.calls], [current["revision"]])
        self.assert_preserved(current)

    def test_conflicting_revision_file_is_not_overwritten(self):
        active = self.activate(7)
        revision = hashlib.sha256(candidate(8)["code"].encode()).hexdigest()
        path = self.store.directory / f"{revision}.py"
        path.write_text("unexpected content")
        self.display.calls.clear()
        with self.assertRaisesRegex(ActivationError, "Revision integrity mismatch"):
            self.activate(8)
        self.assertEqual(path.read_text(), "unexpected content")
        self.assertEqual(self.display.calls, [])
        self.assert_preserved(active)

    def test_reactivating_identical_source_never_rewrites_immutable_file(self):
        active = self.activate(7)
        source_path = self.store.directory / active["source"]
        write_text = Path.write_text

        def reject_overwrite(path, *args, **kwargs):
            if path == source_path:
                raise OSError("an existing source must not be reopened for writing")
            return write_text(path, *args, **kwargs)

        with patch.object(Path, "write_text", reject_overwrite):
            self.activate(7)
        self.assertEqual(source_path.read_text(), candidate(7)["code"])
        self.assertEqual(self.store.revision, active["revision"])


if __name__ == "__main__":
    unittest.main()
