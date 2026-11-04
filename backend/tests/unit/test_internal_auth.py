from __future__ import annotations

import time
from dataclasses import dataclass

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from src.api.errors import ApiError
from src.api.internal_auth import InternalTokenValidator

_TENANT_ID = "11111111-1111-1111-1111-111111111111"
_AUDIENCE = "api://internal-orchestration"
_KID = "test-key-1"


@dataclass
class _FakeSigningKey:
    key: object


class _FakeJwksClient:
    """Stands in for `jwt.PyJWKClient` so tests never hit Entra ID's real discovery
    endpoint - it always returns the single test RSA key regardless of the token's
    `kid`, which is enough to exercise the real signature/audience/issuer/expiry
    validation logic in InternalTokenValidator.validate()."""

    def __init__(self, public_key: object) -> None:
        self._public_key = public_key
        self.calls = 0

    def __call__(self, _jwks_uri: str) -> _FakeJwksClient:
        return self

    def get_signing_key_from_jwt(self, _token: str) -> _FakeSigningKey:
        self.calls += 1
        return _FakeSigningKey(key=self._public_key)


@pytest.fixture
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _sign(private_key, *, audience=_AUDIENCE, issuer=None, expires_in=3600, **extra_claims) -> str:
    now = int(time.time())
    claims = {
        "aud": audience,
        "iss": issuer or f"https://login.microsoftonline.com/{_TENANT_ID}/v2.0",
        "iat": now,
        "exp": now + expires_in,
        "oid": "service-principal-object-id",
        "appid": "durable-functions-app-id",
        **extra_claims,
    }
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": _KID})


def _validator(public_key) -> InternalTokenValidator:
    return InternalTokenValidator(
        tenant_id=_TENANT_ID,
        audience=_AUDIENCE,
        jwks_client_factory=_FakeJwksClient(public_key),
    )


def test_validates_a_correctly_signed_token(rsa_keypair) -> None:
    private_key, public_key = rsa_keypair
    token = _sign(private_key)

    caller = _validator(public_key).validate(token)

    assert caller.subject == "service-principal-object-id"
    assert caller.app_id == "durable-functions-app-id"
    assert caller.audience == _AUDIENCE


def test_rejects_wrong_audience(rsa_keypair) -> None:
    private_key, public_key = rsa_keypair
    token = _sign(private_key, audience="api://some-other-api")

    with pytest.raises(ApiError) as exc_info:
        _validator(public_key).validate(token)
    assert exc_info.value.status_code == 401


def test_rejects_wrong_issuer(rsa_keypair) -> None:
    private_key, public_key = rsa_keypair
    token = _sign(private_key, issuer="https://login.microsoftonline.com/some-other-tenant/v2.0")

    with pytest.raises(ApiError) as exc_info:
        _validator(public_key).validate(token)
    assert exc_info.value.status_code == 401


def test_rejects_expired_token(rsa_keypair) -> None:
    private_key, public_key = rsa_keypair
    token = _sign(private_key, expires_in=-60)

    with pytest.raises(ApiError) as exc_info:
        _validator(public_key).validate(token)
    assert exc_info.value.status_code == 401


def test_rejects_token_signed_by_a_different_key(rsa_keypair) -> None:
    _private_key, public_key = rsa_keypair
    other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _sign(other_private_key)

    with pytest.raises(ApiError) as exc_info:
        _validator(public_key).validate(token)
    assert exc_info.value.status_code == 401


def test_rejects_token_missing_a_subject_claim(rsa_keypair) -> None:
    private_key, public_key = rsa_keypair
    now = int(time.time())
    claims = {
        "aud": _AUDIENCE,
        "iss": f"https://login.microsoftonline.com/{_TENANT_ID}/v2.0",
        "iat": now,
        "exp": now + 3600,
    }
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": _KID})

    with pytest.raises(ApiError) as exc_info:
        _validator(public_key).validate(token)
    assert exc_info.value.status_code == 401


def test_accepts_the_legacy_v1_issuer_for_the_same_tenant(rsa_keypair) -> None:
    private_key, public_key = rsa_keypair
    token = _sign(private_key, issuer=f"https://sts.windows.net/{_TENANT_ID}/")

    caller = _validator(public_key).validate(token)

    assert caller.subject == "service-principal-object-id"
