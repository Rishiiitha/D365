"""Append-only investigation audit events, optionally persisted as JSONL."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, path=None):
        self.events = []
        self.path = Path(path) if path else None
        if self.path and self.path.exists():
            with self.path.open(encoding="utf-8") as stream:
                self.events = [json.loads(line) for line in stream if line.strip()]

    def record(self, event_type, **details):
        event = {"audit_id": f"AUD-{len(self.events) + 1:06d}",
                 "timestamp": datetime.now(timezone.utc).isoformat(),
                 "event_type": event_type, **copy.deepcopy(details)}
        encoded = json.dumps(event, allow_nan=False)
        if self.path:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(encoded + "\n")
        self.events.append(event)
        return event["audit_id"]
