"""Caller -> dependency graph. Relationships require explicit or trace evidence."""
from collections import Counter, defaultdict, deque


def build_dependency_graph(store):
    edges = defaultdict(set)
    nodes = set()
    node_evidence = defaultdict(set)
    paths, issues = [], []
    explicit_count = 0
    for eid, record in store.records.items():
        if record["source"] == "dependencies":
            # Explicit supported schema: caller/callee or service/depends_on.
            caller = record.get("caller", record.get("service"))
            targets = record.get("callee", record.get("depends_on"))
            targets = targets if isinstance(targets, list) else [targets]
            if not isinstance(caller, str) or not caller.strip() or not targets or any(not isinstance(t, str) or not t.strip() for t in targets):
                issues.append({"evidence_ids": [eid], "reason": "Unsupported dependency schema; expected caller/callee or service/depends_on"})
                continue
            for target in targets:
                nodes.update((caller, target))
                node_evidence[caller].add(eid)
                node_evidence[target].add(eid)
                if caller != target:
                    edges[(caller, target)].add(eid)
                    explicit_count += 1
        if record["source"] != "traces":
            continue
        spans = [s for s in record["spans"] if isinstance(s.get("span_id"), str) and
                 (s.get("parent_span_id") is None or isinstance(s.get("parent_span_id"), str))]
        if len(spans) != len(record["spans"]):
            issues.append({"evidence_ids": [eid], "reason": "Invalid span identifiers excluded"})
        counts = Counter(s["span_id"] for s in spans)
        by_id = {s["span_id"]: s for s in spans if counts[s["span_id"]] == 1}
        if any(count > 1 for count in counts.values()):
            issues.append({"evidence_ids": [eid], "reason": "Duplicate span IDs; ambiguous spans excluded"})
        valid_edges = []
        for span in by_id.values():
            service = span.get("service")
            if not isinstance(service, str) or not service:
                issues.append({"evidence_ids": [eid], "reason": "Span service missing or invalid"})
                continue
            nodes.add(service)
            node_evidence[service].add(eid)
            parent_id = span["parent_span_id"]
            if parent_id is None:
                continue
            parent = by_id.get(parent_id)
            if parent is None:
                issues.append({"evidence_ids": [eid], "reason": "Missing or ambiguous parent span", "span_id": span["span_id"]})
                continue
            # A cyclic parent chain cannot establish a request path.
            seen, cursor = {span["span_id"]}, parent
            while cursor is not None and cursor["span_id"] not in seen:
                seen.add(cursor["span_id"])
                cursor = by_id.get(cursor["parent_span_id"])
            if cursor is not None:
                issues.append({"evidence_ids": [eid], "reason": "Cyclic span ancestry", "span_id": span["span_id"]})
                continue
            caller = parent.get("service")
            if not isinstance(caller, str) or not caller:
                continue
            valid_edges.append({"parent_span_id": parent_id, "span_id": span["span_id"],
                                "caller": caller, "callee": service})
            if caller != service:
                edges[(caller, service)].add(eid)
        # A tree/edge representation preserves branching; list order is not a call chain.
        paths.append({"trace_id": record["trace_id"], "request_id": record["request_id"],
                      "root_operation": record["root_operation"], "timestamp": record["ts"],
                      "roots": [s["span_id"] for s in by_id.values() if s["parent_span_id"] is None],
                      "services": sorted({s["service"] for s in by_id.values() if isinstance(s.get("service"), str) and s["service"]}),
                      "span_edges": valid_edges, "evidence_ids": [eid]})
    return {"nodes": sorted(nodes),
            "node_evidence": {n: sorted(ids) for n, ids in sorted(node_evidence.items())},
            "edges": [{"caller": a, "callee": b, "evidence_ids": sorted(ids)} for (a, b), ids in sorted(edges.items())],
            "request_paths": paths, "partial": True,
            "uncertainties": ["Observed relationships only; telemetry cannot establish graph completeness."] +
                (["No usable explicit dependency relationships; graph is trace-derived."] if not explicit_count else []),
            "issues": issues}


def relationships(graph, service):
    def traverse(reverse=False):
        adjacency = defaultdict(list)
        for edge in graph["edges"]:
            a, b = (edge["callee"], edge["caller"]) if reverse else (edge["caller"], edge["callee"])
            adjacency[a].append((b, edge["evidence_ids"]))
        queue = deque([(service, [], 0)])
        seen, result = {service}, []
        while queue:
            current, proof, distance = queue.popleft()
            for target, ids in adjacency[current]:
                if target in seen:
                    continue
                seen.add(target)
                evidence = sorted(set(proof + ids))
                result.append({"service": target, "distance": distance + 1, "evidence_ids": evidence})
                queue.append((target, evidence, distance + 1))
        return sorted(result, key=lambda r: (r["distance"], r["service"]))
    upstream, downstream = traverse(True), traverse()
    return {"service": service, "known": service in graph["nodes"], "upstream": upstream,
            "downstream": downstream, "potential_blast_radius": upstream,
            "partial": graph["partial"],
            "uncertainties": graph["uncertainties"] + ["Reachability indicates potential exposure, not observed failure."]}


def request_path_membership(graph, service, trace_id):
    paths = [p for p in graph["request_paths"] if p["trace_id"] == trace_id]
    if not paths:
        return {"status": "unavailable", "evidence_ids": []}
    matched = [p for p in paths if service in p["services"]]
    return {"status": "observed" if matched else "not_observed", "service": service,
            "evidence_ids": sorted({eid for p in (matched or paths) for eid in p["evidence_ids"]})}
