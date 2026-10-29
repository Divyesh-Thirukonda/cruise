"""Private, durable copies of acknowledged apps, separate from activation authority.

Only the trusted host calls ``record_activation`` after device acknowledgement.
Saved checks are provenance, never permission to bypass fresh verification or a
live capability check. Generated candidates are not automatically library apps.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
from datetime import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time


class AppLibraryError(ValueError):
    pass


_REVISION = re.compile(r"[0-9a-f]{64}\Z")
_METADATA = {"id", "revision", "title", "kind", "favorite", "trashed", "trashed_at", "created_at", "last_opened"}


def _bytes(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError):
        raise AppLibraryError("Invalid app library data") from None


def _revision(value):
    if type(value) is not str or not _REVISION.fullmatch(value):
        raise AppLibraryError("Invalid app revision")
    return value


def _timestamp(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AppLibraryError("Duplicate app library field")
        result[key] = value
    return result


class AppLibrary:
    MAX_ITEMS = 512
    MAX_PURGED = 8192
    MAX_INDEX_BYTES = 2 * 1024 * 1024
    MAX_RECORD_BYTES = 256 * 1024
    MAX_PACKAGE_BYTES = 128 * 1024
    MAX_HISTORY_BYTES = 32 * 1024 * 1024

    def __init__(self, directory, *, clock=time.time):
        self.directory = Path(directory)
        self.records = self.directory / "packages"
        self.path = self.directory / "index.json"
        self.clock = clock
        self.lock = threading.RLock()
        for path in (self.directory, self.records):
            if path.is_symlink():
                raise AppLibraryError("App library directory cannot be a link")
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.chmod(0o700)
        with self._locked():
            if self.path.is_symlink():
                raise AppLibraryError("App library index cannot be a link")
            if not self.path.exists():
                if any(self.records.iterdir()):
                    raise AppLibraryError("App library index is missing; existing packages were preserved")
                self._write(self.path, {"version": 1, "items": {}, "purged": []})
            index = self._load()
            # Complete only deletions already committed to the durable index.
            for revision in index["purged"]:
                self._unlink_record(revision)

    @contextmanager
    def _locked(self):
        with self.lock:
            path = self.directory / ".lock"
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                os.fchmod(descriptor, 0o600)
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                yield
            finally:
                os.close(descriptor)

    @staticmethod
    def _read(path, limit):
        try:
            if path.is_symlink():
                raise AppLibraryError("App library file cannot be a link")
            with path.open("rb") as stream:
                data = stream.read(limit + 1)
            if len(data) > limit:
                raise AppLibraryError("App library file exceeds its size limit")
            return json.loads(data, object_pairs_hook=_unique_object)
        except (OSError, ValueError, UnicodeError, RecursionError):
            raise AppLibraryError("App library data is missing or corrupt; saved files were preserved") from None

    @staticmethod
    def _write(path, value):
        data = _bytes(value)
        descriptor, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def _load(self):
        data = self._read(self.path, self.MAX_INDEX_BYTES)
        if (type(data) is not dict or set(data) != {"version", "items", "purged"}
                or type(data["version"]) is not int or data["version"] != 1
                or type(data["items"]) is not dict or len(data["items"]) > self.MAX_ITEMS
                or type(data["purged"]) is not list or len(data["purged"]) > self.MAX_PURGED):
            raise AppLibraryError("Invalid app library index; saved files were preserved")
        for revision, item in data["items"].items():
            _revision(revision)
            if (type(item) is not dict or set(item) != _METADATA
                    or item["id"] != revision or item["revision"] != revision
                    or type(item["title"]) is not str or not 1 <= len(item["title"]) <= 80
                    or item["kind"] not in ("game", "control")
                    or type(item["favorite"]) is not bool or type(item["trashed"]) is not bool
                    or not _timestamp(item["created_at"]) or not _timestamp(item["last_opened"])
                    or item["last_opened"] < item["created_at"]
                    or (item["trashed"] and not _timestamp(item["trashed_at"]))
                    or (not item["trashed"] and item["trashed_at"] is not None)):
                raise AppLibraryError("Invalid app library entry; saved files were preserved")
        purged = [_revision(revision) for revision in data["purged"]]
        if len(set(purged)) != len(purged) or set(purged) & set(data["items"]):
            raise AppLibraryError("Invalid app deletion history; saved files were preserved")
        return data

    def _record(self, record):
        if type(record) is not dict:
            raise AppLibraryError("A confirmed activation record is required")
        revision = _revision(record.get("revision"))
        package, report = record.get("package"), record.get("report")
        if (type(package) is not dict or package.get("kind") not in ("game", "control")
                or type(package.get("title")) is not str or not package["title"].strip()
                or len(package["title"]) > 80 or len(_bytes(package)) > self.MAX_PACKAGE_BYTES
                or hashlib.sha256(_bytes(package)).hexdigest() != revision
                or type(report) is not dict or report.get("passed") is not True
                or report.get("candidate_id") != revision):
            raise AppLibraryError("App package and successful checks must match the exact revision")
        result = {"version": 1, "revision": revision, "package": copy.deepcopy(package), "report": copy.deepcopy(report)}
        if len(_bytes(result)) > self.MAX_RECORD_BYTES:
            raise AppLibraryError("Saved app exceeds the library size limit")
        return result

    def _record_path(self, revision):
        return self.records / (_revision(revision) + ".json")

    def _read_record(self, revision):
        value = self._read(self._record_path(revision), self.MAX_RECORD_BYTES)
        record = self._record(value)
        if type(value.get("version")) is not int or value["version"] != 1 or record != value or record["revision"] != revision:
            raise AppLibraryError("Saved app record is corrupt")
        return record

    def _save(self, index):
        if len(_bytes(index)) > self.MAX_INDEX_BYTES:
            raise AppLibraryError("App library index is full")
        self._write(self.path, index)

    @staticmethod
    def _item(index, revision):
        item = index["items"].get(_revision(revision))
        if item is None:
            raise AppLibraryError("App was not found in the library")
        return item

    def _remember(self, index, value, *, imported=False):
        record = self._record(value)
        revision = record["revision"]
        at = value.get("activated_at", self.clock())
        if not _timestamp(at):
            raise AppLibraryError("Invalid app activation time")
        if imported and revision in index["purged"]:
            return None
        item = index["items"].get(revision)
        if item is None and len(index["items"]) >= self.MAX_ITEMS:
            raise AppLibraryError("App library is full; permanently delete an app from Trash to make room")
        path = self._record_path(revision)
        if path.is_symlink():
            raise AppLibraryError("Saved app record cannot be a link")
        if path.exists():
            existing = self._read_record(revision)
            if existing["package"] != record["package"]:
                raise AppLibraryError("Saved app package differs from its revision")
        elif item is not None:
            raise AppLibraryError("Saved app package is missing; library entry was preserved")
        else:
            self._write(path, record)
        if item is None:
            item = {"id": revision, "revision": revision, "title": record["package"]["title"],
                    "kind": record["package"]["kind"], "favorite": False, "trashed": False,
                    "trashed_at": None, "created_at": at, "last_opened": at}
            index["items"][revision] = item
        else:
            item["created_at"] = min(item["created_at"], at)
            item["last_opened"] = max(item["last_opened"], at)
        if revision in index["purged"]:
            index["purged"].remove(revision)
        return copy.deepcopy(item)

    def record_activation(self, record):
        """Archive a host-confirmed activation; never call this for a candidate."""
        with self._locked():
            index = self._load()
            result = self._remember(index, record)
            self._save(index)
            return result

    def import_active(self, active):
        """Conservatively migrate the host's confirmed current and rollback copy."""
        if active is None:
            return {"imported": 0}
        if type(active) is not dict:
            raise AppLibraryError("Invalid confirmed active app")
        with self._locked():
            index = self._load()
            before = len(index["items"])
            for record in (active.get("previous"), active):
                if record is not None:
                    self._remember(index, record, imported=True)
            self._save(index)
            return {"imported": len(index["items"]) - before}

    def import_history(self, requests_directory):
        """Import only logged successful, device-acknowledged activations.

        A passing check alone or an agent's final text is not activation evidence.
        Malformed individual historical entries are skipped; a corrupt library
        index itself always fails closed. No request text enters the library.
        """
        directory = Path(requests_directory)
        trace = directory / "trace.jsonl"
        summary = {"imported": 0, "skipped": 0, "limited": False}
        if not trace.exists():
            return summary
        if trace.is_symlink():
            raise AppLibraryError("History trace cannot be a link")
        with self._locked():
            index = self._load()
            with trace.open("rb") as stream:
                consumed = 0
                while True:
                    line = stream.readline(65537)
                    if not line:
                        break
                    consumed += len(line)
                    if consumed > self.MAX_HISTORY_BYTES or len(line) > 65536:
                        summary["limited"] = True
                        break
                    try:
                        event = json.loads(line, object_pairs_hook=_unique_object)
                        if (type(event) is not dict or event.get("type") != "tool_finished"
                                or event.get("tool") != "activate_package" or event.get("status") != "passed"):
                            continue
                        result = event.get("detail")
                        if (type(result) is not dict or result.get("activated") is not True
                                or result.get("device_acknowledged") is not True):
                            continue
                        revision = _revision(result.get("revision"))
                        if revision in index["purged"]:
                            continue
                        if len(index["items"]) >= self.MAX_ITEMS and revision not in index["items"]:
                            summary["limited"] = True
                            continue
                        at = datetime.fromisoformat(event["at"])
                        if at.tzinfo is None:
                            raise ValueError("Missing history timezone")
                        package = self._read(directory / (revision + ".json"), self.MAX_PACKAGE_BYTES)
                        report = self._read(directory / (revision + ".checks.json"), self.MAX_RECORD_BYTES)
                        record = {"revision": revision, "package": package, "report": report, "activated_at": at.timestamp()}
                        # Validate historical input separately. Corrupt existing
                        # library records and write failures must not be skipped.
                        self._record(record)
                        if not _timestamp(record["activated_at"]):
                            raise ValueError("Invalid history timestamp")
                    except (ValueError, KeyError, TypeError, OverflowError, UnicodeError):
                        summary["skipped"] += 1
                        continue
                    new = revision not in index["items"]
                    self._remember(index, record, imported=True)
                    summary["imported"] += int(new)
            self._save(index)
        return summary

    def list_items(self, view="all"):
        if view not in ("all", "favorites", "trash"):
            raise AppLibraryError("Choose all, favorites, or trash")
        with self._locked():
            items = self._load()["items"].values()
            result = [copy.deepcopy(item) for item in items
                      if (item["trashed"] if view == "trash" else not item["trashed"])
                      and (view != "favorites" or item["favorite"])]
            return sorted(result, key=lambda item: (-item["last_opened"], item["id"]))

    def get_record(self, revision, *, include_trashed=False):
        with self._locked():
            item = self._item(self._load(), revision)
            if item["trashed"] and not include_trashed:
                raise AppLibraryError("Restore this app from Trash before opening it")
            record = self._read_record(revision)
            if (record["package"]["title"], record["package"]["kind"]) != (item["title"], item["kind"]):
                raise AppLibraryError("Saved app metadata does not match its package")
            return record

    def set_favorite(self, revision, favorite):
        if type(favorite) is not bool:
            raise AppLibraryError("Favorite must be true or false")
        return self._update(revision, favorite=favorite)

    def _update(self, revision, **changes):
        with self._locked():
            index = self._load()
            item = self._item(index, revision)
            item.update(changes)
            self._save(index)
            return copy.deepcopy(item)

    def trash(self, revision):
        at = self.clock()
        if not _timestamp(at):
            raise AppLibraryError("Invalid library time")
        return self._update(revision, trashed=True, trashed_at=at)

    def restore(self, revision):
        return self._update(revision, trashed=False, trashed_at=None)

    def _unlink_record(self, revision):
        path = self._record_path(revision)
        try:
            if not path.exists() and not path.is_symlink():
                return
            path.unlink(missing_ok=True)
            descriptor = os.open(self.records, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError:
            raise AppLibraryError("App deletion is pending; its saved package could not yet be removed") from None

    def purge(self, revision, *, protected=()):
        """Delete the library copy only, retaining a tombstone against migration.

        The caller must supply active, previous and in-flight activation revisions.
        Request traces/candidate copies are outside this store and require separate
        cleanup before promising that all historical source copies were deleted.
        """
        revision = _revision(revision)
        protected = {_revision(value) for value in protected if value is not None}
        with self._locked():
            if revision in protected:
                raise AppLibraryError("This app is still active or needed for rollback; open other apps before permanently deleting it")
            index = self._load()
            if revision not in index["purged"]:
                item = self._item(index, revision)
                if not item["trashed"]:
                    raise AppLibraryError("Move this app to Trash before permanently deleting it")
                if len(index["purged"]) >= self.MAX_PURGED:
                    raise AppLibraryError("App deletion history is full; no files were deleted")
                del index["items"][revision]
                index["purged"].append(revision)
                self._save(index)
            self._unlink_record(revision)
            return {"deleted": True, "revision": revision}
