"""Optional fixed Vercel provider gateway; credentials never reach the browser.

This changes transport only. The companion's existing durable model and speech
ledgers still reserve before dispatch, including uncertain-call reservations.
An incomplete cloud configuration fails closed instead of falling back to a key
held locally. The server gateway accepts only the fixed model, speech and transcription operations.
"""
from __future__ import annotations

import os

from .deployment import GATEWAY_URL


class CloudConfigurationError(ValueError):
    pass


class CloudProvider:
    def __init__(self):
        self._url = os.environ.get("MODULATE_CLOUD_URL", "").strip()
        self._key = os.environ.get("MODULATE_CLOUD_KEY", "").strip()
        if self._url or self._key:
            if (self._url != GATEWAY_URL or not 32 <= len(self._key) <= 256
                    or not self._key.isascii()
                    or any(not (c.isalnum() or c in "_-") for c in self._key)):
                raise CloudConfigurationError("Modulate cloud provider configuration is incomplete or invalid")

    @property
    def enabled(self):
        return bool(self._url and self._key)

    def request(self, action, payload):
        if not self.enabled or action not in {"meta", "speech", "transcribe"}:
            raise CloudConfigurationError("Modulate cloud provider action is unavailable")
        return (self._url + "?action=" + action,
                {"Authorization": "Bearer " + self._key,
                 "Content-Type": "application/json",
                 "Accept": "audio/pcm" if action == "speech" else "application/json"}, payload)
