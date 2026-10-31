"""Four JSON-only LLM roles and a bounded read-only investigation loop.

Phase 3 never declares root cause: deterministic confidence is added in Phase 4.
Transport injection exists for explicitly labelled offline tests, not fake live runs.
"""
import copy
import json
import math
import re
import time
from pathlib import Path
from urllib import error, request
from jsonschema import Draft202012Validator, ValidationError
from agent_schemas import ACTION_PARAMETERS, SCHEMAS, TAXONOMY, TOOL_ARGUMENTS
from anomaly_detector import detect_metrics, detect_log_spikes
from config import DetectionConfig, LLMConfig
from dependency_engine import build_dependency_graph
from loader import RESERVED
from redaction import redact
from timeline_builder import build_timeline
from tools import InvestigationTools
from confidence_engine import assess

ROOT = Path(__file__).resolve().parent


class AgentError(Exception):
    pass


class BudgetExceeded(AgentError):
    pass


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON object key")
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError("Non-finite JSON number")
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Non-finite JSON number")
        return number
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant, parse_float=finite_float)


def evidence_ids(value):
    result = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "evidence_id" and isinstance(child, str):
                result.add(child)
            elif key.endswith("evidence_ids") and isinstance(child, list):
                result.update(v for v in child if isinstance(v, str))
            else:
                result.update(evidence_ids(child))
    elif isinstance(value, list):
        for child in value:
            result.update(evidence_ids(child))
    return result


def load_playbooks():
    value = strict_json((ROOT / "playbooks.json").read_text(encoding="utf-8"))
    if set(value) != set(TAXONOMY):
        raise AgentError("Playbooks must contain exactly the seven incident types")
    fields = {"description", "confirming_evidence_patterns", "contradicting_evidence_patterns", "required_signals",
              "first_investigation_tools", "useful_metrics", "useful_log_patterns", "relevant_trace_patterns",
              "typical_red_herrings", "safe_remediation_suggestions", "risk_levels", "verification_conditions"}
    for playbook in value.values():
        if set(playbook) != fields or any(not v for v in playbook.values()):
            raise AgentError("Incomplete diagnostic playbook")
    return value


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Prevent a redirected request from forwarding credentials elsewhere.
        return None


class ChatTransport:
    mode = "live"

    def __init__(self, config):
        self.config = config
        self._ready_at = 0
        if not config.model.strip() or not config.api_key.strip():
            raise AgentError("Live LLM unavailable: set GROQ_MODEL and GROQ_API_KEY (or LLM_MODEL / LLM_API_KEY)")

    def complete(self, messages, schema, role):
        config = self.config
        while time.monotonic() < self._ready_at:
            time.sleep(min(1, self._ready_at - time.monotonic()))
        payload = {"model": config.model, "messages": messages, "temperature": config.temperature,
                   "max_completion_tokens": config.max_output_tokens,
                   "response_format": {"type": "json_object"}}
        req = request.Request(config.base_url.rstrip("/") + "/chat/completions",
                              data=json.dumps(payload, allow_nan=False).encode("utf-8"),
                              headers={"Authorization": "Bearer " + config.api_key, "Content-Type": "application/json",
                                       "User-Agent": "aiops-agent/0.1", "Accept": "application/json"},
                              method="POST")
        try:
            with request.build_opener(NoRedirect()).open(req, timeout=config.timeout_seconds) as response:
                raw = response.read(2_000_001)
                reset = response.headers.get("x-ratelimit-reset-tokens")
                if config.provider == "groq" and isinstance(reset, str):
                    parts = re.findall(r"([\d.]+)(ms|m|s)", reset)
                    seconds = sum(float(v) * {"m": 60, "s": 1, "ms": 0.001}[unit] for v, unit in parts)
                    if 0 < seconds <= 60:
                        self._ready_at = time.monotonic() + seconds + 0.5
            if len(raw) > 2_000_000:
                raise AgentError("Provider response exceeded byte limit")
            result = strict_json(raw.decode("utf-8"))
            choice = result["choices"][0]
            content = choice["message"].get("content")
            if choice.get("finish_reason") != "stop" or not isinstance(content, str):
                raise AgentError("Provider output incomplete or refused; no agent output accepted")
            return content, result.get("usage", {})
        except error.HTTPError as exc:
            # Never log response bodies, authorization headers, or full exception URLs.
            body = exc.read(10000).decode("utf-8", errors="replace")
            limits = re.findall(r"(?:Limit|Requested|limit|requested)[: ]+\d+", body)
            raise AgentError(f"LLM HTTP {exc.code}; {'; '.join(limits)}; check model access, JSON mode, temperature support or rate limits") from None
        except (error.URLError, TimeoutError, OSError):
            raise AgentError("LLM transport unavailable or timed out") from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise AgentError("Malformed provider response envelope") from None


class AgentRunner:
    def __init__(self, store, audit, config=None, transport=None):
        self.store, self.audit = store, audit
        self.config = config or LLMConfig.from_env()
        self.transport = transport or ChatTransport(self.config)
        self.playbooks = load_playbooks()
        self.requests = 0
        self.reserved_output_tokens = 0
        self.transcripts = []
        self.usage = []

    def messages(self, role, context, retry=False, rejection_reason=None):
        safe = redact(context, secrets=(self.config.api_key,))
        if isinstance(safe.get("confidence_assessment"), dict):
            assessment = safe["confidence_assessment"]
            if "rankings" in assessment:
                assessment["rankings"] = [{k: v for k, v in r.items() if k != "breakdown"} for r in assessment["rankings"]]
        # Evidence and reasoning accumulate in the local report, not unbounded model
        # context. Explicit sampling preserves contradictions and recent observations.
        omitted = {}
        for key, limit in (("evidence", 8), ("anomalies", 3), ("timeline", 4), ("investigation_history", 2)):
            items = safe.get(key)
            if isinstance(items, list) and len(items) > limit:
                omitted[key] = len(items) - limit
                safe[key] = items[:limit // 2] + items[-(limit - limit // 2):]
        if isinstance(safe.get("evaluations"), list):
            values = safe["evaluations"]
            contradictions = [v for v in values if v["classification"] == "contradicts"][-4:]
            chosen = contradictions + [v for v in values[-8:] if v not in contradictions]
            safe["evaluations"] = [{**v, "reason": v["reason"][:320]} for v in chosen[:8]]
            omitted["evaluations"] = max(0, len(values) - len(safe["evaluations"]))
        if omitted:
            safe["context_sampling"] = {"omitted_counts": omitted, "note": "Full records and classifications remain in local report; query tools for omitted evidence"}
        types = {h["type"] for h in safe.get("hypotheses", [])}
        if safe.get("leading_hypothesis"):
            types.add(safe["leading_hypothesis"]["type"])
        plays = self.playbooks if role == "hypothesis_agent" else {t: self.playbooks[t] for t in types if t in self.playbooks}
        # Full diagnostic knowledge stays in the local playbooks; bounded excerpts avoid
        # repeating entire documents in every request on low-rate-limit Groq accounts.
        plays = {kind: {k: [item[:140] for item in v[:1]] if isinstance(v, list) else v[:140] if isinstance(v, str) else v
                        for k, v in playbook.items()} for kind, playbook in plays.items()}
        system = (ROOT / "prompts" / f"{role}.txt").read_text(encoding="utf-8")
        envelope = {"output_schema": SCHEMAS[role], "context": safe}
        if role in {"hypothesis_agent", "evidence_evaluator", "remediation_agent"}:
            envelope["playbooks"] = plays
        if role == "orchestrator":
            envelope["tool_arguments"] = TOOL_ARGUMENTS
        if role == "remediation_agent":
            envelope["action_parameters"] = ACTION_PARAMETERS
        if retry:
            envelope["correction"] = "Previous response was invalid JSON, schema-invalid, or used unsupported references. Return corrected JSON only; use the same supplied evidence and contract."
            envelope["rejection_reason"] = rejection_reason
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(envelope, allow_nan=False, ensure_ascii=False, separators=(",", ":"))}]
        size = len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
        if size > self.config.max_prompt_bytes:
            raise BudgetExceeded("Prompt exceeds configured byte limit; narrow context before retrying")
        return messages, size

    def validate(self, role, output, context):
        Draft202012Validator(SCHEMAS[role]).validate(output)
        visible = evidence_ids(context)
        referenced = evidence_ids(output) | set(re.findall(r"\bEV-\d+\b", json.dumps(output)))
        if not referenced <= visible or not referenced <= self.store.records.keys():
            raise ValueError("Unknown or unpresented evidence reference")
        hypotheses = context.get("hypotheses", [])
        hids = {h["hypothesis_id"] for h in hypotheses}
        if role == "hypothesis_agent":
            generated = output["hypotheses"]
            if (output["status"] == "generated") != bool(generated):
                raise ValueError("Hypothesis status/list mismatch")
            ids = [h["hypothesis_id"] for h in generated]
            if len(set(ids)) != len(ids):
                raise ValueError("Duplicate hypothesis IDs")
            old = {h["hypothesis_id"]: h for h in hypotheses}
            for h in generated:
                if h["hypothesis_id"] in old and h["testable_prediction"] != old[h["hypothesis_id"]]["testable_prediction"]:
                    raise ValueError("A changed prediction requires a new hypothesis ID")
        elif role == "orchestrator":
            if output["decision"] == "investigate":
                if output["tool_name"] not in TOOL_ARGUMENTS or output["stop_reason"] is not None:
                    raise ValueError("Invalid investigation decision")
                Draft202012Validator(TOOL_ARGUMENTS[output["tool_name"]]).validate(output["arguments"])
            else:
                if output["tool_name"] is not None or output["arguments"]:
                    raise ValueError("Non-tool decision cannot contain a tool invocation")
                if (output["decision"] == "stop") != (output["stop_reason"] is not None):
                    raise ValueError("Invalid stop reason")
        elif role == "evidence_evaluator":
            expected = {(h, eid) for h in hids for eid in context.get("new_evidence_ids", [])}
            pairs = [(v["hypothesis_id"], v["evidence_id"]) for v in output["evaluations"]]
            if set(pairs) != expected or len(set(pairs)) != len(pairs):
                raise ValueError("Evaluator must cover each hypothesis/new-evidence pair exactly once")
        elif role == "remediation_agent":
            actions = output["actions"]
            if (output["status"] == "proposed") != bool(actions):
                raise ValueError("Remediation status/list mismatch")
            if len({a["action_id"] for a in actions}) != len(actions):
                raise ValueError("Duplicate action IDs")
            assessment = context.get("confidence_assessment", {})
            leading = context.get("leading_hypothesis")
            if actions and (assessment.get("status") != "confirmed" or not leading):
                raise ValueError("Remediation requires a Python-confirmed leading hypothesis")
            records = context.get("evidence", [])
            targets = {r[k] for r in records for k in ("service", "pod", "node") if isinstance(r.get(k), str)}
            for action in actions:
                if action["target"] not in targets:
                    raise ValueError("Remediation target not observed in evidence")
                if not set(action["evidence_ids"]) & set(leading["initial_evidence_ids"]):
                    raise ValueError("Remediation must cite the leading hypothesis evidence")
                Draft202012Validator(ACTION_PARAMETERS[action["action_type"]]).validate(action["parameters"])
                cited = [r for r in records if r["evidence_id"] in action["evidence_ids"]]
                if not any(action["target"] in (r.get("service"), r.get("pod"), r.get("node")) for r in cited):
                    raise ValueError("Target must appear in action's cited evidence")
                for key, value in action["parameters"].items():
                    aliases = {"version": ("version", "previous_version", "from_version"),
                               "key": ("key", "config_key", "flag"),
                               "value": ("old_value", "previous_value"),
                               "replicas": ("replicas", "previous_replicas")}[key]
                    if not any(any(alias in r and r[alias] == value for alias in aliases) or
                               any(isinstance(r.get("parameters"), dict) and alias in r["parameters"] and r["parameters"][alias] == value for alias in aliases)
                               for r in cited):
                        raise ValueError("Exact action parameters require structured evidence; collect it before proposing")
                # Exact action authorization and parameter binding are enforced in Phase 5.
        return output

    def call(self, role, context):
        if role not in SCHEMAS:
            raise AgentError("Unknown agent role")
        safe_context = redact(context, secrets=(self.config.api_key,))
        rejection_reason = None
        for attempt in range(2):
            messages, prompt_bytes = self.messages(role, safe_context, retry=bool(attempt), rejection_reason=rejection_reason)
            presented_context = strict_json(messages[1]["content"])["context"]
            if (self.requests >= self.config.max_requests or
                    self.reserved_output_tokens + self.config.max_output_tokens > self.config.max_total_output_tokens):
                raise BudgetExceeded("LLM request or aggregate output-token budget exhausted")
            self.requests += 1
            self.reserved_output_tokens += self.config.max_output_tokens
            self.audit.record("agent_call", agent=role, attempt=attempt + 1,
                              mode=self.transport.mode, model=self.config.model,
                              prompt_bytes=prompt_bytes, evidence_ids=sorted(evidence_ids(presented_context)))
            try:
                raw, usage = self.transport.complete(messages, SCHEMAS[role], role)
                self.usage.append({"agent": role, "attempt": attempt + 1, "provider_usage": usage})
                if not isinstance(raw, str) or len(raw.encode("utf-8")) > 100_000:
                    raise ValueError("Agent output exceeds response bound")
                output = strict_json(raw)
                self.validate(role, output, presented_context)
            except (ValueError, ValidationError) as exc:
                # Validation errors may contain raw telemetry; keep only their category.
                rejection_reason = ("Schema violation: " + str(exc.validator) + " at " + "/".join(map(str, exc.absolute_path))
                                    if isinstance(exc, ValidationError) else str(exc)[:160])
                self.audit.record("agent_output_rejected", agent=role, attempt=attempt + 1,
                                  error_type=type(exc).__name__, reason=rejection_reason)
                if attempt:
                    raise AgentError(f"{role}: output validation failed after one retry: {rejection_reason}") from None
                continue
            except AgentError as exc:
                self.audit.record("agent_error", agent=role, error=str(exc))
                raise
            safe_output = redact(output, secrets=(self.config.api_key,))
            self.transcripts.append({"agent": role, "mode": self.transport.mode,
                                     "input_messages": messages, "validated_output": safe_output})
            self.audit.record("agent_output_validated", agent=role, output=safe_output,
                              evidence_ids=sorted(evidence_ids(output)), provider_usage=usage)
            return output


def compact_record(record):
    record = redact(copy.deepcopy(record))
    # Do not send optional user identifiers or full stack dumps to the model.
    allowed = {"evidence_id", "source", "original_source", "id", "ts", "service", "pod", "node", "level",
               "message", "version", "metric", "unit", "value", "request_id", "trace_id", "root_operation",
               "total_duration_ms", "status", "spans", "event", "key", "old_value", "new_value", "parameters",
               "config_key", "flag", "previous_value", "previous_version", "from_version", "replicas", "previous_replicas"}
    result = {k: v for k, v in record.items() if k in allowed}
    for key, value in list(result.items()):
        if isinstance(value, str) and len(value) > 900:
            result[key] = value[:900] + " [TRUNCATED]"
    if isinstance(result.get("spans"), list) and len(result["spans"]) > 12:
        result["spans"] = result["spans"][:12]
        result["spans_truncated"] = True
    return result


def initial_context(store, detection_config=None):
    anomalies, diagnostics = detect_metrics(store, detection_config)
    spikes = detect_log_spikes(store, detection_config)
    timeline = build_timeline(store, anomalies + spikes)
    graph = build_dependency_graph(store)
    chosen, seen = [], set()
    for anomaly in sorted(anomalies, key=lambda a: (a["adverse"] is True, abs(a["z_score"] or 0)), reverse=True):
        key = anomaly["service"], anomaly["metric"]
        if key not in seen:
            seen.add(key)
            chosen.append(anomaly)
        if len(chosen) == 6:
            break
    ids = [eid for a in chosen for eid in a["evidence_ids"] + a["baseline_evidence_ids"][:1]]
    changes, errors, traces = [], [], []
    for record in store.records.values():
        if record["source"] in {"deployments", "config_changes", "alerts"} or (
                record["source"] in {"application_logs", "infra_logs"} and
                re.search(r"\b(?:deploy\w*|version|feature.flag|config\w*|rollout)\b", record.get("message", ""), re.I)):
            changes.append(record["evidence_id"])
        if record["source"] in {"application_logs", "infra_logs"} and record.get("level") in {"ERROR", "FATAL"}:
            errors.append(record["evidence_id"])
        if record["source"] == "traces":
            traces.append(record)
    ids += changes[:2] + changes[-2:] + errors[:1] + errors[-1:]
    failed = [r for r in traces if r.get("status") not in {"SUCCESS", "OK"}]
    ids += [r["evidence_id"] for r in traces[:1] + failed[:1]]
    ids = list(dict.fromkeys(ids))
    context = {"scenario_id": store.scenario_id,
               "source_availability": {k: v for k, v in store.sources.items() if k not in RESERVED},
               "incident_start": timeline["incident_start"],
               "anomalies": [{k: v for k, v in a.items() if k != "baseline_evidence_ids"} |
                              {"baseline_evidence_ids": a["baseline_evidence_ids"][:1]} for a in chosen],
               "timeline": [event for event in timeline["events"] if set(event["evidence_ids"]) & set(ids)][:10],
               "dependency_graph": {"partial": graph["partial"], "uncertainties": graph["uncertainties"],
                                    "edges": [{**edge, "evidence_ids": edge["evidence_ids"][:1]} for edge in graph["edges"][:15]]},
               "evidence": [compact_record(store.records[eid]) for eid in ids],
               "sampling": {"metric_anomaly_total": len(anomalies), "metric_anomalies_shown": len(chosen),
                            "log_spike_total": len(spikes), "selected_evidence_count": len(ids),
                            "warning": "Bounded initial sample, not exhaustive. Query tools for supporting and contradicting records. Baseline assumed healthy, not established."},
               "hypotheses": [], "evaluations": [], "investigation_history": [],
               "confidence_assessment": {"status": "pending_phase4", "reason": "Deterministic confidence engine not yet implemented"}}
    return context


def run_investigation(store, audit, runner, enable_confidence=False, resume=None, confidence_config=None):
    context = initial_context(store, getattr(runner, "detection_config", None))
    tools = InvestigationTools(store, audit)
    evaluations = {}
    steps, replans = [], []
    status = "max_steps"
    failure = None
    graph = build_dependency_graph(store)
    if resume:
        context["hypotheses"] = resume["hypotheses"]
        context["evidence"] += [compact_record(store.records[e]) for e in resume.get("new_evidence_ids", [])]
        evaluations.update({(v["hypothesis_id"], v["evidence_id"]): v for v in resume.get("evaluations", [])})

    def recalculate():
        previous = context["confidence_assessment"].get("leading_hypothesis_id")
        context["confidence_assessment"] = assess(context["hypotheses"], list(evaluations.values()), store,
                                                 graph, context["incident_start"], confidence_config)
        current = context["confidence_assessment"]["leading_hypothesis_id"]
        audit.record("confidence_recalculated", assessment=context["confidence_assessment"])
        if previous and previous != current:
            change = {"reason": "New evidence changed deterministic ranking", "previous_leader": previous,
                      "new_leader": current, "evidence_ids": sorted({v["evidence_id"] for v in evaluations.values()})}
            replans.append(change)
            audit.record("investigation_replanned", **change)

    def evaluate(ids):
        # Four evidence items × at most five hypotheses bounds JSON output size.
        for start in range(0, len(ids), 2):
            batch = ids[start:start + 2]
            evaluation_context = {"hypotheses": context["hypotheses"], "new_evidence_ids": batch,
                                  "incident_start": context["incident_start"], "dependency_graph": context["dependency_graph"],
                                  "evidence": [compact_record(store.records[eid]) for eid in batch]}
            output = runner.call("evidence_evaluator", evaluation_context)
            for value in output["evaluations"]:
                evaluations[(value["hypothesis_id"], value["evidence_id"])] = value
        context["evaluations"] = list(evaluations.values())[-30:]
        if enable_confidence:
            recalculate()
        else:
            audit.record("confidence_recalculation_requested", status="pending_phase4",
                         reason="Classified evidence ready; no LLM confidence substituted")

    try:
        if not resume:
            output = runner.call("hypothesis_agent", context)
            context["hypotheses"] = output["hypotheses"]
        audit.record("hypotheses_changed", hypotheses=redact(context["hypotheses"]))
        if not context["hypotheses"]:
            status = "insufficient_evidence"
        else:
            seed_ids = list(dict.fromkeys(eid for h in context["hypotheses"] for eid in h["initial_evidence_ids"])) if not resume else resume.get("new_evidence_ids", [])
            evaluate(seed_ids)
            previous_calls = set()
            for index in range(runner.config.max_steps):
                if enable_confidence and context["confidence_assessment"]["status"] == "confirmed":
                    status = "root_cause_supported"
                    break
                decision = runner.call("orchestrator", context)
                step = {"step": index + 1, "decision": decision}
                steps.append(step)
                audit.record("investigation_decision", **redact(step))
                if decision["decision"] == "stop":
                    status = "insufficient_evidence" if enable_confidence else decision["stop_reason"]
                    break
                if decision["decision"] == "reconsider":
                    old = context["hypotheses"]
                    revised = runner.call("hypothesis_agent", context)["hypotheses"]
                    replans.append({"step": index + 1, "before": old, "after": revised, "reason": decision["reason"]})
                    context["hypotheses"] = revised
                    evaluations.clear()
                    audit.record("hypotheses_changed", **redact(replans[-1]))
                    if not revised:
                        status = "insufficient_evidence"
                        break
                    evaluate(list(dict.fromkeys([r["evidence_id"] for r in context["evidence"][-4:]] +
                                               [eid for h in revised for eid in h["initial_evidence_ids"]])))
                else:
                    call_key = json.dumps([decision["tool_name"], decision["arguments"]], sort_keys=True)
                    if call_key in previous_calls:
                        step["result"] = {"status": "error", "error": {"code": "REPEATED_CALL", "message": "Identical call already performed"}, "evidence_ids": []}
                        audit.record("tool_call_skipped", reason="repeated_call", tool=decision["tool_name"])
                    else:
                        previous_calls.add(call_key)
                        result = tools.call(decision["tool_name"], decision["arguments"])
                        step["result"] = result
                        if result["status"] in {"ok", "empty"}:
                            # IDs from dependency results are bounded before evaluator batching.
                            new_ids = result["evidence_ids"][:4]
                            context["evidence"] = (context["evidence"] + [compact_record(store.records[eid]) for eid in new_ids])[-24:]
                            if new_ids:
                                evaluate(new_ids)
                # Error/unavailable results go to planning, never to evidence evaluation.
                latest = copy.deepcopy(step)
                if "result" in latest:
                    raw_result = latest["result"]
                    latest["result"] = {k: v for k, v in raw_result.items() if k not in {"records", "evidence_ids", "upstream", "downstream", "potential_blast_radius"}}
                    latest["result"]["evidence_ids"] = raw_result["evidence_ids"][:4]
                    latest["result"]["omitted_evidence_count"] = max(0, len(raw_result["evidence_ids"]) - 4)
                context["investigation_history"] = (context["investigation_history"] + [latest])[-3:]
    except BudgetExceeded as exc:
        status, failure = "budget_exhausted", str(exc)
    except AgentError as exc:
        status, failure = "agent_unavailable", str(exc)
    if enable_confidence:
        recalculate()
        if context["confidence_assessment"]["status"] == "confirmed" and failure is None:
            status = "root_cause_supported"
    root = next((h for h in context["hypotheses"] if h["hypothesis_id"] == context["confidence_assessment"].get("leading_hypothesis_id")), None) if context["confidence_assessment"]["status"] == "confirmed" and failure is None else None
    audit.record("investigation_stopped", status=status, error=failure,
                 root_cause_status=context["confidence_assessment"]["status"], simulated_action_executed=False)
    return {"phase": 4 if enable_confidence else 3, "mode": runner.transport.mode, "scenario_id": store.scenario_id,
            "status": status, "error": failure, "hypotheses": context["hypotheses"],
            "evaluations": list(evaluations.values()), "investigation_steps": redact(steps),
            "replanning_history": redact(replans), "root_cause": root,
            "confidence_assessment": context["confidence_assessment"],
            "agent_transcripts": runner.transcripts, "usage": runner.usage,
            "requests": runner.requests, "reserved_output_tokens": runner.reserved_output_tokens,
            "audit_log": redact(audit.events), "simulated_action_executed": False}
