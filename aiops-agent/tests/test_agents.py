"""Synthetic contract fixtures only. No fixture output is a live investigation."""
import copy
import json
import unittest
from unittest.mock import patch
from jsonschema import Draft202012Validator
from agent_schemas import SCHEMAS, TOOL_ARGUMENTS
from agents import AgentError, AgentRunner, BudgetExceeded, ChatTransport, initial_context, load_playbooks, run_investigation, strict_json
from audit_log import AuditLog
from config import LLMConfig
from loader import EvidenceStore
from redaction import redact


class ScriptedTransport:
    mode = "scripted_test"

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def complete(self, messages, schema, role):
        self.calls.append({"role": role, "messages": messages})
        value = next(self.outputs)
        if isinstance(value, Exception):
            raise value
        if callable(value):
            value = value(json.loads(messages[1]["content"])["context"])
        return value if isinstance(value, str) else json.dumps(value), {"completion_tokens": 100}


def fixture():
    store = EvidenceStore("synthetic_contract_fixture")
    store.sources["application_logs"] = {"status": "available"}
    eid = store.add({"id": "fixture-log-1", "ts": "2026-01-01T00:00:00+00:00", "service": "fixture-worker",
                     "node": "fixture-node", "pod": "fixture-pod", "level": "ERROR",
                     "message": "worker pool exhausted; database timeout",
                     "email": "fixture@example.test", "api_key": "synthetic-secret-only"},
                    "application_logs", "application_logs.jsonl", 0)
    store.add({"id": "fixture-log-2", "ts": "2026-01-01T00:01:00+00:00", "service": "fixture-worker",
               "node": "fixture-node", "pod": "fixture-pod", "level": "INFO", "message": "healthy database query"},
              "application_logs", "application_logs.jsonl", 1)
    return store, eid


def hypothesis(eid, hid="H-1", kind="resource_exhaustion"):
    return {"hypothesis_id": hid, "type": kind, "statement": "Worker saturation may explain the fixture timeout",
            "testable_prediction": "More worker saturation observations precede timeouts", "prior_confidence": 0.4,
            "initial_evidence_ids": [eid], "uncertainties": ["Capacity and incident onset are unknown"]}


def generated(eid, hid="H-1", kind="resource_exhaustion"):
    return {"status": "generated", "hypotheses": [hypothesis(eid, hid, kind)], "reason": "Testable fixture signal"}


def evaluation(context):
    return {"evaluations": [{"hypothesis_id": h["hypothesis_id"], "evidence_id": eid,
                              "classification": "supports", "strength": "weak",
                              "reason": "Fixture observation is compatible; causal timing is unknown",
                              "timing_assessment": "uncertain", "dependency_assessment": "unknown", "relevance": 0.5}
                             for h in context["hypotheses"] for eid in context["new_evidence_ids"]]}


def decision(eid, tool=None, args=None, reconsider=False):
    return {"decision": "investigate" if tool else "reconsider" if reconsider else "stop",
            "tool_name": tool, "arguments": args or {}, "evidence_ids": [eid],
            "reason": "Check fixture prediction" if tool else "Fixture evidence is insufficient",
            "stop_reason": None if tool or reconsider else "insufficient_evidence"}


def action(eid):
    return {"action_id": "A-1", "action_type": "restart_service", "target": "fixture-worker", "parameters": {},
            "expected_effect": "May release stuck workers in the synthetic fixture", "risk_level": "medium",
            "blast_radius": "Potential interruption of fixture-worker requests", "dry_run_description": "Describe simulated restart only",
            "rollback_plan": "Restore previous simulated instance state if verification fails", "evidence_ids": [eid],
            "verification_conditions": ["Multiple observed requests succeed and no worker exhaustion recurs"]}


def contract_examples():
    store, eid = fixture()
    audit = AuditLog()
    h = hypothesis(eid)
    context = {"evidence": [store.records[eid]], "hypotheses": [h], "new_evidence_ids": [eid],
               "leading_hypothesis": h, "confidence_assessment": {"status": "confirmed", "origin": "synthetic test fixture only"}}
    outputs = [generated(eid), decision(eid), evaluation(context),
               {"status": "proposed", "actions": [action(eid)], "reason": "Synthetic contract example only"}]
    runner = AgentRunner(store, audit, LLMConfig(model="scripted-test-only"), ScriptedTransport(outputs))
    for role in ("hypothesis_agent", "orchestrator", "evidence_evaluator", "remediation_agent"):
        runner.call(role, context)
    return {"mode": "scripted_test", "scenario_id": store.scenario_id,
            "warning": "Synthetic schema/validation examples, not model-generated findings or a confidence calculation.",
            "agent_transcripts": runner.transcripts, "audit_log": audit.events}


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.store, self.eid = fixture()
        self.context = {"evidence": [self.store.records[self.eid]], "hypotheses": [hypothesis(self.eid)],
                        "new_evidence_ids": [self.eid]}

    def runner(self, outputs, **config):
        return AgentRunner(self.store, AuditLog(), LLMConfig(model="scripted-test-only", **config), ScriptedTransport(outputs))

    def test_all_schemas_and_playbooks_are_valid(self):
        for schema in [*SCHEMAS.values(), *TOOL_ARGUMENTS.values()]:
            Draft202012Validator.check_schema(schema)
        self.assertEqual(len(load_playbooks()), 7)
        self.assertEqual(len(contract_examples()["agent_transcripts"]), 4)

    def test_invalid_json_retries_exactly_once(self):
        runner = self.runner(["broken", generated(self.eid)])
        output = runner.call("hypothesis_agent", self.context)
        self.assertEqual(len(output["hypotheses"]), 1)
        self.assertEqual(runner.requests, 2)
        self.assertIn("correction", runner.transport.calls[1]["messages"][1]["content"])
        runner = self.runner(["bad", "still bad"])
        with self.assertRaises(AgentError):
            runner.call("hypothesis_agent", self.context)
        self.assertEqual(runner.requests, 2)

    def test_unknown_and_unpresented_evidence_rejected(self):
        for invalid_id in ("EV-999999", "EV-000002"):
            output = generated(invalid_id)
            with self.assertRaises(AgentError):
                self.runner([output, output]).call("hypothesis_agent", self.context)

    def test_inline_fabricated_citations_rejected(self):
        output = generated(self.eid)
        output["hypotheses"][0]["statement"] += " EV-999999"
        with self.assertRaises(AgentError):
            self.runner([output, output]).call("hypothesis_agent", self.context)

    def test_schema_unknown_fields_and_duplicate_hypotheses_rejected(self):
        for mutate in (lambda o: o.update({"confidence": 1}), lambda o: o["hypotheses"].append(copy.deepcopy(o["hypotheses"][0]))):
            output = generated(self.eid)
            mutate(output)
            with self.assertRaises(AgentError):
                self.runner([output, output]).call("hypothesis_agent", self.context)

    def test_orchestrator_cannot_escape_registry_or_tool_schema(self):
        for output in [decision(self.eid, "shell", {"command": "ignored"}),
                       decision(self.eid, "query_logs", {"store": "injected"}),
                       decision(self.eid, "query_logs", {"limit": 500})]:
            with self.assertRaises(AgentError):
                self.runner([output, output]).call("orchestrator", self.context)

    def test_evaluator_requires_complete_unique_matrix(self):
        output = evaluation(self.context)
        self.runner([output]).call("evidence_evaluator", self.context)
        for bad in ({"evaluations": []}, {"evaluations": output["evaluations"] * 2}):
            with self.assertRaises(AgentError):
                self.runner([bad, bad]).call("evidence_evaluator", self.context)

    def test_redaction_happens_before_provider_or_audit(self):
        self.context["evidence"][0]["message"] += " password=samplepass user_id=person-99 email=someone@example.test Bearer abc.def123"
        runner = self.runner([generated(self.eid)])
        runner.call("hypothesis_agent", self.context)
        serialized = json.dumps(runner.transport.calls) + json.dumps(runner.audit.events)
        for secret in ("samplepass", "person-99", "someone@example.test", "fixture@example.test", "synthetic-secret-only", "abc.def123"):
            self.assertNotIn(secret, serialized)
        self.assertIn("REDACTED", serialized)

    def test_groq_secrets_and_usage_counts_redact_separately(self):
        result = redact({"message": "key gsk_abcdefghijklmnopqrstuvwxyz123456 IPv6 2001:db8::abcd phone 555-123-4567",
                         "completion_tokens": 123, "access_token": "secret"})
        self.assertNotIn("gsk_", result["message"])
        self.assertNotIn("2001:db8::abcd", result["message"])
        self.assertNotIn("555-123-4567", result["message"])
        self.assertEqual(result["completion_tokens"], 123)
        self.assertEqual(result["access_token"], "[REDACTED]")

    def test_redaction_preserves_timestamps_and_metric_values(self):
        for ts in ("2026-01-01T09:00:00+00:00", "2026-01-01T09:00:00.123Z"):
            self.assertEqual(redact({"ts": ts, "value": 38}), {"ts": ts, "value": 38})
        self.assertEqual(redact("a custom-provider-key", secrets=("custom-provider-key",)), "a [REDACTED_SECRET]")

    def test_budgets_prevent_request(self):
        for config in ({"max_prompt_bytes": 10}, {"max_total_output_tokens": 1}):
            runner = self.runner([generated(self.eid)], **config)
            with self.assertRaises(BudgetExceeded):
                runner.call("hypothesis_agent", self.context)
            self.assertEqual(runner.transport.calls, [])
        runner = self.runner([generated(self.eid)], max_requests=1)
        runner.call("hypothesis_agent", self.context)
        with self.assertRaises(BudgetExceeded):
            runner.call("hypothesis_agent", self.context)

    def test_live_transport_requires_explicit_credentials_and_model(self):
        with self.assertRaises(AgentError):
            ChatTransport(LLMConfig())

    def test_groq_environment_and_secret_repr(self):
        with patch.dict("os.environ", {"LLM_PROVIDER": "groq", "GROQ_MODEL": "fixture-model", "GROQ_API_KEY": "private-test-key"}, clear=True):
            config = LLMConfig.from_env(env_file=False)
        self.assertEqual(config.model, "fixture-model")
        self.assertEqual(config.base_url, "https://api.groq.com/openai/v1")
        self.assertNotIn("private-test-key", repr(config))

    def test_dotenv_loading_and_process_precedence(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            env_file = Path(folder) / ".env"
            env_file.write_text("GROQ_API_KEY=fixture-private-key\nGROQ_MODEL=fixture-file-model\n")
            with patch.dict("os.environ", {}, clear=True):
                config = LLMConfig.from_env(env_file=env_file)
                self.assertEqual(config.api_key, "fixture-private-key")
                self.assertEqual(config.model, "fixture-file-model")
            with patch.dict("os.environ", {"GROQ_MODEL": "fixture-process-model"}, clear=True):
                self.assertEqual(LLMConfig.from_env(env_file=env_file).model, "fixture-process-model")

    def test_groq_http_contract(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "usage": {"completion_tokens": 2}}).encode()
        opener = unittest.mock.Mock()
        opener.open.return_value = response
        with patch("agents.request.build_opener", return_value=opener):
            result, _ = ChatTransport(LLMConfig(model="fixture-model", api_key="private-test-key")).complete([], {}, "orchestrator")
        req = opener.open.call_args.args[0]
        payload = json.loads(req.data)
        self.assertEqual(req.full_url, "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(payload["temperature"], 0.1)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["max_completion_tokens"], 3000)
        self.assertEqual(result, "{}")

    def test_remediation_needs_confirmed_assessment_and_observed_target(self):
        output = {"status": "proposed", "actions": [action(self.eid)], "reason": "Synthetic example"}
        with self.assertRaises(AgentError):
            self.runner([output, output]).call("remediation_agent", self.context)
        self.context.update(leading_hypothesis=hypothesis(self.eid), confidence_assessment={"status": "confirmed"})
        self.runner([output]).call("remediation_agent", self.context)
        output["actions"][0]["target"] = "imaginary-service"
        with self.assertRaises(AgentError):
            self.runner([output, output]).call("remediation_agent", self.context)

    def test_unobserved_action_parameters_rejected(self):
        self.context.update(leading_hypothesis=hypothesis(self.eid), confidence_assessment={"status": "confirmed"})
        output = {"status": "proposed", "actions": [action(self.eid)], "reason": "Synthetic example"}
        output["actions"][0].update(action_type="rollback_deployment", parameters={"version": "invented-version"})
        with self.assertRaises(AgentError):
            self.runner([output, output]).call("remediation_agent", self.context)

    def test_tool_error_is_returned_to_planner_not_evaluator(self):
        runner = self.runner([generated(self.eid), evaluation, decision(self.eid, "get_alerts"), decision(self.eid)])
        report = run_investigation(self.store, runner.audit, runner)
        self.assertEqual(report["status"], "insufficient_evidence")
        self.assertIsNone(report["root_cause"])
        self.assertEqual([c["role"] for c in runner.transport.calls].count("evidence_evaluator"), 1)
        last = json.loads(runner.transport.calls[-1]["messages"][1]["content"])["context"]
        self.assertEqual(last["investigation_history"][0]["result"]["status"], "unavailable")

    def test_tool_execution_and_new_evidence_evaluation(self):
        runner = self.runner([generated(self.eid), evaluation,
                              decision(self.eid, "query_logs", {"service": "fixture-worker", "limit": 2}),
                              evaluation, decision(self.eid)])
        report = run_investigation(self.store, runner.audit, runner)
        self.assertEqual(report["status"], "insufficient_evidence")
        self.assertEqual(len(report["evaluations"]), 2)
        self.assertFalse(report["simulated_action_executed"])
        self.assertEqual(report["confidence_assessment"]["status"], "pending_phase4")

    def test_explicit_replanning_updates_hypotheses(self):
        runner = self.runner([generated(self.eid), evaluation, decision(self.eid, reconsider=True),
                              generated(self.eid, "H-2", "database_issue"), evaluation, decision(self.eid)])
        report = run_investigation(self.store, runner.audit, runner)
        self.assertEqual(report["hypotheses"][0]["hypothesis_id"], "H-2")
        self.assertEqual(len(report["replanning_history"]), 1)
        self.assertEqual({v["hypothesis_id"] for v in report["evaluations"]}, {"H-2"})

    def test_max_steps_stops_loop(self):
        runner = self.runner([generated(self.eid), evaluation, decision(self.eid, "get_alerts")], max_steps=1)
        report = run_investigation(self.store, runner.audit, runner)
        self.assertEqual(report["status"], "max_steps")
        self.assertEqual(len(report["investigation_steps"]), 1)

    def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(self):
        for value in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":1e999}'):
            with self.assertRaises(ValueError):
                strict_json(value)


if __name__ == "__main__":
    unittest.main()
