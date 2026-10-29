"""Synthetic library navigation and device transport tests; no GPIO/model calls."""
import copy
import queue
import time
import unittest

from modulate.controls import neutral_input
from modulate.device_transport import TransportError
from modulate.library_screen import LibraryScreen, validate_view
from tests import test_device as device_fixtures


def entry(identifier="a", **kwargs):
    return {"id": identifier * 64, "title": "Kart " + identifier, "kind": "game",
            "favorite": False, "trashed": False, "active": False, **kwargs}


def view(**kwargs):
    return {"id": "1" * 32, "version": 1, "open": True, "tab": "all",
            "selected_id": "a" * 64, "entries": [entry(), entry("b")], **kwargs}


class LibraryScreenTests(unittest.TestCase):
    def setUp(self):
        self.screen = LibraryScreen()
        self.update(view())

    def update(self, value, *, fresh=True, wall=1000):
        return self.screen.update(value, fresh=fresh, wall=wall)

    def inputs(self, now=10, **kwargs):
        return self.screen.inputs({**neutral_input(), **kwargs}, now=now)

    def press(self, key="button_a"):
        self.inputs()
        return self.inputs(**{key: True})

    def acknowledge(self, action, **kwargs):
        state = {**copy.deepcopy(self.screen.view), "version": self.screen.view["version"] + 1, **kwargs}
        self.screen.complete(action, {"library": state}, wall=1000)

    def test_bounded_metadata_rejects_code_shaped_ids_duplicates_and_bad_types(self):
        for update in ({"id": "../apps"}, {"version": True}, {"entries": [entry(), entry()]},
                       {"selected_id": "c" * 64}, {"entries": [entry(title="Bad\nTitle")]},
                       {"entries": [entry(favorite=1)]}, {"entries": [entry()] * 513}):
            with self.subTest(update=update):
                self.assertIsNone(validate_view(view(**update), 1000))
        self.assertIsNotNone(validate_view(view(), 1000))

    def test_optional_controls_cannot_act_until_released_after_open(self):
        self.inputs(button_a=True, encoder_pressed=True)
        self.inputs(joystick_y=1)
        self.assertEqual(self.screen.mode, "list")
        self.assertEqual(self.screen.selected_id, "a" * 64)
        self.press()
        self.assertEqual(self.screen.mode, "actions")
        self.assertIsNone(self.inputs(button_a=True))
        self.assertIsNone(self.screen.pending)

    def test_immediate_highlight_sends_exact_selection_then_waits_for_ack(self):
        self.inputs()
        action = self.inputs(encoder_delta=1)
        self.assertEqual(action, {"action": "select", "entry_id": "b" * 64,
                                  "view_id": "1" * 32, "version": 1})
        self.assertEqual(self.screen.selected_id, "b" * 64)
        self.assertIsNone(self.inputs(encoder_delta=1))
        self.press()
        self.assertEqual(self.screen.mode, "list")
        self.acknowledge(action, selected_id="b" * 64)
        self.press()
        self.assertEqual(self.screen.mode, "actions")
        launch = self.press()
        self.assertEqual(launch["action"], "launch")
        self.assertEqual(launch["entry_id"], "b" * 64)
        self.assertEqual(launch["version"], 2)

    def test_tab_picker_is_accessible_using_only_knob_and_two_buttons(self):
        self.inputs(encoder_delta=-1)
        self.press()
        self.assertEqual(self.screen.mode, "tabs")
        self.inputs(encoder_delta=1)
        action = self.press()
        self.assertEqual(action["action"], "tab")
        self.assertEqual(action["tab"], "favorites")
        self.acknowledge(action, tab="favorites", selected_id=None)
        self.assertEqual(self.screen.entries(), [])
        self.assertEqual(self.screen.render().size, (240, 135))

    def test_favorite_and_trash_require_item_actions_not_a_game_button_shortcut(self):
        self.press()
        self.inputs(encoder_delta=1)
        action = self.press()
        self.assertEqual(action["action"], "favorite")
        self.assertTrue(action["favorite"])
        self.acknowledge(action, entries=[entry(favorite=True), entry("b")])
        self.assertEqual(self.screen.mode, "list")
        self.press()
        self.inputs(encoder_delta=2)
        action = self.press()
        self.assertEqual(action["action"], "trash")
        self.acknowledge(action, entries=[entry(trashed=True), entry("b")], selected_id="b" * 64)
        self.assertEqual([item["id"] for item in self.screen.entries()], ["b" * 64])

    def test_permanent_delete_needs_host_nonce_and_release_fresh_press(self):
        self.update(view(version=2, tab="trash", entries=[entry(trashed=True)]))
        self.press()
        self.inputs(encoder_delta=1)
        action = self.press()
        self.assertEqual(action["action"], "purge")
        confirmation = {"id": "c" * 32, "entry_id": "a" * 64, "title": "Kart a", "expires_at": 1120}
        self.acknowledge(action, purge_confirmation=confirmation)
        self.assertEqual(self.screen.mode, "confirm")
        self.assertIsNone(self.inputs(button_a=True))
        self.assertIsNone(self.inputs(button_a=True, now=30))
        confirm = self.press()
        self.assertEqual(confirm["action"], "confirm_purge")
        self.assertEqual(confirm["confirmation_id"], "c" * 32)
        self.assertEqual(confirm["entry_id"], "a" * 64)

    def test_expired_confirmation_never_confirms_and_b_cancels_without_delete(self):
        confirmation = {"id": "c" * 32, "entry_id": "a" * 64, "title": "Kart a", "expires_at": 1010}
        self.update(view(version=2, purge_confirmation=confirmation))
        self.assertEqual(self.press("button_b")["action"], "cancel_purge")
        self.update(view(version=3, purge_confirmation=confirmation), wall=1011)
        self.assertEqual(self.screen.mode, "list")
        self.assertIsNone(self.inputs(button_a=True))

    def test_stale_response_cannot_replace_newer_voice_opened_view(self):
        action = self.inputs(encoder_delta=1)
        self.update(view(id="2" * 32, selected_id="a" * 64))
        self.screen.complete(action, {"library": view(version=2, open=False)}, wall=1000)
        self.assertEqual(self.screen.view["id"], "2" * 32)
        self.assertTrue(self.screen.visible)
        self.update(view(id="2" * 32, version=4))
        self.update(view(id="2" * 32, version=2, open=False))
        self.assertTrue(self.screen.visible)
        self.update(view(version=99, open=False))
        self.assertEqual(self.screen.view["id"], "2" * 32)
        self.assertTrue(self.screen.visible)

    def test_protected_rollback_entry_can_restore_but_has_no_purge_action(self):
        self.update(view(version=2, tab="trash", entries=[entry(trashed=True, protected=True)]))
        self.press()
        self.assertEqual([action for action, _ in self.screen.choices()], ["restore", "back"])
        self.assertEqual(self.screen.render().size, (240, 135))

    def test_offline_and_malformed_views_disable_actions_but_allow_local_close(self):
        self.update(view(), fresh=False)
        self.assertIsNone(self.press())
        self.assertEqual(self.screen.mode, "list")
        self.press("button_b")
        self.assertFalse(self.screen.visible)
        self.update(view())
        self.assertFalse(self.screen.visible)
        self.update(view(id="2" * 32))
        self.assertTrue(self.screen.visible)
        self.update(view(version="bad"))
        self.assertFalse(self.screen.fresh)
        self.assertIsNone(self.press())

    def test_uncertain_delivery_does_not_claim_saved_or_automatically_retry(self):
        action = self.inputs(encoder_delta=1)
        self.screen.complete(action, None, wall=1000, error=True)
        self.assertIsNone(self.screen.pending)
        self.assertIn("Not confirmed", self.screen.error)
        self.assertIsNone(self.inputs())

    def test_joystick_repeat_survives_selection_ack_but_waits_for_initial_center(self):
        self.inputs(joystick_y=1, now=10)
        self.assertEqual(self.screen.selected_id, "a" * 64)
        self.inputs(now=11)
        action = self.inputs(joystick_y=1, now=12)
        self.acknowledge(action, selected_id="b" * 64)
        self.assertIsNone(self.inputs(joystick_y=1, now=12.1))
        self.inputs(joystick_y=1, now=12.5)
        self.assertEqual(self.screen.index, 0)

    def test_largest_catalogue_remains_bounded_and_every_row_can_be_reached(self):
        entries = [{**entry(), "id": format(index, "064x")} for index in range(512)]
        self.update(view(version=2, entries=entries, selected_id=entries[-2]["id"]))
        action = self.inputs(encoder_delta=1)
        self.assertEqual(action["entry_id"], entries[-1]["id"])
        self.assertEqual(self.screen.render().size, (240, 135))

    def test_reverse_preference_changes_only_knob_direction_and_preserves_sample(self):
        self.update(view(version=2, selected_id="b" * 64, preferences={"encoder_direction": "reversed"}))
        sample = {**neutral_input(), "encoder_delta": 1}
        original = dict(sample)
        action = self.screen.inputs(sample, now=10)
        self.assertEqual(action["entry_id"], "a" * 64)
        self.assertEqual(sample, original)
        self.acknowledge(action, selected_id="a" * 64)
        self.inputs(encoder_delta=1)  # Header remains reachable by reversed knob.
        self.assertEqual(self.screen.index, 0)
        self.inputs()  # Center stick before using its normal direction.
        self.inputs(joystick_y=1, now=11)
        self.assertEqual(self.screen.index, 1)
        self.assertEqual(self.screen.selected_id, "a" * 64)

    def test_reverse_applies_before_joystick_mix_and_also_works_in_action_menus(self):
        self.update(view(version=2, preferences={"encoder_direction": "reversed"}))
        self.inputs()
        self.assertIsNone(self.inputs(encoder_delta=1, joystick_y=1))
        self.assertEqual(self.screen.index, 1)  # Reversed knob -1, stick +1.
        self.press()
        self.assertEqual(self.screen.mode, "actions")
        self.inputs(encoder_delta=1)
        self.assertEqual(self.screen.choices()[self.screen.index][0], "back")
        self.inputs(encoder_delta=-1)
        self.assertEqual(self.screen.choices()[self.screen.index][0], "launch")

    def test_legacy_preference_defaults_forward_and_invalid_preferences_disable_actions(self):
        self.assertEqual(self.screen.view["preferences"], {"encoder_direction": "forward"})
        for prefs in (None, {}, {"encoder_direction": True}, {"encoder_direction": "toggle"},
                      {"encoder_direction": "reversed", "global": True}):
            with self.subTest(prefs=prefs):
                self.assertIsNone(validate_view(view(preferences=prefs), 1000))
        self.update(view(version=2, preferences={"encoder_direction": "toggle"}))
        self.assertFalse(self.screen.fresh)
        self.assertIsNone(self.inputs(encoder_delta=1))

    def test_preference_update_needs_new_button_press_and_stale_view_cannot_undo_it(self):
        confirmation = {"id": "c" * 32, "entry_id": "a" * 64, "title": "Kart a", "expires_at": 1120}
        self.update(view(version=2, purge_confirmation=confirmation))
        self.inputs()
        self.update(view(version=3, purge_confirmation=confirmation, preferences={"encoder_direction": "reversed"}))
        self.assertIsNone(self.inputs(button_a=True))
        self.update(view(version=2, preferences={"encoder_direction": "forward"}))
        self.assertEqual(self.screen.view["preferences"], {"encoder_direction": "reversed"})
        action = self.press()
        self.assertEqual(action["action"], "confirm_purge")
        self.assertEqual(action["version"], 3)
        self.assertEqual(action["confirmation_id"], confirmation["id"])


class LibraryControllerTests(unittest.TestCase):
    def setUp(self):
        device_fixtures.ControllerTests.setUp(self)
        self.controller.host = {"paired": True, "library": view()}
        self.controller._library_card()
        self.controller.display_state = {"kind": "library"}

    def handle(self, **kwargs):
        return self.controller._handle_buttons({**neutral_input(), **kwargs}, time.monotonic())

    def test_menu_queues_without_network_and_consumes_control_inputs(self):
        self.handle()
        result = self.handle(encoder_delta=1, joystick_x=1)
        self.assertEqual(result, neutral_input())
        self.Companion.post.assert_not_called()
        action = self.controller.library_actions.get_nowait()
        self.assertEqual(action["entry_id"], "b" * 64)
        self.assertEqual(self.controller.encoder_pending, 0)

    def test_physical_actions_only_when_library_is_actually_visible_and_not_interrupted(self):
        self.handle()
        self.controller.build = {"job_id": "c" * 32}
        self.handle(encoder_delta=1, button_a=True)
        self.assertTrue(self.controller.library_actions.empty())
        self.controller.build = None
        self.controller.display_state = {"kind": "speaker"}
        self.handle(encoder_delta=1, button_a=True)
        self.assertTrue(self.controller.library_actions.empty())

    def test_ptt_chord_remains_available_inside_menu(self):
        self.buttons[0].current = self.buttons[1].current = False
        self.controller._handle_buttons(neutral_input(), 10)
        self.controller._handle_buttons(neutral_input(), 11)
        self.VoiceListener.request_ptt.assert_called_once()
        self.assertTrue(self.controller.library_actions.empty())

    def test_transport_failure_drops_queued_action_without_replay(self):
        self.handle(encoder_delta=1)
        self.Companion.post.side_effect = TransportError("Disconnected")
        self.controller._network_step()
        self.assertTrue(self.controller.library_actions.empty())
        self.assertIsNone(self.controller.library_screen.pending)
        self.assertIn("Not confirmed", self.controller.library_screen.error)
        self.assertEqual(self.Companion.post.call_args.args[0], "heartbeat")

    def test_heartbeat_input_is_neutral_even_if_an_earlier_encoder_delta_was_queued(self):
        self.controller.sample = {**neutral_input(), "button_a": True, "joystick_y": 1}
        self.controller.encoder_pending = 8
        self.Companion.post.return_value = {"paired": True, "library": view()}
        self.controller._network_step()
        self.assertEqual(self.Companion.post.call_args.args[1]["input"], neutral_input())

    def test_uncertain_action_delivery_is_not_replayed_on_the_next_heartbeat(self):
        self.handle(encoder_delta=1)
        self.Companion.post.side_effect = [{"paired": True, "library": view()}, TransportError("Timed out")]
        self.controller._network_step()
        self.assertEqual([call.args[0] for call in self.Companion.post.call_args_list], ["heartbeat", "library"])
        self.Companion.post.side_effect = None
        self.Companion.post.return_value = {"paired": True, "library": view()}
        self.Companion.post.reset_mock()
        self.controller._network_step()
        self.assertEqual([call.args[0] for call in self.Companion.post.call_args_list], ["heartbeat"])
        self.assertIn("Not confirmed", self.controller.library_screen.error)

    def test_close_requires_release_before_retained_game_can_receive_button(self):
        self.handle()
        self.handle(button_b=True)
        action = self.controller.library_actions.get_nowait()
        closed = view(version=2, open=False)
        self.controller.library_screen.complete(action, {"library": closed}, wall=time.time())
        self.controller.host["library"] = closed
        self.assertEqual(self.handle(button_b=True), neutral_input())
        self.assertEqual(self.handle(), neutral_input())
        self.assertTrue(self.handle(button_b=True)["button_b"])


if __name__ == "__main__":
    unittest.main()
