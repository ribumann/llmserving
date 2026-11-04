from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from fastapi import Request
from jwt import PyJWKClient

from src.api.errors import ApiError
from src.config import Settings


class SigningKeyProvider(Protocol):
    """The subset of `jwt.PyJWKClient` this module depends on, so tests can supply a
    fake JWKS source instead of making a real network call to Entra ID's discovery
    endpoint."""

    def get_signing_key_from_jwt(self, token: str) -> Any: ...


@dataclass(slots=True, frozen=True)
class InternalCaller:
    """The managed identity that authenticated an internal callback request
    (contracts/api.md Internal Orchestration Callback API)."""

    subject: str
    app_id: str | None
    audience: str


class InternalAuthError(ApiError):
    def __init__(self, message: str, *, code: str = "internal_authentication_required") -> None:
        super().__init__(status_code=401, code=code, message=message, details={})


def _jwks_uri(tenant_id: str) -> str:
    return f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"


def _issuers(tenant_id: str) -> list[str]:
    # Entra ID issues v2.0 tokens with the `.../v2.0` issuer, but some callers/flows
    # still observe the legacy v1.0 issuer shape - accept either for the same tenant.
    return [
        f"https://login.microsoftonline.com/{tenant_id}/v2.0",
        f"https://sts.windows.net/{tenant_id}/",
    ]


class EntraTokenVerifier:
    """Shared signature/issuer/audience/time validation; callers enforce identity semantics."""

    def __init__(
        self,
        *,
        tenant_id: str,
        audience: str,
        jwks_client_factory: Callable[[str], SigningKeyProvider] | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._audience = audience
        self._jwks_client = (
            jwks_client_factory(_jwks_uri(tenant_id))
            if jwks_client_factory
            else PyJWKClient(_jwks_uri(tenant_id), timeout=5)
        )

    def decode(self, token: str) -> dict[str, Any]:
        signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=self._audience,
            issuer=_issuers(self._tenant_id),
            options={"require": ["exp", "iat", "aud", "iss"]},
        )


class InternalTokenValidator(EntraTokenVerifier):
    """Validates audience-restricted managed-identity tokens for internal callbacks."""

    def validate(self, token: str) -> InternalCaller:
        try:
            claims = self.decode(token)
        except jwt.PyJWTError as exc:
            raise InternalAuthError(f"Invalid internal service token: {exc}") from exc

        subject = str(claims.get("oid") or claims.get("sub") or "")
        if not subject:
            raise InternalAuthError("Internal service token is missing a subject claim.")
        return InternalCaller(
            subject=subject,
            app_id=claims.get("appid") or claims.get("azp"),
            audience=self._audience,
        )


def build_internal_token_validator(settings: Settings) -> InternalTokenValidator | None:
    if not settings.azure_tenant_id or not settings.internal_api_audience:
        return None
    return InternalTokenValidator(
        tenant_id=settings.azure_tenant_id,
        audience=settings.internal_api_audience,
    )


def require_internal_identity(request: Request) -> InternalCaller:
    """FastAPI dependency enforcing managed-identity bearer auth on the internal
    callback routes. Fails closed (503) if no validator is configured, and 401 on any
    missing/invalid/wrong-audience token."""
    validator: InternalTokenValidator | None = getattr(
        request.app.state, "internal_token_validator", None
    )
    if validator is None:
        raise ApiError(
            status_code=503,
            code="internal_auth_unconfigured",
            message="Internal callback authentication is not configured.",
            details={},
        )

    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise InternalAuthError("A bearer token is required for internal callback endpoints.")
    return validator.validate(token.strip())
