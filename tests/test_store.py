import tempfile
import unittest
from pathlib import Path

from elm import ELMConfig, ELMStore


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "elm.sqlite"
        self.store = ELMStore(self.db, ELMConfig(enabled=True, retrieval_enabled=True, injection_enabled=True))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_schema_and_idempotent_event(self):
        a = self.store.add_event(scope="private:1", event_type="user_message", idempotency_key="m1", provenance="real_conversation")
        b = self.store.add_event(scope="private:1", event_type="user_message", idempotency_key="m1", provenance="real_conversation")
        self.assertEqual(a, b)
        self.assertEqual(self.store.counts()["learning_events"], 1)
        self.assertEqual(self.store.verify(), [])

    def test_scope_and_evidence_lifecycle(self):
        event = self.store.add_event(scope="private:1", event_type="explicit_feedback", idempotency_key="m2", provenance="explicit_feedback", explicit_feedback=True)
        exp = self.store.create_experience(scope="private:1", hypothesis="使用更自然的短句", scene="chat")
        self.store.add_evidence(experience_id=exp, event_id=event, direction="positive", strength=0.9)
        self.assertEqual(self.store.get_experience(exp)["state"], "testing")
        self.assertEqual(self.store.retrieve(scope="private:1", scene="chat", query="自然短句")[0]["experience_id"], exp)
        self.assertEqual(self.store.retrieve(scope="private:2", scene="chat", query="自然短句"), [])

    def test_injection_limits(self):
        for i in range(5):
            self.store.create_experience(scope="private:1", hypothesis=f"经验 {i} " + "自然" * 100, scene="chat", state="established")
        rows = self.store.retrieve(scope="private:1", scene="chat", query="自然", limit=10)
        injected = self.store.inject(rows)
        self.assertLessEqual(len(injected["items"]), 3)
        self.assertLessEqual(injected["tokens"], 520)  # small marker overhead is tolerated by portable estimator

    def test_run_idempotency(self):
        a = self.store.start_run(task_type="extract", idempotency_key="run-1")
        b = self.store.start_run(task_type="extract", idempotency_key="run-1")
        self.assertEqual(a, b)
        self.store.finish_run(a)
        self.assertEqual(self.store.counts()["learning_runs"], 1)


if __name__ == "__main__":
    unittest.main()
