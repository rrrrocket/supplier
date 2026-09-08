from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timezone

from fastapi import HTTPException, status


def invalid_cursor() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "INVALID_CURSOR", "message": "分页游标无效"},
    )


def encode_cursor(updated_at: datetime, entity_id: str) -> str:
    if updated_at.tzinfo is None or updated_at.utcoffset() is None:
        raise ValueError("cursor timestamp must be timezone-aware")
    if not entity_id:
        raise ValueError("cursor entity ID must not be empty")

    utc_timestamp = updated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = json.dumps(
        {"u": utc_timestamp, "i": entity_id},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(value: str) -> tuple[datetime, str]:
    try:
        if not value or len(value) > 2048:
            raise ValueError
        padding = "=" * (-len(value) % 4)
        decoded = base64.b64decode(
            value + padding,
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(decoded.decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) != {"u", "i"}:
            raise ValueError
        raw_updated_at = payload["u"]
        entity_id = payload["i"]
        if not isinstance(raw_updated_at, str) or not isinstance(entity_id, str):
            raise ValueError
        if not entity_id or len(entity_id) > 200:
            raise ValueError
        updated_at = datetime.fromisoformat(raw_updated_at.replace("Z", "+00:00"))
        if updated_at.tzinfo is None or updated_at.utcoffset() is None:
            raise ValueError
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        raise invalid_cursor() from None

    return updated_at.astimezone(timezone.utc), entity_id
