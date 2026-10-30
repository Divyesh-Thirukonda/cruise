"""Small, bundled runtime skills with metadata-only discovery.

The model selects a skill; this module does not route user text or grant tools.
Only the fixed files below may be loaded. Bodies are read on explicit load,
never returned by catalog(), and require no YAML parser or external service.
"""

from pathlib import Path
import json
import stat


_ROOT = Path(__file__).resolve().parent / "skills"
_IDS = ("computer-use", "device-apps", "games", "hardware-controls", "hardware-debugger", "component-setup", "connection-setup", "app-library")
MAX_HEADER_BYTES = 2048
MAX_SKILL_BYTES = 12_288
MAX_DESCRIPTION_CHARACTERS = 320


class SkillError(ValueError):
    """A requested bundled skill is unknown or cannot be read safely."""


def _identifier(value):
    if type(value) is not str or value not in _IDS:
        raise SkillError("Unknown runtime skill")
    return value


def _path(identifier):
    try:
        root = _ROOT.resolve(strict=True)
        path = (root / identifier / "SKILL.md").resolve(strict=True)
        path.relative_to(root)
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError("Not a regular skill file")
        return path
    except (OSError, RuntimeError, ValueError):
        raise SkillError("Bundled runtime skill is unavailable") from None


def _metadata(header, identifier):
    """Read our deliberately flat name/description frontmatter, not YAML code."""
    fields = {}
    try:
        for line in header.decode("utf-8").splitlines():
            key, separator, value = line.partition(":")
            if not separator or key not in {"name", "description"} or key in fields:
                raise ValueError("Unexpected skill metadata")
            value = value.strip()
            if value.startswith('"'):
                value = json.loads(value)
            if type(value) is not str or not value or not value.isprintable():
                raise ValueError("Invalid skill metadata")
            fields[key] = value
        if (set(fields) != {"name", "description"} or fields["name"] != identifier
                or len(fields["description"]) > MAX_DESCRIPTION_CHARACTERS):
            raise ValueError("Invalid skill metadata")
    except (UnicodeError, ValueError, TypeError):
        raise SkillError("Bundled runtime skill metadata is invalid") from None
    return {"id": identifier, "description": fields["description"]}


def _read(identifier, *, body):
    path = _path(identifier)
    try:
        with path.open("rb") as source:
            first = source.readline(MAX_HEADER_BYTES + 1)
            if first.rstrip(b"\r\n") != b"---":
                raise SkillError("Bundled runtime skill metadata is invalid")
            header, used = bytearray(), len(first)
            while True:
                line = source.readline(MAX_HEADER_BYTES - used + 1)
                used += len(line)
                if not line or used > MAX_HEADER_BYTES:
                    raise SkillError("Bundled runtime skill metadata is invalid")
                if line.rstrip(b"\r\n") == b"---":
                    break
                header.extend(line)
            metadata = _metadata(bytes(header), identifier)
            if not body:
                return metadata
            raw = source.read(MAX_SKILL_BYTES - used + 1)
            if len(raw) + used > MAX_SKILL_BYTES:
                raise SkillError("Bundled runtime skill exceeds its size limit")
            instructions = raw.decode("utf-8").strip()
            if not instructions or any(ord(c) < 32 and c not in "\n\r\t" for c in instructions):
                raise SkillError("Bundled runtime skill instructions are invalid")
            return {"id": identifier, "instructions": instructions}
    except (OSError, UnicodeError):
        raise SkillError("Bundled runtime skill is unavailable") from None


def catalog():
    """Return fresh metadata entries without reading any instruction bodies."""
    return [_read(identifier, body=False) for identifier in _IDS]


def load_skill(identifier):
    """Load one fixed bundled skill; identifiers are not file paths or URLs."""
    return _read(_identifier(identifier), body=True)
