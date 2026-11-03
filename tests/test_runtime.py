import tempfile
import unittest
from pathlib import Path

from elm import ELMConfig, ELMRuntime


class RuntimeTests(unittest.TestCase):
    def test_disabled_runtime_is_fail_open(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = ELMRuntime(str(Path(root) / "elm.sqlite"), ELMConfig(enabled=False))
            self.assertIsNone(runtime.observe_event({"scope": "private:1", "event_type": "message_received", "idempotency_key": "x"}))
            self.assertEqual(runtime.retrieve_context(scope="private:1")["items"], [])
            runtime.close()

    def test_enabled_runtime_deduplicates(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = ELMRuntime(str(Path(root) / "elm.sqlite"), ELMConfig(enabled=True))
            event = {"scope": "private:1", "event_type": "message_received", "idempotency_key": "x", "provenance": "real_conversation"}
            first = runtime.observe_event(event)
            second = runtime.observe_event(event)
            self.assertEqual(first, second)
            self.assertEqual(runtime.status()["counts"]["learning_events"], 1)
            runtime.close()


if __name__ == "__main__":
    unittest.main()
