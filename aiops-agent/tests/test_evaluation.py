import json
import tempfile
import unittest
from pathlib import Path
from evaluate import evaluate_report, scenario_folders


class EvaluationTests(unittest.TestCase):
    def test_evaluate_ground_truth_only_after_report(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / "key_evidence.json").write_text(json.dumps({"root_cause_type": "config_change", "key_evidence_ids": ["original-id"]}))
            report = {"scenario_id": folder.name, "status": "root_cause_supported", "root_cause": {"type": "config_change", "statement": "Controlled change", "initial_evidence_ids": ["EV-000001"]},
                      "evidence_reference_map": {"EV-000001": {"source_id": "original-id"}}}
            result = evaluate_report(folder, report)
            self.assertEqual(result["root_cause_accuracy"], 1)
            self.assertEqual(result["evidence_coverage"], 1)
            self.assertFalse(result["false_conclusion"])

    def test_unknown_ground_truth_not_guessed(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "key_evidence.json").write_text(json.dumps({"root_cause": "A long free-text cause"}))
            result = evaluate_report(folder, {"root_cause": None})
            self.assertIsNone(result["root_cause_accuracy"])

    def test_discover_independent_scenarios(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("one", "two"):
                child = root / name
                child.mkdir()
                (child / "metrics.json").write_text('{"series":[]}')
            self.assertEqual(len(scenario_folders(root)), 2)
            self.assertEqual(len(scenario_folders(root / "one")), 1)


if __name__ == "__main__":
    unittest.main()
