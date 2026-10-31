"""Exact-action human authorization and simulated state changes. No production I/O."""
import copy
import hashlib
import json
import secrets
from datetime import datetime, timezone
from jsonschema import Draft202012Validator
from agent_schemas import ACTION, ACTION_PARAMETERS


def digest(action):
    return hashlib.sha256(json.dumps(action, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class SimulatedState:
    def __init__(self):
        self.versions = {}
        self.config = {}
        self.replicas = {}
        self.restarts = {}
        self.executions = []


class ApprovalGate:
    def __init__(self, store, audit, state=None):
        self.store, self.audit = store, audit
        self.state = state or SimulatedState()
        self._approvals = {}

    def validate(self, action):
        Draft202012Validator(ACTION).validate(action)
        Draft202012Validator(ACTION_PARAMETERS[action["action_type"]]).validate(action["parameters"])
        if any(e not in self.store.records for e in action["evidence_ids"]):
            raise ValueError("Unknown action evidence")
        cited = [self.store.records[e] for e in action["evidence_ids"]]
        targets = {r.get(k) for r in cited for k in ("service", "pod", "node") if isinstance(r.get(k), str)}
        targets.update(s["service"] for r in cited for s in r.get("spans", []))
        if action["target"] not in targets:
            raise ValueError("Action target must be supported by cited evidence")
        return copy.deepcopy(action)

    def approval_phrase(self, action):
        self.validate(action)
        return f"APPROVE {action['action_id']} {digest(action)[:12]}"

    def approve(self, action, human_response):
        action = self.validate(action)
        approved = human_response == self.approval_phrase(action)
        self.audit.record("approval_decision", action=action, approved=approved)
        if not approved:
            raise PermissionError("Exact explicit human approval required for this action")
        token = secrets.token_urlsafe(24)
        self._approvals[token] = digest(action)
        return token

    def request(self, action, input_fn=input, output_fn=print):
        action = self.validate(action)
        phrase = self.approval_phrase(action)
        self.audit.record("approval_request", action=action, digest=digest(action))
        output_fn("SIMULATED ACTION ONLY\n" + json.dumps(action, indent=2, allow_nan=False))
        output_fn("To execute this exact simulated action, type: " + phrase)
        try:
            response = input_fn("> ")
        except (EOFError, KeyboardInterrupt):
            response = ""
        return self.approve(action, response)

    def execute(self, action, approval_token=None, dry_run=True):
        action = self.validate(action)
        if type(dry_run) is not bool:
            raise ValueError("dry_run must be boolean")
        if dry_run:
            audit_id = self.audit.record("remediation_dry_run", action=action)
            return {"status": "dry_run", "action_id": action["action_id"], "audit_id": audit_id, "state_changed": False}
        if not approval_token or self._approvals.get(approval_token) != digest(action):
            self.audit.record("remediation_rejected", action_id=action["action_id"], reason="missing_or_modified_approval")
            raise PermissionError("Missing approval, changed action, or already consumed approval")
        del self._approvals[approval_token]
        before = copy.deepcopy({"versions": self.state.versions, "config": self.state.config,
                                "replicas": self.state.replicas, "restarts": self.state.restarts})
        target, parameters = action["target"], action["parameters"]
        kind = action["action_type"]
        if kind == "rollback_deployment":
            self.state.versions[target] = parameters["version"]
        elif kind == "revert_config":
            self.state.config.setdefault(target, {})[parameters["key"]] = parameters["value"]
        elif kind == "restart_service":
            self.state.restarts[target] = self.state.restarts.get(target, 0) + 1
        elif kind == "scale_service":
            self.state.replicas[target] = parameters["replicas"]
        after = {"versions": self.state.versions, "config": self.state.config,
                 "replicas": self.state.replicas, "restarts": self.state.restarts}
        execution = {"execution_id": f"SIM-{len(self.state.executions) + 1:04d}", "action_id": action["action_id"],
                     "action": action, "action_digest": digest(action), "approved": True,
                     "executed_at": datetime.now(timezone.utc).isoformat(), "before_state": before,
                     "state_changed": before != after, "simulated": True}
        self.state.executions.append(copy.deepcopy(execution))
        execution["audit_id"] = self.audit.record("simulated_action_executed", **execution)
        return execution
