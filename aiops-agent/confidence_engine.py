"""Documented evidence-weighted heuristic, never a calibrated probability."""
import math
import re
from dataclasses import dataclass
from datetime import datetime
from dependency_engine import relationships


@dataclass
class ConfidenceConfig:
    threshold: float = 0.65
    margin: float = 0.15
    min_support: int = 2
    saturation: float = 2.0


RELIABILITY = {"metrics": 0.95, "traces": 0.9, "application_logs": 0.8, "infra_logs": 0.85,
               "deployments": 0.9, "config_changes": 0.9, "alerts": 0.7,
               "past_incidents": 0.35, "support_tickets": 0.4}


def services(record):
    return {s for s in [record.get("service")] + [p.get("service") for p in record.get("spans", [])] if isinstance(s, str)}


def hypothesis_services(hypothesis, store):
    # Anchor only services actually named in the statement/prediction and cited records.
    records = [store.records[e] for e in hypothesis["initial_evidence_ids"] if e in store.records]
    observed = set().union(*(services(r) for r in records)) if records else set()
    text = hypothesis["statement"] + " " + hypothesis["testable_prediction"]
    named = {s for s in observed if s.casefold() in text.casefold()}
    return named or observed


def assess(hypotheses, evaluations, store, graph, incident_start=None, config=None):
    config = config or ConfidenceConfig()
    if not 0 < config.threshold <= 1 or not 0 <= config.margin <= 1 or config.min_support < 1 or config.saturation <= 0:
        raise ValueError("Invalid confidence configuration")
    onset = (incident_start or {}).get("timestamp")
    onset = datetime.fromisoformat(onset) if onset else None
    latest = {(e["hypothesis_id"], e["evidence_id"]): e for e in evaluations}
    rankings = []
    for hypothesis in hypotheses:
        targets = hypothesis_services(hypothesis, store)
        related = set()
        for target in targets:
            rel = relationships(graph, target)
            related.update(r["service"] for r in rel["upstream"] + rel["downstream"])
        breakdown, support, contradictions, neutral, uncertainties = [], [], [], [], []
        critical = []
        for (hid, eid), evaluation in latest.items():
            if hid != hypothesis["hypothesis_id"]:
                continue
            if eid not in store.records:
                raise ValueError("Unknown evidence ID in confidence evaluation")
            record = store.records[eid]
            classification = evaluation["classification"]
            direction = {"supports": 1, "contradicts": -1, "neutral": 0}[classification]
            direction *= 1 if evaluation["strength"] == "strong" else 0.5
            relevance = float(evaluation["relevance"])
            if not math.isfinite(relevance) or not 0 <= relevance <= 1:
                raise ValueError("Invalid evidence relevance")
            entities = services(record)
            dependency = 1.0 if entities & targets else 0.65 if entities & related else 0.1 if entities and targets else 0.4
            if dependency == 0.4:
                uncertainties.append("Unknown dependency relationship")
            ts = datetime.fromisoformat(record["ts"]) if record.get("ts") else None
            timing = 1.0 if ts and onset and ts <= onset else 0.5
            timing_reason = "before_or_at_signal" if timing == 1 else "uncertain"
            # Later symptom observations can support mechanism, but cannot establish causal precedence.
            is_change = record["source"] in {"deployments", "config_changes"} or bool(re.search(
                r"\b(?:deploy\w*|rollout|config(?:uration)?\s+(?:changed|updated)|feature.flag\s+(?:enabled|disabled))\b",
                str(record.get("message", "")), re.I))
            if ts and onset and ts > onset:
                timing_reason = "change_after_symptom" if is_change else "observation_after_symptom"
                timing = 0 if direction > 0 else 1
                if direction > 0 and is_change:
                    critical.append({"evidence_id": eid, "reason": "Alleged causal change occurs after symptom", "evaluated": True})
            elif not ts or not onset:
                uncertainties.append("Causal timing not established")
            reliability = RELIABILITY.get(record["source"], 0.5)
            contribution = reliability * relevance * timing * dependency * direction
            breakdown.append({"evidence_id": eid, "classification": classification, "strength": evaluation["strength"],
                              "reliability_weight": reliability, "relevance_weight": relevance,
                              "timing_weight": timing, "timing_reason": timing_reason,
                              "dependency_weight": dependency, "evidence_direction": direction,
                              "contribution": contribution, "reason": evaluation["reason"]})
            {"supports": support, "contradicts": contradictions, "neutral": neutral}[classification].append(eid)
            if classification == "contradicts" and evaluation["strength"] == "strong" and relevance >= 0.7 and dependency >= 0.65:
                critical.append({"evidence_id": eid, "reason": evaluation["reason"], "evaluated": True})
        raw = sum(row["contribution"] for row in breakdown)
        positive = sum(max(0, row["contribution"]) for row in breakdown)
        negative = -sum(min(0, row["contribution"]) for row in breakdown)
        # Fixed saturation prevents adding neutral items from improving scores.
        score = max(0, raw) / (config.saturation + positive + negative)
        meaningful = [r["evidence_id"] for r in breakdown if r["contribution"] >= 0.2]
        if graph.get("partial"):
            uncertainties.append("Dependency coverage is partial")
        if any(v.get("status") in {"missing", "invalid"} for v in store.sources.values()):
            uncertainties.append("Some telemetry sources unavailable")
        rankings.append({"hypothesis_id": hypothesis["hypothesis_id"], "score": score, "raw_score": raw,
                         "supporting_evidence_ids": support, "contradicting_evidence_ids": contradictions,
                         "neutral_evidence_ids": neutral, "sufficient_support": len(set(meaningful)) >= config.min_support,
                         "critical_contradictions": critical, "breakdown": breakdown,
                         "uncertainties": sorted(set(uncertainties))})
    rankings.sort(key=lambda r: (-r["score"], r["hypothesis_id"]))
    top = rankings[0] if rankings else None
    margin = top["score"] - (rankings[1]["score"] if len(rankings) > 1 else 0) if top else 0
    confirmed = bool(top and top["score"] >= config.threshold and margin >= config.margin and
                     top["sufficient_support"] and not top["critical_contradictions"])
    return {"status": "confirmed" if confirmed else "insufficient_evidence", "rankings": rankings,
            "leading_hypothesis_id": top["hypothesis_id"] if top else None, "margin": margin,
            "threshold": config.threshold, "minimum_margin": config.margin,
            "method": "max(0,sum(weight products))/(saturation + positive mass + contradiction mass); heuristic, not calibrated probability"}
