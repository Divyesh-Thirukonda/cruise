"""Bounded recent requests and observed effects, never new execution authority.

Public device requests survive a companion restart in its private state folder.
Computer-task text stays in RAM for two minutes and is explicitly requested by
the private computer path; screenshots and raw tool payloads are never stored.
"""
import copy
import json
import math
from pathlib import Path
import threading
import time
import uuid

from .device_transport import save_private


class IntentMemory:
    LIMIT = 12
    TTL = 8 * 60 * 60
    PRIVATE_TTL = 120
    MAX_BYTES = 24_000

    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.lock = threading.RLock()
        self.records = []
        try:
            if self.path.exists() and self.path.stat().st_size <= self.MAX_BYTES:
                data = json.loads(self.path.read_text())
                if type(data) is list and len(data) <= self.LIMIT and all(self._valid(r) for r in data):
                    self.records = data
        except (OSError, ValueError, TypeError):
            pass  # Missing/corrupt context cannot invent a previous instruction.
        self._prune()

    def _valid(self, r):
        return (type(r) is dict and set(r) == {"id", "at", "request", "outcome", "reply", "actions", "skills", "private"}
                and type(r["id"]) is str and len(r["id"]) == 32
                and type(r["at"]) in (int, float) and math.isfinite(r["at"]) and r["at"] >= 0
                and type(r["request"]) is str and len(r["request"]) <= 1600
                and type(r["reply"]) is str and len(r["reply"]) <= 400
                and r["outcome"] in {"completed", "failed", "cancelled", "awaiting_answer"}
                and r["private"] is False and type(r["skills"]) is list
                and all(type(s) is str and len(s) < 64 for s in r["skills"])
                and type(r["actions"]) is list and len(r["actions"]) <= 12
                and all(type(a) is dict for a in r["actions"]))

    def _prune(self):
        now = self.clock()
        self.records = [r for r in self.records if 0 <= now - r["at"] <
                        (self.PRIVATE_TTL if r["private"] else self.TTL)][-self.LIMIT:]
        while self.records and len(json.dumps(self.records, indent=2).encode()) > self.MAX_BYTES:
            self.records.pop(0)

    def append(self, request, reply, outcome, *, actions=(), skills=(), private=False):
        if outcome not in {"completed", "failed", "cancelled", "awaiting_answer"}:
            raise ValueError("Invalid memory outcome")
        with self.lock:
            self.records.append({"id": uuid.uuid4().hex, "at": self.clock(), "request": str(request)[:1600],
                                 "reply": str(reply)[:400], "outcome": outcome,
                                 "actions": copy.deepcopy(list(actions)[-12:]),
                                 "skills": list(dict.fromkeys(skills))[:5], "private": bool(private)})
            self._prune()
            save_private(self.path, [r for r in self.records if not r["private"]])

    def snapshot(self, include_private=False):
        with self.lock:
            self._prune()
            result = []
            for record in self.records:
                if record["private"] and not include_private:
                    result.append({"id": record["id"], "at": record["at"], "outcome": record["outcome"],
                                   "skills": record["skills"], "private": True,
                                   "note": "Recent computer task; read_recent_context can recover its short-lived details."})
                else:
                    result.append(copy.deepcopy(record))
            return result

    def clear(self):
        with self.lock:
            self.records.clear()
            save_private(self.path, [])


def observed_action(name, arguments, result):
    """Keep useful control outcomes, not arbitrary provider/screen content."""
    if type(arguments) is not dict or type(result) is not dict or "error" in result:
        return None
    if name in {"system_control", "speaker_control"}:
        fields = {k: copy.deepcopy(result[k]) for k in ("volume", "muted", "brightness", "before", "after", "verified") if k in result}
        return {"tool": name, "action": arguments.get("action"),
                **({"value": arguments["value"]} if "value" in arguments else {}), "observed": fields}
    if name in {"computer_audio", "camera_control"}:
        return {"tool": name, "action": arguments.get("action"),
                "observed": {k: result[k] for k in ("state", "running") if k in result}}
    if name == "activate_package":
        return {"tool": name, "observed": {k: result[k] for k in ("revision", "title", "kind", "activated") if k in result}}
    if name == "app_library":
        return {"tool": name, "action": arguments.get("action"),
                "entry_id": result.get("changed_id", arguments.get("entry_id")),
                "observed": {k: result[k] for k in ("revision", "title", "activated") if k in result}}
    if name == "computer_act":
        # Labels/typed contents are available only in the current observed UI.
        return {"tool": name, "action": (arguments.get("action") or {}).get("type"), "observed": "Action returned successfully; inspect current screen again"}
    return None
