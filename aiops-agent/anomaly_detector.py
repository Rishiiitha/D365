"""Fixed initial baseline; disjoint subsequent windows. No LLM calculations."""
import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from config import DetectionConfig


def detect_metrics(store, config=None):
    config = config or DetectionConfig()
    groups = defaultdict(list)
    for record in store.records.values():
        if record["source"] == "metrics":
            groups[(record["service"], record.get("pod"), record["id"])].append(record)
    anomalies, diagnostics = [], []
    for key, records in groups.items():
        records.sort(key=lambda r: r["ts"])
        cutoff = datetime.fromisoformat(records[0]["ts"]) + timedelta(minutes=config.baseline_minutes)
        baseline = [r for r in records if datetime.fromisoformat(r["ts"]) < cutoff]
        if len(baseline) < config.min_baseline_samples:
            diagnostics.append({"series_id": key[2], "status": "insufficient_baseline", "samples": len(baseline)})
            continue
        mean = statistics.mean(r["value"] for r in baseline)
        std = statistics.pstdev(r["value"] for r in baseline)
        for record in records[len(baseline):]:
            delta = record["value"] - mean
            z = delta / std if std else None
            severity = ("strong" if abs(z) >= config.strong_z else "warning" if abs(z) >= config.warning_z else None) if std else ("strong" if delta else None)
            if not severity:
                continue
            direction = config.directions.get(record["metric"], "unknown")
            adverse = delta > 0 if direction == "higher_worse" else delta < 0 if direction == "lower_worse" else None
            anomalies.append({"kind": "metric", "service": record["service"], "metric": record["metric"],
                              "series_id": key[2], "timestamp": record["ts"], "baseline_mean": mean,
                              "baseline_std": std, "baseline_samples": len(baseline), "current_value": record["value"],
                              "z_score": z, "threshold": config.strong_z if severity == "strong" else config.warning_z,
                              "method": "z_score" if std else "zero_variance_deviation", "severity": severity,
                              "direction": direction, "adverse": adverse,
                              "baseline_window": {"start": records[0]["ts"], "end_exclusive": cutoff.isoformat()},
                              "observation_window_minutes": config.observation_minutes,
                              "evidence_ids": [record["evidence_id"]],
                              "baseline_evidence_ids": [r["evidence_id"] for r in baseline]})
    return anomalies, diagnostics


def log_pattern(message):
    message = re.sub(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", "<uuid>", message, flags=re.I)
    message = re.sub(r"\b(?:req|trace|order|user|pod)-[\w-]+", "<id>", message)
    return re.sub(r"\b\d+(?:\.\d+)*\b", "<n>", message)


def detect_log_spikes(store, config=None):
    config = config or DetectionConfig()
    logs = [r for r in store.records.values() if r["source"] in {"application_logs", "infra_logs"}]
    if not logs:
        return []
    start = min(datetime.fromisoformat(r["ts"]) for r in logs)
    cutoff = start + timedelta(minutes=config.baseline_minutes)
    groups = defaultdict(lambda: defaultdict(list))
    for record in logs:
        ts = datetime.fromisoformat(record["ts"])
        bucket = -1 if ts < cutoff else int((ts - cutoff).total_seconds() // (60 * config.observation_minutes))
        groups[(record.get("service", record.get("node")), log_pattern(record["message"]))][bucket].append(record)
    result = []
    end = max(datetime.fromisoformat(r["ts"]) for r in logs)
    for (service, pattern), windows in groups.items():
        baseline = windows.get(-1, [])
        for bucket, current in windows.items():
            window_start = cutoff + timedelta(minutes=bucket * config.observation_minutes)
            window_end = window_start + timedelta(minutes=config.observation_minutes)
            if bucket < 0 or window_end > end:
                continue  # Do not compare a partial observation window to a full baseline.
            expected = len(baseline) * config.observation_minutes / config.baseline_minutes
            ratio = (len(current) + config.epsilon) / (expected + config.epsilon)
            if len(current) >= config.min_pattern_count and ratio >= config.spike_ratio:
                result.append({"kind": "log_spike", "service": service, "pattern": pattern,
                               "current_count": len(current), "baseline_count": len(baseline),
                               "normalized_baseline_count": expected, "spike_ratio": ratio,
                               "window_start": window_start.isoformat(), "window_end": window_end.isoformat(),
                               "severity": "strong" if ratio >= config.spike_ratio * 2 else "warning",
                               "evidence_ids": [r["evidence_id"] for r in current],
                               "baseline_evidence_ids": [r["evidence_id"] for r in baseline]})
    return result


def trace_error_rates(store, config=None):
    config = config or DetectionConfig()
    traces = [r for r in store.records.values() if r["source"] == "traces"]
    if not traces:
        return {"status": "unavailable", "reason": "No trace request observations"}
    start = min(datetime.fromisoformat(r["ts"]) for r in traces)
    cutoff = start + timedelta(minutes=config.baseline_minutes)
    windows = defaultdict(list)
    for record in traces:
        ts = datetime.fromisoformat(record["ts"])
        bucket = -1 if ts < cutoff else int((ts - cutoff).total_seconds() // (60 * config.observation_minutes))
        windows[bucket].append(record)
    result = []
    baseline_requests = {}
    for record in windows.get(-1, []):
        status = str(record["status"]).upper()
        if status in {"SUCCESS", "OK", "ERROR", "FAILED", "FAILURE"}:
            baseline_requests.setdefault(record["request_id"], []).append(record)
    baseline_failures = sum(any(str(r["status"]).upper() in {"ERROR", "FAILED", "FAILURE"} for r in rs) for rs in baseline_requests.values())
    baseline_rate = baseline_failures / len(baseline_requests) * 100 if baseline_requests else None
    for bucket, records in sorted(windows.items()):
        # Only recognized status values establish success/failure counts.
        requests = {}
        for record in records:
            status = str(record["status"]).upper()
            if status in {"SUCCESS", "OK", "ERROR", "FAILED", "FAILURE"}:
                requests.setdefault(record["request_id"], []).append(record)
        failed = sum(any(str(r["status"]).upper() in {"ERROR", "FAILED", "FAILURE"} for r in rs) for rs in requests.values())
        rate = failed / len(requests) * 100 if requests else None
        window_start = start if bucket == -1 else cutoff + timedelta(minutes=bucket * config.observation_minutes)
        window_end = cutoff if bucket == -1 else window_start + timedelta(minutes=config.observation_minutes)
        result.append({"window": "baseline" if bucket == -1 else bucket,
                       "window_start": window_start.isoformat(), "window_end_exclusive": window_end.isoformat(),
                       "total_requests": len(requests),
                       "failed_requests": failed, "error_rate_percent": rate,
                       "baseline_error_rate_percent": baseline_rate,
                       "change_percentage_points": rate - baseline_rate if rate is not None and baseline_rate is not None else None,
                       "evidence_ids": [r["evidence_id"] for rs in requests.values() for r in rs]})
    return {"status": "available", "scope": "observed trace requests only; sampling coverage unknown", "windows": result}
