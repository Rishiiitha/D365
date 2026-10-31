"""Schema-aware ingestion. Reserved harness files are never opened here."""
import csv
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ground-truth keys and deferred evidence are never ingested into a normal run.
RESERVED = {"key_evidence", "verification_metrics", "answer_key", "injected_evidence"}
REQUIRED = {
    "application_logs": {"ts", "service", "pod", "node", "level", "message", "id"},
    "infra_logs": {"ts", "source", "node", "pod", "level", "message", "id"},
    "traces": {"ts", "trace_id", "request_id", "root_operation", "total_duration_ms", "status", "spans", "id"},
}
OPTIONAL = ("alerts", "deployments", "config_changes", "dependencies", "past_incidents", "support_tickets")


def timestamp(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def numeric(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


class EvidenceStore:
    def __init__(self, scenario_id):
        self.scenario_id = scenario_id
        self.records = {}
        self.reference_map = {}
        self.sources = {}
        self.errors = []

    def add(self, record, source, filename, index, **provenance):
        eid = f"EV-{len(self.records) + 1:06d}"
        self.records[eid] = {**record,
                             **({"original_source": record["source"]} if "source" in record else {}),
                             "evidence_id": eid, "source": source}
        self.reference_map[eid] = {"file": filename, "record_index": index,
                                   "source_id": record.get("id"), **provenance}
        return eid

    def error(self, file, index, error):
        self.errors.append({"file": file, "record_index": index, "error": str(error)})


def read_records(path, store):
    if path.suffix.lower() == ".jsonl":
        with path.open(encoding="utf-8-sig") as stream:
            for index, line in enumerate(stream):
                if not line.strip():
                    continue
                try:
                    yield index, json.loads(line)
                except ValueError as exc:
                    store.error(path.name, index, exc)
    elif path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            yield from enumerate(csv.DictReader(stream))
    else:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(value, dict):
            value = value.get("series", value.get("records", [value]))
        if not isinstance(value, list):
            raise ValueError("Expected record list, records wrapper, or series wrapper")
        yield from enumerate(value)


def load_scenario(folder):
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError(f"Scenario directory does not exist: {folder}")
    store = EvidenceStore(folder.name)
    for path in sorted(folder.iterdir()):
        source = path.stem.lower()
        if not path.is_file() or path.suffix.lower() not in {".json", ".jsonl", ".csv"}:
            continue
        if source in RESERVED:
            store.sources[source] = {"status": "excluded", "reason": "Reserved harness source"}
            continue
        before, errors_before = len(store.records), len(store.errors)
        try:
            for index, raw in read_records(path, store):
                try:
                    if not isinstance(raw, dict):
                        raise ValueError("Record must be an object")
                    record = dict(raw)
                    missing = REQUIRED.get(source, set()) - record.keys()
                    if missing:
                        raise ValueError(f"Missing fields: {sorted(missing)}")
                    if source == "metrics":
                        required = {"id", "service", "pod", "metric", "unit", "interval_seconds", "start", "points"}
                        if required - record.keys():
                            raise ValueError(f"Missing metric fields: {sorted(required - record.keys())}")
                        interval = record["interval_seconds"]
                        if not numeric(interval) or interval <= 0 or not isinstance(record["points"], list):
                            raise ValueError("Invalid interval or points")
                        start = datetime.fromisoformat(timestamp(record["start"]))
                        for point_index, point in enumerate(record["points"]):
                            try:
                                if isinstance(point, dict):
                                    value = point.get("value")
                                    ts = timestamp(point.get("ts", point.get("timestamp")))
                                else:
                                    value = point
                                    ts = (start + timedelta(seconds=interval * point_index)).isoformat()
                                if not numeric(value):
                                    raise ValueError(f"Invalid metric point {point_index}")
                                store.add({k: v for k, v in record.items() if k != "points"} |
                                          {"ts": ts, "value": value}, source, path.name, index,
                                          series_id=record["id"], point_index=point_index, timestamp=ts)
                            except (ValueError, TypeError) as exc:
                                store.error(path.name, index, exc)
                        continue
                    if "ts" in record:
                        record["original_ts"] = record["ts"]
                        record["ts"] = timestamp(record["ts"])
                    if source in {"application_logs", "infra_logs"}:
                        if not all(isinstance(record[k], str) for k in ("id", "level", "message")):
                            raise ValueError("Log id, level and message must be strings")
                    if source == "traces":
                        fields = {"span_id", "parent_span_id", "service", "operation", "start_offset_ms", "duration_ms", "status", "error_message"}
                        if not isinstance(record["spans"], list) or not numeric(record["total_duration_ms"]):
                            raise ValueError("Invalid trace spans or duration")
                        for span in record["spans"]:
                            if not isinstance(span, dict) or fields - span.keys():
                                raise ValueError("Invalid span fields")
                            if not all(numeric(span[k]) for k in ("duration_ms", "start_offset_ms")):
                                raise ValueError("Invalid span timing")
                    store.add(record, source, path.name, index)
                except (ValueError, TypeError, KeyError, OverflowError) as exc:
                    store.error(path.name, index, exc)
        except (ValueError, OSError, csv.Error) as exc:
            store.error(path.name, None, exc)
        count = len(store.records) - before
        status = "available" if len(store.errors) == errors_before else ("partially_valid" if count else "invalid")
        entry = store.sources.setdefault(source, {"files": [], "record_count": 0, "status": status})
        entry["files"].append(path.name)
        entry["record_count"] += count
        if status != "available":
            entry["status"] = status
    for source in (*REQUIRED, "metrics", *OPTIONAL):
        store.sources.setdefault(source, {"status": "missing", "record_count": 0})
    return store
