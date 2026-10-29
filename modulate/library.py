"""Trusted library UI and lifecycle; saved source never gains extra authority."""
from __future__ import annotations

import copy
import re
import time
import uuid

from .agent import AgentError, digest
from .app_library import AppLibrary, AppLibraryError
from .game_runtime import verify


class LibraryManager:
    def __init__(self, product, *, clock=time.time):
        self.product, self.clock = product, clock
        self.store = None
        self.error = None
        self.view = {"id": uuid.uuid4().hex, "version": 0, "open": False,
                     "tab": "all", "selected_id": None}
        self.confirmation = None
        self.launching = set()
        self._preferences = {"encoder_direction": "forward"}
        try:
            self.store = AppLibrary(product.directory / "library")
            self._preferences = self.store.preferences()
            self.store.import_active(product.active)
            self.store.import_history(product.directory / "requests")
        except (OSError, ValueError) as error:
            self.error = str(error)[:240]

    def protected(self):
        product = self.product
        values = {product.revision}
        values.add(((product.active or {}).get("previous") or {}).get("revision"))
        if product.pending and product.pending.get("phase") not in {"abort", "confirmed"}:
            values.add(product.pending.get("revision"))
        return (values - {None}) | self.launching

    def available(self):
        if self.store is None:
            raise AgentError("App library unavailable: " + (self.error or "storage could not open"))

    def entries(self):
        self.available()
        protected = self.protected()
        items = self.store.list_items("all") + self.store.list_items("trash")
        def display_title(title):
            return " ".join("".join(character if character.isprintable() else " "
                                    for character in title).split()) or "Untitled app"
        return [{**item, "title": display_title(item["title"]), "active": item["id"] == self.product.revision,
                 "protected": item["id"] in protected} for item in items]

    def _expire(self):
        if self.confirmation and self.confirmation["expires_at"] <= self.clock():
            self.confirmation = None
            self.view["version"] += 1

    def preferences(self):
        """Cheap, owned context for the agent; catalogue enumeration is separate."""
        return dict(self._preferences)

    def device_state(self):
        self._expire()
        try:
            items = self.entries()
        except (OSError, ValueError, AgentError) as error:
            return {**self.view, "preferences": self.preferences(), "selected_id": None, "entries": [], "purge_confirmation": None,
                    "notice": str(error)[:120]}
        tab = self.view["tab"]
        items = [item for item in items if (item["trashed"] if tab == "trash" else
                 not item["trashed"] and (tab != "favorites" or item["favorite"]))]
        ids = {item["id"] for item in items}
        if self.view["selected_id"] not in ids:
            selected = items[0]["id"] if items else None
            if selected != self.view["selected_id"]:
                self.view.update(selected_id=selected, version=self.view["version"] + 1)
        fields = ("id", "title", "kind", "favorite", "trashed", "active", "protected")
        return {**self.view, "preferences": self.preferences(), "entries": [{key: item[key] for key in fields} for item in items],
                "purge_confirmation": copy.deepcopy(self.confirmation)}

    def snapshot(self):
        try:
            items = self.entries()
        except (OSError, ValueError, AgentError) as error:
            return {"items": [], "view": self.device_state(), "preferences": self.preferences(), "purge_confirmation": None,
                    "error": str(error)[:240]}
        view = self.device_state()
        return {"items": items, "view": view, "preferences": self.preferences(),
                "purge_confirmation": view["purge_confirmation"], "error": self.error}

    def note_activation(self, record):
        if not record:
            return
        self.view.update(open=False, selected_id=record["revision"], version=self.view["version"] + 1)
        self.confirmation = None
        try:
            self.available()
            self.store.record_activation(record)
            self.error = None
        except (OSError, ValueError, AgentError) as error:
            # A confirmed device activation stays authoritative if archival fails.
            self.error = str(error)[:240]

    def selected(self):
        return self.view["selected_id"] if self.view["open"] else self.product.revision

    def call(self, data, *, origin="web"):
        with self.product.lock:
            self.available()
            self._expire()
            allowed = {"action", "entry_id", "tab", "favorite", "confirmation_id", "view_id", "version", "encoder_direction"}
            if type(data) is not dict or set(data) - allowed:
                raise AgentError("Invalid library action")
            action = data.get("action")
            entry_id = None
            actions = {"list", "open", "close", "select", "tab", "favorite", "trash", "restore",
                       "launch", "purge", "confirm_purge", "cancel_purge", "set_preferences"}
            if type(action) is not str or action not in actions:
                raise AgentError("Unknown library action")
            if action != "set_preferences" and "encoder_direction" in data:
                raise AgentError("Encoder direction belongs to library preferences")
            if origin == "agent" and action == "confirm_purge":
                raise AgentError("Permanent deletion needs a direct human confirmation")
            if origin == "device" and (not self.view["open"] or data.get("view_id") != self.view["id"]
                    or type(data.get("version")) is not int or data["version"] != self.view["version"]):
                raise AgentError("Library changed; use the refreshed menu")
            if action not in {"list", "close", "cancel_purge"}:
                self.product.check_request_access()
            if self.product.running and origin in {"web", "device"} and action not in {"list", "close", "cancel_purge"}:
                raise AgentError("Finish or cancel the current request before changing the library")
            if action == "set_preferences":
                if set(data) - {"action", "encoder_direction", "view_id", "version"}:
                    raise AgentError("Library preferences cannot change app actions")
                before = self.preferences()
                after = self.store.set_encoder_direction(data.get("encoder_direction"))
                self._preferences = after
                if before != after:
                    # A new version invalidates queued selection/delete actions
                    # made under the previous navigation setting.
                    self.view["version"] += 1
                return {"library": self.device_state(), "preferences": self.preferences(),
                        "preference_change": {"before": before, "after": self.preferences(), "saved": True},
                        "changed_id": None}
            if action in {"open", "tab"}:
                tab = data.get("tab", "all")
                if type(tab) is not str or tab not in {"all", "favorites", "trash"}:
                    raise AgentError("Unknown library tab")
                self.view.update(tab=tab)
                if action == "open":
                    self.view.update(id=uuid.uuid4().hex, open=True, selected_id=self.product.revision)
                self.confirmation = None
            elif action in {"close", "cancel_purge"}:
                self.confirmation = None
                if action == "close":
                    self.view["open"] = False
            elif action != "list":
                entry_id = data.get("entry_id", self.selected())
                if type(entry_id) is not str or re.fullmatch(r"[0-9a-f]{64}", entry_id) is None:
                    raise AgentError("Choose an app from the library first")
                record = self.store.get_record(entry_id, include_trashed=True)
                item = next(item for item in self.entries() if item["id"] == entry_id)
                if action == "select":
                    if entry_id not in {item["id"] for item in self.device_state()["entries"]}:
                        raise AgentError("That app is not in the current library tab")
                    self.view["selected_id"] = entry_id
                    self.confirmation = None
                elif action == "favorite":
                    if type(data.get("favorite")) is not bool:
                        raise AgentError("favorite must be true or false")
                    self.store.set_favorite(entry_id, data["favorite"])
                elif action == "trash":
                    self.store.trash(entry_id)
                    self.confirmation = None
                elif action == "restore":
                    self.store.restore(entry_id)
                    self.confirmation = None
                elif action == "purge":
                    if not item["trashed"]:
                        raise AgentError("Move the app to Trash before deleting it forever")
                    if entry_id in self.protected():
                        raise AgentError("This version is still active or needed for rollback. Open another app first.")
                    self.confirmation = {"id": uuid.uuid4().hex, "entry_id": entry_id,
                                         "title": item["title"], "expires_at": self.clock() + 120}
                    if origin == "agent":
                        question = f'Delete “{item["title"]}” forever? Say yes to permanently delete it, or no to keep it in Trash.'
                        self.product._question(question, kind="library_purge")
                        self.product.clarification["library_confirmation"] = copy.deepcopy(self.confirmation)
                        self.product.agent.clarification = question
                elif action == "confirm_purge":
                    pending = self.confirmation
                    if (not pending or pending["entry_id"] != entry_id
                            or data.get("confirmation_id") != pending["id"]):
                        raise AgentError("Delete confirmation expired or changed; start again from Trash")
                    if entry_id in self.protected():
                        raise AgentError("This version is still active or needed for rollback")
                    # Delete the exact historical source/check copies too. Trace
                    # events remain diagnostics; import tombstones prevent revival.
                    # Keep the durable library copy until cleanup succeeds so an
                    # I/O failure can be retried with this same confirmation.
                    for suffix in (".json", ".checks.json"):
                        (self.product.directory / "requests" / (entry_id + suffix)).unlink(missing_ok=True)
                    self.store.purge(entry_id, protected=self.protected())
                    self.confirmation = None
                elif action == "launch":
                    if item["trashed"]:
                        raise AgentError("Restore this app from Trash before opening it")
                    if origin != "agent":
                        result = self.product.request("Open saved app “" + record["package"]["title"] + "”.",
                                                      _library_entry=entry_id)
                        return {**result, "library": self.device_state()}
                    # Release the Product lock while verification / device ack run.
                    launch = entry_id
                self.view["version"] += 1
            if action != "launch" or origin != "agent":
                if action != "list":
                    self.view["version"] += 1
                view = self.device_state()
                return {"library": view, "items": self.entries(), "changed_id": entry_id,
                        "purge_confirmation": copy.deepcopy(self.confirmation)}
        result = self.launch(launch)
        return result

    def human_reply(self, confirmation, reply):
        normalized = re.sub(r"[^a-z ]", "", reply.lower()).strip()
        if normalized not in {"yes", "yes please", "yes delete it", "delete it", "confirm", "confirm delete"}:
            self.call({"action": "cancel_purge"}, origin="voice")
            return "Kept it in Trash."
        self.call({"action": "confirm_purge", "entry_id": confirmation["entry_id"],
                   "confirmation_id": confirmation["id"]}, origin="voice")
        return "Deleted “" + confirmation["title"] + "” from your library."

    def launch(self, entry_id):
        with self.product.lock:
            self.available()
            self.product.check_request_access()
            if self.product.agent.cancelled.is_set():
                raise AgentError("Request cancelled")
            if not self.product.connected():
                raise AgentError("Controller disconnected before opening the saved app")
            record = self.store.get_record(entry_id)
            package = record["package"]
            base = self.product.revision
            manifest = digest(self.product.capabilities())
            self.product.progress.update(phase="checking", title="Checking saved app", tool="app_library")
            self.launching.add(entry_id)
        try:
            report = verify(package) if package["kind"] == "game" else self.product.verify_control(package)
            report = {**report, "candidate_id": entry_id, "manifest_revision": manifest}
            with self.product.lock:
                self.product.check_request_access()
                if self.product.agent.cancelled.is_set():
                    raise AgentError("Request cancelled")
                if digest(self.product.capabilities()) != manifest:
                    raise AgentError("Connected controls changed while checking the saved app")
                if not report["passed"]:
                    raise AgentError("Saved app did not pass current checks: " + str(report.get("errors", []))[:220])
                self.product.progress.update(phase="activating", title="Opening saved app")
            with self.product.lock:
                self.store.get_record(entry_id)
                already_active = base == entry_id and self.product.revision == entry_id and self.product.device_revision == entry_id
            result = ({"activated": True, "already_active": True, "device_acknowledged": True,
                       "revision": entry_id, "kind": package["kind"], "title": package["title"]}
                      if already_active else self.product.activate(package, report, base_revision=base))
            with self.product.lock:
                self.view.update(open=False, version=self.view["version"] + 1)
                self.confirmation = None
            return result
        finally:
            with self.product.lock:
                self.launching.discard(entry_id)
