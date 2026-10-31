"""Impact measured from observed traces and metric deviations, not business guesses."""
from dependency_engine import relationships


def assess_impact(store, graph, anomalies):
    affected = {}
    for a in anomalies:
        if a.get("adverse") is True:
            affected.setdefault(a["service"], set()).update(a["evidence_ids"])
    traces = [r for r in store.records.values() if r["source"] == "traces"]
    failed = [r for r in traces if str(r.get("status", "")).upper() in {"ERROR", "FAILED", "FAILURE"}]
    requests = {r["request_id"] for r in traces}
    failed_requests = {r["request_id"] for r in failed}
    paths = [{"trace_id": r["trace_id"], "root_operation": r["root_operation"],
              "services": sorted({s["service"] for s in r["spans"]}), "evidence_ids": [r["evidence_id"]]} for r in failed]
    return {"affected_services": [{"service": s, "evidence_ids": sorted(ids),
                                    "potential_dependents": relationships(graph, s)["potential_blast_radius"]} for s, ids in sorted(affected.items())],
            "observed_requests": len(requests), "failed_request_count": len(failed_requests),
            "failed_trace_count": len(failed), "observed_error_rate_percent": len(failed_requests) / len(requests) * 100 if requests else None,
            "evidence_ids": [r["evidence_id"] for r in traces], "affected_request_paths": paths,
            "metric_changes": [{k: a[k] for k in ("service", "metric", "baseline_mean", "current_value", "timestamp", "evidence_ids")} for a in anomalies if a.get("adverse") is True],
            "potential_user_impact": {"description": "Observed failed operations may affect callers; user counts and business loss are unavailable" if failed else "Insufficient evidence to quantify user impact",
                                      "evidence_ids": [r["evidence_id"] for r in failed]},
            "uncertainties": ["Trace sampling coverage unknown", "Reachable dependents indicate potential exposure, not established failures", "No user counts or revenue inferred"]}
