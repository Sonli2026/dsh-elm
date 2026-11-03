"""Fail-open runtime facade used by future DSH/QQ adapters."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping

from .store import ELMConfig, ELMStore


class ELMRuntime:
    def __init__(self, db_path: str, config: ELMConfig | None = None):
        self.config = config or ELMConfig()
        self.store = ELMStore(db_path, self.config)

    def close(self) -> None:
        self.store.close()

    def observe_event(self, event: Mapping[str, Any]) -> str | None:
        """Record an event when enabled; failures are intentionally fail-open."""
        if not self.config.enabled:
            return None
        try:
            payload = dict(event)
            return self.store.add_event(
                scope=str(payload["scope"]),
                event_type=str(payload["event_type"]),
                idempotency_key=str(payload.get("idempotency_key") or payload.get("event_id") or ""),
                owner_id=payload.get("owner_id"),
                session_id=payload.get("session_id"),
                message_id=payload.get("message_id"),
                user_id=payload.get("user_id"),
                source_archive_ref=payload.get("source_archive_ref"),
                scene=str(payload.get("scene") or "unknown"),
                feedback_type=str(payload.get("feedback_type") or "uncertain"),
                explicit_feedback=bool(payload.get("explicit_feedback")),
                provenance=str(payload.get("provenance") or "unknown"),
                delivery_status=str(payload.get("delivery_status") or "unknown"),
                payload=payload,
                occurred_at=payload.get("occurred_at"),
            )
        except Exception:
            return None

    def retrieve_context(self, *, scope: str, owner_id: str | None = None,
                         scene: str | None = None, query: str = "") -> dict[str, Any]:
        if not self.config.enabled or not self.config.retrieval_enabled:
            return {"text": "", "items": [], "tokens": 0, "truncated": False}
        try:
            candidates = self.store.retrieve(scope=scope, owner_id=owner_id, scene=scene, query=query)
            return self.store.inject(candidates)
        except Exception:
            return {"text": "", "items": [], "tokens": 0, "truncated": False}

    def status(self) -> dict[str, Any]:
        return {"config": asdict(self.config), "counts": self.store.counts(), "verify": self.store.verify()}
