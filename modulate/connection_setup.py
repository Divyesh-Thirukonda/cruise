"""Trusted setup guidance; pairing credentials travel only to the enrolled Pi."""
from __future__ import annotations

import copy
import time
import uuid

from .agent import AgentError


CONNECT_URL = "https://divy.live/connect"
ACTIONS = ("status", "show", "start_pairing", "create_browser_code")
OFFER_SECONDS = 300


class ConnectionSetup:
    def __init__(self, product):
        self.product = product

    def brief(self):
        """Small non-secret device contract, independent of model/provider access."""
        product = self.product
        remote = product.remote_access.local_status() if product.remote_access else {}
        return {"paired_mac": bool(product._paired_session()),
                "remote_enabled": remote.get("enabled") is True,
                "browser_count": len(remote.get("browsers", [])), "connect_url": CONNECT_URL}

    def status(self):
        product = self.product
        brief = self.brief()
        session = product._paired_session()
        remote = product.remote_access.local_status() if product.remote_access else {}
        native = product.computer_status()
        permissions = native.get("permissions") or {}
        offer = product.setup_offer
        offer_id = offer["id"] if offer and offer["expires_at"] > time.time() else None
        display = product.telemetry.get("display", {})
        if type(display) is not dict:
            display = {}
        visible = bool(product.connected() and offer_id and display.get("kind") == "setup"
                       and display.get("offer_id") == offer_id)
        if not product.connected():
            instructions = ["Keep Modulate powered and on the companion's network.",
                            "Open Modulate Studio on the Mac and keep it running."]
        elif not brief["paired_mac"]:
            instructions = ["Start Mac pairing, then compare the code and press the small A button on Modulate.",
                            "Grant any required macOS permissions yourself on the Mac."]
        elif not brief["browser_count"] and brief["remote_enabled"]:
            instructions = ["Create a browser code on Modulate, then open divy.live/connect on your phone or computer.",
                            "Enter the code shown on the device and choose its access switches."]
        else:
            instructions = ["The Mac is paired. Use divy.live/connect to manage the existing device connection."]
        return {**brief, "device_connected": product.connected(), "companion_running": True,
                "pairing_expires_at": session.get("expires_at") if session else None,
                "native_permissions": {key: permissions.get(key) if type(permissions.get(key)) is bool else None
                                       for key in ("screen_recording", "accessibility")},
                "computer_paused": native.get("paused") is True,
                "display_status": {"offer_id": offer_id, "visible": visible},
                "permissions": dict(remote.get("permissions", {})),
                "instructions": instructions,
                "limits": ["Meta runs on the companion; an offline Pi shows local setup guidance without AI.",
                           "A browser controls this configured Mac/Pi hub, not the phone's own operating system.",
                           "Installing the companion, network enrollment and macOS permission grants still require the user."]}

    def device_offer(self):
        product = self.product
        offer = product.setup_offer
        if not offer or offer["expires_at"] <= time.time():
            product.setup_offer = None
            return None
        if offer["kind"] == "browser_code":
            remote = product.remote_access
            if (remote is None or not remote.pairing_active(offer["code"], offer["expires_at"])
                    or self.brief()["browser_count"] > offer["browser_count"]):
                product.setup_offer = None
                return None
        return copy.deepcopy(offer)

    def call(self, action):
        if type(action) is not str or action not in ACTIONS:
            raise AgentError("Unknown connection setup action")
        product = self.product
        with product.lock:
            if product.running:
                product.check_request_access()
            if action == "status":
                return self.status()
            if not product.connected():
                raise AgentError("The device is offline; keep the Pi and Mac companion powered and on the same network")
            brief = self.brief()
            if action == "start_pairing":
                if brief["paired_mac"]:
                    return {**self.status(), "pairing_started": False,
                            "instruction": "The Mac is already paired; its current grant is unchanged."}
                pairing = product.create_pairing()
                product.setup_offer = None
                return {**brief, "pairing_started": True, "expires_at": pairing["expires_at"],
                        "display_requested": True, "displayed": False,
                        "instruction": "Compare the pairing code in Studio with Modulate, then press the small A button on the device. The Mac is not authorized until that confirmation."}
            offer = {"kind": "guide", "id": uuid.uuid4().hex,
                     "expires_at": time.time() + OFFER_SECONDS, "title": "Connect your computer",
                     "lines": ["Open divy.live/connect", "A: continue setup", "B: not now"],
                     "connect_url": CONNECT_URL, "browser_count": brief["browser_count"]}
            if action == "create_browser_code":
                if not brief["remote_enabled"]:
                    raise AgentError("The public gateway is not configured. Open the Mac's local Studio to finish companion setup.")
                pairing = product.remote_access.create_pairing()
                offer.update(kind="browser_code", code=pairing["code"], expires_at=pairing["expires_at"],
                             title="Connect this browser", lines=["Open divy.live/connect", "Enter this one-use code", "B: not now"])
            elif not brief["remote_enabled"]:
                offer["lines"] = ["On Mac: 127.0.0.1:8787", "A: pair this Mac", "B: not now"]
            product.setup_offer = offer
            return {**brief, "display_requested": True, "displayed": False, "expires_at": offer["expires_at"],
                    "instruction": ("Enter the code on Modulate's screen at divy.live/connect and choose the access switches."
                                    if offer["kind"] == "browser_code" else
                                    "Setup guidance is ready for the device screen. Press its small A button to continue or B to dismiss.")}
