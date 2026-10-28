"""Checked, immutable revisions with a local atomic active pointer."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from .runtime import Frame, run, validate


class ActivationError(Exception):
    pass


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.pointer = self.directory / "active.json"
        self.active = json.loads(self.pointer.read_text()) if self.pointer.exists() else None

    @property
    def revision(self):
        return self.active["revision"] if self.active else None

    def current_code(self):
        if not self.active:
            return ""
        source = (self.directory / self.active["source"]).read_text()
        if hashlib.sha256(source.encode()).hexdigest() != self.revision:
            raise ActivationError("Active source hash mismatch")
        validate(source)
        return source

    def restore(self, display):
        if self.active:
            self.current_code()  # Recheck saved source before restoring metadata.
            frame = Frame(**self.active["frame"])
            if display.render(frame, self.revision, self.active["provider"]) != self.revision:
                raise ActivationError("Restore acknowledgement mismatch")

    def _write_pointer(self, record):
        temporary = self.directory / "active.pending"
        with temporary.open("w") as stream:
            json.dump(record, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.pointer)

    def _restore_committed(self, display):
        # An interruption can arrive immediately after the atomic replacement.
        # Recover from the committed pointer, not possibly older memory state.
        self.active = json.loads(self.pointer.read_text()) if self.pointer.exists() else None
        self.restore(display)

    def activate(self, candidate, display, *, base_revision):
        if base_revision != self.revision:
            raise ActivationError("Stale base revision")
        source = candidate["code"]
        validate(source)
        frame = run(source)
        revision = hashlib.sha256(source.encode()).hexdigest()
        source_path = self.directory / (revision + ".py")
        if source_path.exists():
            if source_path.read_text() != source:
                raise ActivationError("Revision integrity mismatch")
        else:
            # An existing revision may be the only rollback copy. Never reopen
            # it for writing: a failed rewrite could truncate a working source.
            source_path.write_text(source)
        predecessor = {**self.active, "previous": None} if self.active else None
        record = {"revision": revision, "source": source_path.name,
                  "frame": frame.as_dict(), "provider": candidate["provider"],
                  "model": candidate["model"], "activated_at": time.time(),
                  "previous": predecessor, "runtime": "bounded-python-v1"}
        # Never commit the pointer until the driver acknowledges this exact hash.
        try:
            if display.render(frame, revision, candidate["provider"]) != revision:
                raise ActivationError("Display acknowledgement mismatch")
            self._write_pointer(record)
        except BaseException:
            self._restore_committed(display)
            raise
        self.active = record
        return record

    def rollback(self, display):
        previous = self.active and self.active.get("previous")
        if not previous:
            raise ActivationError("No previous revision")
        try:
            source = (self.directory / previous["source"]).read_text()
            if hashlib.sha256(source.encode()).hexdigest() != previous["revision"]:
                raise ActivationError("Previous source hash mismatch")
            validate(source)
            if display.render(Frame(**previous["frame"]), previous["revision"], previous["provider"]) != previous["revision"]:
                raise ActivationError("Rollback acknowledgement mismatch")
            self._write_pointer(previous)
            self.active = previous
        except BaseException:
            self._restore_committed(display)
            raise
        return previous
