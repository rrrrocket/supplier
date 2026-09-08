from __future__ import annotations

from pydantic import BaseModel


class SupplierBrandCooperationView(BaseModel):
    brand_id: str
    brand_code: str
    brand_name: str
    commercial_mode: str
    status: str
