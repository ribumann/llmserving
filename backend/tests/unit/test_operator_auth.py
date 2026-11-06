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
from src.api.auth import AuthenticatedUser, OperatorTokenValidator, build_operator_token_validator
from src.api.errors import ApiError
from src.api.internal_auth import build_internal_token_validator
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
        response = client.get("/session", headers={header: value})
        assert response.status_code == 200
        assert response.json()["authenticated"] is True
        assert set(response.json()) == {"authenticated", "requestId"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/session"),
        ("GET", "/environments"),
        ("GET", "/catalog"),
        ("GET", "/environments/private/runs"),
        ("GET", "/environments/private/runs/private/report"),
        ("GET", "/environments/private/model-configurations"),
        ("GET", "/environments/private/inference-configurations"),
        ("POST", "/environments/preview"),
        ("POST", "/environments"),
        ("POST", "/environments/private/deployments"),
        ("POST", "/environments/private/prompts"),
        ("POST", "/environments/private/runs"),
        ("POST", "/environments/private/runs/private/cancel"),
        ("POST", "/environments/private/model-configurations"),
        ("POST", "/environments/private/inference-configurations"),
        ("POST", "/environments/private/teardown"),
        ("POST", "/comparisons"),
    ],
)
def test_public_shell_does_not_make_operator_data_or_actions_public(keypair, method, path) -> None:
    with TestClient(cloud_app(keypair[1])) as client:
        assert client.request(method, path).status_code == 401
        token = signed(keypair[0], preferred_username="user@outside.test")
        response = client.request(method, path, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403


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


def test_separate_sso_tenant_keeps_arm_and_internal_auth_independent(keypair, monkeypatch) -> None:
    sso_tenant = "33333333-3333-3333-3333-333333333333"
    internal_audience = "api://internal-test"
    key_urls = []

    def keys(url, **_kwargs):
        key_urls.append(url)
        return SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=keypair[1]))

    monkeypatch.setattr("src.api.internal_auth.PyJWKClient", keys)
    settings = Settings(
        auth_mode="entra-jwt",
        app_env="production",
        azure_subscription_id="44444444-4444-4444-4444-444444444444",
        azure_tenant_id=TENANT,
        auth_tenant_id=sso_tenant,
        auth_audience=AUDIENCE,
        internal_api_audience=internal_audience,
    )
    app = create_app(settings)
    with TestClient(app) as client:

        def request(**claims):
            token = signed(
                keypair[0],
                **{
                    "iss": f"https://login.microsoftonline.com/{sso_tenant}/v2.0",
                    "tid": sso_tenant,
                    **claims,
                },
            )
            return client.get("/providers", headers={"Authorization": f"Bearer {token}"})

        assert request().status_code == 200
        assert request(preferred_username="user@outside.test").status_code == 403
        assert request(aud="wrong-audience").status_code == 401
        assert request(tid=TENANT).status_code == 401
        deployment_token = signed(keypair[0])
        assert (
            client.get(
                "/providers", headers={"Authorization": f"Bearer {deployment_token}"}
            ).status_code
            == 401
        )

    internal = app.state.internal_token_validator
    service_token = signed(keypair[0], aud=internal_audience, appid="test-managed-identity")
    assert internal.validate(service_token).app_id == "test-managed-identity"
    with pytest.raises(ApiError) as error:
        internal.validate(
            signed(
                keypair[0],
                aud=internal_audience,
                tid=sso_tenant,
                iss=f"https://login.microsoftonline.com/{sso_tenant}/v2.0",
            )
        )
    assert error.value.status_code == 401
    assert settings.azure_tenant_id == TENANT
    assert settings.azure_subscription_id == "44444444-4444-4444-4444-444444444444"
    assert f"https://login.microsoftonline.com/{sso_tenant}/discovery/v2.0/keys" in key_urls
    assert f"https://login.microsoftonline.com/{TENANT}/discovery/v2.0/keys" in key_urls


def test_unset_sso_tenant_preserves_deployment_tenant(monkeypatch) -> None:
    monkeypatch.delenv("AUTH_TENANT_ID", raising=False)
    settings = Settings(auth_mode="entra-jwt", azure_tenant_id=TENANT, auth_audience=AUDIENCE)
    assert build_operator_token_validator(settings)._tenant_id == TENANT


def test_operator_tenant_does_not_configure_internal_identity() -> None:
    settings = Settings(
        auth_mode="entra-jwt",
        auth_tenant_id=TENANT,
        auth_audience=AUDIENCE,
        azure_tenant_id=None,
        internal_api_audience="api://internal",
    )
    assert build_operator_token_validator(settings)._tenant_id == TENANT
    assert build_internal_token_validator(settings) is None


@pytest.mark.parametrize("value", ["", " ", "common", "organizations", "not-a-uuid"])
def test_explicit_invalid_sso_tenant_fails_instead_of_falling_back(value) -> None:
    with pytest.raises(ValidationError, match="tenant UUID"):
        Settings(azure_tenant_id=TENANT, auth_tenant_id=value)


def test_sso_tenant_environment_setting_is_canonical(monkeypatch) -> None:
    tenant = "abcdefab-abcd-abcd-abcd-abcdefabcdef"
    monkeypatch.setenv("AUTH_TENANT_ID", tenant.upper())
    assert Settings().auth_tenant_id == tenant
