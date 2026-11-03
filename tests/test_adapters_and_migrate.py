import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import migrate
from adapters import adapt_receipt, safe_send_learning_event


class AdapterAndMigrationTests(unittest.TestCase):
    def test_receipt_contract_never_guesses(self):
        self.assertEqual(adapt_receipt({"status": "ok", "retcode": 0}).state, "unknown")
        self.assertEqual(adapt_receipt({"ok": True}).state, "unknown")
        confirmed = adapt_receipt({"ok": True, "message_id": "m-1", "idempotency_key": "d-1"})
        self.assertEqual(confirmed.state, "confirmed")
        self.assertEqual(adapt_receipt({"ok": False}).state, "failed")

    def test_safe_send_writes_only_confirmed(self):
        writes = []
        unknown = safe_send_learning_event(
            lambda: {"status": "ok", "retcode": 0}, writes.append, {"event_type": "sent"}
        )
        self.assertEqual(unknown.state, "unknown")
        self.assertEqual(writes, [])
        confirmed = safe_send_learning_event(
            lambda: {"ok": True, "message_id": "m-2"}, writes.append, {"event_type": "sent"}
        )
        self.assertEqual(confirmed.state, "confirmed")
        self.assertEqual(writes[0]["delivery_status"], "confirmed")

    def test_dry_run_is_non_mutating_and_apply_is_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source = root_path / "social-v2.json"
            source.write_text(json.dumps({"conversations": {
                "private:1": {"recentMessages": [
                    {"seq": 1, "messageId": "m1", "userId": "u1", "text": "hello", "time": 1700000000000},
                    {"seq": 2, "messageId": "m2", "isSelf": True, "text": "reply", "time": 1700000001000}
                ]}
            }}), encoding="utf-8")
            target = root_path / "elm.sqlite"
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = migrate.main(["--source", str(source), "--target", str(target), "--dry-run"])
            self.assertEqual(rc, 0)
            self.assertFalse(target.exists())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(migrate.main(["--source", str(source), "--target", str(target), "--apply"]), 0)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(migrate.main(["--source", str(source), "--target", str(target), "--apply"]), 0)
            with contextlib.redirect_stdout(io.StringIO()) as captured:
                self.assertEqual(migrate.main(["--target", str(target), "--verify"]), 0)
            self.assertIn('"ok": true', captured.getvalue())


if __name__ == "__main__":
    unittest.main()
