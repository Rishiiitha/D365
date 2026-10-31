"""Local-only analysis bridge. Scenario telemetry is never sent to an LLM/provider."""
from __future__ import annotations

import json
import re
import sys
import time
import traceback
from collections import defaultdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from anomaly_detector import detect_log_spikes, detect_metrics, trace_error_rates  # noqa: E402
from approval_gate import ApprovalGate  # noqa: E402
from audit_log import AuditLog  # noqa: E402
from config import DetectionConfig  # noqa: E402
from dependency_engine import build_dependency_graph, relationships  # noqa: E402
from impact_assessment import assess_impact  # noqa: E402
from loader import load_scenario  # noqa: E402
from run_incident import verification_baselines  # noqa: E402
from timeline_builder import build_timeline  # noqa: E402
from verifier import verify  # noqa: E402

SCENARIOS = {
    "memory": "scenario_3_memory_leak",
    "pool": "scenario_2_bad_config",
    "cache": "scenario_1_bad_deployment",
}
SOURCE_TYPES = {"application_logs": "log", "infra_logs": "log", "metrics": "metric",
                "traces": "trace", "alerts": "alert", "deployments": "deploy",
                "config_changes": "config", "support_tickets": "ticket",
                "dependencies": "config", "past_incidents": "ticket"}
SESSIONS: dict[str, dict] = {}


def read_meta(folder: str) -> dict:
    return json.loads((DATA / folder / "scenario.json").read_text(encoding="utf-8"))


def evidence_record(record: dict) -> dict:
    source = record.get("source", "log")
    content = record.get("message")
    if content is None and source == "metrics":
        content = f"{record.get('metric')}={record.get('value')} {record.get('unit', '')}; pod={record.get('pod')}"
    elif content is None:
        content = json.dumps({k: v for k, v in record.items() if k not in {"evidence_id", "source"}},
                             ensure_ascii=False, indent=2)
    service = record.get("service")
    if not service and record.get("spans"):
        service = ", ".join(dict.fromkeys(s.get("service", "") for s in record["spans"] if s.get("service")))
    return {"id": record["evidence_id"], "source": SOURCE_TYPES.get(source, "log"),
            "timestamp": record.get("ts", "Timestamp unavailable"), "service": service or "unknown",
            "content": str(content), "supports": [], "contradicts": []}


def nested_source_records(store, source):
    """Flatten metadata arrays while retaining their parent evidence reference."""
    for record in store.records.values():
        if record.get("source") != source:
            continue
        nested = False
        for key, value in record.items():
            if key in {"source", "evidence_id", "original_source", "id"} or not isinstance(value, list):
                continue
            for child in value:
                if isinstance(child, dict):
                    nested = True
                    yield {**child, "evidence_id": record["evidence_id"], "source": source}
        if not nested and (record.get("ts") or record.get("date") or record.get("summary") or record.get("title")):
            yield record


def local_hypotheses(meta, store, anomalies, timeline, graph, impact):
    """Create transparent rule-based candidates; these are not model conclusions."""
    service = meta.get("affected_service", "unknown")
    onset = timeline.get("incident_start", {}).get("timestamp")
    onset_ids = timeline.get("incident_start", {}).get("evidence_ids", [])
    candidates = []
    changes = []
    for source in ("deployments", "config_changes"):
        changes.extend(x for x in nested_source_records(store, source) if x.get("service") == service)
    changes.sort(key=lambda x: str(x.get("ts", "")))
    if changes:
        change = changes[-1]
        stamp = change.get("ts", change.get("rollout_finished_at", ""))
        title_text = change.get("description") or change.get("summary") or f"{change.get('key', 'Configuration')} changed"
        correlation_score = 0.32
        supports, contradicts = [], []
        timing_note = "Change and symptom timing cannot be compared from available timestamps."
        if stamp and onset:
            try:
                delta_minutes = (datetime.fromisoformat(onset.replace("Z", "+00:00")) - datetime.fromisoformat(stamp.replace("Z", "+00:00"))).total_seconds() / 60
                if delta_minutes >= 0:
                    correlation_score = 0.68 if delta_minutes <= 30 else 0.54 if delta_minutes <= 120 else 0.4
                    supports = [change["evidence_id"]]
                    timing_note = f"Observed change precedes estimated symptom onset by {delta_minutes:.0f} minutes; timing alone does not establish causality."
                else:
                    correlation_score = 0.2
                    contradicts = onset_ids[:3]
                    timing_note = "Observed change occurs after the estimated symptom onset, which weakens it as an initiating cause."
            except (TypeError, ValueError):
                pass
        candidates.append({"hypothesis_id": "RULE-CHANGE", "type": "change_correlation",
                           "statement": f"Recent change on {service}: {title_text}",
                           "testable_prediction": timing_note, "prior_confidence": correlation_score,
                           "initial_evidence_ids": [change["evidence_id"]], "uncertainties": ["Correlation is not causation."]})
        candidates[-1]["_support"] = supports
        candidates[-1]["_contradict"] = contradicts

    service_anomalies = [a for a in anomalies if a.get("service") == service and a.get("adverse") is True]
    service_anomalies.sort(key=lambda a: abs(a.get("z_score") or 0), reverse=True)
    unique_metrics = []
    seen_metrics = set()
    for anomaly in service_anomalies:
        if anomaly.get("metric") not in seen_metrics:
            seen_metrics.add(anomaly.get("metric"))
            unique_metrics.append(anomaly)
        if len(unique_metrics) >= 2:
            break
    for index, anomaly in enumerate(unique_metrics):
        ids = anomaly.get("evidence_ids", [])[:3]
        metric = str(anomaly.get("metric", "metric")).replace("_", " ")
        score = 0.67 if anomaly.get("severity") == "strong" else 0.5
        candidates.append({"hypothesis_id": f"RULE-SIGNAL-{index+1}", "type": "metric_signal",
                           "statement": f"{metric} deviation is affecting {service}",
                           "testable_prediction": f"Measured {anomaly.get('current_value')} versus a {anomaly.get('baseline_mean')} baseline at {anomaly.get('timestamp')}.",
                           "prior_confidence": score, "initial_evidence_ids": ids or onset_ids[:1],
                           "uncertainties": ["A metric deviation identifies a symptom, not its cause."]})
        candidates[-1]["_support"] = ids
        candidates[-1]["_contradict"] = []

    failed_traces = impact.get("failed_trace_count", 0)
    if failed_traces and graph.get("edges"):
        trace_ids = [r["evidence_id"] for r in store.records.values() if r.get("source") == "traces" and
                     str(r.get("status", "")).upper() in {"ERROR", "FAILED", "FAILURE"}][:3]
        candidates.append({"hypothesis_id": "RULE-DEPENDENCY", "type": "dependency_signal",
                           "statement": "Failed requests traverse observed service dependencies",
                           "testable_prediction": f"{failed_traces} failed trace records were observed; graph edges are partial telemetry relationships.",
                           "prior_confidence": 0.46, "initial_evidence_ids": trace_ids,
                           "uncertainties": ["Trace sampling may be incomplete.", "A dependency path does not prove the downstream service caused the failure."]})
        candidates[-1]["_support"] = trace_ids
        candidates[-1]["_contradict"] = []

    candidates.sort(key=lambda h: (-h["prior_confidence"], h["hypothesis_id"]))
    return candidates[:4]


def local_analysis(folder):
    """Run only local Python analysis over allowlisted scenario telemetry."""
    store = load_scenario(folder)
    config = DetectionConfig()
    audit = AuditLog()
    durations = {}

    def measured(name, callback):
        started = time.perf_counter()
        value = callback()
        durations[name] = round((time.perf_counter() - started) * 1000, 2)
        return value

    anomalies, diagnostics = measured("detect_metrics", lambda: detect_metrics(store, config))
    spikes = measured("detect_log_spikes", lambda: detect_log_spikes(store, config))
    timeline = measured("build_timeline", lambda: build_timeline(store, anomalies + spikes))
    graph = measured("build_dependency_graph", lambda: build_dependency_graph(store))
    impact = measured("assess_impact", lambda: assess_impact(store, graph, anomalies))
    trace_rates = measured("trace_error_rates", lambda: trace_error_rates(store, config))

    extra_events = []
    for source in ("alerts", "deployments", "config_changes", "support_tickets"):
        for record in nested_source_records(store, source):
            timestamp = record.get("ts") or record.get("timestamp")
            if not timestamp:
                continue
            extra_events.append({"timestamp": str(timestamp), "kind": source,
                                 "service": record.get("service"), "text": str(record.get("summary") or record.get("description") or record.get("name") or record.get("key") or source),
                                 "evidence_ids": [record["evidence_id"]]})
    timeline["events"].extend(extra_events)
    timeline["events"].sort(key=lambda event: event.get("timestamp", ""))

    meta = read_meta(Path(folder).name)
    hypotheses = measured("build_rule_hypotheses", lambda: local_hypotheses(meta, store, anomalies, timeline, graph, impact))
    evaluations = []
    scores = []
    for hypothesis in hypotheses:
        support = hypothesis.pop("_support", [])
        contradict = hypothesis.pop("_contradict", [])
        for evidence_id in support:
            evaluations.append({"hypothesis_id": hypothesis["hypothesis_id"], "evidence_id": evidence_id,
                                "classification": "supports", "reason": "Selected by a deterministic local rule from observed data."})
        for evidence_id in contradict:
            evaluations.append({"hypothesis_id": hypothesis["hypothesis_id"], "evidence_id": evidence_id,
                                "classification": "contradicts", "reason": "Timestamp ordering weakens this causal candidate."})
        scores.append({"hypothesis_id": hypothesis["hypothesis_id"], "score": hypothesis["prior_confidence"],
                       "supporting_evidence_ids": support, "contradicting_evidence_ids": contradict,
                       "uncertainties": hypothesis["uncertainties"]})

    tool_names = ["detect_metrics", "detect_log_spikes", "build_timeline", "build_dependency_graph", "assess_impact", "trace_error_rates"]
    tool_counts = {"detect_metrics": (len(anomalies), list(dict.fromkeys(e for a in anomalies[:25] for e in a.get("evidence_ids", [])))),
                   "detect_log_spikes": (len(spikes), list(dict.fromkeys(e for a in spikes[:25] for e in a.get("evidence_ids", [])))),
                   "build_timeline": (len(timeline["events"]), list(dict.fromkeys(e for a in anomalies[:10] for e in a.get("evidence_ids", [])))),
                   "build_dependency_graph": (len(graph.get("edges", [])), list(dict.fromkeys(e for edge in graph.get("edges", []) for e in edge.get("evidence_ids", [])))),
                   "assess_impact": (impact.get("observed_requests", 0), impact.get("evidence_ids", [])[:20]),
                   "trace_error_rates": (len(trace_rates.get("windows", [])), list(dict.fromkeys(e for w in trace_rates.get("windows", [])[-5:] for e in w.get("evidence_ids", [])))[:20])}
    for name in tool_names:
        call_id = audit.record("tool_call", tool=name, arguments={"mode": "local-only", "provider_called": False})
        count, ids = tool_counts[name]
        audit.record("tool_result", call_id=call_id, tool=name,
                     result={"status": "ok", "count": count, "duration_ms": durations.get(name, 0)}, evidence_ids=ids)

    steps = [{"tool_name": name, "reason": f"Local analysis produced {tool_counts[name][0]} observed result(s)."} for name in tool_names]
    allowed = meta.get("allowed_actions", [])
    actions = []
    for option in allowed:
        action = action_from_allowed(option, meta, store)
        actions.append({"source_option": option, "action": action})
    status_report = {"scenario_id": store.scenario_id, "mode": "local_only", "status": "local_rules_only",
                     "error": "No LLM/provider calls were made. Hypothesis scores are deterministic signal scores, not model confidence.",
                     "data_source_availability": store.sources, "validation_errors": store.errors,
                     "timeline": timeline, "detected_anomalies": anomalies, "log_spikes": spikes,
                     "metric_diagnostics": diagnostics, "trace_error_rates": trace_rates,
                     "dependency_graph": graph, "impact_assessment": impact,
                     "hypotheses": hypotheses, "supporting_evidence": [x for x in evaluations if x["classification"] == "supports"],
                     "contradicting_evidence": [x for x in evaluations if x["classification"] == "contradicts"],
                     "neutral_evidence": [], "confidence_score_breakdown": {"status": "rule_based_signal_scores", "rankings": scores},
                     "root_cause": None, "investigation_steps": steps, "recovery_attempts": [{"recommendations": {"actions": [x["action"] for x in actions if x["action"]]}}],
                     "audit_log": audit.events, "simulation_only": True, "allowed_actions": actions,
                     "investigation_duration_seconds": sum(durations.values()) / 1000,
                     "local_durations_ms": durations}
    return status_report, store


def action_from_allowed(option, meta, store):
    label = str(option.get("label", ""))
    lowered = label.lower()
    service = meta.get("affected_service", "")
    known_services = {r.get("service") for r in store.records.values() if isinstance(r.get("service"), str)}
    target = next((name for name in sorted(known_services, key=len, reverse=True) if name.lower() in lowered), service)
    params = {}
    action_type = None
    if "rollback" in lowered or "roll back" in lowered:
        match = re.search(r"v(\d+(?:\.\d+)+)", label, re.I)
        if match:
            action_type, params = "rollback_deployment", {"version": match.group(1)}
    elif "disable" in lowered or "revert" in lowered:
        key_match = re.search(r"(?:flag\s+|disable\s+|revert\s+)([A-Za-z][\w.-]+)", label, re.I)
        value_match = re.search(r"\bto\s+(\d+(?:\.\d+)?)\b", label, re.I)
        if key_match:
            key = key_match.group(1)
            value = float(value_match.group(1)) if value_match and "." in value_match.group(1) else int(value_match.group(1)) if value_match else False
            action_type, params = "revert_config", {"key": key, "value": value}
    elif "restart" in lowered:
        action_type, params = "restart_service", {}
    elif "scale" in lowered:
        match = re.search(r"\bto\s+(\d+)\b", label, re.I)
        if match:
            action_type, params = "scale_service", {"replicas": int(match.group(1))}
    if not action_type:
        return None
    evidence_ids = [r["evidence_id"] for r in store.records.values()
                    if r.get("service") == target or any(span.get("service") == target for span in r.get("spans", []))][:8]
    if not evidence_ids:
        return None
    risk = str(option.get("risk", "medium")).lower()
    if risk not in {"low", "medium", "high"}:
        risk = "medium"
    return {"action_id": str(option.get("action_id", "LOCAL-OPTION")), "action_type": action_type,
            "target": target, "parameters": params, "expected_effect": f"Scenario option: {label}",
            "risk_level": risk, "blast_radius": f"{target}; local simulation only",
            "dry_run_description": label, "rollback_plan": "Only this local simulated state can change.",
            "evidence_ids": evidence_ids, "verification_conditions": ["Read the matching local verification fixture; no production system is contacted."]}


def report_to_scenario(frontend_id: str, report: dict, store, session_id: str) -> dict:
    folder = SCENARIOS[frontend_id]
    meta = read_meta(folder)
    main_service = meta.get("affected_service", "unknown")
    graph = report.get("dependency_graph", {})
    anomalies = report.get("detected_anomalies", [])
    by_service = defaultdict(list)
    for anomaly in anomalies:
        if anomaly.get("adverse") is True:
            by_service[anomaly.get("service")].append(anomaly)
    services = []
    for name in graph.get("nodes", []):
        rows = by_service.get(name, [])
        strongest = any(x.get("severity") == "strong" for x in rows)
        services.append({"id": name, "name": name,
                         "health": "failing" if name == main_service and strongest else "degraded" if rows else "healthy",
                         "group": "origin" if name == main_service else "blast" if rows else None})
    edges = [[edge["caller"], edge["callee"]] for edge in graph.get("edges", [])]

    timeline_events = report.get("timeline", {}).get("events", [])
    important_sources = {"alerts", "deployments", "config_changes", "support_tickets", "anomaly"}
    candidates = [e for e in timeline_events if e.get("service") == main_service and
                  (e.get("kind") in important_sources or e.get("kind") == "error" or e.get("kind") == "anomaly")]
    if not candidates:
        candidates = [e for e in timeline_events if e.get("service") == main_service]
    candidates.sort(key=lambda e: e.get("timestamp", ""))
    if len(candidates) > 10:
        positions = [round(i * (len(candidates) - 1) / 9) for i in range(10)]
        candidates = [candidates[i] for i in positions]
    timeline = []
    used_ids: set[str] = set()
    for event in candidates:
        ids = event.get("evidence_ids", [])[:2]
        used_ids.update(ids)
        source = event.get("kind", "log")
        if source == "error":
            source = "log"
        if source == "anomaly":
            source = "metric"
        ts = event.get("timestamp", "")
        clock = ts[11:16] if len(ts) >= 16 else ts
        record = store.records.get(ids[0], {}) if ids else {}
        summary = event.get("text") or record.get("message") or record.get("operation") or record.get("metric") or source.replace("_", " ")
        timeline.append({"time": clock, "source": SOURCE_TYPES.get(source, "log"),
                         "text": str(summary)[:220], "evidenceIds": ids})

    anomaly_rows = []
    grouped = defaultdict(list)
    for anomaly in anomalies:
        if anomaly.get("adverse") is True:
            grouped[(anomaly.get("service"), anomaly.get("metric"))].append(anomaly)
    ranked_groups = sorted(grouped.items(), key=lambda item: max(abs(x.get("z_score") or 0) for x in item[1]), reverse=True)[:6]
    for (service, metric), rows in ranked_groups:
        rows.sort(key=lambda x: x.get("timestamp", ""))
        chosen = rows[-10:]
        last = chosen[-1]
        evidence_ids = [x["evidence_ids"][0] for x in chosen if x.get("evidence_ids")]
        used_ids.update(evidence_ids)
        z = last.get("z_score")
        baseline = last.get("baseline_mean")
        current = last.get("current_value")
        why = f"Observed {current} against baseline {baseline}"
        if z is not None:
            why += f" (z-score {z:.1f})"
        anomaly_rows.append({"title": str(metric).replace("_", " ").title(),
                             "severity": "critical" if last.get("severity") == "strong" else "high",
                             "service": service, "why": why,
                             "values": [x.get("current_value", 0) for x in chosen],
                             "evidenceIds": evidence_ids})

    report_hypotheses = report.get("hypotheses", [])
    score_report = report.get("confidence_score_breakdown", {}) or {}
    score_by_id = {x.get("hypothesis_id"): x for x in score_report.get("rankings", [])}
    evaluations = report.get("supporting_evidence", []) + report.get("contradicting_evidence", []) + report.get("neutral_evidence", [])
    root = report.get("root_cause") or {}
    root_id = root.get("hypothesis_id") if isinstance(root, dict) else None
    hypotheses = []
    for index, hypothesis in enumerate(report_hypotheses):
        hid = hypothesis.get("hypothesis_id", f"H-{index + 1}")
        score = score_by_id.get(hid, {})
        supports = list(dict.fromkeys(x.get("evidence_id") for x in evaluations if x.get("hypothesis_id") == hid and x.get("classification") == "supports"))
        contradicts = list(dict.fromkeys(x.get("evidence_id") for x in evaluations if x.get("hypothesis_id") == hid and x.get("classification") == "contradicts"))
        supports = [x for x in supports if x][:8]
        contradicts = [x for x in contradicts if x][:8]
        used_ids.update(supports + contradicts)
        hypotheses.append({"id": hid, "title": hypothesis.get("statement", "Hypothesis"),
                           "status": "confirmed" if hid == root_id else "open",
                           "confidence": round(float(score.get("score", hypothesis.get("prior_confidence", 0))) * 100),
                           "supporting": supports, "contradicting": contradicts})
    confidence_trend = []
    for index, investigation in enumerate(report.get("investigations", [])):
        assessment = investigation.get("confidence_assessment", {}) or {}
        scores = {row.get("hypothesis_id"): round(float(row.get("score", 0)) * 100)
                  for row in assessment.get("rankings", [])}
        if scores:
            confidence_trend.append({"step": f"Agent pass {index + 1}", "scores": scores})
    if not confidence_trend and score_by_id:
        confidence_trend.append({"step": "Local rule score",
                                 "scores": {key: round(float(value.get("score", 0)) * 100) for key, value in score_by_id.items()}})

    steps = []
    for index, step in enumerate(report.get("investigation_steps", [])):
        tool = step.get("tool_name") or step.get("tool") or "evidence review"
        steps.append({"id": f"real-{index+1}", "text": str(step.get("reason") or f"Investigate with {tool}")[:180],
                      "tests": str(tool), "state": "done"})
    calls = [e for e in report.get("audit_log", []) if e.get("event_type") == "tool_call"]
    results = {e.get("call_id"): e for e in report.get("audit_log", []) if e.get("event_type") in {"tool_result", "tool_error"}}
    tool_calls = []
    for call in calls[:12]:
        result = results.get(call.get("audit_id"), {})
        ids = result.get("evidence_ids", [])[:20]
        used_ids.update(ids)
        args = json.dumps(call.get("arguments", {}), ensure_ascii=False, separators=(",", ":"))
        command = f"{call.get('tool', 'tool')}({args[1:-1]})"
        body = result.get("result", {})
        count = len(ids)
        duration = body.get("duration_ms")
        result_count = body.get("count", count)
        tool_calls.append({"id": call.get("audit_id", str(len(tool_calls))), "command": command,
                           "status": "complete", "duration": f"{duration} ms" if duration is not None else "—", "result": f"{result_count} local results",
                           "evidenceIds": ids[:8], "records": ids})

    impact = report.get("impact_assessment", {})
    trace_windows = report.get("trace_error_rates", {}).get("windows", [])
    chart = []
    for row in trace_windows[-8:]:
        stamp = row.get("window_start", "")
        chart.append({"time": stamp[11:16] if len(stamp) >= 16 else str(row.get("window", "")),
                      "error": row.get("error_rate_percent") or 0, "latency": 0})
    if not chart:
        chart = [{"time": "No trace series", "error": 0, "latency": 0}]
    latency_rows = [a for a in anomalies if a.get("service") == main_service and "latency" in str(a.get("metric", ""))]
    latency = latency_rows[-1] if latency_rows else {}
    ticket_count = len(list(nested_source_records(store, "support_tickets"))) or int(store.sources.get("support_tickets", {}).get("record_count", 0))
    impact_data = {"users": None, "tickets": ticket_count or None,
                   "errorBefore": round(float((trace_windows[0].get("error_rate_percent") or 0) if trace_windows else 0), 2),
                   "errorDuring": round(float(impact.get("observed_error_rate_percent") or 0), 2),
                   "latencyBefore": round(float(latency.get("baseline_mean") or 0), 2),
                   "latencyDuring": round(float(latency.get("current_value") or 0), 2), "chart": chart}

    actions = []
    for item in report.get("allowed_actions", []):
        option = item.get("source_option", {})
        action = item.get("action")
        if action:
            used_ids.update(action.get("evidence_ids", []))
        actions.append({"title": option.get("label", "Scenario option"),
                        "risk": str(option.get("risk", "unknown")).title(),
                        "recovery": "Scenario-defined option", "rationale": "Listed in the dataset’s allowed recovery options; no ranking or success claim is made.",
                        "approval": True, "actionId": action.get("action_id") if action else None,
                        "action": action, "executable": bool(action), "recommended": False})
    past = []
    for record in nested_source_records(store, "past_incidents"):
        past.append({"id": record.get("id", "Past incident"), "title": record.get("title", record.get("summary", "Related incident")),
                     "similarity": "—", "note": f"Recorded root cause: {record.get('root_cause', 'not recorded')}; fix: {record.get('fix', 'not recorded')}"})
        if len(past) == 3:
            break

    evidence = [evidence_record(store.records[eid]) for eid in sorted(used_ids) if eid in store.records]
    status = report.get("status", "unknown")
    error = report.get("error")
    availability = report.get("data_source_availability", {})
    countable_sources = {key: value for key, value in availability.items()
                         if value.get("status") != "excluded" and key not in {"key_evidence", "verification_metrics"}}
    source_count = sum(value.get("status") in {"available", "partially_valid"} for value in countable_sources.values())
    title = meta.get("title", frontend_id)
    root_title = root.get("statement") if isinstance(root, dict) else None
    scenario = {"id": frontend_id, "title": title, "service": main_service,
                "severity": "SEV-1" if meta.get("severity") == "critical" else "SEV-2",
                "incidentId": meta.get("incident_id", meta.get("id", "INC-UNKNOWN")),
                "rootCause": root_title or "No cause confirmed by local rules.",
                "services": services, "edges": edges, "timeline": timeline, "evidence": evidence,
                "anomalies": anomaly_rows, "hypotheses": hypotheses, "plan": steps,
                "toolCalls": tool_calls, "impact": impact_data, "remediations": actions,
                "newEvidence": {"evidenceId": evidence[0]["id"] if evidence else "", "summary": "No injected evidence was added to this live run.",
                                "confidenceChanges": {}, "revisedPlan": [], "revisedRecommendation": "The live agent has not reported a revised recommendation."},
                "pastIncidents": past, "dataMode": "live", "agentStatus": status, "agentMessage": error or "",
                "confidenceTrend": confidence_trend, "sourceAvailability": availability,
                "sourceCount": source_count, "sourceTotal": len(countable_sources)}
    SESSIONS[session_id] = {"folder": DATA / folder, "store": store, "report": report,
                            "actions": [a.get("action") for a in actions], "audit": AuditLog()}
    return {"scenario": scenario, "sessionId": session_id, "agentStatus": status,
            "agentMessage": error or "", "duration": report.get("investigation_duration_seconds", 0),
            "report": {"scenario_id": report.get("scenario_id"), "status": status,
                       "investigation_duration_seconds": report.get("investigation_duration_seconds", 0),
                       "simulation_only": True, "source_availability": report.get("data_source_availability", {}),
                       "root_cause": root or None, "confidence": score_report}}


class Handler(BaseHTTPRequestHandler):
    server_version = "IncidentIQLocal/1.0"

    def _send(self, status: int, value: dict):
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "http://localhost:5173")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send(200, {"ok": True, "mode": "local_only", "providerCalls": False, "dataScenarios": len(SCENARIOS)})
        elif path == "/api/scenarios":
            values = []
            for frontend_id, folder in SCENARIOS.items():
                meta = read_meta(folder)
                values.append({"id": frontend_id, "folder": folder, "title": meta.get("title"), "service": meta.get("affected_service")})
            self._send(200, {"scenarios": values})
        else:
            self._send(404, {"error": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path.strip("/").split("/")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            if path == ["api", "investigate"]:
                frontend_id = body.get("scenarioId")
                if frontend_id not in SCENARIOS:
                    return self._send(404, {"error": "Scenario has no real data folder"})
                session_id = str(uuid4())
                folder = SCENARIOS[frontend_id]
                report, store = local_analysis(DATA / folder)
                return self._send(200, report_to_scenario(frontend_id, report, store, session_id))
            if len(path) == 4 and path[:2] == ["api", "investigations"]:
                session = SESSIONS.get(path[2])
                if not session:
                    return self._send(404, {"error": "Investigation session expired; run the investigation again."})
                if path[3] == "inject":
                    injected_path = session["folder"] / "injected_evidence.json"
                    if not injected_path.exists():
                        return self._send(404, {"error": "No deferred evidence fixture exists for this scenario."})
                    payload = json.loads(injected_path.read_text(encoding="utf-8"))
                    rows = payload.get("evidence", []) if isinstance(payload, dict) else []
                    if not rows:
                        return self._send(404, {"error": "The deferred evidence fixture is empty."})
                    injected_records = []
                    for index, row in enumerate(rows):
                        source = "metric" if "heap" in str(row.get("type", "")).lower() else "config" if "config" in str(row.get("type", "")).lower() else "log"
                        details = row.get("details", {})
                        record_id = session["store"].add({"id": row.get("id"), "ts": row.get("ts"),
                                                           "service": details.get("repository", details.get("pod", "unknown")),
                                                           "message": row.get("summary", "") + "\n" + json.dumps(details, ensure_ascii=False)},
                                                          "injected_evidence", injected_path.name, index)
                        rec = evidence_record(session["store"].records[record_id])
                        rec["source"] = source
                        injected_records.append(rec)
                    changes = {}
                    for hypothesis in session["report"].get("hypotheses", []):
                        text_value = (hypothesis.get("statement", "") + " " + hypothesis.get("testable_prediction", "")).lower()
                        details_text = json.dumps(rows, ensure_ascii=False).lower()
                        base = float(hypothesis.get("prior_confidence", 0)) * 100
                        related = any(word in text_value and word in details_text for word in ("cache", "memory", "heap", "deployment", "change"))
                        changes[hypothesis.get("hypothesis_id", "")] = min(96, round(base + (24 if related else -5)))
                    summary = " ".join(row.get("summary", "") for row in rows)
                    evidence_event = {"evidenceId": injected_records[0]["id"], "summary": summary,
                                      "confidenceChanges": changes,
                                      "revisedPlan": ["Compare deferred evidence with the deployment/configuration window",
                                                      "Review the affected service's metric and log signals",
                                                      "Select an allowed local recovery option only after human review"],
                                      "revisedRecommendation": "Deferred dataset evidence is now available. The local rules do not rank recovery actions; review the scenario-defined options below."}
                    return self._send(200, {"evidence": injected_records, "newEvidence": evidence_event,
                                            "confidenceChanges": changes,
                                            "confidenceStep": {"step": "Deferred local evidence", "scores": changes},
                                            "providerCalls": False})
                action_index = int(body.get("actionIndex", 0))
                if action_index < 0 or action_index >= len(session["actions"]):
                    return self._send(404, {"error": "No live agent action exists at that index."})
                action = session["actions"][action_index]
                if action is None:
                    return self._send(400, {"error": "This dataset option has no supported simulated action mapping."})
                if path[3] == "reject":
                    session["audit"].record("approval_decision", action=action, approved=False)
                    return self._send(200, {"status": "rejected", "actionId": action["action_id"]})
                if path[3] == "approve":
                    audit = session["audit"]
                    gate = ApprovalGate(session["store"], audit)
                    token = gate.approve(action, gate.approval_phrase(action))
                    execution = gate.execute(action, token, dry_run=False)
                    graph = build_dependency_graph(session["store"])
                    rel = relationships(graph, action["target"])
                    required = {action["target"]} | {r["service"] for r in rel["upstream"] + rel["downstream"]}
                    anomalies, _ = detect_metrics(session["store"], DetectionConfig())
                    baselines = verification_baselines(anomalies, session["store"], required, DetectionConfig())
                    verification = verify(session["folder"], gate.state, execution, baselines, audit)
                    return self._send(200, {"status": "executed_simulation", "execution": execution,
                                            "verification": verification, "simulationOnly": True})
                return self._send(404, {"error": "Unknown investigation action"})
            self._send(404, {"error": "Not found"})
        except Exception as exc:
            traceback.print_exc()
            self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

    def log_message(self, _format, *args):
        print("[incidentiq-api]", *args)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("IncidentIQ agent API listening on http://127.0.0.1:8000")
    server.serve_forever()
