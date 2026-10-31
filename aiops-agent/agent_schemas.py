"""Local JSON Schema contracts. Validation remains mandatory with provider JSON mode."""
TAXONOMY = ("bad_deployment", "config_change", "resource_exhaustion", "dependency_failure",
            "database_issue", "network_issue", "third_party_degradation")


def obj(properties, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required, "additionalProperties": False}


def array(items, minimum=0, maximum=100):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


def choice(*values):
    return {"enum": list(values)}


STRING = {"type": "string", "minLength": 1, "maxLength": 1600}
IDS = {**array({"type": "string", "pattern": r"^EV-\d{6,}$"}, maximum=100), "uniqueItems": True}
PROOF = {**IDS, "minItems": 1}
NULLABLE = {"type": ["string", "null"], "maxLength": 512}
RANGE = obj({"start": STRING, "end": STRING})
TIME = {"anyOf": [RANGE, {"type": "null"}]}
PAGE = {"limit": {"type": "integer", "minimum": 1, "maximum": 20},
        "offset": {"type": "integer", "minimum": 0}}
TOOL_ARGUMENTS = {
    "query_logs": obj({"service": NULLABLE, "time_range": TIME, "pattern": NULLABLE, **PAGE}, []),
    "query_metrics": obj({"service": NULLABLE, "metric": NULLABLE, "time_range": TIME, **PAGE}, []),
    "get_traces": obj({"service": NULLABLE, "time_range": TIME, **PAGE}, []),
    **{name: obj({"time_range": TIME, **PAGE}, []) for name in ("get_alerts", "get_deployments", "get_config_changes")},
    "get_dependencies": obj({"service": STRING}),
    "search_past_incidents": obj({"symptoms": STRING, **PAGE}, ["symptoms"]),
    "search_support_tickets": obj({"keywords": STRING, **PAGE}, ["keywords"]),
}

ACTION_PARAMETERS = {
    "rollback_deployment": obj({"version": STRING}),
    "revert_config": obj({"key": STRING, "value": {"type": ["string", "number", "boolean", "null"]}}),
    "restart_service": obj({}),
    "scale_service": obj({"replicas": {"type": "integer", "minimum": 1, "maximum": 1000}}),
}

HYPOTHESIS = obj({
    "hypothesis_id": {"type": "string", "pattern": r"^H-[A-Za-z0-9_-]+$"},
    "type": choice(*TAXONOMY), "statement": STRING, "testable_prediction": STRING,
    "prior_confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "initial_evidence_ids": PROOF, "uncertainties": array(STRING, maximum=15),
})
EVALUATION = obj({
    "hypothesis_id": STRING, "evidence_id": {"type": "string", "pattern": r"^EV-\d{6,}$"},
    "classification": choice("supports", "contradicts", "neutral"), "strength": choice("strong", "weak"),
    "reason": STRING, "timing_assessment": choice("before_symptom", "after_symptom", "uncertain", "noncausal"),
    "dependency_assessment": choice("direct", "indirect", "unrelated", "unknown"),
    "relevance": {"type": "number", "minimum": 0, "maximum": 1},
})
ACTION = obj({
    "action_id": STRING,
    "action_type": choice("rollback_deployment", "revert_config", "restart_service", "scale_service"),
    "target": STRING, "parameters": {"type": "object", "maxProperties": 10},
    "expected_effect": STRING, "risk_level": choice("low", "medium", "high"), "blast_radius": STRING,
    "dry_run_description": STRING, "rollback_plan": STRING, "evidence_ids": PROOF,
    "verification_conditions": array(STRING, minimum=1, maximum=10),
})
SCHEMAS = {
    "hypothesis_agent": obj({"status": choice("generated", "insufficient_evidence"),
                             "hypotheses": array(HYPOTHESIS, maximum=5), "reason": STRING}),
    "orchestrator": obj({"decision": choice("investigate", "reconsider", "stop"),
                         "tool_name": choice(None, *TOOL_ARGUMENTS), "arguments": {"type": "object", "maxProperties": 8},
                         "reason": STRING, "evidence_ids": IDS,
                         "stop_reason": choice(None, "insufficient_evidence", "no_useful_tools", "request_assessment")}),
    "evidence_evaluator": obj({"evaluations": array(EVALUATION, maximum=100)}),
    "remediation_agent": obj({"status": choice("proposed", "insufficient_evidence"),
                              "actions": array(ACTION, maximum=4), "reason": STRING}),
}
