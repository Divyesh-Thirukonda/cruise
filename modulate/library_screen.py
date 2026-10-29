"""Trusted, voice-opened app library; navigation never runs generated code."""
from __future__ import annotations

import math
import re
from collections import deque

from PIL import Image, ImageDraw

from .rendering import font

TABS = ("all", "favorites", "trash")
TAB_NAMES = {"all": "All apps", "favorites": "Favorites", "trash": "Trash"}


def _identifier(value, length):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{%d}" % length, value) is not None


def _text(value, limit):
    return type(value) is str and 0 < len(value) <= limit and value.isprintable()


def validate_view(value, wall):
    """Accept bounded metadata only, never package code or arbitrary actions."""
    if (type(value) is not dict or not _identifier(value.get("id"), 32)
            or type(value.get("version")) is not int or not 0 <= value["version"] < 2**53
            or type(value.get("open")) is not bool or value.get("tab") not in TABS
            or type(value.get("entries")) is not list or len(value["entries"]) > 512):
        return None
    entries, seen = [], set()
    for entry in value["entries"]:
        if (type(entry) is not dict or not _identifier(entry.get("id"), 64)
                or entry["id"] in seen or not _text(entry.get("title"), 120)
                or not _text(entry.get("kind"), 24)
                or any(type(entry.get(flag)) is not bool for flag in ("favorite", "trashed", "active"))):
            return None
        seen.add(entry["id"])
        entries.append({key: entry[key] for key in ("id", "title", "kind", "favorite", "trashed", "active")})
        entries[-1]["protected"] = entry.get("protected") is True
    selected = value.get("selected_id")
    if selected is not None and selected not in seen:
        return None
    result = {key: value[key] for key in ("id", "version", "open", "tab")}
    preferences = value.get("preferences", {"encoder_direction": "forward"})
    if (type(preferences) is not dict or set(preferences) != {"encoder_direction"}
            or type(preferences["encoder_direction"]) is not str
            or preferences["encoder_direction"] not in {"forward", "reversed"}):
        return None
    result["preferences"] = dict(preferences)
    result.update(entries=entries, selected_id=selected)
    if _text(value.get("notice"), 160):
        result["notice"] = value["notice"]
    confirmation = value.get("purge_confirmation")
    if (type(confirmation) is dict and _identifier(confirmation.get("id"), 32)
            and confirmation.get("entry_id") in seen and _text(confirmation.get("title"), 120)
            and type(confirmation.get("expires_at")) in (int, float)
            and math.isfinite(confirmation["expires_at"])
            and wall < confirmation["expires_at"] <= wall + 300):
        result["purge_confirmation"] = {key: confirmation[key]
                                       for key in ("id", "entry_id", "title", "expires_at")}
    return result


class LibraryScreen:
    """Local highlight with version-bound host actions and release-to-act input."""

    def __init__(self):
        self.view = None
        self.fresh = False
        self.pending = None
        self.mode = "list"
        self.index = 0
        self.selected_id = None
        self.buttons_released = False
        self.stick_released = False
        self.stick_direction = 0
        self.repeat_at = 0.0
        self.dismissed = None
        self.error = None
        self.confirmation_id = None
        self.retired_views = deque(maxlen=64)

    def update(self, value, *, fresh, wall):
        was_fresh = self.fresh
        incoming = validate_view(value, wall) if fresh else None
        self.fresh = fresh and incoming is not None
        if incoming and incoming["id"] in self.retired_views:
            return self.visible
        if incoming is not None:
            old = self.view
            if old is None or incoming["id"] != old["id"] or incoming["version"] >= old["version"]:
                changed = old is None or (incoming["id"], incoming["version"]) != (old["id"], old["version"])
                new_view = old is None or incoming["id"] != old["id"]
                if new_view and old:
                    self.retired_views.append(old["id"])
                self.view = incoming
                if changed:
                    pending = self.pending
                    self.pending = None
                    self.error = None
                    self.selected_id = incoming["selected_id"]
                    if new_view or not old["open"] or old["tab"] != incoming["tab"]:
                        self.mode = "list"
                        self.interrupt()
                    elif (pending and pending["action"] in {"favorite", "trash", "restore"}
                          or self.mode == "actions" and old["selected_id"] != incoming["selected_id"]):
                        self.mode = "list"
                        self.interrupt()
                    self.index = self._entry_index() if self.mode == "list" else self.index
                    if self.mode == "actions" and self.entry() is None:
                        self.mode, self.index = "list", 0
                    if old and old["preferences"] != incoming["preferences"]:
                        self.interrupt()
                confirmation = incoming.get("purge_confirmation")
                if confirmation and confirmation["id"] != self.confirmation_id:
                    self.confirmation_id = confirmation["id"]
                    self.mode = "confirm"
                    self.interrupt()  # Opening/holding A can never confirm deletion.
                elif not confirmation and self.mode == "confirm":
                    self.mode, self.index = "list", self._entry_index()
                    self.confirmation_id = None
                    self.interrupt()
                if self.mode in {"tabs", "actions"}:
                    self.index = min(self.index, len(self.choices()) - 1)
        if not self.fresh and was_fresh:
            self.pending = None
            self.interrupt()
        if self.view and self.view.get("purge_confirmation", {}).get("expires_at", 0) <= wall:
            self.view.pop("purge_confirmation", None)
            if self.mode == "confirm":
                self.mode, self.index = "list", self._entry_index()
                self.confirmation_id = None
                self.interrupt()
        return self.visible

    @property
    def visible(self):
        return bool(self.view and self.view["open"] and self.view["id"] != self.dismissed)

    def interrupt(self):
        self.buttons_released = self.stick_released = False
        self.stick_direction = 0

    def entries(self):
        if not self.view:
            return []
        tab = self.view["tab"]
        return [entry for entry in self.view["entries"] if
                (entry["trashed"] if tab == "trash" else not entry["trashed"]
                 and (tab != "favorites" or entry["favorite"]))]

    def _entry_index(self):
        return next((index + 1 for index, entry in enumerate(self.entries())
                     if entry["id"] == self.selected_id), 0)

    def entry(self):
        return next((entry for entry in self.entries() if entry["id"] == self.selected_id), None)

    def choices(self):
        if self.mode == "tabs":
            return [(tab, TAB_NAMES[tab]) for tab in TABS]
        entry = self.entry()
        if self.mode == "actions" and entry:
            if entry["trashed"]:
                if entry["protected"]:
                    return [("restore", "Restore app"), ("back", "Back")]
                return [("restore", "Restore app"), ("purge", "Delete forever..."), ("back", "Back")]
            return [("launch", "Open app"), ("favorite", "Unfavorite" if entry["favorite"] else "Favorite"),
                    ("trash", "Move to Trash"), ("back", "Back")]
        return [("tabs", TAB_NAMES[self.view["tab"]] + " / change")]

    def _action(self, action, **kwargs):
        if self.pending or not self.fresh or not self.visible:
            return None
        payload = {"action": action, "view_id": self.view["id"], "version": self.view["version"], **kwargs}
        self.pending = payload
        self.error = None
        return payload

    def complete(self, action, result, *, wall, error=False):
        # A response from an older menu must never clear a newer action or reopen it.
        if self.pending != action:
            return
        self.pending = None
        if not error and type(result) is dict and "library" in result:
            self.update(result["library"], fresh=True, wall=wall)
        if error:
            self.error = "Not confirmed. Try again."
            self.mode, self.index = "list", self._entry_index()
        elif action["action"] in {"favorite", "trash", "restore"}:
            self.mode, self.index = "list", self._entry_index()
        if error or action["action"] != "select":
            self.interrupt()

    def inputs(self, sample, *, now, valid=True):
        if not self.visible:
            self.interrupt()
            return None
        a = sample.get("button_a") is True or sample.get("encoder_pressed") is True
        b = sample.get("button_b") is True
        if not valid or a and b:
            self.interrupt()
            return None
        if not a and not b:
            self.buttons_released = True
        elif self.buttons_released:
            self.buttons_released = False
            if b:
                if self.mode == "confirm":
                    return self._action("cancel_purge")
                if self.mode != "list":
                    self.mode, self.index = "list", self._entry_index()
                    return None
                if not self.fresh:
                    self.dismissed = self.view["id"]
                    return None
                return self._action("close")
            if not self.fresh or self.pending:
                return None
            if self.mode == "confirm":
                confirmation = self.view.get("purge_confirmation")
                if confirmation:
                    return self._action("confirm_purge", entry_id=confirmation["entry_id"],
                                        confirmation_id=confirmation["id"])
                return None
            if self.mode == "list":
                if self.index == 0:
                    self.mode, self.index = "tabs", TABS.index(self.view["tab"])
                elif self.entry():
                    self.mode, self.index = "actions", 0
                return None
            choice = self.choices()[self.index][0]
            if self.mode == "tabs":
                self.mode, self.index = "list", 0
                return self._action("tab", tab=choice)
            if choice == "back":
                self.mode, self.index = "list", self._entry_index()
                return None
            entry = self.entry()
            extras = {"favorite": not entry["favorite"]} if choice == "favorite" else {}
            return self._action(choice, entry_id=entry["id"], **extras)
        if not self.fresh or self.pending or self.mode == "confirm" or a or b:
            return None
        delta = sample.get("encoder_delta", 0)
        delta = max(-10, min(10, delta)) if type(delta) is int else 0
        if self.view["preferences"]["encoder_direction"] == "reversed":
            delta = -delta
        y = sample.get("joystick_y", 0)
        y = y if type(y) in (int, float) and math.isfinite(y) else 0
        direction = 1 if y > 0.55 else -1 if y < -0.55 else 0
        if not direction:
            self.stick_released, self.stick_direction = True, 0
        elif self.stick_released and (direction != self.stick_direction or now >= self.repeat_at):
            delta += direction
            self.repeat_at = now + (0.45 if direction != self.stick_direction else 0.18)
            self.stick_direction = direction
        if not delta:
            return None
        count = len(self.entries()) + 1 if self.mode == "list" else len(self.choices())
        self.index = (self.index + delta) % count
        if self.mode == "list" and self.index:
            self.selected_id = self.entries()[self.index - 1]["id"]
            if self.selected_id != self.view["selected_id"]:
                return self._action("select", entry_id=self.selected_id)
        return None

    def render(self):
        image = Image.new("RGB", (240, 135), "#101113")
        draw = ImageDraw.Draw(image)
        draw.text((8, 5), "MODULATE / LIBRARY", font=font(10), fill="#469DFF")
        if self.mode == "confirm":
            confirmation = self.view.get("purge_confirmation") or {}
            draw.text((8, 27), "Delete forever?", font=font(16), fill="#FF9F9F")
            draw.text((8, 55), confirmation.get("title", "App")[:28], font=font(12), fill="white")
            draw.text((8, 79), "This cannot be undone.", font=font(11), fill="#CCD5E0")
            footer = "A: delete forever   B: cancel"
        else:
            entries = self.entries()
            if self.mode == "list":
                rows = [TAB_NAMES[self.view["tab"]] + " / change tab"] + [
                    ("* " if item["favorite"] else "") + item["title"] + ("  [on]" if item["active"] else "")
                    for item in entries]
                title = f"{TAB_NAMES[self.view['tab']]}  {len(entries)}"
            else:
                rows = [label for _, label in self.choices()]
                title = "Choose a shelf" if self.mode == "tabs" else (self.entry() or {}).get("title", "App")
            draw.text((8, 23), title[:29], font=font(13), fill="white")
            start = max(0, min(self.index - 1, len(rows) - 3))
            for position, label in enumerate(rows[start:start + 3]):
                y = 46 + position * 21
                selected = start + position == self.index
                if selected:
                    draw.rounded_rectangle((5, y - 1, 235, y + 18), radius=4, fill="#193755")
                draw.text((10, y + 1), label[:32], font=font(11), fill="white" if selected else "#A6B0BC")
            if self.mode == "list" and not entries:
                draw.text((10, 75), "No apps on this shelf yet", font=font(11), fill="#A6B0BC")
            footer = ("Kept for active app / rollback" if self.mode == "actions" and
                      self.entry().get("protected") and self.entry()["trashed"] else
                      "Turn / stick   A: select   B: back")
        draw.line((8, 113, 232, 113), fill="#343A42")
        footer = ("Offline - B: close" if not self.fresh else "Saving..." if self.pending else
                  self.error or self.view.get("notice") or footer)
        draw.text((8, 119), footer[:38], font=font(9), fill="#A6B0BC")
        return image
