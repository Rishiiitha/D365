"""Controlled end-to-end recovery tests. Approvals below are synthetic test inputs."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from agents import AgentRunner
from approval_gate import ApprovalGate
from audit_log import AuditLog
from confidence_engine import ConfidenceConfig, assess
from config import LLMConfig
from dependency_engine import build_dependency_graph
from loader import EvidenceStore
from run_incident import execute_recovery, run_workflow
from test_agents import ScriptedTransport
from test_approval_gate import fixture_gate
from test_confidence_engine import evaluation


def hypothesis(hid, kind, ids):
    return {"hypothesis_id": hid, "type": kind, "statement": "worker failure may follow " + kind,
            "testable_prediction": "worker recovers after the appropriate change is reverted for " + kind,
            "initial_evidence_ids": ids, "prior_confidence": 0.5, "uncertainties": ["Controlled fixture only"]}


def evaluator(context):
    values = []
    for h in context["hypotheses"]:
        for eid in context["new_evidence_ids"]:
            row = evaluation(h["hypothesis_id"], eid, "contradicts" if h["hypothesis_id"] == "H-1" else "supports")
            row.update(timing_assessment="noncausal", dependency_assessment="direct")
            values.append(row)
    return {"evaluations": values}


class FailedFixTests(unittest.TestCase):
    def run_two_attempts(self, decline_second=False):
        store = EvidenceStore("controlled_failed_fix")
        store.sources["application_logs"] = {"status": "available"}
        ids = [store.add({"id": str(i), "service": "worker", "ts": "2026-01-01T00:00:00+00:00", "level": "INFO",
                          "version": "v1", "message": "deployment evidence" if i >= 6 else "worker observation"},
                         "application_logs", "application_logs.jsonl", i) for i in range(10)]
        hs = [hypothesis("H-1", "resource_exhaustion", ids[:2]), hypothesis("H-2", "bad_deployment", ids[:2])]
        evs = [evaluation("H-1", e) for e in ids[:6]] + [evaluation("H-2", e) for e in ids[:2]]
        config = ConfidenceConfig(threshold=0.3, margin=0.05, saturation=1)
        assessment = assess(hs, evs, store, build_dependency_graph(store), config=config)
        self.assertEqual(assessment["status"], "confirmed")
        investigation = {"root_cause": hs[0], "hypotheses": hs, "evaluations": evs, "confidence_assessment": assessment}
        _, rollback = fixture_gate()
        rollback["evidence_ids"] = [ids[0]]
        rollback["action_id"] = "A-2"
        restart = copy.deepcopy(rollback)
        restart.update(action_id="A-1", action_type="restart_service", parameters={})
        decision = {"decision": "investigate", "tool_name": "query_logs", "arguments": {"service": "worker", "pattern": "deployment", "limit": 4},
                    "reason": "Collect discriminating deployment observations", "evidence_ids": [ids[0]], "stop_reason": None}
        outputs = [{"status": "proposed", "actions": [restart], "reason": "Controlled first action"}, evaluator, decision,
                   evaluator, evaluator, {"status": "proposed", "actions": [rollback], "reason": "Controlled revised action"}]
        audit = AuditLog()
        runner = AgentRunner(store, audit, LLMConfig(model="scripted-test-only"), ScriptedTransport(outputs))
        gate = ApprovalGate(store, audit)
        approvals = []
        def approve(gate, action):
            approvals.append(action["action_id"])
            if decline_second and len(approvals) == 2:
                raise PermissionError("Synthetic second approval declined")
            return gate.approve(action, gate.approval_phrase(action))
        anomalies = [{"service": "worker", "metric": "latency_ms", "adverse": True, "direction": "higher_worse",
                      "baseline_mean": 10, "current_value": 100, "baseline_evidence_ids": [], "evidence_ids": [ids[0]]}]
        with tempfile.TemporaryDirectory() as folder:
            branch = lambda values: {"start": "2026-01-01T00:02:00Z", "interval_seconds": 60,
                                      "points": [{"service": "worker", "latency_ms": v} for v in values]}
            good = branch([10, 11, 10])
            good["action"] = {"target": "worker", "parameters": {"version": "v1"}}
            (Path(folder) / "verification_metrics.json").write_text(json.dumps({"no_action": branch([100, 100, 100]), "after_rollback": good}))
            attempts, investigations = execute_recovery(folder, store, audit, runner, investigation, anomalies, gate,
                                                        approval_callback=approve, confidence_config=config)
        self.assertEqual(approvals, ["A-1", "A-2"])
        self.assertEqual(attempts[0]["status"], "not_recovered")
        self.assertEqual(len(investigations), 2)
        self.assertEqual(investigations[-1]["root_cause"]["hypothesis_id"], "H-2")
        self.assertTrue(investigations[-1]["replanning_history"])
        self.assertNotIn("verification_metrics.json", json.dumps(runner.transcripts))
        return attempts, gate

    def test_failed_fix_replans_and_second_action_has_separate_approval(self):
        attempts, gate = self.run_two_attempts()
        self.assertEqual(attempts[-1]["status"], "recovered")
        self.assertEqual(len(gate.state.executions), 2)
        self.assertEqual(gate.state.versions["worker"], "v1")
        self.assertEqual(gate.state.restarts["worker"], 1)

    def test_second_action_can_be_declined_independently(self):
        attempts, gate = self.run_two_attempts(decline_second=True)
        self.assertEqual(attempts[-1]["status"], "approval_declined")
        self.assertEqual(len(gate.state.executions), 1)

    def test_complete_workflow_success_and_ground_truth_isolation(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            logs = [{"id": str(i), "service": "worker", "pod": None, "node": "n", "version": "v1", "level": "INFO",
                     "ts": "2026-01-01T00:00:00Z", "message": "deployment observation"} for i in range(2)]
            (folder / "application_logs.json").write_text(json.dumps(logs))
            (folder / "metrics.json").write_text(json.dumps({"series": [{"id": "m", "service": "worker", "pod": None,
                "metric": "latency_ms", "unit": "ms", "interval_seconds": 60, "start": "2026-01-01T00:00:00Z", "points": [10] * 15 + [100] * 3}]}))
            (folder / "key_evidence.json").write_text("FORBIDDEN GROUND TRUTH")
            (folder / "verification_metrics.json").write_text(json.dumps({"after_rollback": {
                "start": "2026-01-01T00:18:00Z", "interval_seconds": 60,
                "action": {"target": "worker", "parameters": {"version": "v1"}},
                "points": [{"service": "worker", "latency_ms": v} for v in [10, 11, 10]]}}))
            hs = [hypothesis("H-1", "bad_deployment", ["EV-000001", "EV-000002"])]
            _, action = fixture_gate()
            action["evidence_ids"] = ["EV-000001"]
            def supports(context):
                rows = []
                for eid in context["new_evidence_ids"]:
                    row = evaluation("H-1", eid)
                    row.update(timing_assessment="before_symptom", dependency_assessment="direct")
                    rows.append(row)
                return {"evaluations": rows}
            outputs = [{"status": "generated", "hypotheses": hs, "reason": "Controlled fixture"}, supports,
                       {"status": "proposed", "actions": [action], "reason": "Controlled rollback"}]
            original = Path.open
            def guarded(path, *args, **kwargs):
                if path.name == "key_evidence.json":
                    raise AssertionError("Ground truth entered runtime")
                return original(path, *args, **kwargs)
            with patch.object(Path, "open", guarded):
                report = run_workflow(folder, config=LLMConfig(model="scripted-test-only"), transport=ScriptedTransport(outputs),
                                      confidence_config=ConfidenceConfig(threshold=0.3, margin=0.05, saturation=1),
                                      approval_callback=lambda gate, action: gate.approve(action, gate.approval_phrase(action)))
            self.assertEqual(report["status"], "recovered")
            self.assertTrue(report["simulation_only"])
            self.assertIsNotNone(report["root_cause"])
            self.assertEqual(len(report["simulated_action_results"]), 1)
            json.dumps(report, allow_nan=False)
            self.demonstration_report = report


if __name__ == "__main__":
    unittest.main()
