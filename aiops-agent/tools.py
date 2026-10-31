"""Registered read-only tools. Literal text search, bounded pages, explicit failures."""
import copy
import inspect
from loader import timestamp
from dependency_engine import build_dependency_graph, relationships


def text(value, name, optional=False):
    if value is None and optional:
        return
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"{name} must be a nonempty string of at most 512 characters")


def time_bounds(time_range):
    if time_range is None:
        return None
    if not isinstance(time_range, dict) or set(time_range) != {"start", "end"}:
        raise ValueError("time_range must contain start and end timestamps")
    start, end = timestamp(time_range["start"]), timestamp(time_range["end"])
    if start >= end:
        raise ValueError("time_range start must precede end (end is exclusive)")
    return start, end


def select(store, sources, *, service=None, time_range=None, term=None, metric=None, limit=100, offset=0):
    text(service, "service", optional=True)
    text(term, "search text", optional=True)
    text(metric, "metric", optional=True)
    bounds = time_bounds(time_range)
    if type(limit) is not int or not 1 <= limit <= 500 or type(offset) is not int or offset < 0:
        raise ValueError("limit must be 1..500 and offset a nonnegative integer")
    statuses = {s: store.sources.get(s, {"status": "missing"})["status"] for s in sources}
    usable = [s for s, status in statuses.items() if status in {"available", "partially_valid"}]
    base = {"source_status": statuses, "evidence_ids": [], "records": [], "total_matches": 0,
            "offset": offset, "limit": limit, "next_offset": None}
    if not usable:
        return {**base, "status": "unavailable", "error": {"code": "SOURCE_UNAVAILABLE", "message": "Required sources are missing or invalid"}}
    found, unavailable_times = [], 0
    for record in store.records.values():
        if record["source"] not in usable:
            continue
        if service is not None:
            if record["source"] == "traces":
                if not any(s.get("service") == service for s in record["spans"]):
                    continue
            elif service not in (record.get("service"), record.get("node"), record.get("pod")):
                continue
        if metric is not None and record.get("metric") != metric:
            continue
        if bounds:
            if not record.get("ts"):
                unavailable_times += 1
                continue
            if not bounds[0] <= record["ts"] < bounds[1]:
                continue
        if term is not None:
            # Search values only; IDs and schema field names aren't symptoms.
            def strings(value):
                if isinstance(value, str):
                    yield value
                elif isinstance(value, dict):
                    for key, child in value.items():
                        if key not in {"id", "evidence_id", "source"}:
                            yield from strings(child)
                elif isinstance(value, list):
                    for child in value:
                        yield from strings(child)
            if not any(term.casefold() in value.casefold() for value in strings(record)):
                continue
        found.append(record)
    found.sort(key=lambda r: (r.get("ts", ""), r["evidence_id"]))
    page = found[offset:offset + limit]
    return {**base, "status": "ok" if found else "empty", "records": copy.deepcopy(page),
            "total_matches": len(found), "evidence_ids": [r["evidence_id"] for r in page],
            "next_offset": offset + limit if offset + limit < len(found) else None,
            "uncertainties": (["Some sources missing or invalid; results are partial"] if len(usable) < len(sources) or any(v == "partially_valid" for v in statuses.values()) else []) +
                ([f"{unavailable_times} records excluded because timestamp unavailable"] if unavailable_times else [])}


def query_logs(store, service=None, time_range=None, pattern=None, limit=100, offset=0):
    return select(store, ("application_logs", "infra_logs"), service=service, time_range=time_range, term=pattern, limit=limit, offset=offset)


def query_metrics(store, service=None, metric=None, time_range=None, limit=100, offset=0):
    return select(store, ("metrics",), service=service, metric=metric, time_range=time_range, limit=limit, offset=offset)


def get_traces(store, service=None, time_range=None, limit=100, offset=0):
    return select(store, ("traces",), service=service, time_range=time_range, limit=limit, offset=offset)


def get_alerts(store, time_range=None, limit=100, offset=0):
    return select(store, ("alerts",), time_range=time_range, limit=limit, offset=offset)


def get_deployments(store, time_range=None, limit=100, offset=0):
    return select(store, ("deployments",), time_range=time_range, limit=limit, offset=offset)


def get_config_changes(store, time_range=None, limit=100, offset=0):
    return select(store, ("config_changes",), time_range=time_range, limit=limit, offset=offset)


def search_past_incidents(store, symptoms, limit=100, offset=0):
    text(symptoms, "symptoms")
    return select(store, ("past_incidents",), term=symptoms, limit=limit, offset=offset)


def search_support_tickets(store, keywords, limit=100, offset=0):
    text(keywords, "keywords")
    return select(store, ("support_tickets",), term=keywords, limit=limit, offset=offset)


def get_dependencies(store, service):
    text(service, "service")
    graph = build_dependency_graph(store)
    if not graph["nodes"]:
        return {"status": "unavailable", "evidence_ids": [], "error": {"code": "SOURCE_UNAVAILABLE", "message": "No usable trace or dependency relationships"}}
    result = relationships(graph, service)
    ids = sorted(set(graph["node_evidence"].get(service, [])) |
                 {eid for edge in result["upstream"] + result["downstream"] for eid in edge["evidence_ids"]})
    return {"status": "ok" if result["known"] else "empty", **result, "evidence_ids": ids,
            "source_status": {s: store.sources.get(s, {"status": "missing"})["status"] for s in ("dependencies", "traces")}}


REGISTRY = {f.__name__: f for f in (query_logs, query_metrics, get_traces, get_alerts,
           get_deployments, get_config_changes, get_dependencies, search_past_incidents, search_support_tickets)}


class InvestigationTools:
    """Only this audited dispatcher is exposed to agents in the next phase."""
    def __init__(self, store, audit):
        self.store, self.audit = store, audit

    def call(self, name, arguments=None):
        call_id = self.audit.record("tool_call", tool=name, arguments=arguments)
        try:
            if not isinstance(name, str) or name not in REGISTRY:
                raise ValueError("Unregistered investigation tool")
            if arguments is None:
                arguments = {}
            if not isinstance(arguments, dict) or "store" in arguments:
                raise ValueError("Tool arguments must be an object without store access")
            inspect.signature(REGISTRY[name]).bind(self.store, **arguments)
            result = REGISTRY[name](self.store, **arguments)
            if any(eid not in self.store.records for eid in result["evidence_ids"]):
                raise RuntimeError("Tool returned invalid evidence references")
        except (ValueError, TypeError) as exc:
            result = {"status": "error", "error": {"code": "INVALID_ARGUMENTS", "message": str(exc)}, "evidence_ids": []}
        except Exception as exc:
            result = {"status": "error", "error": {"code": "TOOL_ERROR", "message": f"{type(exc).__name__}: {exc}"}, "evidence_ids": []}
        audit_id = self.audit.record("tool_error" if result["status"] in {"error", "unavailable"} else "tool_result",
                                     call_id=call_id, tool=name, result=result,
                                     evidence_ids=result["evidence_ids"])
        return {**result, "call_id": call_id, "audit_id": audit_id}
