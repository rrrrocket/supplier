from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
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
        updated_at = updated_at.astimezone(timezone.utc)
        if encode_cursor(updated_at, entity_id) != value:
            raise ValueError
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        raise invalid_cursor() from None

    return updated_at, entity_id


@dataclass(frozen=True)
class BoundCursor:
    updated_at: datetime
    entity_id: str
    sync_watermark: datetime


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("cursor timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def encode_bound_cursor(
    updated_at: datetime,
    entity_id: str,
    *,
    sync_watermark: datetime,
    resource: str,
    supplier_id: str | None,
    updated_since: datetime | None,
    include_inactive: bool,
) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "r": resource,
            "s": supplier_id,
            "f": _utc_text(updated_since) if updated_since is not None else None,
            "a": include_inactive,
            "w": _utc_text(sync_watermark),
            "u": _utc_text(updated_at),
            "i": entity_id,
        },
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_bound_cursor(
    value: str,
    *,
    resource: str,
    supplier_id: str | None,
    updated_since: datetime | None,
    include_inactive: bool,
) -> BoundCursor:
    try:
        if not value or len(value) > 4096:
            raise ValueError
        padding = "=" * (-len(value) % 4)
        decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
        payload = json.loads(decoded.decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) != {
            "v", "r", "s", "f", "a", "w", "u", "i"
        }:
            raise ValueError
        expected_filter = _utc_text(updated_since) if updated_since is not None else None
        if (
            payload["v"] != 1
            or payload["r"] != resource
            or payload["s"] != supplier_id
            or payload["f"] != expected_filter
            or payload["a"] is not include_inactive
            or not isinstance(payload["i"], str)
            or not payload["i"]
        ):
            raise ValueError
        watermark = datetime.fromisoformat(payload["w"].replace("Z", "+00:00"))
        updated_at = datetime.fromisoformat(payload["u"].replace("Z", "+00:00"))
        if watermark.tzinfo is None or updated_at.tzinfo is None:
            raise ValueError
        result = BoundCursor(
            updated_at=updated_at.astimezone(timezone.utc),
            entity_id=payload["i"],
            sync_watermark=watermark.astimezone(timezone.utc),
        )
        canonical = encode_bound_cursor(
            result.updated_at,
            result.entity_id,
            sync_watermark=result.sync_watermark,
            resource=resource,
            supplier_id=supplier_id,
            updated_since=updated_since,
            include_inactive=include_inactive,
        )
        if canonical != value:
            raise ValueError
        return result
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    ):
        raise invalid_cursor() from None
