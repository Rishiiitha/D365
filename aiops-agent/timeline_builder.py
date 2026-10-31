"""Evidence-backed chronology; potential onset is explicitly an estimate."""
from collections import defaultdict
from datetime import datetime


def build_timeline(store, anomalies):
    events = []
    for record in store.records.values():
        if "ts" not in record or record["source"] == "metrics":
            continue
        source = record["source"]
        kind = "error" if str(record.get("level", record.get("status", ""))).upper() in {"ERROR", "FATAL", "FAILED", "FAILURE"} else source
        events.append({"timestamp": record["ts"], "kind": kind,
                       "service": record.get("service"), "evidence_ids": [record["evidence_id"]]})
    for anomaly in anomalies:
        if anomaly.get("adverse") is False:
            continue
        events.append({"timestamp": anomaly.get("timestamp", anomaly.get("window_start")),
                       "kind": "anomaly", "service": anomaly.get("service"),
                       "evidence_ids": anomaly["evidence_ids"]})
    events.sort(key=lambda event: event["timestamp"])
    signals = [e for e in events if e["kind"] in {"error", "anomaly"}]
    symptom_series = defaultdict(list)
    for a in anomalies:
        if a.get("kind") == "metric" and a.get("adverse") is True and a["severity"] == "strong" and any(word in a["metric"].lower() for word in ("error", "latency", "duration")):
            symptom_series[a["series_id"]].append(a)
    sustained = []
    for observations in symptom_series.values():
        observations.sort(key=lambda a: a["timestamp"])
        for i in range(len(observations) - 2):
            group = observations[i:i + 3]
            interval = store.records[group[0]["evidence_ids"][0]].get("interval_seconds", 60)
            if all((datetime.fromisoformat(group[j + 1]["timestamp"]) - datetime.fromisoformat(group[j]["timestamp"])).total_seconds() == interval for j in (0, 1)):
                sustained.append({"timestamp": group[0]["timestamp"], "evidence_ids": [eid for a in group for eid in a["evidence_ids"]]})
                break
    sustained.sort(key=lambda a: a["timestamp"])
    onset = sustained[0] if sustained else signals[0] if signals else None
    return {"incident_start": {"status": "estimated" if signals else "unknown",
                               "timestamp": onset["timestamp"] if onset else None,
                               "evidence_ids": onset["evidence_ids"] if onset else [],
                               "explanation": ("Earliest run of three consecutive strong adverse error/latency metric samples" if sustained else "Weak estimate from earliest observed signal; no sustained symptom metric establishes onset") + ". Baseline assumed healthy; causal onset remains estimated."},
            "earliest_observed_signal": signals[0] if signals else None,
            "events": events}
