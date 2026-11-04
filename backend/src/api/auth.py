from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import FastAPI, Request

from src.api.errors import ApiError
from src.api.internal_auth import EntraTokenVerifier
from src.config import Settings


@dataclass(slots=True, frozen=True)
class AuthenticatedUser:
    subject: str
    email: str
    display_name: str
    auth_source: str


class OperatorTokenValidator(EntraTokenVerifier):
    def validate(self, token: str) -> AuthenticatedUser:
        try:
            claims = self.decode(token)
        except jwt.PyJWTError as error:
            raise ApiError(
                status_code=401,
                code="authentication_required",
                message="A valid tenant- and audience-restricted operator token is required.",
            ) from error
        email = claims.get("preferred_username") or claims.get("email") or claims.get("upn")
        subject = claims.get("oid") or claims.get("sub")
        if (
            claims.get("tid") != self._tenant_id
            or claims.get("idtyp") == "app"
            or not isinstance(email, str)
            or "@" not in email
            or not isinstance(subject, str)
            or not subject
        ):
            raise ApiError(
                status_code=401,
                code="authentication_required",
                message="An authenticated operator user identity is required.",
            )
        return AuthenticatedUser(
            subject=subject,
            email=email,
            display_name=str(claims.get("name") or email),
            auth_source="entra-jwt",
        )


def build_operator_token_validator(settings: Settings) -> OperatorTokenValidator | None:
    if (
        settings.auth_mode != "entra-jwt"
        or not settings.azure_tenant_id
        or not settings.auth_audience
    ):
        return None
    return OperatorTokenValidator(
        tenant_id=settings.azure_tenant_id, audience=settings.auth_audience
    )


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

        if settings.auth_mode == "local-demo":
            user = extract_authenticated_user(request)
        else:
            validator = request.app.state.operator_token_validator
            if validator is None:
                raise ApiError(
                    status_code=503,
                    code="operator_auth_unconfigured",
                    message="Operator authentication requires a tenant and audience.",
                )
            authorization = request.headers.get("Authorization", "")
            scheme, _, bearer = authorization.partition(" ")
            token = bearer.strip() if scheme.lower() == "bearer" else ""
            token = token or request.headers.get("X-MS-TOKEN-AAD-ID-TOKEN", "")
            user = validator.validate(token) if token else None
        if user is None:
            raise ApiError(
                status_code=401,
                code="authentication_required",
                message="Organization SSO authentication is required.",
                details={
                    "authMode": settings.auth_mode,
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
