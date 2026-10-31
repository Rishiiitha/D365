import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from anomaly_detector import detect_metrics, detect_log_spikes, log_pattern, trace_error_rates
from config import DetectionConfig
from loader import load_scenario
from timeline_builder import build_timeline


class PhaseOneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def metrics(self, points, name="latency_ms"):
        record = dict(id="series-A", service="svc", pod=None, metric=name, unit="ms",
                      interval_seconds=60, start="2026-01-01T00:00:00Z", points=points)
        (self.folder / "metrics.json").write_text(json.dumps({"series": [record]}))
        return load_scenario(self.folder)

    def test_normal_series(self):
        anomalies, _ = detect_metrics(self.metrics([9, 10, 11] * 10))
        self.assertEqual(anomalies, [])

    def test_strong_anomaly_and_provenance(self):
        store = self.metrics([9, 10, 11] * 5 + [100])
        anomalies, _ = detect_metrics(store)
        self.assertEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0]["severity"], "strong")
        eid = anomalies[0]["evidence_ids"][0]
        self.assertEqual(store.reference_map[eid]["point_index"], 15)
        self.assertEqual(store.records[eid]["ts"], "2026-01-01T00:15:00+00:00")

    def test_zero_variance(self):
        anomalies, _ = detect_metrics(self.metrics([10] * 15 + [20]))
        self.assertIsNone(anomalies[0]["z_score"])
        self.assertEqual(anomalies[0]["method"], "zero_variance_deviation")
        json.dumps(anomalies, allow_nan=False)

    def test_insufficient_baseline(self):
        anomalies, diagnostics = detect_metrics(self.metrics([1, 2, 3]))
        self.assertEqual(anomalies, [])
        self.assertEqual(diagnostics[0]["status"], "insufficient_baseline")

    def test_invalid_points_preserve_valid_data(self):
        store = self.metrics([10] * 15 + [None, "bad", True, 100])
        self.assertEqual(len(store.errors), 3)
        self.assertEqual(store.sources["metrics"]["status"], "partially_valid")
        self.assertEqual(len(detect_metrics(store)[0]), 1)

    def test_unknown_direction(self):
        anomalies, _ = detect_metrics(self.metrics([10] * 15 + [20], "custom_metric"))
        self.assertIsNone(anomalies[0]["adverse"])

    def test_reserved_files_never_opened(self):
        for name in ("key_evidence.json", "verification_metrics.json"):
            (self.folder / name).write_text("not even valid JSON")
        original = Path.open
        def guarded(path, *args, **kwargs):
            self.assertNotIn(path.stem, {"key_evidence", "verification_metrics"})
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", guarded):
            store = load_scenario(self.folder)
        self.assertEqual(store.records, {})
        self.assertEqual(store.sources["key_evidence"]["status"], "excluded")

    def test_bad_jsonl_line_and_naive_timestamp(self):
        valid = dict(ts="2026-01-01T00:00:00Z", service="svc", pod=None,
                     node="n", level="ERROR", message="error 1", id="original")
        naive = dict(valid, ts="2026-01-01T00:00:00")
        (self.folder / "application_logs.jsonl").write_text("broken\n" + json.dumps(valid) + "\n" + json.dumps(naive))
        store = load_scenario(self.folder)
        self.assertEqual(len(store.records), 1)
        self.assertEqual(len(store.errors), 2)
        self.assertEqual(store.reference_map["EV-000001"]["source_id"], "original")
        self.assertEqual(build_timeline(store, [])["incident_start"]["status"], "estimated")

    def test_csv_optional_and_missing_sources(self):
        (self.folder / "alerts.csv").write_text("id,ts,message\na,2026-01-01T00:00:00Z,alert\n")
        store = load_scenario(self.folder)
        self.assertEqual(store.sources["alerts"]["record_count"], 1)
        self.assertEqual(store.sources["deployments"]["status"], "missing")
        self.assertEqual(trace_error_rates(store)["status"], "unavailable")

    def test_log_pattern_groups_variable_ids(self):
        self.assertEqual(log_pattern("timeout req-abc after 20 ms"), log_pattern("timeout req-def after 30 ms"))

    def test_constant_metric_has_no_anomaly(self):
        self.assertEqual(detect_metrics(self.metrics([10] * 30))[0], [])

    def test_independent_scenario_ids_and_stable_references(self):
        first = self.metrics([10] * 16)
        second = load_scenario(self.folder)
        self.assertEqual(first.reference_map, second.reference_map)
        other = self.folder / "another_scenario"
        other.mkdir()
        self.assertNotEqual(first.scenario_id, load_scenario(other).scenario_id)
        self.assertEqual(load_scenario(other).records, {})

    def test_duration_normalized_log_spike(self):
        from datetime import datetime, timedelta, timezone
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        records = []
        # One baseline timeout, ten current timeouts, plus a boundary heartbeat.
        for index, seconds in enumerate([0] + list(range(901, 911)) + [1200]):
            records.append(dict(ts=(start + timedelta(seconds=seconds)).isoformat(), service="svc",
                                pod=None, node="n", id=str(index), level="INFO",
                                message="heartbeat" if seconds == 1200 else f"timeout req-{index} after 20 ms"))
        (self.folder / "application_logs.json").write_text(json.dumps(records))
        spikes = detect_log_spikes(load_scenario(self.folder))
        self.assertEqual(len(spikes), 1)
        self.assertEqual(spikes[0]["baseline_count"], 1)
        self.assertEqual(spikes[0]["current_count"], 10)
        self.assertAlmostEqual(spikes[0]["normalized_baseline_count"], 1 / 3)

    def test_error_rate_deduplicates_observed_requests(self):
        from loader import EvidenceStore
        store = EvidenceStore("test")
        for index, (ts, request, status) in enumerate([
            ("2026-01-01T00:00:00+00:00", "r1", "SUCCESS"),
            ("2026-01-01T00:16:00+00:00", "r2", "ERROR"),
            ("2026-01-01T00:16:00+00:00", "r2", "ERROR"),
            ("2026-01-01T00:17:00+00:00", "r3", "SUCCESS")]):
            store.add(dict(id=str(index), ts=ts, request_id=request, status=status), "traces", "traces.jsonl", index)
        windows = trace_error_rates(store)["windows"]
        self.assertEqual(windows[1]["total_requests"], 2)
        self.assertEqual(windows[1]["error_rate_percent"], 50)
        self.assertEqual(windows[1]["change_percentage_points"], 50)


if __name__ == "__main__":
    unittest.main()
