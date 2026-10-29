"""Local, dismissible connection guidance; usable without a model or companion."""
from __future__ import annotations

import math
import re

CONNECT_URL = "https://divy.live/connect"


class SetupScreen:
    def __init__(self, started):
        self.started = started
        self.reason = None
        self.dismissed = False
        self.dismissed_offer = None
        self.force = False
        self.page = 0
        self.buttons_released = False
        self.identity = None

    def wake(self):
        if self.reason:
            self.dismissed = False
            self.page = 0

    def update(self, *, enrolled, fresh, host, now, wall):
        reason = ("enrollment" if not enrolled else "offline" if not fresh and now - self.started >= 8
                  else "pairing" if fresh and host.get("paired") is False else None)
        # A recovered paired connection ends the episode. Dismissal never persists
        # across a process start, and an outage cannot erase a stored application.
        if fresh and host.get("paired") is True:
            self.dismissed = False
        self.reason = reason
        offer = self._offer(host.get("setup"), fresh, wall)
        if offer and offer["id"] != self.dismissed_offer:
            card = dict(offer)
            card["action"] = "next" if offer["kind"] == "browser_code" else self._action(host)
        elif (reason and not self.dismissed) or self.force:
            card = self._local_card(reason, host, enrolled, fresh)
        else:
            self.identity = None
            self.buttons_released = False
            return None
        identity = (card.get("id"), reason, self.page, card.get("code"), card["action"])
        if identity != self.identity:
            self.identity = identity
            self.buttons_released = False
        return card

    @staticmethod
    def _offer(offer, fresh, wall):
        if not fresh or type(offer) is not dict:
            return None
        if (type(offer.get("id")) is not str or not re.fullmatch(r"[0-9a-f]{32}", offer["id"])
                or offer.get("kind") not in {"guide", "browser_code"}
                or type(offer.get("expires_at")) not in (int, float)
                or not math.isfinite(offer["expires_at"]) or not wall < offer["expires_at"] <= wall + 600
                or offer.get("connect_url") != CONNECT_URL):
            return None
        title, lines = offer.get("title"), offer.get("lines")
        if type(title) is not str or len(title) > 40 or not title.isprintable() or type(lines) is not list or len(lines) > 4:
            return None
        if any(type(line) is not str or len(line) > 60 or not line.isprintable() for line in lines):
            return None
        if offer["kind"] == "browser_code" and (type(offer.get("code")) is not str
                                               or re.fullmatch(r"[0-9]{8}", offer["code"]) is None):
            return None
        return {key: offer[key] for key in ("id", "kind", "title", "lines", "connect_url", "expires_at", "code") if key in offer}

    @staticmethod
    def _action(host):
        status = host.get("setup_status") or {}
        if status.get("remote_enabled") is True and not status.get("browser_count"):
            return "create_browser_code"
        return "start_pairing" if host.get("paired") is False else "create_browser_code" if status.get("remote_enabled") is True else "next"

    def _local_card(self, reason, host, enrolled, fresh):
        if not enrolled:
            title = "Set up Modulate"
            lines = (["Open on your computer:", "divy.live/connect", "Follow the setup guide."] if self.page == 0 else
                     ["Start the Mac companion.", "Enroll this Pi once.", "Then restart Modulate."])
            action = "next"
        elif not fresh:
            title = "Reconnect your Mac"
            lines = (["Open Modulate Studio", "on your Mac. Check Wi-Fi", "on both. Retrying..."] if self.page == 0 else
                     ["Guide: divy.live/connect", "Keep the companion open.", "Your saved app is safe."])
            action = "next"
        else:
            title = "Link your computer" if reason == "pairing" else "Connection setup"
            action = self._action(host)
            if action == "create_browser_code":
                lines = ["Open divy.live/connect", "on your phone or Mac.", "A shows a one-use code."]
            elif action == "start_pairing":
                lines = ["Browser connected." if (host.get("setup_status") or {}).get("browser_count") else "Mac companion found.",
                         "A starts Mac pairing.", "Confirm on the next screen."]
            else:
                lines = ["Mac pairing is ready.", "Local Studio: on your Mac", "127.0.0.1:8787"]
        return {"kind": "guide", "title": title, "lines": lines, "action": action, "connect_url": CONNECT_URL}

    def buttons(self, card, a, b, valid):
        if not valid:
            self.buttons_released = False
            return None
        if not a and not b:
            self.buttons_released = True
            return None
        # Both buttons remain push-to-talk, never pairing approval or dismissal.
        if a and b or not self.buttons_released:
            return None
        self.buttons_released = False
        if b:
            self.dismissed = True
            self.dismissed_offer = card.get("id")
            self.force = False
            return "dismiss"
        if card["action"] == "next":
            self.page = (self.page + 1) % 2
            if card.get("id"):
                self.dismissed_offer = card["id"]
                self.force = True
            return "next"
        return card["action"]
