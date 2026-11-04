"""Provisioning checks for the Pi-owned agent. No new/reset spending ledger.

Provider keys remain in the existing Vercel gateway. Only its scoped transport
credential lives in the trusted Pi service, outside isolated application code.
"""
import json
from pathlib import Path

from .cloud_provider import CloudProvider


def validate_provisioning(directory):
    directory = Path(directory)
    if not CloudProvider().enabled:
        raise ValueError("Standalone AI requires the configured Modulate provider gateway")
    # Deliberately refuse the default Ledger/CharacterLedger fresh-file behavior
    # during migration. The installer must transfer BOTH existing cumulative files.
    for name in ("budget.json", "tts-character-ledger.json"):
        path = directory / name
        if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError("Standalone AI requires both existing private spending ledgers")
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or data.get("migrated_to_pi"):
            raise ValueError("This spending ledger has moved; use its current owner")
    # Invoke the same strict validators without making a request or reserving cost.
    from .agent import Ledger
    from .tts import _CharacterLedger
    Ledger(directory / "budget.json", 0).status()
    _CharacterLedger(directory, 5000)._change(0, check_only=True)

