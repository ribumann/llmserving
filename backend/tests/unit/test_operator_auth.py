from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import ValidationError
from src.api.app import create_app
from src.api.auth import AuthenticatedUser, OperatorTokenValidator
from src.config import Settings

TENANT = "11111111-1111-1111-1111-111111111111"
AUDIENCE = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(scope="module")
def keypair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, private.public_key()


def signed(private, **overrides):
    now = int(time.time())
    return jwt.encode(
        {
            "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
            "aud": AUDIENCE,
            "tid": TENANT,
            "iat": now,
            "exp": now + 60,
            "oid": "operator-object",
            "preferred_username": "operator@example.com",
            **overrides,
        },
        private,
        algorithm="RS256",
    )


def cloud_app(public):
    app = create_app(
        Settings(
            auth_mode="entra-jwt",
            app_env="production",
            azure_tenant_id=TENANT,
            auth_audience=AUDIENCE,
        )
    )
    app.state.operator_token_validator = OperatorTokenValidator(
        tenant_id=TENANT,
        audience=AUDIENCE,
        jwks_client_factory=lambda _: SimpleNamespace(
            get_signing_key_from_jwt=lambda _: SimpleNamespace(key=public)
        ),
    )
    return app


@pytest.mark.parametrize(
    "header",
    ["X-Demo-User", "X-User-Email", "X-Forwarded-Email", "X-MS-CLIENT-PRINCIPAL-NAME"],
)
def test_cloud_rejects_all_unverified_identity_headers(keypair, header) -> None:
    with TestClient(cloud_app(keypair[1])) as client:
        response = client.get("/providers", headers={header: "operator@example.com"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


@pytest.mark.parametrize("header", ["Authorization", "X-MS-TOKEN-AAD-ID-TOKEN"])
def test_cloud_requires_real_signed_operator_token(keypair, header) -> None:
    token = signed(keypair[0])
    value = f"Bearer {token}" if header == "Authorization" else token
    with TestClient(cloud_app(keypair[1])) as client:
        assert client.get("/providers", headers={header: value}).status_code == 200


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "other"},
        {"iss": "https://login.microsoftonline.com/other/v2.0"},
        {"tid": "other"},
        {"exp": 1},
        {"preferred_username": ""},
        {"oid": ""},
        {"idtyp": "app"},
    ],
)
def test_cloud_rejects_invalid_tenant_audience_time_or_user(keypair, claims) -> None:
    token = signed(keypair[0], **claims)
    with TestClient(cloud_app(keypair[1])) as client:
        response = client.get("/providers", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_cloud_rejects_wrong_signature_and_unsigned_identity(keypair) -> None:
    other_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with TestClient(cloud_app(keypair[1])) as client:
        for token in [signed(other_private), "not-a-jwt"]:
            assert (
                client.get("/providers", headers={"Authorization": f"Bearer {token}"}).status_code
                == 401
            )


def test_cloud_still_enforces_allowed_email_domains(keypair) -> None:
    token = signed(keypair[0], preferred_username="user@other.test")
    with TestClient(cloud_app(keypair[1])) as client:
        response = client.get(
            "/providers",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 403


def test_unconfigured_cloud_fails_closed_but_liveness_is_available() -> None:
    app = create_app(Settings(auth_mode="entra-jwt", azure_tenant_id=None, auth_audience=None))
    with TestClient(app) as client:
        response = client.get("/providers", headers={"X-Demo-User": "operator@example.com"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "operator_auth_unconfigured"
        assert client.get("/healthz").status_code == 200


def test_explicit_local_demo_preserves_local_workflow() -> None:
    app = create_app(Settings(auth_mode="local-demo", app_env="development"))
    with TestClient(app) as client:
        assert (
            client.get("/providers", headers={"X-Demo-User": "operator@example.com"}).status_code
            == 200
        )


@pytest.mark.parametrize("marker", ["CONTAINER_APP_NAME", "WEBSITE_SITE_NAME"])
def test_cloud_hosting_cannot_enable_demo_headers(monkeypatch, marker) -> None:
    monkeypatch.setenv(marker, "cloud-host")
    with pytest.raises(ValidationError, match="not allowed"):
        Settings(auth_mode="local-demo", app_env="development")


def test_production_cannot_enable_demo_headers() -> None:
    with pytest.raises(ValidationError, match="not allowed"):
        Settings(auth_mode="local-demo", app_env="production")


@pytest.mark.asyncio
async def test_slow_key_lookup_does_not_block_liveness_or_event_loop(keypair) -> None:
    app = cloud_app(keypair[1])
    started = threading.Event()

    def slow_validation(_token):
        started.set()
        time.sleep(0.25)
        return AuthenticatedUser("operator", "operator@example.com", "Operator", "entra-jwt")

    app.state.operator_token_validator = SimpleNamespace(validate=slow_validation)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        authenticated = asyncio.create_task(
            client.get("/providers", headers={"Authorization": "Bearer token"})
        )
        deadline = time.monotonic() + 1
        while not started.is_set() and time.monotonic() < deadline:
            await asyncio.sleep(0.001)
        assert started.is_set()
        start = time.monotonic()
        assert (await client.get("/healthz")).status_code == 200
        assert time.monotonic() - start < 0.15
        assert (await authenticated).status_code == 200


def test_key_discovery_failure_is_explicit_unavailable(keypair) -> None:
    app = cloud_app(keypair[1])

    def unavailable(_token):
        raise jwt.PyJWKClientConnectionError("offline")

    app.state.operator_token_validator._jwks_client = SimpleNamespace(
        get_signing_key_from_jwt=unavailable
    )
    with TestClient(app) as client:
        response = client.get("/providers", headers={"Authorization": "Bearer token"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "identity_provider_unavailable"
