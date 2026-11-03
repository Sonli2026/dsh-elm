from __future__ import annotations

import argparse
import json
from pathlib import Path

from .store import ELMConfig, ELMStore


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Isolated DSH-ELM SQLite core")
    p.add_argument("--db", default="data/elm.sqlite")
    sub = p.add_subparsers(dest="command", required=True)
    # Accept --db both before and after the subcommand so the documented
    # `elm.cli init --db path` form is as valid as `elm.cli --db path init`.
    for name in ("init", "stats", "verify"):
        child = sub.add_parser(name)
        child.add_argument("--db", default=argparse.SUPPRESS)
    event = sub.add_parser("event")
    event.add_argument("--db", default=argparse.SUPPRESS)
    event.add_argument("--scope", required=True)
    event.add_argument("--type", required=True, dest="event_type")
    event.add_argument("--idempotency-key", required=True)
    event.add_argument("--provenance", default="unknown")
    event.add_argument("--scene", default="unknown")
    event.add_argument("--text", default="")
    exp = sub.add_parser("experience")
    exp.add_argument("--db", default=argparse.SUPPRESS)
    exp.add_argument("--scope", required=True)
    exp.add_argument("--hypothesis", required=True)
    exp.add_argument("--scene", default="unknown")
    exp.add_argument("--owner-id")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    path = Path(args.db)
    config = ELMConfig(enabled=True, retrieval_enabled=True, injection_enabled=True)
    with ELMStore(path, config) as store:
        if args.command == "init":
            print(json.dumps({"ok": True, "db": str(path), "counts": store.counts()}, ensure_ascii=False))
        elif args.command == "stats":
            print(json.dumps({"ok": True, "counts": store.counts()}, ensure_ascii=False))
        elif args.command == "verify":
            errors = store.verify()
            print(json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False))
            return 0 if not errors else 1
        elif args.command == "event":
            event_id = store.add_event(scope=args.scope, event_type=args.event_type, idempotency_key=args.idempotency_key,
                                       provenance=args.provenance, scene=args.scene, payload={"text": args.text})
            print(json.dumps({"ok": True, "event_id": event_id}, ensure_ascii=False))
        elif args.command == "experience":
            experience_id = store.create_experience(scope=args.scope, owner_id=args.owner_id, scene=args.scene,
                                                    hypothesis=args.hypothesis)
            print(json.dumps({"ok": True, "experience_id": experience_id}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
