"""Phase 1 CLI; accepts any single scenario directory without relocating it."""
import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from anomaly_detector import detect_metrics, detect_log_spikes, trace_error_rates
from config import DetectionConfig
from loader import load_scenario
from timeline_builder import build_timeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario_folder")
    parser.add_argument("--output", default="phase1_report.json")
    parser.add_argument("--baseline-minutes", type=int, default=15)
    parser.add_argument("--observation-minutes", type=int, default=5)
    parser.add_argument("--min-baseline-samples", type=int, default=10)
    args = parser.parse_args()
    config = DetectionConfig(baseline_minutes=args.baseline_minutes,
                             observation_minutes=args.observation_minutes,
                             min_baseline_samples=args.min_baseline_samples)
    store = load_scenario(args.scenario_folder)
    metrics, diagnostics = detect_metrics(store, config)
    spikes = detect_log_spikes(store, config)
    timeline = build_timeline(store, metrics + spikes)
    report = {"phase": 1, "scenario_id": store.scenario_id, "configuration": asdict(config),
              "assumptions": ["Initial baseline window is assumed healthy; no supplied incident onset establishes this.",
                              "Metric z-scores use population standard deviation, fixed per-series initial baseline.",
                              "Log spikes compare disjoint complete observation windows to duration-normalized baseline counts.",
                              "Metric deviations and log spikes are signals, not established causes.",
                              "Trace error rates apply only to observed deduplicated requests, not all production traffic."],
              "sources": store.sources, "validation_errors": store.errors,
              "timeline": timeline, "metric_anomalies": metrics, "metric_diagnostics": diagnostics,
              "log_spikes": spikes, "trace_error_rates": trace_error_rates(store, config),
              "evidence_reference_map": store.reference_map}
    output = Path(args.output)
    # Never overwrite scenario evidence, including reserved harness files.
    if output.resolve().is_relative_to(Path(args.scenario_folder).resolve()):
        parser.error("Report output must be outside the scenario directory")
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    summary = {"scenario_id": store.scenario_id, "sources": store.sources,
               "validation_errors": len(store.errors), "evidence_records": len(store.records),
               "evidence_examples": dict(list(store.reference_map.items())[:2]),
               "timeline_sample": timeline["events"][:3], "incident_start": timeline["incident_start"],
               "metric_anomaly_count": len(metrics),
               "metric_anomalies_by_metric": dict(Counter(a["metric"] for a in metrics)),
               "metric_anomaly_examples": metrics[:2], "log_spike_count": len(spikes),
               "report": str(output.resolve())}
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
