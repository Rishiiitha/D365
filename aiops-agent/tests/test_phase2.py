import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from audit_log import AuditLog
from dependency_engine import build_dependency_graph, relationships, request_path_membership
from loader import EvidenceStore
from tools import InvestigationTools, REGISTRY


def span(sid, parent, service):
    return {"span_id": sid, "parent_span_id": parent, "service": service}


def add_trace(store, spans, trace_id="t1"):
    eid = store.add({"id": trace_id, "ts": "2026-01-01T00:00:00+00:00", "trace_id": trace_id,
                     "request_id": "r1", "root_operation": "GET /example", "spans": spans},
                    "traces", "traces.jsonl", 0)
    store.sources["traces"] = {"status": "available"}
    return eid


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.store = EvidenceStore("test")

    def test_branching_parent_relationships_and_blast_radius(self):
        eid = add_trace(self.store, [span("1", None, "gateway"), span("2", "1", "orders"),
                                   span("3", "2", "database"), span("4", "1", "inventory")])
        graph = build_dependency_graph(self.store)
        edges = {(e["caller"], e["callee"]) for e in graph["edges"]}
        self.assertEqual(edges, {("gateway", "orders"), ("orders", "database"), ("gateway", "inventory")})
        result = relationships(graph, "database")
        self.assertEqual([(r["service"], r["distance"]) for r in result["upstream"]], [("orders", 1), ("gateway", 2)])
        self.assertTrue(all(r["evidence_ids"] == [eid] for r in result["upstream"]))
        self.assertTrue(graph["partial"])
        self.assertEqual(request_path_membership(graph, "database", "t1")["status"], "observed")
        self.assertEqual(request_path_membership(graph, "other", "t1")["status"], "not_observed")

    def test_orphan_duplicate_and_cycle_do_not_invent_edges(self):
        add_trace(self.store, [span("1", "2", "a"), span("2", "1", "b"),
                              span("3", "missing", "c"), span("4", None, "d"), span("4", None, "e")])
        graph = build_dependency_graph(self.store)
        self.assertEqual(graph["edges"], [])
        self.assertGreaterEqual(len(graph["issues"]), 4)

    def test_single_span_membership_and_self_calls(self):
        add_trace(self.store, [span("1", None, "solo"), span("2", "1", "solo")])
        graph = build_dependency_graph(self.store)
        self.assertEqual(graph["edges"], [])
        self.assertEqual(request_path_membership(graph, "solo", "t1")["status"], "observed")

    def test_explicit_schema_and_graph_cycle(self):
        for i, (a, b) in enumerate([("a", "b"), ("b", "a")]):
            self.store.add({"caller": a, "callee": b}, "dependencies", "dependencies.json", i)
        graph = build_dependency_graph(self.store)
        result = relationships(graph, "a")
        self.assertEqual(len(result["downstream"]), 1)
        self.assertEqual(result["downstream"][0]["service"], "b")
        self.assertEqual(request_path_membership(graph, "a", "unknown")["status"], "unavailable")


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.store = EvidenceStore("test")
        self.audit = AuditLog()
        self.tools = InvestigationTools(self.store, self.audit)
        self.store.sources["application_logs"] = {"status": "available"}
        for i, message in enumerate(["database timeout", "database timeout", "healthy"]):
            self.store.add({"id": str(i), "service": "svc", "ts": f"2026-01-01T00:0{i}:00+00:00",
                            "message": message}, "application_logs", "application_logs.jsonl", i)

    def test_log_filter_pagination_copy_and_audit(self):
        result = self.tools.call("query_logs", {"service": "svc", "pattern": "timeout", "limit": 1})
        self.assertEqual(result["total_matches"], 2)
        self.assertEqual(result["next_offset"], 1)
        self.assertEqual(len(result["records"]), 1)
        result["records"][0]["message"] = "mutated"
        self.assertEqual(self.store.records["EV-000001"]["message"], "database timeout")
        self.assertEqual(self.audit.events[1]["result"]["records"][0]["message"], "database timeout")
        self.assertEqual(self.audit.events[0]["event_type"], "tool_call")

    def test_time_range_is_utc_and_end_exclusive(self):
        result = self.tools.call("query_logs", {"time_range": {"start": "2026-01-01T05:30:00+05:30", "end": "2026-01-01T00:01:00Z"}})
        self.assertEqual(result["total_matches"], 1)

    def test_invalid_arguments_and_registry_are_audited(self):
        for name, args in [("exec", {}), ("query_logs", {"limit": True}),
                           ("query_logs", {"unknown": 1}), ("query_logs", {"store": "injected"}),
                           ("query_logs", {"service": []}), ("query_logs", {"offset": -1}),
                           ("query_logs", {"time_range": {"start": "yesterday", "end": "today"}})]:
            with self.subTest(name=name, args=args):
                result = self.tools.call(name, args)
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["evidence_ids"], [])
                self.assertEqual(self.audit.events[-1]["event_type"], "tool_error")

    def test_empty_is_distinct_from_unavailable(self):
        self.assertEqual(self.tools.call("query_logs", {"pattern": "does-not-exist"})["status"], "empty")
        for name in ("get_alerts", "get_deployments", "get_config_changes"):
            result = self.tools.call(name)
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["error"]["code"], "SOURCE_UNAVAILABLE")

    def test_searches_return_real_optional_records(self):
        for source, name, argument in [("past_incidents", "search_past_incidents", "symptoms"),
                                       ("support_tickets", "search_support_tickets", "keywords")]:
            self.assertEqual(self.tools.call(name, {argument: "timeout"})["status"], "unavailable")
            self.store.sources[source] = {"status": "available"}
            eid = self.store.add({"summary": "Database Timeout"}, source, source + ".json", 0)
            result = self.tools.call(name, {argument: "timeout"})
            self.assertEqual(result["evidence_ids"], [eid])

    def test_present_optional_time_filters_and_missing_timestamps(self):
        for source, name in [("alerts", "get_alerts"), ("deployments", "get_deployments"),
                             ("config_changes", "get_config_changes")]:
            self.store.sources[source] = {"status": "available"}
            eid = self.store.add({"ts": "2026-01-01T00:00:00+00:00", "summary": "observed change"}, source, source + ".json", 0)
            self.store.add({"summary": "undated change"}, source, source + ".json", 1)
            result = self.tools.call(name, {"time_range": {"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:01:00Z"}})
            self.assertEqual(result["evidence_ids"], [eid])
            self.assertTrue(result["uncertainties"])

    def test_original_infrastructure_source_preserved(self):
        eid = self.store.add({"source": "kubelet", "message": "actual source"}, "infra_logs", "infra_logs.jsonl", 0)
        self.assertEqual(self.store.records[eid]["source"], "infra_logs")
        self.assertEqual(self.store.records[eid]["original_source"], "kubelet")

    def test_metric_and_trace_filters(self):
        self.store.sources["metrics"] = {"status": "available"}
        eid = self.store.add({"service": "svc", "metric": "latency_ms", "value": 100}, "metrics", "metrics.json", 0)
        self.assertEqual(self.tools.call("query_metrics", {"metric": "latency_ms"})["evidence_ids"], [eid])
        trace_eid = add_trace(self.store, [span("1", None, "svc")])
        self.assertEqual(self.tools.call("get_traces", {"service": "svc"})["evidence_ids"], [trace_eid])
        self.assertEqual(self.tools.call("get_dependencies", {"service": "svc"})["evidence_ids"], [trace_eid])

    def test_tool_exception_is_error_not_evidence(self):
        with patch.dict(REGISTRY, {"query_logs": lambda store: 1 / 0}):
            result = self.tools.call("query_logs")
        self.assertEqual(result["error"]["code"], "TOOL_ERROR")
        self.assertEqual(result["evidence_ids"], [])

    def test_audit_persistence_and_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "audit.jsonl"
            audit = AuditLog(path)
            data = {"value": [1]}
            audit.record("decision", data=data)
            data["value"].append(2)
            audit2 = AuditLog(path)
            self.assertEqual(audit2.record("decision"), "AUD-000002")
            self.assertEqual(json.loads(path.read_text().splitlines()[0])["data"]["value"], [1])


if __name__ == "__main__":
    unittest.main()
