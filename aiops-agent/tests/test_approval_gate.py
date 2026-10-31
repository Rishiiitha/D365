import copy
import json
import tempfile
import unittest
from pathlib import Path
from approval_gate import ApprovalGate
from audit_log import AuditLog
from loader import EvidenceStore
from verifier import verify


def fixture_gate():
    store = EvidenceStore("controlled")
    eid = store.add({"service": "worker", "version": "v1"}, "application_logs", "logs.json", 0)
    action = {"action_id": "A-1", "action_type": "rollback_deployment", "target": "worker", "parameters": {"version": "v1"},
              "expected_effect": "Recover worker", "risk_level": "medium", "blast_radius": "worker requests",
              "dry_run_description": "Simulated version change", "rollback_plan": "Restore previous state",
              "evidence_ids": [eid], "verification_conditions": ["Three healthy observations"]}
    return ApprovalGate(store, AuditLog()), action


def baselines():
    return [{"service": "worker", "metric": "latency_ms", "direction": "higher_worse", "baseline_mean": 10,
             "incident_value": 100, "evidence_ids": [], "baseline_evidence_ids": []}]


class ApprovalTests(unittest.TestCase):
    def test_unapproved_rejected_and_dry_run_no_mutation(self):
        gate, action = fixture_gate()
        self.assertFalse(gate.execute(action)["state_changed"])
        self.assertEqual(gate.state.versions, {})
        with self.assertRaises(PermissionError):
            gate.execute(action, dry_run=False)

    def test_approval_executes_exact_action_once(self):
        gate, action = fixture_gate()
        token = gate.approve(action, gate.approval_phrase(action))
        result = gate.execute(action, token, dry_run=False)
        self.assertTrue(result["simulated"])
        self.assertEqual(gate.state.versions, {"worker": "v1"})
        with self.assertRaises(PermissionError):
            gate.execute(action, token, dry_run=False)

    def test_changed_action_cannot_reuse_approval(self):
        gate, action = fixture_gate()
        token = gate.approve(action, gate.approval_phrase(action))
        changed = copy.deepcopy(action)
        changed["parameters"]["version"] = "v2"
        with self.assertRaises(PermissionError):
            gate.execute(changed, token, dry_run=False)
        changed = copy.deepcopy(action)
        changed["action_id"] = "A-2"
        with self.assertRaises(PermissionError):
            gate.execute(changed, token, dry_run=False)

    def test_decline_and_invalid_target(self):
        gate, action = fixture_gate()
        with self.assertRaises(PermissionError):
            gate.approve(action, "yes")
        action["target"] = "invented"
        with self.assertRaises(ValueError):
            gate.execute(action)

    def test_verifier_requires_executed_state(self):
        gate, action = fixture_gate()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(PermissionError):
                verify(folder, gate.state, {"execution_id": "SIM-1"}, baselines(), gate.audit)

    def test_sustained_recovery_failure_and_insufficient_data(self):
        gate, action = fixture_gate()
        result = gate.execute(action, gate.approve(action, gate.approval_phrase(action)), dry_run=False)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "verification_metrics.json"
            for values, expected in [([10, 11, 10], "recovered"), ([90, 100, 95], "not_recovered"), ([10], "insufficient_verification_data")]:
                path.write_text(json.dumps({"after_rollback": {"start": "2026-01-01T00:02:00Z", "interval_seconds": 60,
                              "action": {"target": "worker", "parameters": {"version": "v1"}},
                              "points": [{"service": "worker", "latency_ms": v} for v in values]}}))
                verified = verify(folder, gate.state, result, baselines(), gate.audit)
                self.assertEqual(verified["status"], expected)

    def test_wrong_binding_does_not_recover(self):
        gate, action = fixture_gate()
        result = gate.execute(action, gate.approve(action, gate.approval_phrase(action)), dry_run=False)
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "verification_metrics.json").write_text(json.dumps({"after_rollback": {
                "action": {"target": "other", "parameters": {}}, "points": []}}))
            self.assertEqual(verify(folder, gate.state, result, baselines(), gate.audit)["status"], "insufficient_verification_data")


if __name__ == "__main__":
    unittest.main()
