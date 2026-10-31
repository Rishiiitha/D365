"""Complete incident workflow. Real LLM, read-only telemetry, human-approved simulation."""
import argparse
import json
import time
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from agents import AgentError, AgentRunner, compact_record, run_investigation
from anomaly_detector import detect_metrics, detect_log_spikes, trace_error_rates
from approval_gate import ApprovalGate
from audit_log import AuditLog
from config import DetectionConfig, LLMConfig
from confidence_engine import ConfidenceConfig
from dependency_engine import build_dependency_graph, relationships
from impact_assessment import assess_impact
from loader import load_scenario
from redaction import redact
from timeline_builder import build_timeline
from verifier import verify


def verification_baselines(anomalies, store=None, required_services=None, detection_config=None):
    grouped = {}
    for a in anomalies:
        if a.get("adverse") is not True:
            continue
        if required_services is not None and a["service"] not in required_services:
            continue
        key = a["service"], a["metric"]
        if key not in grouped or abs(a["current_value"] - a["baseline_mean"]) > abs(grouped[key]["incident_value"] - a["baseline_mean"]):
            grouped[key] = {"service": a["service"], "metric": a["metric"], "direction": a["direction"],
                            "baseline_mean": a["baseline_mean"], "incident_value": a["current_value"],
                            "baseline_evidence_ids": a["baseline_evidence_ids"], "evidence_ids": a["evidence_ids"]}
    if store is not None:
        config = detection_config or DetectionConfig()
        series = defaultdict(list)
        for record in store.records.values():
            if record["source"] == "metrics" and record["metric"] in config.directions and (
                    required_services is None or record["service"] in required_services):
                series[(record["service"], record["metric"])].append(record)
        for key, rows in series.items():
            if key in grouped:
                continue
            rows.sort(key=lambda r: r["ts"])
            end = datetime.fromisoformat(rows[0]["ts"]) + timedelta(minutes=config.baseline_minutes)
            base = [r for r in rows if datetime.fromisoformat(r["ts"]) < end]
            if len(base) < config.min_baseline_samples:
                continue
            direction = config.directions[key[1]]
            incident = (max if direction == "higher_worse" else min)(rows[len(base):] or base, key=lambda r: r["value"])
            grouped[key] = {"service": key[0], "metric": key[1], "direction": direction,
                            "baseline_mean": statistics.mean(r["value"] for r in base), "incident_value": incident["value"],
                            "baseline_evidence_ids": [r["evidence_id"] for r in base], "evidence_ids": [incident["evidence_id"]]}
    return list(grouped.values())


def execute_recovery(folder, store, audit, runner, investigation, anomalies, gate, *, interactive=False,
                     approval_callback=None, max_attempts=2, confidence_config=None):
    attempts, investigations = [], [investigation]
    for _ in range(max_attempts):
        if not investigation.get("root_cause"):
            break
        root = investigation["root_cause"]
        ids = list(dict.fromkeys(root["initial_evidence_ids"] +
                   [v["evidence_id"] for v in investigation["evaluations"] if v["hypothesis_id"] == root["hypothesis_id"]]))
        context = {"leading_hypothesis": root, "hypotheses": investigation["hypotheses"],
                   "confidence_assessment": investigation["confidence_assessment"],
                   "evidence": [compact_record(store.records[e]) for e in ids[:20]]}
        try:
            recommendations = runner.call("remediation_agent", context)
        except AgentError as exc:
            attempts.append({"status": "recommendation_unavailable", "error": str(exc)})
            break
        attempt = {"recommendations": recommendations, "approval": {"status": "not_requested"}}
        attempts.append(attempt)
        if not recommendations["actions"]:
            attempt["status"] = "insufficient_action_evidence"
            break
        action = recommendations["actions"][0]
        audit.record("remediation_recommended", action=action)
        attempt["dry_run"] = gate.execute(action)
        if not interactive and approval_callback is None:
            attempt["status"] = "awaiting_human_approval"
            break
        try:
            token = approval_callback(gate, action) if approval_callback else gate.request(action)
            result = gate.execute(action, token, dry_run=False)
            attempt["approval"] = {"status": "approved", "action_digest": result["action_digest"]}
        except PermissionError:
            attempt["approval"] = {"status": "declined"}
            attempt["status"] = "approval_declined"
            break
        attempt["execution"] = result
        graph = build_dependency_graph(store)
        rel = relationships(graph, action["target"])
        required_services = {action["target"]} | {r["service"] for r in rel["upstream"] + rel["downstream"]}
        health = verification_baselines(anomalies, store, required_services, getattr(runner, "detection_config", None))
        attempt["verification"] = (verify(folder, gate.state, result, health, audit)
                                   if result["state_changed"] else {"status": "not_recovered", "reason": "Action made no simulated state change"})
        attempt["status"] = attempt["verification"]["status"]
        if attempt["status"] == "recovered":
            break
        # Raw harness observations stay private; reopen with a factual state-result summary.
        evidence_id = store.add({"id": result["execution_id"], "service": action["target"],
                                 "ts": result["executed_at"], "status": attempt["status"],
                                 "message": f"Approved simulated {action['action_type']} did not establish full recovery; reopen investigation",
                                 "action_id": action["action_id"]}, "verification_result", "simulated_state", len(attempts))
        audit.record("failed_fix_replanning", evidence_ids=[evidence_id], action_id=action["action_id"])
        investigation = run_investigation(store, audit, runner, enable_confidence=True,
                                          resume={**investigation, "new_evidence_ids": [evidence_id]}, confidence_config=confidence_config)
        investigations.append(investigation)
    return attempts, investigations


def run_workflow(folder, *, config=None, transport=None, interactive=False, approval_callback=None,
                 confidence_config=None, detection_config=None):
    started = time.monotonic()
    store = load_scenario(folder)
    audit = AuditLog()
    graph = build_dependency_graph(store)
    detection_config = detection_config or DetectionConfig()
    anomalies, diagnostics = detect_metrics(store, detection_config)
    spikes = detect_log_spikes(store, detection_config)
    timeline = build_timeline(store, anomalies + spikes)
    config = config or LLMConfig.from_env()
    report = {"scenario_id": store.scenario_id, "mode": getattr(transport, "mode", "live"),
              "data_source_availability": store.sources, "validation_errors": store.errors,
              "timeline": timeline, "detected_anomalies": anomalies, "log_spikes": spikes,
              "metric_diagnostics": diagnostics, "trace_error_rates": trace_error_rates(store, detection_config),
              "dependency_graph": graph, "impact_assessment": assess_impact(store, graph, anomalies),
              "recovery_attempts": [], "investigations": [], "root_cause": None}
    try:
        runner = AgentRunner(store, audit, config, transport)
        runner.detection_config = detection_config
        investigation = run_investigation(store, audit, runner, enable_confidence=True, confidence_config=confidence_config)
        gate = ApprovalGate(store, audit)
        attempts, investigations = execute_recovery(folder, store, audit, runner, investigation, anomalies, gate,
                                                   interactive=interactive, approval_callback=approval_callback, confidence_config=confidence_config)
        last = investigations[-1]
        report.update(investigations=investigations, recovery_attempts=attempts, root_cause=last["root_cause"],
                      hypotheses=last["hypotheses"], confidence_score_breakdown=last["confidence_assessment"],
                      supporting_evidence=[v for v in last["evaluations"] if v["classification"] == "supports"],
                      contradicting_evidence=[v for v in last["evaluations"] if v["classification"] == "contradicts"],
                      neutral_evidence=[v for v in last["evaluations"] if v["classification"] == "neutral"],
                      investigation_steps=[s for i in investigations for s in i["investigation_steps"]],
                      replanning_history=[s for i in investigations for s in i["replanning_history"]],
                      agent_transcripts=runner.transcripts, usage=runner.usage,
                      status=attempts[-1]["status"] if attempts else last["status"],
                      simulated_action_results=gate.state.executions)
    except AgentError as exc:
        report.update(status="agent_unavailable", error=str(exc))
    report.update(audit_log=audit.events, evidence_reference_map=store.reference_map,
                  investigation_duration_seconds=time.monotonic() - started,
                  simulation_only=True)
    return redact(report, secrets=(config.api_key,))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario_folder")
    parser.add_argument("--output", default="report.json")
    parser.add_argument("--interactive", action="store_true", help="Ask separately for each exact simulated action")
    parser.add_argument("--baseline-minutes", type=int, default=15)
    parser.add_argument("--observation-minutes", type=int, default=5)
    parser.add_argument("--min-baseline-samples", type=int, default=10)
    parser.add_argument("--confidence-threshold", type=float, default=0.65)
    parser.add_argument("--confidence-margin", type=float, default=0.15)
    args = parser.parse_args()
    output = Path(args.output)
    if output.resolve().is_relative_to(Path(args.scenario_folder).resolve()):
        parser.error("Report must be outside scenario directory")
    report = run_workflow(args.scenario_folder, interactive=args.interactive,
                          detection_config=DetectionConfig(baseline_minutes=args.baseline_minutes, observation_minutes=args.observation_minutes,
                                                           min_baseline_samples=args.min_baseline_samples),
                          confidence_config=ConfidenceConfig(threshold=args.confidence_threshold, margin=args.confidence_margin))
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"scenario_id": report["scenario_id"], "status": report["status"],
                      "root_cause": report["root_cause"], "report": str(output.resolve()), "simulation_only": True}, indent=2))
    if report["status"] in {"agent_unavailable", "budget_exhausted"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
