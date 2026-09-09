from fastapi import APIRouter

from app.api.routes import (
    admin,
    admin_catalog,
    auth,
    dashboard,
    directory,
    events,
    imports,
    integrations,
    offers,
    operators,
    operator_cooperations,
    products,
    profile,
    public,
    supplier_catalog,
    supplier_operator,
)


api_router = APIRouter()
api_router.include_router(public.router)
api_router.include_router(directory.router)
api_router.include_router(directory.operator_router)
api_router.include_router(admin.router)
api_router.include_router(admin_catalog.router)
api_router.include_router(auth.router)
api_router.include_router(dashboard.router)
api_router.include_router(profile.router)
api_router.include_router(products.router)
api_router.include_router(offers.router)
api_router.include_router(operators.router)
api_router.include_router(operator_cooperations.router)
api_router.include_router(supplier_operator.router)
api_router.include_router(supplier_catalog.router)
api_router.include_router(imports.router)
api_router.include_router(events.router)
api_router.include_router(integrations.router)
