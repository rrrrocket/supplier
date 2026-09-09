from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.api.routes.integrations import OPERATIONS_WITHOUT_422, CostAuditMiddleware
from app.core.config import get_settings
from app.db.bootstrap import sync_platform_admin
from app.db.session import SessionLocal


settings = get_settings()
WEB_ROOT = Path(__file__).resolve().parent / "web"
PAGES = WEB_ROOT / "pages"
ASSETS = WEB_ROOT / "assets"


def build_public_openapi_schema(application: FastAPI) -> dict[str, Any]:
    return get_openapi(
        title=application.title,
        version=application.version,
        openapi_version=application.openapi_version,
        summary=application.summary,
        description=application.description,
        routes=application.routes,
        webhooks=application.webhooks.routes,
        tags=application.openapi_tags,
        servers=application.servers,
        terms_of_service=application.terms_of_service,
        contact=application.contact,
        license_info=application.license_info,
        separate_input_output_schemas=application.separate_input_output_schemas,
        external_docs=application.openapi_external_docs,
    )


def normalize_public_openapi_schema(schema: dict[str, Any]) -> dict[str, Any]:
    for path, method in OPERATIONS_WITHOUT_422.items():
        schema["paths"][path][method]["responses"].pop("422", None)
    return schema


def normalize_public_openapi(application: FastAPI) -> None:
    openapi_lock = Lock()

    def openapi() -> dict[str, Any]:
        with openapi_lock:
            if application.openapi_schema is not None:
                return application.openapi_schema

            schema = normalize_public_openapi_schema(
                build_public_openapi_schema(application)
            )
            application.openapi_schema = schema
            return schema

    application.openapi = openapi


@asynccontextmanager
async def lifespan(_: FastAPI):
    with SessionLocal() as db:
        sync_platform_admin(db, settings)
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Matrix One 中国供应网络 API",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(CostAuditMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie=settings.session_cookie_name,
    max_age=settings.session_max_age_seconds,
    same_site="lax",
    https_only=settings.is_production,
)
if settings.is_production:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
        "frame-ancestors 'none'; form-action 'self'; base-uri 'self'",
    )
    return response

app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")
app.include_router(api_router, prefix="/api")
normalize_public_openapi(app)


@app.get("/api/health", tags=["系统"])
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "supplier-network",
        "environment": settings.app_env,
    }


@app.exception_handler(404)
async def not_found(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "页面或资源不存在"})


@app.get("/", include_in_schema=False)
def landing_page() -> FileResponse:
    return FileResponse(PAGES / "index.html")


@app.get("/apply", include_in_schema=False)
def apply_page() -> FileResponse:
    return FileResponse(PAGES / "apply.html")


@app.get("/operator/apply", include_in_schema=False)
def operator_apply_page() -> FileResponse:
    return FileResponse(PAGES / "operator-apply.html")


@app.get("/suppliers", include_in_schema=False)
def suppliers_page() -> FileResponse:
    return FileResponse(PAGES / "suppliers.html")


@app.get("/operators", include_in_schema=False)
def operators_page() -> FileResponse:
    return FileResponse(PAGES / "operators.html")


@app.get("/login", include_in_schema=False)
def login_page() -> FileResponse:
    return FileResponse(PAGES / "login.html")


@app.get("/app", include_in_schema=False)
def supplier_app() -> FileResponse:
    return FileResponse(PAGES / "app.html")


@app.get("/admin", include_in_schema=False)
def admin_app() -> FileResponse:
    return FileResponse(PAGES / "admin.html")


@app.get("/operator", include_in_schema=False)
def operator_app() -> FileResponse:
    return FileResponse(PAGES / "operator.html")


@app.get("/sample-offers.csv", include_in_schema=False)
def sample_csv() -> FileResponse:
    return FileResponse(
        WEB_ROOT / "sample-offers.csv",
        media_type="text/csv; charset=utf-8",
        filename="matrix-one-supplier-offers-template.csv",
    )


@app.get("/robots.txt", include_in_schema=False)
def robots() -> Response:
    body = "User-agent: *\nDisallow: /app\nDisallow: /admin\nDisallow: /api/\n"
    return Response(content=body, media_type="text/plain")
