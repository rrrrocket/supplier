from __future__ import annotations

import base64
import binascii
import json

from fastapi import HTTPException, status


def encode_list_cursor(resource: str, entity_id: str, filters: dict[str, str | None]) -> str:
    payload = json.dumps(
        {"v": 1, "r": resource, "i": entity_id, "f": filters},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_list_cursor(
    value: str,
    resource: str,
    filters: dict[str, str | None],
) -> str:
    try:
        if not value or len(value) > 4096:
            raise ValueError
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
        payload = json.loads(decoded.decode("utf-8"))
        if (
            not isinstance(payload, dict)
            or payload != {"v": 1, "r": resource, "i": payload.get("i"), "f": filters}
            or not isinstance(payload["i"], str)
            or not payload["i"]
            or encode_list_cursor(resource, payload["i"], filters) != value
        ):
            raise ValueError
        return payload["i"]
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
        KeyError,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="分页游标无效",
        ) from None
