from __future__ import annotations

from app.models.entities import SupplierProfile


PROFILE_FIELDS: tuple[tuple[str, int], ...] = (
    ("unified_social_credit_code", 12),
    ("province", 5),
    ("city", 5),
    ("address", 8),
    ("contact_name", 8),
    ("contact_phone", 8),
    ("contact_email", 8),
    ("categories", 12),
    ("cooperation_modes", 10),
    ("export_markets", 8),
    ("website", 6),
    ("supports_dropshipping", 5),
    ("supports_oem", 5),
)


def calculate_profile_completion(profile: SupplierProfile | None) -> int:
    if profile is None:
        return 0

    score = 0
    for field_name, weight in PROFILE_FIELDS:
        value = getattr(profile, field_name, None)
        if isinstance(value, bool):
            if value:
                score += weight
        elif value:
            score += weight

    return min(score, 100)
