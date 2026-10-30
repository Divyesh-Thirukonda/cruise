"""Library integration uses synthetic devices and explicit mocked verifier results.

The real host stage/acknowledgement path runs here; no native control, physical
screen, spoken input or live model behavior is claimed by these tests.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from modulate.agent import AgentError, digest
from modulate.app_library import AppLibraryError
from modulate.library import LibraryManager
from modulate.product import Product
from tests.test_assistant_io import FakeComputer, SyntheticProvider
from tests.test_product import FakeBackend, checks, game


class LibraryActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.provider = SyntheticProvider([])
        self.product = Product(self.directory, self.provider, backend=FakeBackend(), computer=FakeComputer())
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.addCleanup(self.pool.shutdown, wait=True)
        self.addCleanup(self.product.cancel)
        self.manager = self.product.app_library
        self.now = 1000
        self.manager.clock = lambda: self.now
        self.sequence = 0
        self.heartbeat()

    def heartbeat(self, **changes):
        self.sequence += 1
        packet = {"session": "a" * 32, "sequence": self.sequence, "name": "Synthetic library controller",
                  "capabilities": {"controls": ["encoder", "button_a"], "devices": [], "warnings": []},
                  "input": {}, "revision": self.product.revision, **changes}
        return self.product.heartbeat(packet)

    def save(self, title="Saved fixture", *, active=False, previous=None):
        package = game(title)
        record = {"revision": digest(package), "package": package, "report": checks(package),
                  "activated_at": 100, "previous": previous}
        if active:
            self.product._commit(record)
            self.heartbeat()
        else:
            self.manager.store.record_activation(record)
        return record

    def action(self, action, entry=None, **kwargs):
        return self.product.library_action({"action": action, **({"entry_id": entry} if entry else {}), **kwargs})

    def trash_and_prepare(self, record, *, agent=False):
        self.action("trash", record["revision"])
        return self.product.library_action({"action": "purge", "entry_id": record["revision"]}, agent=agent)["purge_confirmation"]

    def confirm(self, confirmation, **kwargs):
        return self.product.library_action({"action": "confirm_purge", "entry_id": confirmation["entry_id"],
                                           "confirmation_id": confirmation["id"]}, **kwargs)

    def wait_stage(self):
        with self.product.changed:
            self.assertTrue(self.product.changed.wait_for(
                lambda: self.product.pending is not None and self.product.pending["phase"] == "stage", timeout=2))
            return copy.deepcopy(self.product.pending)

    def acknowledge(self, pending):
        reply = self.heartbeat(revision=pending["base_revision"], ack={"id": pending["id"],
            "revision": pending["revision"], "phase": "ready"})
        self.assertEqual(reply["activation"]["phase"], "commit")
        reply = self.heartbeat(revision=pending["revision"], ack={"id": pending["id"],
            "revision": pending["revision"], "phase": "activated"})
        self.assertEqual(reply["activation"]["phase"], "confirmed")

    def wait_request(self):
        with self.product.changed:
            self.assertTrue(self.product.changed.wait_for(lambda: not self.product.running, timeout=2))

    def test_reuse_catalog_excludes_trash_and_groups_versions_without_losing_source(self):
        first = self.save("Example racer")
        newer = copy.deepcopy(first)
        newer["package"]["code"] += "\n// changed version"
        newer["revision"] = digest(newer["package"])
        newer["report"] = checks(newer["package"])
        newer["activated_at"] = 200
        self.manager.store.record_activation(newer)
        other = self.save("Other app")
        self.manager.store.trash(other["revision"])
        catalog = self.manager.catalog()
        self.assertEqual(catalog, [{"id": newer["revision"], "title": "Example racer", "kind": "game"}])
        self.assertEqual(len(self.manager.store.list_items()), 2)
        self.assertEqual(self.manager.store.get_record(first["revision"])["package"], first["package"])
        self.assertEqual([e["id"] for e in self.manager.device_state()["entries"]], [newer["revision"]])
        self.assertEqual(self.product.intent_context()["library"]["saved_apps"], catalog)

    def test_stale_version_and_reopened_view_cannot_apply_device_actions(self):
        record = self.save()
        view = self.action("open")["library"]
        self.product.library_action({"action": "favorite", "entry_id": record["revision"], "favorite": True,
                                    "view_id": view["id"], "version": view["version"]}, device=True)
        with self.assertRaisesRegex(AgentError, "refreshed"):
            self.product.library_action({"action": "trash", "entry_id": record["revision"],
                                        "view_id": view["id"], "version": view["version"]}, device=True)
        current = self.action("open")["library"]
        with self.assertRaisesRegex(AgentError, "refreshed"):
            self.product.library_action({"action": "trash", "entry_id": record["revision"],
                                        "view_id": view["id"], "version": current["version"]}, device=True)
        self.assertTrue(self.manager.store.list_items()[0]["favorite"])
        self.assertFalse(self.manager.store.list_items()[0]["trashed"])

    def test_closed_or_boolean_version_device_commands_are_rejected(self):
        record = self.save()
        view = self.action("open")["library"]
        with self.assertRaises(AgentError):
            self.product.library_action({"action": "select", "entry_id": record["revision"],
                                        "view_id": view["id"], "version": True}, device=True)
        self.action("close")
        with self.assertRaises(AgentError):
            self.product.library_action({"action": "trash", "entry_id": record["revision"],
                                        "view_id": view["id"], "version": self.manager.view["version"]}, device=True)

    def test_trashing_current_app_keeps_program_and_excludes_it_from_main_shelf(self):
        record = self.save(active=True)
        self.action("trash", record["revision"])
        self.assertEqual(self.product.revision, record["revision"])
        self.assertEqual(self.product.current_package(), record["package"])
        self.assertEqual(self.manager.store.list_items(), [])
        self.assertTrue(self.manager.entries()[0]["protected"])
        self.assertTrue(self.manager.entries()[0]["active"])

    def test_model_can_prepare_deletion_but_cannot_confirm_even_with_real_nonce(self):
        record = self.save()
        confirmation = self.trash_and_prepare(record, agent=True)
        self.assertEqual(self.product.clarification["kind"], "library_purge")
        with self.assertRaisesRegex(AgentError, "direct human"):
            self.confirm(confirmation, agent=True)
        self.assertIsNotNone(self.manager.store.get_record(record["revision"], include_trashed=True))
        self.assertEqual(self.provider.requests, [])

    def test_human_confirmation_is_one_use_and_removes_exact_source_copies(self):
        record = self.save()
        requests = self.directory / "requests"
        for suffix in (".json", ".checks.json"):
            (requests / (record["revision"] + suffix)).write_text("synthetic source copy")
        other = requests / (("f" * 64) + ".json")
        other.write_text("unrelated candidate")
        confirmation = self.trash_and_prepare(record)
        self.confirm(confirmation)
        self.assertIsNone(self.manager.confirmation)
        self.assertEqual(self.manager.store.list_items("trash"), [])
        self.assertFalse((requests / (record["revision"] + ".json")).exists())
        self.assertFalse((requests / (record["revision"] + ".checks.json")).exists())
        self.assertEqual(other.read_text(), "unrelated candidate")
        with self.assertRaises((AgentError, AppLibraryError)):
            self.confirm(confirmation)

    def test_wrong_nonce_or_target_cannot_confirm_another_app(self):
        record = self.save()
        other = self.save("Other fixture")
        self.action("trash", other["revision"])
        confirmation = self.trash_and_prepare(record)
        for changed in ({**confirmation, "id": "f" * 32}, {**confirmation, "entry_id": other["revision"]}):
            with self.subTest(changed=changed), self.assertRaisesRegex(AgentError, "expired or changed"):
                self.confirm(changed)
        self.assertEqual(len(self.manager.store.list_items("trash")), 2)
        self.confirm(confirmation)
        self.assertEqual(self.manager.store.list_items("trash")[0]["id"], other["revision"])

    def test_expired_nonce_never_purges_and_new_prompt_gets_new_nonce(self):
        record = self.save()
        confirmation = self.trash_and_prepare(record)
        self.now = confirmation["expires_at"]
        with self.assertRaisesRegex(AgentError, "expired or changed"):
            self.confirm(confirmation)
        self.assertEqual(len(self.manager.store.list_items("trash")), 1)
        replacement = self.action("purge", record["revision"])["purge_confirmation"]
        self.assertNotEqual(replacement["id"], confirmation["id"])

    def test_active_and_previous_are_protected_at_prepare_and_confirmation(self):
        previous = self.save("Rollback fixture")
        current = self.save("Current fixture", active=True, previous=previous)
        for record in (previous, current):
            self.action("trash", record["revision"])
            with self.subTest(title=record["package"]["title"]), self.assertRaisesRegex(AgentError, "rollback"):
                self.action("purge", record["revision"])
        future = self.save("Protected after prompt")
        confirmation = self.trash_and_prepare(future)
        self.product._commit(future)
        with self.assertRaisesRegex(AgentError, "rollback|expired or changed"):
            self.confirm(confirmation)
        self.assertIsNotNone(self.manager.store.get_record(future["revision"], include_trashed=True))

    def test_back_from_device_cancels_confirmation_without_deleting(self):
        record = self.save()
        self.action("trash", record["revision"])
        self.action("open", tab="trash")
        result = self.action("purge", record["revision"])
        view = result["library"]
        self.product.library_action({"action": "cancel_purge", "view_id": view["id"], "version": view["version"]}, device=True)
        self.assertIsNone(self.manager.confirmation)
        self.assertEqual(len(self.manager.store.list_items("trash")), 1)

    def test_direct_yes_followup_deletes_without_another_model_call(self):
        record = self.save()
        self.trash_and_prepare(record, agent=True)
        followup = copy.deepcopy(self.product.clarification)
        self.product.request("yes", followup_id=followup["id"])
        self.wait_request()
        self.assertEqual(self.product.progress["phase"], "ready")
        self.assertEqual(self.manager.store.list_items("trash"), [])
        self.assertEqual(self.provider.requests, [])

    def test_direct_no_followup_keeps_trash_without_model_call(self):
        record = self.save()
        self.trash_and_prepare(record, agent=True)
        followup = copy.deepcopy(self.product.clarification)
        self.product.request("no", followup_id=followup["id"])
        self.wait_request()
        self.assertEqual(self.product.progress["phase"], "ready")
        self.assertIsNone(self.manager.confirmation)
        self.assertEqual(len(self.manager.store.list_items("trash")), 1)
        self.assertEqual(self.provider.requests, [])

    def test_saved_launch_runs_fresh_checks_and_waits_for_exact_ack(self):
        current = self.save("Current fixture", active=True)
        saved = self.save("Saved target")
        self.action("open")
        fresh_report = {"passed": True, "checks": [{"name": "fresh synthetic verifier", "passed": True}]}
        with patch("modulate.library.verify", return_value=fresh_report) as verify:
            future = self.pool.submit(self.product.library_action,
                                     {"action": "launch", "entry_id": saved["revision"]}, agent=True)
            pending = self.wait_stage()
            verify.assert_called_once_with(saved["package"])
            self.assertEqual(pending["report"]["checks"], fresh_report["checks"])
            self.assertEqual(pending["report"]["manifest_revision"], digest(self.product.capabilities()))
            self.assertEqual(self.product.revision, current["revision"])
            self.assertFalse(future.done())
            self.heartbeat(ack={"id": "f" * 32, "revision": saved["revision"], "phase": "activated"})
            self.assertFalse(future.done())
            self.assertEqual(self.product.revision, current["revision"])
            self.acknowledge(pending)
            self.assertTrue(future.result(timeout=2)["device_acknowledged"])
        self.assertEqual(self.product.revision, saved["revision"])
        self.assertEqual(self.product.active["previous"]["revision"], current["revision"])
        self.assertFalse(self.manager.view["open"])
        self.assertEqual(self.provider.requests, [])

    def test_failed_fresh_checks_do_not_reuse_old_pass_or_activate(self):
        current = self.save("Current fixture", active=True)
        saved = self.save("Saved target")
        with patch("modulate.library.verify", return_value={"passed": False, "errors": ["synthetic bad draw"]}), \
                patch.object(self.product, "activate") as activate:
            with self.assertRaisesRegex(AgentError, "current checks"):
                self.product.library_action({"action": "launch", "entry_id": saved["revision"]}, agent=True)
            activate.assert_not_called()
        self.assertEqual(self.product.revision, current["revision"])

    def test_changed_capabilities_during_checks_cannot_activate(self):
        saved = self.save()

        def changed(package):
            self.product.device["controls"].append("button_b")
            return {"passed": True}

        with patch("modulate.library.verify", side_effect=changed), patch.object(self.product, "activate") as activate:
            with self.assertRaisesRegex(AgentError, "controls changed"):
                self.product.library_action({"action": "launch", "entry_id": saved["revision"]}, agent=True)
            activate.assert_not_called()

    def test_web_launch_uses_fixed_request_and_activation_without_model(self):
        saved = self.save()
        with patch("modulate.library.verify", return_value={"passed": True}):
            result = self.action("launch", saved["revision"])
            self.assertTrue(result["accepted"])
            pending = self.wait_stage()
            self.assertIsNone(self.product.revision)
            self.acknowledge(pending)
            self.wait_request()
        self.assertEqual(self.product.progress["phase"], "ready")
        self.assertEqual(self.product.revision, saved["revision"])
        self.assertEqual(self.provider.requests, [])

    def test_trash_or_cancelled_launch_never_runs_verifier(self):
        saved = self.save()
        self.action("trash", saved["revision"])
        with patch("modulate.library.verify") as verify:
            with self.assertRaisesRegex(AgentError, "Restore"):
                self.product.library_action({"action": "launch", "entry_id": saved["revision"]}, agent=True)
            self.action("restore", saved["revision"])
            self.product.agent.cancelled.set()
            with self.assertRaisesRegex(AgentError, "cancelled"):
                self.product.library_action({"action": "launch", "entry_id": saved["revision"]}, agent=True)
            verify.assert_not_called()

    def test_failed_archival_does_not_undo_confirmed_current_program(self):
        package = game()
        self.action("open")
        with patch.object(self.manager.store, "record_activation", side_effect=OSError("synthetic full disk")):
            future = self.pool.submit(self.product.activate, package, checks(package), base_revision=None, timeout=2)
            pending = self.wait_stage()
            self.acknowledge(pending)
            self.assertTrue(future.result(timeout=2)["activated"])
        self.assertEqual(self.product.revision, digest(package))
        self.assertFalse(self.manager.view["open"])
        self.assertIsNotNone(self.manager.snapshot()["error"])
        self.assertEqual(json.loads(self.product.active_path.read_text())["revision"], digest(package))

    def test_source_cleanup_failure_preserves_library_and_confirmation_can_retry(self):
        record = self.save()
        source = self.directory / "requests" / (record["revision"] + ".json")
        source.write_text("synthetic retained source")
        confirmation = self.trash_and_prepare(record)
        original = Path.unlink

        def failed_source(target, *args, **kwargs):
            if target == source:
                raise OSError("synthetic source permission error")
            return original(target, *args, **kwargs)

        with patch.object(Path, "unlink", failed_source):
            with self.assertRaises(OSError):
                self.confirm(confirmation)
        self.assertEqual(self.manager.store.get_record(record["revision"], include_trashed=True)["package"], record["package"])
        self.confirm(confirmation)
        self.assertFalse(source.exists())
        self.assertEqual(self.manager.store.list_items("trash"), [])

    def test_inflight_fresh_verification_protects_app_from_concurrent_purge(self):
        saved = self.save()
        checking = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        def held_verifier(package):
            checking.set()
            self.assertTrue(release.wait(timeout=2))
            return {"passed": True}

        with patch("modulate.library.verify", side_effect=held_verifier):
            future = self.pool.submit(self.product.library_action,
                                     {"action": "launch", "entry_id": saved["revision"]}, agent=True)
            self.assertTrue(checking.wait(timeout=1))
            self.action("trash", saved["revision"])
            with self.assertRaisesRegex(AgentError, "rollback"):
                self.action("purge", saved["revision"])
            self.assertTrue(self.manager.store._record_path(saved["revision"]).exists())
            self.product.agent.cancelled.set()
            release.set()
            with self.assertRaisesRegex(AgentError, "cancelled"):
                future.result(timeout=2)
        self.assertNotIn(saved["revision"], self.manager.protected())
        self.assertEqual(len(self.manager.store.list_items("trash")), 1)

    def test_control_title_is_normalized_for_display_without_changing_saved_source(self):
        from modulate.library_screen import validate_view
        title = "  Desk\nVolume\t  control  "
        package = {"kind": "control", "title": title, "target": "synthetic-paired-host",
                   "bindings": [{"control": "encoder", "action": "volume.delta", "scale": 1}]}
        record = {"revision": digest(package), "package": package, "report": checks(package), "activated_at": 100}
        self.manager.store.record_activation(record)
        view = self.action("open")["library"]
        self.assertEqual(view["entries"][0]["title"], "Desk Volume control")
        self.assertIsNotNone(validate_view(view, self.now))
        self.assertEqual(self.manager.store.get_record(record["revision"])["package"], package)
        self.action("trash", record["revision"])
        self.action("open", tab="trash")
        result = self.action("purge", record["revision"])
        self.assertEqual(result["purge_confirmation"]["title"], "Desk Volume control")
        self.assertIsNotNone(validate_view(result["library"], self.now))

    def test_unprintable_display_title_has_a_nonempty_fallback(self):
        record = self.save()
        item = {**self.manager.store.list_items()[0], "title": "\u200b\u200c"}
        with patch.object(self.manager.store, "list_items", side_effect=lambda view: [item] if view == "all" else []):
            self.assertEqual(self.manager.entries()[0]["title"], "Untitled app")
        self.assertEqual(self.manager.store.get_record(record["revision"])["package"]["title"], "Saved fixture")

    def test_opening_already_active_app_rechecks_without_overwriting_rollback(self):
        previous = self.save("Rollback fixture")
        current = self.save("Current fixture", active=True, previous=previous)
        original_pointer = self.product.active_path.read_bytes()
        self.action("open")
        with patch("modulate.library.verify", return_value={"passed": True}) as verify, \
                patch.object(self.product, "activate") as activate:
            result = self.product.library_action({"action": "launch", "entry_id": current["revision"]}, agent=True)
        verify.assert_called_once_with(current["package"])
        activate.assert_not_called()
        self.assertTrue(result["already_active"])
        self.assertEqual(self.product.active["previous"], previous)
        self.assertEqual(self.product.active_path.read_bytes(), original_pointer)
        self.assertFalse(self.manager.view["open"])
        self.assertEqual(self.manager.launching, set())

    def test_already_active_app_with_stale_device_presence_cannot_claim_acknowledgement(self):
        current = self.save(active=True)
        self.product.last_seen = 0
        self.assertFalse(self.product.connected())
        with patch("modulate.library.verify", return_value={"passed": True}):
            with self.assertRaisesRegex(AgentError, "disconnected"):
                self.product.library_action({"action": "launch", "entry_id": current["revision"]}, agent=True)
        self.assertEqual(self.product.revision, current["revision"])

    def test_unclear_direct_answer_retains_exact_deletion_confirmation_context(self):
        saved = self.save()
        confirmation = self.trash_and_prepare(saved, agent=True)
        first_followup = copy.deepcopy(self.product.clarification)
        self.product.unclear("incomplete", first_followup["id"])
        repeated = copy.deepcopy(self.product.clarification)
        self.assertNotEqual(repeated["id"], first_followup["id"])
        self.assertEqual(repeated["kind"], "library_purge")
        self.assertEqual(repeated["library_confirmation"], confirmation)
        self.product.request("yes", followup_id=repeated["id"])
        self.wait_request()
        self.assertEqual(self.product.progress["phase"], "ready")
        self.assertEqual(self.manager.store.list_items("trash"), [])
        self.assertEqual(self.provider.requests, [])

    def test_agent_can_persist_menu_preference_without_rebuilding_or_changing_active_app(self):
        active = self.save(active=True)
        pointer = self.product.active_path.read_bytes()
        opened = self.action("open")["library"]
        result = self.product.library_action({"action": "set_preferences", "encoder_direction": "reversed"}, agent=True)
        self.assertEqual(result["preference_change"], {
            "before": {"encoder_direction": "forward"}, "after": {"encoder_direction": "reversed"}, "saved": True})
        self.assertTrue(result["library"]["open"])
        self.assertEqual(result["library"]["selected_id"], opened["selected_id"])
        self.assertGreater(result["library"]["version"], opened["version"])
        self.assertEqual(self.product.current_package(), active["package"])
        self.assertEqual(self.product.active_path.read_bytes(), pointer)
        self.assertEqual(self.product.revision, active["revision"])
        self.assertIsNone(self.product.pending)
        self.assertEqual(self.provider.requests, [])
        self.assertEqual(self.heartbeat()["library"]["preferences"], {"encoder_direction": "reversed"})
        restarted = LibraryManager(self.product)
        self.assertEqual(restarted.preferences(), {"encoder_direction": "reversed"})

    def test_repeating_absolute_menu_preference_is_idempotent_and_results_are_copies(self):
        self.save()
        self.action("open")
        first = self.action("set_preferences", encoder_direction="reversed")
        with patch.object(self.manager.store, "_write") as write:
            again = self.action("set_preferences", encoder_direction="reversed")
        write.assert_not_called()
        self.assertEqual(first["library"]["version"], again["library"]["version"])
        self.assertEqual(again["preference_change"]["before"], again["preference_change"]["after"])
        again["library"]["preferences"]["encoder_direction"] = "forward"
        again["preferences"]["encoder_direction"] = "forward"
        self.manager.snapshot()["preferences"]["encoder_direction"] = "forward"
        self.assertEqual(self.manager.preferences(), {"encoder_direction": "reversed"})

    def test_preference_action_rejects_app_fields_unknown_values_and_stale_device_views(self):
        saved = self.save()
        opened = self.action("open")["library"]
        for extra in ({"favorite": True}, {"entry_id": saved["revision"]}, {"tab": "trash"}, {"code": "x"}):
            with self.subTest(extra=extra), self.assertRaises(AgentError):
                self.action("set_preferences", encoder_direction="reversed", **extra)
        for value in (True, -1, "reverse", "toggle", None):
            with self.subTest(value=value), self.assertRaises(AppLibraryError):
                self.action("set_preferences", encoder_direction=value)
        with self.assertRaises(AgentError):
            self.action("favorite", saved["revision"], favorite=True, encoder_direction="reversed")
        self.assertEqual(self.manager.preferences(), {"encoder_direction": "forward"})
        packet = {"action": "set_preferences", "encoder_direction": "reversed",
                  "view_id": opened["id"], "version": opened["version"]}
        self.product.library_action(packet, device=True)
        with self.assertRaisesRegex(AgentError, "refreshed"):
            self.product.library_action({**packet, "encoder_direction": "forward"}, device=True)
        with self.assertRaisesRegex(AgentError, "refreshed"):
            self.product.library_action({"action": "trash", "entry_id": saved["revision"],
                                        "view_id": opened["id"], "version": opened["version"]}, device=True)
        self.assertFalse(self.manager.store.list_items()[0]["trashed"])
        self.assertEqual(self.manager.preferences(), {"encoder_direction": "reversed"})

    def test_failed_preference_write_does_not_claim_saved_or_update_view(self):
        opened = self.action("open")["library"]
        with patch.object(self.manager.store, "set_encoder_direction", side_effect=OSError("synthetic storage failure")):
            with self.assertRaises(OSError):
                self.action("set_preferences", encoder_direction="reversed")
        self.assertEqual(self.manager.preferences(), {"encoder_direction": "forward"})
        self.assertEqual(self.manager.view["version"], opened["version"])


if __name__ == "__main__":
    unittest.main()
