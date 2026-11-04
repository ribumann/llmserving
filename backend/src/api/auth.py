from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI, Request

from src.api.errors import ApiError
from src.config import Settings


@dataclass(slots=True, frozen=True)
class AuthenticatedUser:
    subject: str
    email: str
    display_name: str
    auth_source: str


def is_exempt_path(path: str, settings: Settings) -> bool:
    return any(
        path == exempt or path.startswith(f"{exempt}/") for exempt in settings.auth_bypass_paths
    )


def extract_authenticated_user(request: Request) -> AuthenticatedUser | None:
    header_map = {
        "X-MS-CLIENT-PRINCIPAL-NAME": "entra-header",
        "X-Forwarded-Email": "forwarded-email",
        "X-User-Email": "user-email",
        "X-Demo-User": "demo-header",
    }
    for header_name, auth_source in header_map.items():
        value = request.headers.get(header_name)
        if value:
            display_name = request.headers.get("X-User-Display-Name", value)
            return AuthenticatedUser(
                subject=value,
                email=value,
                display_name=display_name,
                auth_source=auth_source,
            )
    return None


def install_auth_middleware(app: FastAPI, settings: Settings) -> None:
    @app.middleware("http")
    async def authenticate_request(request: Request, call_next):
        if is_exempt_path(request.url.path, settings):
            return await call_next(request)

        user = extract_authenticated_user(request)
        if user is None:
            raise ApiError(
                status_code=401,
                code="authentication_required",
                message="Organization SSO authentication is required.",
                details={
                    "acceptedHeaders": [
                        "X-MS-CLIENT-PRINCIPAL-NAME",
                        "X-Forwarded-Email",
                        "X-User-Email",
                        "X-Demo-User",
                    ]
                },
            )

        domain = user.email.rsplit("@", maxsplit=1)[-1].lower() if "@" in user.email else ""
        allowed_domains = {
            domain_name.lower() for domain_name in settings.auth_allowed_email_domains
        }
        if allowed_domains and domain not in allowed_domains:
            raise ApiError(
                status_code=403,
                code="forbidden_domain",
                message=(
                    "The authenticated identity is outside the allowed organization " "domain list."
                ),
                details={"allowedDomains": sorted(allowed_domains)},
            )

        request.state.user = user
        return await call_next(request)
