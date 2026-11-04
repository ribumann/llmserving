"""Run the backend locally with an in-memory fake provider/engine and no external
dependencies (no Postgres, no Azure, no real vLLM/GPU) so the app can be exercised
end-to-end through the real frontend in a browser.

This wires the exact same `FakeProvider` / `MemorySession` / `FakeEngineAdapter`
fakes used by the automated contract/integration tests (see
`backend/tests/support/demo_backend.py`) into a real, running FastAPI app instead
of a `TestClient`. The demo environment (`env-demo`) is pre-seeded and READY, so
you can immediately walk through:

  * Model/Inference configuration + Deploy (US2)
  * Exercise / prompt submission (US2)
  * Quality evaluation runs, golden-dataset and benchmark (US3)
  * Performance runs (US4)

Environment *creation*/provisioning (the very first step of US1) is out of scope
for this script since it still requires a real cloud provider adapter; env-demo is
provided already-provisioned so you can test everything downstream of it.

Usage:
    cd backend
    python scripts/run_local_demo.py [--host 127.0.0.1] [--port 8000]

Then, in another terminal:
    cd frontend
    npm run dev

...and open the printed Vite URL (defaults to http://localhost:5173). The
frontend's default API base URL (http://localhost:8000) already matches this
script's default port, so no extra configuration is required.
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from src.api.app import create_app  # noqa: E402
from src.domain.catalog import ModelCatalogEntry  # noqa: E402
from src.domain.environment import DemoEnvironment  # noqa: E402
from src.evaluation.lm_eval_runner import LmEvalRunner  # noqa: E402
from src.evaluation.run_quality import QualityRunOrchestrator  # noqa: E402
from src.persistence.db import get_db_session  # noqa: E402
from src.providers.base import EnvironmentStateView  # noqa: E402
from tests.support.demo_backend import (  # noqa: E402
    FakeProvider,
    FakeScalarResult,
    MemorySession,
    MemorySessionContext,
)

DEMO_USER_EMAIL = "presenter@example.com"
_IDENTITY_HEADERS = {
    "x-ms-client-principal-name",
    "x-forwarded-email",
    "x-user-email",
    "x-demo-user",
}


class LocalDemoProvider(FakeProvider):
    """Extends the test-only FakeProvider with the read-only environment-state
    lookup the frontend's environment dashboard relies on. Provisioning/teardown
    are intentionally not implemented since env-demo is always pre-seeded READY."""

    def getEnvironmentState(self, environment_id: str) -> EnvironmentStateView:
        environment = self._session.get(DemoEnvironment, environment_id)
        if environment is None:
            raise LookupError(f"Environment '{environment_id}' was not found.")
        return EnvironmentStateView(
            environmentId=environment.environmentId,
            lifecycleState=environment.lifecycleState.value,
            activeRevisionId=environment.activeDeploymentRevisionId,
            providerState=dict(environment.providerState or {}),
            context={"region": environment.region, "profileId": environment.profileId},
        )


class LocalMemorySession(MemorySession):
    """Extends the test-only MemorySession with catalog listing support, which
    the shared test fixture never needed because contract/integration tests
    look up catalog entries by ID rather than listing them (`GET /catalog`)."""

    def scalars(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is ModelCatalogEntry:
            return FakeScalarResult(
                sorted(self.catalog_entries.values(), key=lambda item: item.catalogEntryId)
            )
        return super().scalars(statement)


def _fake_benchmark_runner(score: float = 0.82) -> LmEvalRunner:
    """A benchmark runner that returns a canned lm-eval-style score without
    shelling out to the real `lm_eval` CLI or hitting a real inference endpoint."""

    def evaluator(**_kwargs):
        return {"results": {"gsm8k": {"exact_match,strict-match": score}}}

    return LmEvalRunner(evaluator=evaluator)


def build_app() -> FastAPI:
    app = create_app()

    session = LocalMemorySession()
    session.seed_defaults()

    session_factory = lambda: MemorySessionContext(session)  # noqa: E731
    app.state.provider_adapter = LocalDemoProvider(session)
    app.state.session_factory = session_factory
    app.state.telemetry = None
    app.state.quality_run_orchestrator = QualityRunOrchestrator(
        session_factory=session_factory,
        provider=app.state.provider_adapter,
        telemetry=None,
        benchmark_runner=_fake_benchmark_runner(),
        performance_runner=None,
        executor=ThreadPoolExecutor(max_workers=4),
    )

    def override_db_session():
        yield session

    app.dependency_overrides[get_db_session] = override_db_session

    # Local convenience only: the real frontend doesn't send an auth header in
    # local dev (it's normally supplied by Azure Front Door/App Service auth in
    # production), so inject a demo identity when one is missing. This middleware
    # is registered after create_app() so it runs *before* the app's real auth
    # middleware for each request.
    @app.middleware("http")
    async def inject_demo_identity(request: Request, call_next):
        headers = list(request.scope["headers"])
        has_identity = any(
            name.decode("latin-1").lower() in _IDENTITY_HEADERS for name, _ in headers
        )
        if not has_identity:
            headers.append((b"x-demo-user", DEMO_USER_EMAIL.encode("latin-1")))
            request.scope["headers"] = headers
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn autoreload")
    args = parser.parse_args()

    import uvicorn

    app = build_app()
    print(  # noqa: T201
        f"Local demo backend ready at http://{args.host}:{args.port} "
        f"(demo user: {DEMO_USER_EMAIL}, no Postgres/Azure/GPU required)."
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", reload=args.reload)


if __name__ == "__main__":
    main()
