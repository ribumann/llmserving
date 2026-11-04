from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from fastapi.testclient import TestClient
from src.api.app import create_app
from src.api.internal_auth import InternalCaller, require_internal_identity
from src.domain.environment import DemoEnvironment
from src.persistence.db import get_db_session
from tests.support.demo_backend import MemorySession, NoopPersistenceSession, _extract_equals_value


class RowLockingMemorySession(MemorySession):
    """A `MemorySession` variant that faithfully models Postgres's
    `SELECT ... FOR UPDATE` for the single-writer lock (FR-052): a per-environment
    `threading.Lock`, shared across every "connection" opened against the same
    in-memory database, is held for the duration of the caller's transaction
    (released on commit/rollback) so a concurrent acquire attempt for the same
    environment genuinely blocks - rather than racing to read stale data - exactly
    the property FR-052/SC-012 relies on Postgres's row lock for.

    This repo's test suite has no real Postgres available (no service container in
    CI, no integration tests hit a live database anywhere), so this is the most
    faithful concurrency test achievable at the application layer: it proves the
    service/route logic enforces "exactly one concurrent acquire wins" under real OS
    thread interleaving, even though it cannot exercise Postgres's own wire protocol.
    """

    _row_locks: dict[str, threading.Lock] = {}
    _row_locks_guard = threading.Lock()

    def __init__(self, shared_environments: dict[str, DemoEnvironment]) -> None:
        super().__init__()
        self.environments = shared_environments
        self._held_lock: threading.Lock | None = None

    @classmethod
    def _lock_for(cls, environment_id: str) -> threading.Lock:
        with cls._row_locks_guard:
            if environment_id not in cls._row_locks:
                cls._row_locks[environment_id] = threading.Lock()
            return cls._row_locks[environment_id]

    def execute(self, statement):
        entity = (
            statement.column_descriptions[0].get("entity")
            if hasattr(statement, "column_descriptions")
            else None
        )
        if entity is DemoEnvironment:
            environment_id = _extract_equals_value(statement, "environment_id") or next(
                iter(self.environments), None
            )
            lock = self._lock_for(environment_id)
            lock.acquire()  # Blocks until the previous holder commits/rolls back.
            self._held_lock = lock
            item = self.environments.get(environment_id)
            return SimpleNamespace(scalar_one_or_none=lambda: item)
        return super().execute(statement)

    def commit(self) -> None:
        self._release()

    def close(self) -> None:
        # Mirrors real SQLAlchemy `Session.close()`: rolls back (and releases the
        # row lock for) any transaction that was never explicitly committed - this
        # is what happens on the real `with session_factory() as session:` path in
        # `get_db_session` when a route raises before calling `session.commit()`
        # (e.g. the 409 "environment_locked" path). Without this, a caller that
        # loses the race would hold the lock forever and deadlock every other
        # concurrent request.
        self._release()

    def _release(self) -> None:
        if self._held_lock is not None:
            self._held_lock.release()
            self._held_lock = None


def test_concurrent_create_workflow_requests_only_let_one_operation_through() -> None:
    shared_environments: dict[str, DemoEnvironment] = {}
    seed_session = MemorySession()
    seed_session.seed_defaults()
    shared_environments["env-demo"] = seed_session.environments["env-demo"]

    app = create_app()
    app.state.session_factory = lambda: NoopPersistenceSession()
    app.state.telemetry = None

    def override_db():
        # Each concurrent request gets its own "connection" (session instance),
        # but they all share the same underlying environment row/lock, matching how
        # separate Postgres connections contend for the same row. Wrapped the same
        # way `get_db_session` wraps a real Session in `with session_factory() as
        # session:` - the `finally: session.close()` is what releases the lock for
        # a request that raises (e.g. 409) without ever calling `commit()`.
        session = RowLockingMemorySession(shared_environments)
        try:
            yield session
        finally:
            session.close()

    def override_internal_identity() -> InternalCaller:
        return InternalCaller(subject="durable-functions-app", app_id="test-app", audience="test")

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[require_internal_identity] = override_internal_identity
    client = TestClient(app)

    def call(index: int):
        return client.post(
            "/internal/workflows",
            json={
                "environmentId": "env-demo",
                "operationId": f"op-{index}",
                "workflowType": "provision",
            },
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(executor.map(call, range(8)))

    created = [r for r in responses if r.status_code == 201]
    conflicted = [r for r in responses if r.status_code == 409]

    assert len(created) == 1
    assert len(conflicted) == 7
    for response in conflicted:
        assert response.json()["error"]["code"] == "environment_locked"
