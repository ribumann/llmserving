from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.audit import install_audit_middleware
from src.api.auth import install_auth_middleware
from src.api.correlation import configure_monitoring
from src.api.errors import install_error_handling
from src.api.internal_auth import build_internal_token_validator
from src.api.routes import create_router
from src.api.telemetry import OperationTelemetry, install_telemetry_middleware
from src.config import Settings, get_settings
from src.persistence.db import DatabaseReadiness, create_session_factory
from src.providers.azure import AzureProviderAdapter
from src.providers.local.adapter import LocalProviderAdapter
from src.providers.registry import CompositeProviderAdapter


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    readiness = DatabaseReadiness(resolved_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            readiness.close()

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    # Wires the `workflowId` correlation ID (FR-086) into every log record and,
    # when configured, into Application Insights via OpenTelemetry - must run
    # before any request is served, but has no bearing on request handling
    # itself, so it's safe this early in app construction.
    configure_monitoring(app)
    session_factory = create_session_factory(resolved_settings)
    app.state.settings = resolved_settings
    app.state.database_readiness = readiness
    app.state.session_factory = session_factory
    app.state.telemetry = OperationTelemetry(session_factory=session_factory)
    azure_provider = AzureProviderAdapter(
        session_factory=session_factory,
        settings=resolved_settings,
        telemetry=app.state.telemetry,
    )
    local_provider = LocalProviderAdapter(
        session_factory=session_factory,
        settings=resolved_settings,
        telemetry=app.state.telemetry,
    )
    app.state.provider_adapter = CompositeProviderAdapter(
        azure=azure_provider,
        local=local_provider,
        session_factory=session_factory,
    )
    # Fails closed (503, see require_internal_identity) rather than open when
    # unconfigured, since local/test runs never set azure_tenant_id/
    # internal_api_audience and there is no safe default to validate against.
    app.state.internal_token_validator = build_internal_token_validator(resolved_settings)

    # Registration order matters: Starlette wraps middleware so the *last*
    # registered becomes outermost. install_error_handling must be
    # registered last so it wraps auth/telemetry/audit and can translate
    # their ApiError/HTTPException exceptions into JSON responses. When it
    # was registered first, ApiError raised by the auth middleware escaped
    # this handler entirely and surfaced as a raw framework 500.
    install_auth_middleware(app, resolved_settings)
    install_telemetry_middleware(app)
    install_audit_middleware(app)
    install_error_handling(app)
    # CORSMiddleware is registered last so it becomes the outermost layer,
    # wrapping auth/telemetry/audit/error-handling entirely. This matters for
    # two reasons: (1) browser CORS preflight (OPTIONS) requests are answered
    # by CORSMiddleware itself and never reach the auth middleware, which
    # would otherwise 401 them (they carry no X-Demo-User/Entra header); and
    # (2) Access-Control-Allow-* headers get added even to error responses
    # (e.g. a genuine 401 from auth), so the browser can actually see/report
    # the real error instead of a generic "Failed to fetch" CORS failure.
    if resolved_settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved_settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(create_router())
    return app


app = create_app()
