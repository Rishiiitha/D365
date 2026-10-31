"""Post-approval harness access. Verification observations never enter agent context."""
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from loader import timestamp, numeric


def finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite verification observation")
    return number


def invalid_constant(value):
    raise ValueError("Non-finite verification observation")


def verify(folder, state, execution, baselines, audit, min_samples=3, tolerance=0.2):
    if min_samples < 2 or not 0 <= tolerance <= 1:
        raise ValueError("Verification requires multiple samples and a valid tolerance")
    recorded = next((e for e in state.executions if e["execution_id"] == execution.get("execution_id") and
                     e["action_digest"] == execution.get("action_digest")), None)
    if not recorded or not recorded["approved"] or not recorded["state_changed"]:
        raise PermissionError("Verification harness requires an approved executed state transition")
    action = recorded["action"]
    kind = action["action_type"]
    branch = "after_rollback" if kind == "rollback_deployment" else (
        "after_flag_disable" if kind == "revert_config" and action["parameters"]["value"] in (False, "false", "disabled", "off") else "no_action")
    path = Path(folder) / "verification_metrics.json"
    result = {"status": "insufficient_verification_data", "branch": branch, "execution_id": recorded["execution_id"],
              "metrics": [], "observations": [], "uncertainties": [], "simulated": True}
    if not path.exists():
        result["uncertainties"].append("Verification source unavailable")
    else:
        try:
            value = json.loads(path.read_text(encoding="utf-8"), parse_float=finite_float, parse_constant=invalid_constant)
            section = value.get(branch)
            if not isinstance(section, dict) or not isinstance(section.get("points"), list):
                raise ValueError("Selected verification branch missing or invalid")
            # Optional explicit harness binding prevents a wrong action from observing another fix's data.
            binding = section.get("action")
            if binding and (binding.get("target") != action["target"] or binding.get("parameters") != action["parameters"]):
                raise ValueError("Harness observations do not match exact executed action")
            if not binding:
                result["uncertainties"].append("Legacy harness maps action type to a scenario-wide branch; exact target/parameter efficacy is not independently established")
            interval = section.get("interval_seconds")
            start = datetime.fromisoformat(timestamp(section.get("start")))
            if not numeric(interval) or interval <= 0:
                raise ValueError("Invalid verification interval")
            for index, point in enumerate(section["points"]):
                if not isinstance(point, dict):
                    continue
                result["observations"].append({"verification_id": f"VF-{recorded['execution_id']}-{index:04d}",
                                                "timestamp": (start + timedelta(seconds=index * interval)).isoformat(),
                                                "values": point, "source": path.name, "branch": branch, "point_index": index})
            checks = []
            for baseline in baselines:
                service, metric = baseline["service"], baseline["metric"]
                samples = []
                for observation in result["observations"]:
                    values = observation["values"]
                    # Accept flat points with service metadata, nested service maps, or metric/value rows.
                    if isinstance(values.get(service), dict):
                        current = values[service].get(metric)
                    elif values.get("service", section.get("service")) == service:
                        current = values.get(metric) if values.get("metric") != metric else values.get("value")
                    else:
                        current = None
                    if numeric(current):
                        samples.append((current, observation["verification_id"]))
                base, incident = baseline["baseline_mean"], baseline["incident_value"]
                direction = baseline["direction"]
                if len(samples) < min_samples or direction not in {"higher_worse", "lower_worse"}:
                    continue
                recent = samples[-min_samples:]
                delta = incident - base
                improvement = [(incident - v) / delta for v, _ in recent] if delta and direction == "higher_worse" else None
                allowed = max(abs(base) * tolerance, abs(delta) * tolerance, 1e-9)
                healthy = [v <= base + allowed if direction == "higher_worse" else v >= base - allowed for v, _ in recent]
                check = {"service": service, "metric": metric, "baseline": base, "incident": incident,
                         "post_fix_values": [v for v, _ in recent], "sustained_healthy": all(healthy),
                         "recovery_improvement": improvement, "verification_ids": [eid for _, eid in recent],
                         "baseline_evidence_ids": baseline.get("baseline_evidence_ids", []),
                         "incident_evidence_ids": baseline.get("evidence_ids", [])}
                checks.append(check)
            result["metrics"] = checks
            result["dependent_service_health"] = [{"service": c["service"], "metric": c["metric"],
                                                    "healthy": c["sustained_healthy"], "verification_ids": c["verification_ids"]} for c in checks]
            result["new_anomalies"] = [c for c in checks if abs(c["incident"] - c["baseline"]) <= max(abs(c["baseline"]) * tolerance, 1e-9)
                                       and not c["sustained_healthy"]]
            if checks:
                good = sum(c["sustained_healthy"] for c in checks)
                complete = len(checks) == len(baselines)
                result["status"] = "recovered" if good == len(checks) and complete and binding else "partially_recovered" if good else "not_recovered"
                if not complete:
                    result["uncertainties"].append("Some affected/dependent metrics lack verification observations")
            else:
                result["uncertainties"].append("No comparable sustained metric observations")
            result["event"] = section.get("event")
        except (ValueError, TypeError, OSError, OverflowError) as exc:
            result["uncertainties"].append(str(exc))
    result["audit_id"] = audit.record("verification_result", result=result)
    return result
