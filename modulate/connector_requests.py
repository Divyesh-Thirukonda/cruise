"""Durable request identities for a connector; no raw prompts or credentials."""
import hashlib
import json
import os
import re


class ConnectorRequestError(ValueError):
    pass


def identifier(value):
    return type(value) is str and re.fullmatch(r"[a-f0-9]{32}", value) is not None


class ConnectorRequests:
    # Called under Product.lock. Entries are retained until their parent expires:
    # evicting a live key would permit an old network retry to start another job.
    LIMIT = 1024

    def __init__(self, path):
        self.path = path
        self.records = {}
        if path.exists():
            try:
                records = json.loads(path.read_text())
                if type(records) is not dict or len(records) > self.LIMIT:
                    raise ValueError
                for key, item in records.items():
                    if (not re.fullmatch(r"[a-f0-9]{64}", key) or type(item) is not dict
                            or set(item) != {"owner", "payload_hash", "expires_at", "job_id"}
                            or any(type(item[k]) is not str or not re.fullmatch(r"[a-f0-9]{64}", item[k])
                                   for k in ("owner", "payload_hash"))
                            or type(item["expires_at"]) not in (int, float)
                            or not 0 < item["expires_at"] < 2**53
                            or item["job_id"] is not None and not identifier(item["job_id"])):
                        raise ValueError
                self.records = records
            except (OSError, ValueError, TypeError):
                raise ConnectorRequestError("Connector request history is unreadable; refusing to replay requests") from None

    def save(self):
        temporary = self.path.with_suffix('.pending')
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as stream:
            json.dump(self.records, stream, allow_nan=False, separators=(',', ':'))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.path)

    def key(self, owner, request_id):
        if not identifier(request_id):
            raise ConnectorRequestError("request_id must be a fresh 32-character lowercase UUID hex string")
        return hashlib.sha256((owner + ':' + request_id).encode()).hexdigest()

    def reserve(self, owner, request_id, payload, expires_at, now):
        key = self.key(owner, request_id)
        payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        existing = self.records.get(key)
        if existing:
            if existing['payload_hash'] != payload_hash:
                raise ConnectorRequestError("This request_id already belongs to different text; use a new id for a new request")
            return existing, False
        retained = {k: v for k, v in self.records.items() if v['expires_at'] > now}
        if len(retained) >= self.LIMIT:
            raise ConnectorRequestError("Connector request history is full for this session")
        record = {'owner': owner, 'payload_hash': payload_hash, 'expires_at': expires_at, 'job_id': None}
        before = self.records
        self.records = {**retained, key: record}
        try:
            self.save()
        except Exception:
            self.records = before
            raise
        return record, True

    def find(self, owner, request_id):
        record = self.records.get(self.key(owner, request_id))
        if not record:
            raise ConnectorRequestError("That connector request was not found for this session")
        return record
