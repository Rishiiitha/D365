"""Exercise every Phase 2 tool against one scenario and save reviewable results."""
import argparse
import json
from pathlib import Path
from audit_log import AuditLog
from dependency_engine import build_dependency_graph
from loader import load_scenario
from tools import InvestigationTools


def inspect_tools(folder):
    store = load_scenario(folder)
    graph = build_dependency_graph(store)
    audit = AuditLog()
    tools = InvestigationTools(store, audit)
    service = graph["nodes"][0] if graph["nodes"] else None
    metric_record = next((r for r in store.records.values() if r["source"] == "metrics"), None)
    times = [r["ts"] for r in store.records.values() if r.get("ts")]
    time_range = {"start": min(times), "end": max(times)} if times and min(times) < max(times) else None
    # Arguments come from this scenario's observed entities, never fixed service names.
    calls = [
        ("query_logs", {"service": service, "time_range": time_range, "limit": 3}),
        ("query_metrics", {"service": metric_record["service"] if metric_record else None,
                           "metric": metric_record["metric"] if metric_record else None, "limit": 3}),
        ("get_traces", {"service": service, "time_range": time_range, "limit": 3}),
        ("get_alerts", {"time_range": time_range}),
        ("get_deployments", {"time_range": time_range}),
        ("get_config_changes", {"time_range": time_range}),
        ("get_dependencies", {"service": service or "unobserved-service"}),
        ("search_past_incidents", {"symptoms": "timeout", "limit": 3}),
        ("search_support_tickets", {"keywords": "timeout", "limit": 3}),
    ]
    results = [{"tool": name, "arguments": arguments, "result": tools.call(name, arguments)} for name, arguments in calls]
    negative_checks = [
        {"tool": "query_logs", "result": tools.call("query_logs", {"service": "unobserved-service"})},
        {"tool": "query_logs", "result": tools.call("query_logs", {"limit": -1})},
        {"tool": "arbitrary_shell", "result": tools.call("arbitrary_shell", {"command": "not executed"})},
    ]
    report = {"phase": 2, "scenario_id": store.scenario_id, "sources": store.sources,
              "dependency_graph": graph, "tool_checks": results, "negative_checks": negative_checks,
              "audit_log": audit.events, "evidence_reference_map": store.reference_map}
    def validate(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "evidence_ids":
                    if any(eid not in store.records for eid in child):
                        raise ValueError("Invalid evidence reference in Phase 2 report")
                else:
                    validate(child)
        elif isinstance(value, list):
            for child in value:
                validate(child)
    validate(report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario_folder")
    parser.add_argument("--output", default="phase2_report.json")
    args = parser.parse_args()
    output = Path(args.output)
    if output.resolve().is_relative_to(Path(args.scenario_folder).resolve()):
        parser.error("Report output must be outside the scenario directory")
    report = inspect_tools(args.scenario_folder)
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    graph = report["dependency_graph"]
    print(json.dumps({"scenario_id": report["scenario_id"], "graph_nodes": graph["nodes"],
                      "graph_edge_count": len(graph["edges"]), "trace_path_count": len(graph["request_paths"]),
                      "partial": graph["partial"], "graph_issues": len(graph["issues"]),
                      "tools": [{"tool": c["tool"], "status": c["result"]["status"],
                                 "total_matches": c["result"].get("total_matches"),
                                 "evidence_ids": c["result"]["evidence_ids"][:3]} for c in report["tool_checks"]],
                      "negative_checks": [{"tool": c["tool"], "status": c["result"]["status"]} for c in report["negative_checks"]],
                      "audit_events": len(report["audit_log"]), "report": str(output.resolve())}, indent=2))


if __name__ == "__main__":
    main()
