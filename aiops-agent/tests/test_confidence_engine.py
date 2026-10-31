import unittest
from confidence_engine import ConfidenceConfig, assess
from dependency_engine import build_dependency_graph
from loader import EvidenceStore


def setup_evidence():
    store = EvidenceStore("controlled")
    ids = [store.add({"id": str(i), "service": "worker", "ts": "2026-01-01T00:00:00+00:00"}, "application_logs", "logs.json", i) for i in range(10)]
    hs = [{"hypothesis_id": "H-1", "statement": "worker exhaustion", "testable_prediction": "worker recovers", "initial_evidence_ids": ids[:2]},
          {"hypothesis_id": "H-2", "statement": "worker dependency failure", "testable_prediction": "worker dependency fails", "initial_evidence_ids": ids[:2]}]
    return store, ids, hs


def evaluation(hid, eid, classification="supports", strength="strong"):
    return {"hypothesis_id": hid, "evidence_id": eid, "classification": classification, "strength": strength,
            "relevance": 1, "reason": "Controlled prediction check"}


class ConfidenceTests(unittest.TestCase):
    def setUp(self):
        self.store, self.ids, self.hs = setup_evidence()
        self.graph = build_dependency_graph(self.store)
        self.onset = {"timestamp": "2026-01-01T00:01:00+00:00"}

    def score(self, ev, hs=None):
        return assess(hs or self.hs, ev, self.store, self.graph, self.onset)

    def test_support_increases_contradiction_decreases(self):
        ev = [evaluation("H-1", e) for e in self.ids[:5]]
        before = self.score(ev)["rankings"][0]["score"]
        more = self.score(ev + [evaluation("H-1", self.ids[5])])["rankings"][0]["score"]
        less = self.score(ev + [evaluation("H-1", self.ids[5], "contradicts")])["rankings"][0]["score"]
        self.assertGreater(more, before)
        self.assertLess(less, before)

    def test_late_change_cannot_establish_cause(self):
        eid = self.store.add({"service": "worker", "ts": "2026-01-01T00:02:00+00:00"}, "deployments", "deployments.json", 0)
        row = self.score([evaluation("H-1", eid)])["rankings"][0]
        self.assertEqual(row["score"], 0)
        self.assertEqual(row["breakdown"][0]["timing_weight"], 0)
        self.assertTrue(row["critical_contradictions"])

    def test_unrelated_service_low_weight(self):
        eid = self.store.add({"service": "unrelated", "ts": "2026-01-01T00:00:00+00:00"}, "application_logs", "logs.json", 11)
        row = self.score([evaluation("H-1", eid)])["rankings"][0]
        self.assertEqual(row["breakdown"][0]["dependency_weight"], 0.1)

    def test_late_metric_cannot_establish_earlier_cause(self):
        eid = self.store.add({"service": "worker", "ts": "2026-01-01T00:02:00+00:00"}, "metrics", "metrics.json", 0)
        row = self.score([evaluation("H-1", eid)])["rankings"][0]
        self.assertEqual(row["score"], 0)

    def test_close_competition_never_forces_root(self):
        ev = [evaluation(h, e) for h in ("H-1", "H-2") for e in self.ids]
        result = self.score(ev)
        self.assertGreater(result["rankings"][0]["score"], result["threshold"])
        self.assertEqual(result["status"], "insufficient_evidence")

    def test_late_contradictions_change_ranking(self):
        ev = [evaluation("H-1", e) for e in self.ids[:6]] + [evaluation("H-2", e) for e in self.ids[:2]]
        self.assertEqual(self.score(ev)["leading_hypothesis_id"], "H-1")
        ev += [evaluation("H-1", e, "contradicts") for e in self.ids[6:]] + [evaluation("H-2", e) for e in self.ids[6:]]
        self.assertEqual(self.score(ev)["leading_hypothesis_id"], "H-2")

    def test_deduplicate_and_unknown_ids(self):
        ev = evaluation("H-1", self.ids[0])
        self.assertEqual(self.score([ev])["rankings"], self.score([ev, ev])["rankings"])
        with self.assertRaises(ValueError):
            self.score([evaluation("H-1", "EV-999999")])

    def test_critical_contradiction_blocks_conclusion(self):
        ev = [evaluation("H-1", e) for e in self.ids] + [evaluation("H-1", self.ids[-1], "contradicts")]
        self.assertEqual(self.score(ev)["status"], "insufficient_evidence")


if __name__ == "__main__":
    unittest.main()
