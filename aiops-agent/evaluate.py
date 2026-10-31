"""Offline report evaluation. Only this module reads ground-truth contents, after runtime."""
import argparse
import io
import json
import unittest
from pathlib import Path
from agents import evidence_ids

ROOT = Path(__file__).resolve().parent


def scenario_folders(root):
    root = Path(root)
    def is_scenario(folder):
        return folder.is_dir() and any(p.is_file() and p.stem in {"application_logs", "infra_logs", "metrics", "traces"}
                                      for p in folder.iterdir())
    if is_scenario(root):
        return [root]
    candidates = list(root.iterdir()) + (list((root / "scenarios").iterdir()) if (root / "scenarios").is_dir() else [])
    return sorted({p.resolve() for p in candidates if is_scenario(p)})


def factual_claims(value):
    """Operational structural metric: claim objects, not sentence-level truth scoring."""
    if isinstance(value, dict):
        if any(k in value for k in ("statement", "reason", "description", "current_value", "caller", "root_operation")):
            yield value
        for k, child in value.items():
            if k not in {"agent_transcripts", "audit_log", "evidence_reference_map", "input_messages"}:
                yield from factual_claims(child)
    elif isinstance(value, list):
        for child in value:
            yield from factual_claims(child)


def evaluate_report(folder, report):
    refs = report.get("evidence_reference_map", {})
    cited = evidence_ids(report)
    used = set().union(*(evidence_ids(report.get(k, [])) for k in
                        ("supporting_evidence", "contradicting_evidence", "neutral_evidence", "root_cause", "investigation_steps")))
    claims = list(factual_claims(report))
    traced = sum(bool(evidence_ids(c)) and evidence_ids(c) <= refs.keys() for c in claims)
    ground_path = Path(folder) / "key_evidence.json"
    # The investigation report already exists before this line is reached.
    ground = json.loads(ground_path.read_text(encoding="utf-8")) if ground_path.exists() else None
    result = {"scenario_id": Path(folder).name, "runtime_status": report.get("status"),
              "investigation_duration_seconds": report.get("investigation_duration_seconds"),
              "traceability_percent": traced / len(claims) * 100 if claims else None,
              "traceability_method": "Structural claim objects with valid evidence citations / structural factual claim objects; not semantic entailment",
              "invalid_evidence_ids": sorted(cited - refs.keys()), "root_cause_accuracy": None,
              "evidence_coverage": None, "false_conclusion": None,
              "simulated_recovery_time_seconds": None,
              "failed_remediation_handling": [{"status": a.get("status"), "reopened": len(report.get("investigations", [])) > 1}
                                              for a in report.get("recovery_attempts", []) if a.get("verification", {}).get("status") != "recovered"],
              "missing_sources": [s for s, info in report.get("data_source_availability", {}).items() if info["status"] == "missing"],
              "ground_truth_status": "available" if ground is not None else "missing"}
    successful = next((a for a in report.get("recovery_attempts", []) if a.get("verification", {}).get("status") == "recovered"), None)
    if successful:
        observations = successful["verification"]["observations"]
        if len(observations) > 1:
            from datetime import datetime
            result["simulated_recovery_time_seconds"] = (datetime.fromisoformat(observations[-1]["timestamp"]) - datetime.fromisoformat(observations[0]["timestamp"])).total_seconds()
    if isinstance(ground, dict):
        expected = ground.get("root_cause_type", ground.get("expected_root_cause", ground.get("root_cause")))
        if isinstance(expected, dict):
            expected = expected.get("type", expected.get("incident_type"))
        actual = (report.get("root_cause") or {}).get("type")
        from agent_schemas import TAXONOMY
        if expected in TAXONOMY:
            result["root_cause_accuracy"] = int(actual == expected) if actual else 0
            result["false_conclusion"] = bool(actual and actual != expected)
        else:
            result["root_cause_scoring_note"] = "Ground truth lacks a comparable taxonomy type; not guessed from free text"
        keys = ground.get("key_evidence_ids", ground.get("key_evidence", ground.get("evidence_ids")))
        if isinstance(keys, list):
            expected_ids = {v if isinstance(v, str) else v.get("id", v.get("evidence_id")) for v in keys if isinstance(v, (str, dict))}
            expected_ids.discard(None)
            actual_ids = {refs[e]["source_id"] for e in used if e in refs}
            result["evidence_coverage"] = len(actual_ids & expected_ids) / len(expected_ids) if expected_ids else None
        else:
            result["evidence_coverage_note"] = "No supported ground-truth evidence-ID list; coverage unavailable"
    return result


def behavior_checks():
    # Fixed local tests inject late evidence, failed fixes and missing sources. No LLM
    # or ground truth is used; these are controlled checks, not dataset accuracy.
    suite = unittest.TestSuite()
    for pattern in ("test_confidence_engine.py", "test_approval_gate.py", "test_failed_fix_replanning.py"):
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=pattern))
    stream = io.StringIO()
    outcome = unittest.TextTestRunner(stream=stream).run(suite)
    return {"mode": "controlled_tests", "tests_run": outcome.testsRun, "passed": outcome.wasSuccessful(),
            "failures": len(outcome.failures), "errors": len(outcome.errors), "details": stream.getvalue()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=str(ROOT.parent))
    parser.add_argument("--reports", default=str(ROOT))
    parser.add_argument("--output", default=str(ROOT / "evaluation.json"))
    parser.add_argument("--live", action="store_true", help="Produce new reports using the configured LLM; never approve remediation")
    args = parser.parse_args()
    folders = scenario_folders(args.root)
    if any(Path(args.output).resolve().is_relative_to(folder.resolve()) for folder in folders):
        parser.error("Evaluation output must be outside scenario directories")
    results = []
    for folder in folders:
        path = Path(args.reports) / f"{folder.name}_report.json"
        if args.live:
            if path.resolve().is_relative_to(folder.resolve()):
                parser.error("Runtime reports must be outside scenario directories")
            from run_incident import run_workflow
            report = run_workflow(folder)
            path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
        else:
            fallback = Path(args.reports) / "report.json"
            path = path if path.exists() else fallback
            report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if report is None or report.get("scenario_id") != folder.name:
            results.append({"scenario_id": folder.name, "status": "report_unavailable", "ground_truth_status": "not_read"})
        else:
            results.append(evaluate_report(folder, report))
    summary = {"scenario_count": len(folders), "scenarios": results, "behavior_checks": behavior_checks(),
               "note": "Only discovered scenario folders evaluated; absent scenarios are not fabricated"}
    Path(args.output).write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"scenario_count": len(folders), "behavior_checks_passed": summary["behavior_checks"]["passed"], "output": args.output}))


if __name__ == "__main__":
    main()
