from __future__ import annotations

from fastapi.testclient import TestClient
from src.api.app import create_app
from src.domain.catalog import ModelCatalogEntry
from src.domain.enums import ModelFamily, ModelSizeClass, ProviderType
from src.domain.profile import CloudDeploymentProfile
from src.persistence.db import get_db_session


class NoopPersistenceSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def add(self, _obj) -> None:
        return None

    def commit(self) -> None:
        return None


def _client_with_session(session):
    app = create_app()
    app.state.session_factory = lambda: NoopPersistenceSession()
    app.state.telemetry = None

    def override_db():
        yield session

    app.dependency_overrides[get_db_session] = override_db
    return TestClient(app)


def test_get_profiles_returns_seeded_shape() -> None:
    profile = CloudDeploymentProfile(
        profileId="azure-single-gpu-3b",
        provider=ProviderType.AZURE,
        modelSizeClass=ModelSizeClass.THREE_B,
        eligibleRegions=["eastus2"],
        vmSku="Standard_NC16as_T4_v3",
        capacityAssumptions={"gpuCount": 1},
        configurableInputs={"profileSizeClass": "small"},
        knownLimitations=["Capacity is best-effort."],
        version=1,
    )

    class FakeScalarResult:
        def all(self):
            return [profile]

    class FakeSession:
        def scalars(self, _statement):
            return FakeScalarResult()

    client = _client_with_session(FakeSession())
    response = client.get("/profiles", headers={"X-Demo-User": "presenter@example.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["profiles"][0]["profileId"] == "azure-single-gpu-3b"
    assert body["profiles"][0]["provider"] == "azure"


def test_get_catalog_returns_catalog_shape() -> None:
    entry = ModelCatalogEntry(
        catalogEntryId="qwen3-4b",
        family=ModelFamily.CHINESE_ORIGIN,
        sizeClass=ModelSizeClass.THREE_B,
        huggingFaceRepoId="Qwen/Qwen3-4B",
        checkpointRef="main",
        isGated=False,
        license="Apache 2.0",
        compatibleProfileIds=["azure-single-gpu-3b"],
        quantizationRequired=False,
        notes="Ungated.",
    )

    class FakeScalarResult:
        def all(self):
            return [entry]

    class FakeSession:
        def scalars(self, _statement):
            return FakeScalarResult()

    client = _client_with_session(FakeSession())
    response = client.get("/catalog", headers={"X-Demo-User": "presenter@example.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["catalog"][0]["catalogEntryId"] == "qwen3-4b"
    assert body["catalog"][0]["family"] == "chinese-origin"
