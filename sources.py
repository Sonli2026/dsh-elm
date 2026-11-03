"""Read-only source readers for isolated migration snapshots."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterator


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _event(*, source_ref: str, scope: str, conversation_id: str | None,
           message_id: str | None, user_id: str | None, text: str | None,
           at: float | int | None, outgoing: bool, delivery_status: str | None,
           metadata: dict[str, Any] | None = None, provenance: str = "unknown") -> dict[str, Any]:
    confirmed = outgoing and delivery_status == "confirmed"
    event_type = "assistant_message_sent" if confirmed else ("message_received" if not outgoing else "assistant_message_unknown")
    return {
        "event_id": "src_" + _hash(source_ref)[:48],
        "scope": scope,
        "conversation_id": conversation_id,
        "message_id": message_id,
        "user_id": user_id,
        "source_archive_ref": source_ref,
        "event_type": event_type,
        "scene": "unknown",
        "feedback_type": "unknown",
        "explicit_feedback": 0,
        "occurred_at": float(at or 0),
        "provenance": "real_conversation" if not outgoing or confirmed else provenance,
        "delivery_status": "confirmed" if confirmed else (delivery_status or "unknown"),
        "idempotency_key": source_ref,
        "text": text or "",
        "metadata": metadata or {},
    }


def read_social_v2(path: str | Path) -> Iterator[dict[str, Any]]:
    """Read QQ ``state/social-v2.json`` without modifying it."""
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    conversations = raw.get("conversations", raw) if isinstance(raw, dict) else {}
    if not isinstance(conversations, dict):
        return
    for key, state in conversations.items():
        if not isinstance(state, dict):
            continue
        parts = str(key).split(":", 1)
        scope = parts[0] if parts and parts[0] in {"group", "private"} else "unknown"
        conversation_id = parts[1] if len(parts) == 2 else None
        messages = state.get("recentMessages", [])
        if not isinstance(messages, list):
            continue
        for index, msg in enumerate(messages):
            if not isinstance(msg, dict):
                continue
            seq = msg.get("seq", index)
            ref = f"social-v2:{key}:seq:{seq}"
            yield _event(source_ref=ref, scope=scope,
                         conversation_id=conversation_id,
                         message_id=str(msg.get("messageId")) if msg.get("messageId") is not None else None,
                         user_id=str(msg.get("userId")) if msg.get("userId") is not None else None,
                         text=str(msg.get("text", msg.get("plain", "")))[:200],
                         at=msg.get("time"), outgoing=bool(msg.get("isSelf")),
                         delivery_status=msg.get("delivery_status"),
                         metadata={"sender": msg.get("sender"), "isOwner": bool(msg.get("isOwner")),
                                   "hasMedia": bool(msg.get("hasMedia")), "source_format": "social-v2"})


def read_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    """Read candidate ``MEMORIES/*.jsonl`` archives, preserving provenance."""
    p = Path(path)
    files = sorted(p.glob("*.jsonl")) if p.is_dir() else [p]
    for file in files:
        for number, line in enumerate(file.read_text(encoding="utf-8-sig").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ref = f"jsonl:{file.name}:{number}:{hashlib.sha256(line.encode('utf-8')).hexdigest()[:16]}"
            said = row.get("said") if isinstance(row, dict) else None
            text = "\n".join(str(x) for x in said) if isinstance(said, list) else str(row.get("text", ""))
            kind = str(row.get("kind", "snapshot"))
            yield _event(source_ref=ref, scope=str(row.get("scope", "unknown")),
                         conversation_id=str(row.get("conversation_id")) if row.get("conversation_id") else None,
                         message_id=str(row.get("message_id")) if row.get("message_id") else None,
                         user_id=str(row.get("user_id")) if row.get("user_id") else None,
                         text=text[:4000], at=row.get("at"), outgoing=kind == "said",
                         delivery_status=row.get("delivery_status"),
                         metadata={"kind": kind, "source_format": "jsonl"},
                         provenance="unknown" if kind != "said" else "unknown")


def read_history_sqlite(path: str | Path) -> Iterator[dict[str, Any]]:
    """Read a legacy HistoryStore copy using SQLite URI mode=ro."""
    uri = f"file:{Path(path).resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        try:
            rows = db.execute("SELECT seq, chat, at, body, source FROM records ORDER BY seq").fetchall()
        except sqlite3.Error:
            return
        for seq, chat, at, body_json, source in rows:
            try:
                body = json.loads(body_json)
            except (TypeError, json.JSONDecodeError):
                body = {}
            scope = "unknown"
            conversation_id = None
            bits = str(chat).split(":")
            if len(bits) >= 3 and bits[1] in {"private", "group"}:
                scope, conversation_id = bits[1], bits[2]
            outgoing = bool(body.get("outgoing"))
            ref = f"history.sqlite:records:{seq}"
            yield _event(source_ref=ref, scope=scope, conversation_id=conversation_id,
                         message_id=str(body.get("message_id")) if body.get("message_id") else None,
                         user_id=str(body.get("sender_id")) if body.get("sender_id") else None,
                         text=str(body.get("text", "")), at=body.get("timestamp", at),
                         outgoing=outgoing, delivery_status=body.get("delivery_status"),
                         metadata={"legacy_source": source, "source_format": "history.sqlite"})


def iter_source(path: str | Path, source_format: str = "auto") -> Iterator[dict[str, Any]]:
    p = Path(path)
    fmt = source_format
    if fmt == "auto":
        if p.is_file() and p.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
            fmt = "history-sqlite"
        elif p.is_file() and p.suffix.lower() == ".jsonl":
            fmt = "jsonl"
        elif p.is_file() and p.name == "social-v2.json":
            fmt = "social-v2"
        elif p.is_dir() and any(p.glob("*.jsonl")):
            fmt = "jsonl"
        else:
            fmt = "social-v2"
    if fmt == "social-v2":
        yield from read_social_v2(p)
    elif fmt == "jsonl":
        yield from read_jsonl(p)
    elif fmt in {"history-sqlite", "sqlite"}:
        yield from read_history_sqlite(p)
    else:
        raise ValueError(f"unsupported source format: {source_format}")
