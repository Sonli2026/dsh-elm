import tempfile
import unittest
from pathlib import Path

from elm import ELMConfig, ELMStore


class SafetyAndLimitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ELMStore(
            Path(self.tmp.name) / "elm.sqlite",
            ELMConfig(enabled=True, retrieval_enabled=True, injection_enabled=True,
                      max_candidates=10, max_injected_items=3, max_injected_tokens=500),
        )

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_disabled_is_a_hard_bypass(self):
        disabled = ELMStore(Path(self.tmp.name) / "disabled.sqlite", ELMConfig())
        event = disabled.add_event(scope="private:1", event_type="user_message", idempotency_key="x")
        exp = disabled.create_experience(scope="private:1", hypothesis="short")
        self.assertEqual(disabled.retrieve(scope="private:1", query="short"), [])
        self.assertEqual(disabled.inject([{"experience_id": exp, "hypothesis": "short"}])["text"], "")
        disabled.close()

    def test_sqlite_safety_pragmas(self):
        self.assertEqual(self.store.db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(self.store.db.execute("PRAGMA busy_timeout").fetchone()[0], 5000)
        self.assertEqual(self.store.db.execute("PRAGMA synchronous").fetchone()[0], 2)
        self.assertEqual(self.store.db.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")

    def test_duplicate_evidence_is_idempotent(self):
        event = self.store.add_event(scope="group:1", event_type="explicit_feedback",
                                     idempotency_key="feedback-1", provenance="explicit_feedback",
                                     delivery_status="confirmed")
        exp = self.store.create_experience(scope="group:1", hypothesis="回复更短", scene="chat")
        first = self.store.add_evidence(experience_id=exp, event_id=event, direction="positive")
        second = self.store.add_evidence(experience_id=exp, event_id=event, direction="positive")
        self.assertEqual(first, second)
        self.assertEqual(self.store.get_experience(exp)["positive_count"], 1)
        self.assertEqual(self.store.counts()["experience_evidence"], 1)

    def test_conflicted_and_retired_are_hard_filtered(self):
        for state in ("conflicted", "retired"):
            exp = self.store.create_experience(scope="private:1", hypothesis=f"{state} behavior",
                                               scene="chat", state=state)
            self.assertIsNotNone(exp)
        self.assertEqual(self.store.retrieve(scope="private:1", scene="chat", query="behavior"), [])

    def test_unknown_receipt_is_stored_but_not_promoted_by_core(self):
        event = self.store.add_event(scope="private:1", event_type="assistant_message_sent",
                                     idempotency_key="send-unknown", provenance="unknown",
                                     delivery_status="unknown")
        self.assertEqual(self.store.get_event(event)["delivery_status"], "unknown")
        # The receipt adapter, not the storage layer, must decide whether this can become evidence.
        self.assertEqual(self.store.counts()["experience_evidence"], 0)

    def test_injection_has_three_item_and_token_caps(self):
        candidates = [
            {"experience_id": str(i), "hypothesis": "自然表达 " + "自然" * 500, "scene": "chat"}
            for i in range(10)
        ]
        result = self.store.inject(candidates)
        self.assertLessEqual(len(result["items"]), 3)
        self.assertLessEqual(result["tokens"], 500)


if __name__ == "__main__":
    unittest.main()
