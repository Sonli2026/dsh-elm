"""Isolated dry-run/apply/verify/rollback migration CLI."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from elm import ELMConfig, ELMStore
try:
    from .sources import iter_source
except ImportError:  # executed as ``python migrate.py`` from this folder
    from sources import iter_source


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = path.with_name(path.name + f".bak.{stamp}")
    counter = 1
    while out.exists():
        out = path.with_name(path.name + f".bak.{stamp}.{counter}")
        counter += 1
    shutil.copy2(path, out)
    return out


def apply_events(store: ELMStore, events: Iterable[dict[str, Any]], dry_run: bool) -> dict[str, int]:
    seen = inserted = skipped = 0
    for event in events:
        seen += 1
        if dry_run:
            inserted += 1
            continue
        before = store.counts()["learning_events"]
        try:
            store.add_event(
                scope=str(event.get("scope") or "unknown"),
                event_type=str(event.get("event_type") or "message_received"),
                idempotency_key=str(event.get("idempotency_key") or event["event_id"]),
                session_id=event.get("session_id"),
                message_id=event.get("message_id"),
                user_id=event.get("user_id"),
                source_archive_ref=event.get("source_archive_ref"),
                scene=str(event.get("scene") or "unknown"),
                feedback_type=str(event.get("feedback_type") or "uncertain"),
                explicit_feedback=bool(event.get("explicit_feedback")),
                provenance=str(event.get("provenance") if event.get("provenance") in {
                    "real_conversation", "explicit_feedback", "synthetic", "elm_generated", "unknown"
                } else "unknown"),
                delivery_status=str(event.get("delivery_status") or "unknown"),
                payload={"text": event.get("text", ""), "metadata": event.get("metadata", {})},
                occurred_at=_timestamp_ms(event.get("occurred_at")),
            )
        except Exception:
            skipped += 1
            continue
        after = store.counts()["learning_events"]
        inserted += max(0, after - before)
        if after == before:
            skipped += 1
    return {"seen": seen, "inserted": inserted, "skipped": skipped}


def _timestamp_ms(value: Any) -> int | None:
    """Normalize epoch seconds/milliseconds or ISO-8601 timestamps."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return int(number * 1000 if abs(number) < 10_000_000_000 else number)
    text = str(value).strip()
    try:
        number = float(text)
        return int(number * 1000 if abs(number) < 10_000_000_000 else number)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    except ValueError:
        return None


def verify_db(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"ok": False, "error": "target_missing"}
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        db = sqlite3.connect(uri, uri=True)
        required = {"learning_events", "experiences", "experience_evidence", "experience_versions", "learning_runs"}
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        errors = [f"missing_table:{name}" for name in sorted(required - tables)]
        counts: dict[str, int] = {}
        if not errors:
            if db.execute("PRAGMA foreign_key_check").fetchall():
                errors.append("foreign_key_check returned rows")
            if db.execute("SELECT 1 FROM experience_evidence GROUP BY experience_id,event_id HAVING COUNT(*)>1 LIMIT 1").fetchone():
                errors.append("duplicate evidence pairs")
            counts = {name: int(db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]) for name in required}
        result = {"ok": not errors, "errors": errors, "counts": counts}
        db.close()
        return result
    except sqlite3.Error as exc:
        return {"ok": False, "error": f"verify_failed:{type(exc).__name__}"}


def rollback(target: Path, backup_path: Path) -> None:
    if not backup_path.exists():
        raise FileNotFoundError(backup_path)
    if target.exists():
        target.unlink()
    shutil.copy2(backup_path, target)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(target) + suffix)
        if sidecar.exists():
            sidecar.unlink()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="DSH-ELM isolated migration CLI")
    p.add_argument("--source", help="social-v2.json, JSONL, directory, or history.sqlite snapshot")
    p.add_argument("--source-format", default="auto", choices=["auto", "social-v2", "jsonl", "history-sqlite"])
    p.add_argument("--target", required=True, help="isolated ELM SQLite path")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    p.add_argument("--backup", help="backup file for --rollback")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    target = Path(args.target).resolve()
    if args.verify:
        result = verify_db(target)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    if args.rollback:
        if not args.backup:
            print("--rollback requires --backup", file=sys.stderr)
            return 2
        rollback(target, Path(args.backup).resolve())
        print(json.dumps({"ok": True, "rolled_back": str(target)}, ensure_ascii=False))
        return 0
    if not args.source:
        print("--source is required for --dry-run/--apply", file=sys.stderr)
        return 2
    saved = backup(target) if args.apply else None
    config = ELMConfig(enabled=True, observe_only=False, retrieval_enabled=True, injection_enabled=True)
    # A dry-run must not touch the requested target path. Use an in-memory
    # database while preserving the same schema/validation code path.
    store_path = ":memory:" if args.dry_run else target
    with ELMStore(store_path, config) as store:
        result = apply_events(store, iter_source(args.source, args.source_format), args.dry_run)
        counts = store.counts()
    output = {"ok": True, "mode": "dry-run" if args.dry_run else "apply", "target": str(target), **result, "counts": counts}
    if saved:
        output["backup"] = str(saved)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
