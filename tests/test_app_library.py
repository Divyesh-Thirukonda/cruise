"""Synthetic durable library data only; no device, native action or model calls."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from modulate.app_library import AppLibrary, AppLibraryError


def activation(title="Saved game", at=100):
    package = {"kind": "game", "title": title, "code": "function init(){return {}}",
               "controls": ["button_a"], "assets": {"sprites": {}}}
    revision = hashlib.sha256(json.dumps(package, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {"revision": revision, "package": package, "report": {"passed": True, "candidate_id": revision},
            "activated_at": at, "previous": None}


class AppLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.library = AppLibrary(self.directory / "library", clock=lambda: 300)
        self.record = activation()
        self.revision = self.record["revision"]

    def save(self, record=None):
        return self.library.record_activation(record or self.record)

    def raw_index(self):
        return json.loads(self.library.path.read_text())

    def write_history(self, record=None, **changes):
        record = record or self.record
        requests = self.directory / "requests"
        requests.mkdir(exist_ok=True)
        (requests / (record["revision"] + ".json")).write_text(json.dumps(record["package"]))
        (requests / (record["revision"] + ".checks.json")).write_text(json.dumps(record["report"]))
        event = {"type": "tool_finished", "tool": "activate_package", "status": "passed",
                 "at": "2026-10-29T12:00:00+00:00", "detail": {"activated": True,
                 "device_acknowledged": True, "revision": record["revision"]}, **changes}
        with (requests / "trace.jsonl").open("a") as stream:
            stream.write(json.dumps(event) + "\n")
        return requests

    def test_exact_package_survives_restart_and_return_values_are_copies(self):
        item = self.save()
        item["favorite"] = True
        record = self.library.get_record(self.revision)
        record["package"]["title"] = "Mutated return value"
        self.record["package"]["title"] = "Mutated caller input"
        restarted = AppLibrary(self.library.directory)
        self.assertEqual(restarted.get_record(self.revision)["package"]["title"], "Saved game")
        self.assertFalse(restarted.list_items()[0]["favorite"])
        self.assertNotIn("package", restarted.list_items()[0])

    def test_digest_matches_runtime_and_duplicate_activation_keeps_favorite(self):
        from modulate.agent import digest
        self.assertEqual(self.revision, digest(self.record["package"]))
        self.save()
        self.library.set_favorite(self.revision, True)
        self.save({**self.record, "activated_at": 200, "report": {**self.record["report"], "manifest_revision": "new"}})
        items = self.library.list_items("favorites")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["created_at"], 100)
        self.assertEqual(items[0]["last_opened"], 200)
        self.assertEqual(self.library.get_record(self.revision)["report"], self.record["report"])

    def test_trash_hides_without_destroying_and_restore_preserves_favorite(self):
        self.save()
        self.library.set_favorite(self.revision, True)
        self.library.trash(self.revision)
        self.assertEqual(self.library.list_items(), [])
        self.assertEqual(self.library.list_items("favorites"), [])
        self.assertEqual(self.library.list_items("trash")[0]["trashed_at"], 300)
        with self.assertRaisesRegex(AppLibraryError, "Restore"):
            self.library.get_record(self.revision)
        self.assertEqual(self.library.get_record(self.revision, include_trashed=True)["package"], self.record["package"])
        restored = self.library.restore(self.revision)
        self.assertTrue(restored["favorite"])
        self.assertIsNone(restored["trashed_at"])

    def test_newest_opened_first_and_only_selected_revision_changes(self):
        other = activation("Other game", at=200)
        self.save()
        self.save(other)
        self.library.trash(self.revision)
        self.assertEqual([item["id"] for item in self.library.list_items()], [other["revision"]])
        self.library.restore(self.revision)
        self.assertEqual([item["last_opened"] for item in self.library.list_items()], [200, 100])

    def test_truthy_favorite_values_are_not_silently_accepted(self):
        self.save()
        for value in (1, 0, "false", None, [], {}):
            with self.subTest(value=value), self.assertRaises(AppLibraryError):
                self.library.set_favorite(self.revision, value)
        self.assertFalse(self.library.list_items()[0]["favorite"])

    def test_failed_unmatched_or_modified_packages_cannot_be_saved(self):
        for change in ({"report": {"passed": False, "candidate_id": self.revision}},
                       {"report": {"passed": 1, "candidate_id": self.revision}},
                       {"report": {"passed": True, "candidate_id": "a" * 64}},
                       {"package": {**self.record["package"], "title": "Tampered"}},
                       {"activated_at": float("nan")}):
            with self.subTest(change=change), self.assertRaises(AppLibraryError):
                self.save({**self.record, **change})
        self.assertEqual(self.library.list_items(), [])

    def test_record_does_not_capture_previous_or_extra_request_metadata(self):
        self.save({**self.record, "request": "private spoken text", "previous": activation("Previous")})
        raw = self.library._record_path(self.revision).read_text()
        self.assertNotIn("private spoken text", raw)
        self.assertNotIn("Previous", raw)

    def test_paths_are_revision_ids_not_user_filenames(self):
        self.save()
        for revision in ("../../active", "A" * 64, "a" * 63, None, 12):
            with self.subTest(revision=revision), self.assertRaises(AppLibraryError):
                self.library.get_record(revision)
        self.assertEqual(self.library.get_record(self.revision)["revision"], self.revision)

    def test_private_files_and_directories(self):
        self.save()
        for path in (self.library.directory, self.library.records):
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)
        for path in (self.library.path, self.library._record_path(self.revision), self.library.directory / ".lock"):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_corrupt_index_is_not_reset_or_overwritten(self):
        self.save()
        corrupted = b'{"version": 1, "items":'
        self.library.path.write_bytes(corrupted)
        with self.assertRaises(AppLibraryError):
            AppLibrary(self.library.directory)
        with self.assertRaises(AppLibraryError):
            self.save(activation("Another"))
        self.assertEqual(self.library.path.read_bytes(), corrupted)
        self.assertTrue(self.library._record_path(self.revision).exists())

    def test_missing_index_with_existing_packages_does_not_invent_empty_library(self):
        self.save()
        self.library.path.unlink()
        with self.assertRaisesRegex(AppLibraryError, "index is missing"):
            AppLibrary(self.library.directory)
        self.assertFalse(self.library.path.exists())

    def test_duplicate_json_fields_and_invalid_metadata_fail_closed(self):
        self.library.path.write_text('{"version":1,"version":1,"items":{},"purged":[]}')
        with self.assertRaises(AppLibraryError):
            self.library.list_items()
        self.library.path.write_text(json.dumps({"version": 1, "items": {}, "purged": ["../escape"]}))
        with self.assertRaises(AppLibraryError):
            self.library.list_items()

    def test_corrupt_or_missing_package_is_never_returned_or_repaired_from_input(self):
        self.save()
        path = self.library._record_path(self.revision)
        path.write_text(json.dumps({**self.library.get_record(self.revision), "package": {"kind": "game", "title": "Altered"}}))
        with self.assertRaises(AppLibraryError):
            self.library.get_record(self.revision)
        with self.assertRaises(AppLibraryError):
            self.save()
        path.unlink()
        with self.assertRaises(AppLibraryError):
            self.save()
        self.assertFalse(path.exists())

    def test_symlink_package_cannot_return_an_unrelated_file(self):
        self.save()
        path = self.library._record_path(self.revision)
        original = path.read_bytes()
        target = self.directory / "elsewhere.json"
        target.write_bytes(original)
        path.unlink()
        path.symlink_to(target)
        with self.assertRaises(AppLibraryError):
            self.library.get_record(self.revision)

    def test_failed_index_replace_does_not_mutate_in_memory_or_saved_index(self):
        self.save()
        before = self.library.path.read_bytes()
        with patch("modulate.app_library.os.replace", side_effect=OSError("synthetic disk error")):
            with self.assertRaises(OSError):
                self.library.set_favorite(self.revision, True)
        self.assertEqual(self.library.path.read_bytes(), before)
        self.assertFalse(self.library.list_items()[0]["favorite"])
        self.assertFalse(list(self.library.directory.glob(".pending-*")))

    def test_failed_new_index_write_orphan_is_not_auto_imported_and_retry_recovers(self):
        with patch.object(self.library, "_save", side_effect=OSError("synthetic index failure")):
            with self.assertRaises(OSError):
                self.save()
        restarted = AppLibrary(self.library.directory)
        self.assertEqual(restarted.list_items(), [])
        restarted.record_activation(self.record)
        self.assertEqual(len(restarted.list_items()), 1)

    def test_multiple_instances_preserve_independent_concurrent_mutations(self):
        second = AppLibrary(self.library.directory)
        records = [activation("Game " + str(index), at=100 + index) for index in range(16)]
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda pair: (self.library if pair[0] % 2 else second).record_activation(pair[1]), enumerate(records)))
        self.assertEqual(len(results), 16)
        self.assertEqual(len(self.library.list_items()), 16)
        self.assertEqual(len(second.list_items()), 16)

    def test_capacity_never_silently_evicts_favorites_or_trash(self):
        self.save()
        self.library.set_favorite(self.revision, True)
        self.library.trash(self.revision)
        with patch.object(self.library, "MAX_ITEMS", 1):
            with self.assertRaisesRegex(AppLibraryError, "full"):
                self.save(activation("New game"))
            self.assertTrue(self.library.list_items("trash")[0]["favorite"])

    def test_current_and_previous_import_only_preserves_saved_metadata(self):
        self.save()
        self.library.set_favorite(self.revision, True)
        self.library.trash(self.revision)
        current = activation("Current", at=200)
        current["previous"] = self.record
        self.assertEqual(self.library.import_active(current), {"imported": 1})
        self.assertEqual(self.library.import_active(current), {"imported": 0})
        self.assertTrue(self.library.list_items("trash")[0]["favorite"])
        self.assertEqual(self.library.list_items()[0]["id"], current["revision"])

    def test_history_needs_successful_device_ack_and_exact_checks(self):
        requests = self.write_history(status="failed")
        self.write_history(detail={"activated": True, "revision": self.revision})
        self.write_history(type="request_finished", detail="I activated the game")
        self.assertEqual(self.library.import_history(requests)["imported"], 0)
        self.write_history()
        self.assertEqual(self.library.import_history(requests)["imported"], 1)
        self.assertEqual(self.library.import_history(requests)["imported"], 0)
        self.assertEqual(self.library.get_record(self.revision)["package"], self.record["package"])

    def test_history_skips_individual_corruption_without_hiding_library_corruption(self):
        requests = self.write_history()
        other = activation("Other")
        self.write_history(other)
        (requests / (self.revision + ".checks.json")).write_text('{"passed":false}')
        with (requests / "trace.jsonl").open("a") as stream:
            stream.write("broken json\n")
        result = self.library.import_history(requests)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["skipped"], 2)
        self.library.path.write_text("corrupt index")
        with self.assertRaises(AppLibraryError):
            self.library.import_history(requests)

    def test_history_does_not_promote_unlogged_candidates_or_retain_request_text(self):
        requests = self.write_history(detail={"activated": True, "device_acknowledged": True,
                                             "revision": self.revision, "request": "Sensitive request"})
        candidate = activation("Never activated")
        (requests / (candidate["revision"] + ".json")).write_text(json.dumps(candidate["package"]))
        self.library.import_history(requests)
        self.assertEqual(len(self.library.list_items()), 1)
        self.assertNotIn("Sensitive request", self.library.path.read_text())

    def test_history_read_is_bounded_and_reports_limit(self):
        requests = self.write_history()
        with patch.object(self.library, "MAX_HISTORY_BYTES", 10):
            result = self.library.import_history(requests)
        self.assertTrue(result["limited"])
        self.assertEqual(self.library.list_items(), [])

    def test_nonfinite_or_unrepresentable_metadata_timestamps_are_rejected(self):
        self.save()
        for at in (float("inf"), float("nan"), 10 ** 500, -1, True):
            index = self.raw_index()
            index["items"][self.revision]["last_opened"] = at
            self.library.path.write_text(json.dumps(index))
            with self.subTest(at=at), self.assertRaises(AppLibraryError):
                self.library.list_items()
        self.assertTrue(self.library._record_path(self.revision).exists())

    def test_permanent_delete_requires_trash_and_protects_active_and_rollback(self):
        self.save()
        with self.assertRaisesRegex(AppLibraryError, "Trash"):
            self.library.purge(self.revision)
        self.library.trash(self.revision)
        with self.assertRaisesRegex(AppLibraryError, "rollback"):
            self.library.purge(self.revision, protected=[None, self.revision])
        self.assertTrue(self.library._record_path(self.revision).exists())
        self.assertEqual(len(self.library.list_items("trash")), 1)

    def test_purge_deletes_bytes_and_tombstone_prevents_history_resurrection(self):
        requests = self.write_history()
        self.save()
        self.library.trash(self.revision)
        self.assertTrue(self.library.purge(self.revision)["deleted"])
        self.assertFalse(self.library._record_path(self.revision).exists())
        restarted = AppLibrary(self.library.directory)
        restarted.import_history(requests)
        restarted.import_active(self.record)
        self.assertEqual(restarted.list_items(), [])
        self.assertEqual(restarted.list_items("trash"), [])
        self.assertTrue(restarted.purge(self.revision)["deleted"])

    def test_explicit_new_activation_can_save_an_identical_previously_purged_app(self):
        self.save()
        self.library.trash(self.revision)
        self.library.purge(self.revision)
        self.save({**self.record, "activated_at": 400})
        self.assertEqual(self.library.list_items()[0]["created_at"], 400)
        self.assertNotIn(self.revision, self.raw_index()["purged"])

    def test_failed_purge_index_write_does_not_delete_package(self):
        self.save()
        self.library.trash(self.revision)
        with patch.object(self.library, "_save", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.library.purge(self.revision)
        self.assertTrue(self.library._record_path(self.revision).exists())
        self.assertEqual(len(self.library.list_items("trash")), 1)

    def test_failed_unlink_does_not_claim_deletion_and_restart_finishes_intent(self):
        self.save()
        self.library.trash(self.revision)
        path = self.library._record_path(self.revision)
        original = Path.unlink

        def fail_selected(target, *args, **kwargs):
            if target == path:
                raise OSError("synthetic read-only package")
            return original(target, *args, **kwargs)

        with patch.object(Path, "unlink", fail_selected):
            with self.assertRaisesRegex(AppLibraryError, "pending"):
                self.library.purge(self.revision)
        self.assertTrue(path.exists())
        self.assertIn(self.revision, self.raw_index()["purged"])
        restarted = AppLibrary(self.library.directory)
        self.assertFalse(path.exists())
        self.assertEqual(restarted.list_items(), [])

    def test_full_tombstones_refuses_deletion_without_erasing_package(self):
        self.save()
        self.library.trash(self.revision)
        with patch.object(self.library, "MAX_PURGED", 0):
            with self.assertRaisesRegex(AppLibraryError, "history is full"):
                self.library.purge(self.revision)
        self.assertTrue(self.library._record_path(self.revision).exists())


if __name__ == "__main__":
    unittest.main()
