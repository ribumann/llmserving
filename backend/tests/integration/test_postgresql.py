from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from src.api.app import create_app
from src.config import Settings
from src.domain.enums import DemoEnvironmentState, ProviderType
from src.domain.environment import DemoEnvironment
from src.domain.environment_lock import EnvironmentLockedError, EnvironmentLockService
from src.domain.profile import CloudDeploymentProfile
from src.persistence.db import create_engine_from_settings

pytestmark = pytest.mark.integration


@pytest.fixture
def database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "Set TEST_DATABASE_URL to an explicitly disposable, migrated PostgreSQL database."
        )
    if not url.startswith("postgresql+psycopg://"):
        pytest.fail("TEST_DATABASE_URL must use real PostgreSQL through psycopg.")
    engine = create_engine_from_settings(Settings(database_url=url))
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT current_database()")).scalar_one()
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def environment(database):
    session_factory = sessionmaker(bind=database, expire_on_commit=False)
    environment_id = f"postgres-test-{uuid4().hex}"
    with session_factory() as session:
        assert session.get(CloudDeploymentProfile, "local-ollama") is not None
        session.add(
            DemoEnvironment(
                environmentId=environment_id,
                profileId="local-ollama",
                provider=ProviderType.LOCAL,
                region="local",
                lifecycleState=DemoEnvironmentState.READY,
                providerState={"runtime": "ollama", "nested": {"verified": True}},
                createdBy="postgres-test@example.com",
                lastModifiedBy="postgres-test@example.com",
            )
        )
        session.commit()
    try:
        yield session_factory, environment_id
    finally:
        with session_factory() as session:
            session.execute(
                delete(DemoEnvironment).where(DemoEnvironment.environmentId == environment_id)
            )
            session.commit()


def test_migrated_postgres_serves_real_catalog(database) -> None:
    settings = Settings(database_url=os.environ["TEST_DATABASE_URL"])
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/profiles", headers={"X-Demo-User": "postgres-test@example.com"})
        assert response.status_code == 200
        profiles = {profile["profileId"]: profile for profile in response.json()["profiles"]}
        assert profiles["local-ollama"]["provider"] == "local"
        assert isinstance(profiles["local-ollama"]["capacityAssumptions"], dict)
        catalog = client.get("/catalog", headers={"X-Demo-User": "postgres-test@example.com"})
        assert catalog.status_code == 200
        assert any(
            entry["catalogEntryId"] == "qwen2.5-0.5b-instruct"
            for entry in catalog.json()["catalog"]
        )
    app.state.session_factory.kw["bind"].dispose()


def test_jsonb_roundtrip_and_owner_safe_lock_release(environment) -> None:
    session_factory, environment_id = environment
    locks = EnvironmentLockService()
    with session_factory() as session:
        saved = session.get(DemoEnvironment, environment_id)
        assert saved.providerState == {"runtime": "ollama", "nested": {"verified": True}}
        locks.acquire(session, environment_id=environment_id, operation_id="owner")
        session.commit()
    with session_factory() as session:
        with pytest.raises(EnvironmentLockedError):
            locks.release(session, environment_id=environment_id, operation_id="not-owner")
        session.rollback()
    with session_factory() as session:
        assert locks.current(session, environment_id=environment_id).operation_id == "owner"
        locks.release(session, environment_id=environment_id, operation_id="owner")
        session.commit()
    with session_factory() as session:
        assert locks.current(session, environment_id=environment_id).operation_id is None


def test_postgres_serializes_concurrent_lock_acquisition(environment) -> None:
    session_factory, environment_id = environment
    locks = EnvironmentLockService()
    with session_factory() as owner, session_factory() as contender:
        locks.acquire(owner, environment_id=environment_id, operation_id="owner")
        contender.execute(text("SET LOCAL lock_timeout = '250ms'"))
        with pytest.raises(OperationalError) as error:
            locks.acquire(contender, environment_id=environment_id, operation_id="contender")
        assert error.value.orig.sqlstate == "55P03"
        contender.rollback()
        owner.commit()
    with session_factory() as session:
        with pytest.raises(EnvironmentLockedError):
            locks.acquire(session, environment_id=environment_id, operation_id="contender")
        session.rollback()
