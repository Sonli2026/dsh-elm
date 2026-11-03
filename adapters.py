"""Runtime adapters with conservative receipt handling and failure bypass.

The QQ reference bridge currently exposes ``status=ok``/``retcode=0`` rather
than the ELM contract's ``ok === true``.  ``adapt_receipt`` therefore returns
``unknown`` for that shape and never upgrades it to a learning event.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class ReceiptStatus:
    state: str  # confirmed | unknown | failed
    ok: bool
    message_id: str | None = None
    idempotency_key: str | None = None
    reason: str = ""


def adapt_receipt(raw: Mapping[str, Any] | None) -> ReceiptStatus:
    """Normalize a bridge receipt without guessing.

    Accepted contracts:
    * explicit boolean ``ok is True``;
    * explicit adapter contract ``confirmed is True`` together with a
      non-empty receipt/message identifier.

    OneBot ``status=ok`` and ``retcode=0`` alone are intentionally unknown.
    """

    data = dict(raw or {})
    message_id = data.get("message_id", data.get("messageId"))
    message_id = str(message_id) if message_id not in (None, "") else None
    idem = data.get("idempotency_key", data.get("delivery_id", data.get("deliveryId")))
    idem = str(idem) if idem not in (None, "") else None
    if data.get("ok") is True:
        if not (message_id or idem):
            return ReceiptStatus("unknown", False, None, None, "ok_true_without_identifier")
        return ReceiptStatus("confirmed", True, message_id, idem, "explicit_ok_true")
    if data.get("confirmed") is True and (
        message_id or data.get("receipt") or data.get("receipt_id")
    ):
        return ReceiptStatus("confirmed", True, message_id, idem, "explicit_confirmed_contract")
    if data.get("ok") is False or data.get("confirmed") is False:
        return ReceiptStatus("failed", False, message_id, idem, "explicit_failure")
    if data.get("status") == "ok" and data.get("retcode") == 0:
        return ReceiptStatus("unknown", False, message_id, idem, "onebot_ok_without_elm_receipt")
    return ReceiptStatus("unknown", False, message_id, idem, "receipt_contract_missing")


def safe_send_learning_event(
    send: Callable[[], Mapping[str, Any]],
    write_event: Callable[[Mapping[str, Any]], Any],
    event: Mapping[str, Any],
) -> ReceiptStatus:
    """Run a send callback and persist only after a confirmed receipt.

    Any adapter/database error is converted to ``unknown`` and the caller can
    continue the normal QQ response path.  This function never raises a
    persistence error into the real-time send path.
    """

    try:
        receipt = adapt_receipt(send())
    except Exception as exc:  # pragma: no cover - defensive boundary
        return ReceiptStatus("unknown", False, reason=f"send_error:{type(exc).__name__}")
    if receipt.state != "confirmed":
        return receipt
    payload = dict(event)
    payload["provenance"] = payload.get("provenance", "real_conversation")
    payload["delivery_status"] = "confirmed"
    if receipt.message_id:
        payload["message_id"] = receipt.message_id
    if receipt.idempotency_key:
        payload["idempotency_key"] = receipt.idempotency_key
    try:
        write_event(payload)
    except Exception as exc:  # bounded fallback is owned by caller
        return ReceiptStatus("unknown", False, receipt.message_id, receipt.idempotency_key,
                             f"event_write_error:{type(exc).__name__}")
    return receipt
