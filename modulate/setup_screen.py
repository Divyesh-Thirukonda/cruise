"""Local, dismissible connection guidance; usable without a model or companion."""
from __future__ import annotations

import math
import re

from .deployment import CONNECT_HOST, CONNECT_URL


def setup_address_lines(address, port=None):
    """Keep every address character; IPv6 wraps at a colon on the mini display."""
    text = str(address)
    if port is not None:
        text = f"[{text}]:{port}" if ":" in text else f"{text}:{port}"
    lines = []
    while len(text) > 26:
        boundary = text.rfind(":", 1, 26) + 1 or 26
        lines.append(text[:boundary])
        text = text[boundary:]
    return lines + [text]


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

    def update(self, *, enrolled, fresh, host, now, wall, enrollment_setup=None):
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
            card = (self._enrollment_card(enrollment_setup) if not enrolled else None)
            card = card or self._local_card(reason, host, enrolled, fresh)
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
    def _enrollment_card(setup):
        """Render only the trusted local bootstrap service, never a host offer."""
        if type(setup) is not dict:
            return None
        if setup.get("completed"):
            return {"kind": "guide", "title": "Connecting to your Mac", "lines": [
                "Device details saved.", "Keep Modulate Studio open.", "Checking the connection..."],
                "action": "next", "connect_url": CONNECT_URL}
        if not setup.get("address") and setup.get("available") is True:
            return {"kind": "guide", "title": "Connect to your network", "lines": [
                "Use configured Wi-Fi", "or plug in Ethernet.", "Put your Mac on that network.",
                "A checks the network again."], "action": "open_enrollment", "connect_url": CONNECT_URL}
        if setup.get("available") is not True:
            return {"kind": "guide", "title": "Setup unavailable", "lines": [
                "Restart your device.", "If setup stays unavailable,", "ask for a software update."],
                "action": "next", "connect_url": CONNECT_URL}
        address = str(setup.get("address") or "No network address")
        pending = setup.get("pending")
        if type(pending) is dict and re.fullmatch(r"[0-9a-f]{32}", str(pending.get("id", ""))):
            return {"kind": "enrollment_confirm", "id": pending["id"], "title": "Link this Mac?",
                    "host_address": str(pending.get("host_address", "")),
                    "lines": [str(pending.get("host_address", "")), "Match request on your Mac:",
                              pending["id"][-8:].upper(), "Only approve your request."],
                    "action": "confirm_enrollment", "connect_url": CONNECT_URL}
        code, fingerprint = setup.get("code"), setup.get("fingerprint")
        if (type(code) is str and re.fullmatch(r"[0-9]{8}", code)
                and type(fingerprint) is str and re.fullmatch(r"[0-9a-f]{20}", fingerprint)):
            return {"kind": "enrollment_code", "title": "Mac setup details", "lines": [],
                    "address": address, "port": setup.get("port", 8790), "fingerprint": fingerprint,
                    "code": code, "action": "open_enrollment", "connect_url": CONNECT_URL}
        return {"kind": "guide", "title": "Set up on your Mac", "lines": [
            CONNECT_HOST, "/connect/setup", "A shows your device details.", "Mac + gadget: same Wi-Fi"],
            "action": "open_enrollment", "connect_url": CONNECT_URL}

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
        return "start_pairing" if host.get("paired") is False else "create_browser_code" if status.get("remote_enabled") is True else "next"

    def _local_card(self, reason, host, enrolled, fresh):
        if not enrolled:
            title = "Set up Modulate"
            lines = (["Open on your computer:", CONNECT_HOST, "/connect", "Follow the setup guide."] if self.page == 0 else
                     ["Set up on your Mac first.", "No device shell is needed.", "Use the device setup guide."])
            action = "next"
        elif not fresh:
            title = "Reconnect your Mac"
            lines = (["Keep your Mac awake.", "Check Wi-Fi on both.", "Retrying connection..."] if self.page == 0 else
                     ["Setup guide:", CONNECT_HOST, "/connect", "Resume setup on your Mac."])
            action = "next"
        else:
            title = "Link your computer" if reason == "pairing" else "Connection setup"
            action = self._action(host)
            if action == "create_browser_code":
                lines = [CONNECT_HOST, "/connect", "on your phone or Mac.", "A shows a one-use code."]
            elif action == "start_pairing":
                lines = ["Browser connected." if (host.get("setup_status") or {}).get("browser_count") else "Mac companion found.",
                         "Continue pairing on Mac.", "A shows a comparison code.", "Compare before approving."]
            else:
                lines = ["Your Mac is linked.", "Finish website setup", "with your setup agent."]
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
