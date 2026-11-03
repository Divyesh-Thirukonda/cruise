#!/usr/bin/env python3
"""Reserve $5 ONCE from the authoritative Pi ledger before enabling the web demo.
Run on the Pi, in its existing checkout. This never creates or migrates a ledger.
The allocation remains held there; the Cloudflare sub-ledger spends within it.
"""
import argparse
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modulate.agent import AgentError, Ledger

PURPOSE = "online-demo-allocation-v1"
AMOUNT = 5_000_000


def allocate(path):
    if not Path(path).is_file():
        raise AgentError("An existing authoritative ledger is required")
    ledger = Ledger(path, limit_dollars=50)
    with ledger.transaction():
        if ledger.data.get("halted"):
            raise AgentError("The ledger is halted; do not allocate from a migrated backup")
        matches = [call for call in ledger.data["calls"] if call.get("purpose") == PURPOSE]
        if matches:
            if len(matches) != 1 or any(matches[0][field] != AMOUNT for field in ("reserved", "charged")) or matches[0]["status"] != "reserved":
                raise AgentError("Existing allocation requires manual accounting review")
            reservation = matches[0]["id"]
        else:
            if ledger.data["charged"] + AMOUNT > ledger.limit:
                raise AgentError("The existing $50 ceiling cannot cover a $5 demo allocation")
            reservation = uuid.uuid4().hex
            ledger.data["calls"].append({"id": reservation, "purpose": PURPOSE, "reserved": AMOUNT, "charged": AMOUNT, "status": "reserved"})
            ledger.data["charged"] += AMOUNT
            ledger.save()
        return {"reservation": reservation, "amount": AMOUNT, "total_charged_or_reserved": ledger.data["charged"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True)
    args = parser.parse_args()
    print(json.dumps(allocate(args.ledger)))
