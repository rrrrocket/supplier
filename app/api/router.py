from fastapi import APIRouter

from app.api.routes import (
    admin,
    auth,
    dashboard,
    events,
    imports,
    offers,
    products,
    profile,
    public,
    supplier_catalog,
)


api_router = APIRouter()
api_router.include_router(public.router)
api_router.include_router(admin.router)
api_router.include_router(auth.router)
api_router.include_router(dashboard.router)
api_router.include_router(profile.router)
api_router.include_router(products.router)
api_router.include_router(offers.router)
api_router.include_router(supplier_catalog.router)
api_router.include_router(imports.router)
api_router.include_router(events.router)
