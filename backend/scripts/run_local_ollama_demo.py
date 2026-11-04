"""Run the backend locally against a **real, installed Ollama runtime** using the
actual `LocalProviderAdapter` / `OllamaEngineAdapter` implementation (US7) - not the
canned fakes used by `run_local_demo.py`. Persistence is still an in-memory fake
(the same `MemorySession` used by the automated tests), so no Postgres is required,
but every prompt/quality/performance call goes over real HTTP to Ollama and returns
genuine model output.

Prerequisites:
  1. Install and start Ollama (https://ollama.com/).
  2. Pull a supported small Qwen checkpoint:
       ollama pull qwen2.5:0.5b-instruct
  3. Ollama must be reachable at --ollama-url (default http://localhost:11434).

Usage:
    cd backend
    python scripts/run_local_ollama_demo.py [--host 127.0.0.1] [--port 8000]
        [--ollama-url http://localhost:11434]

Then, in another terminal:
    cd frontend
    npm run dev

...and open the printed Vite URL. In the UI, choose the "Local (Ollama)" profile
during provisioning - everything downstream (deploy, prompt, quality, performance)
runs against your real local Ollama instance.
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import httpx  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from src.config import Settings  # noqa: E402
from src.domain.benchmark_definition import BenchmarkDefinition  # noqa: E402
from src.domain.catalog import ModelCatalogEntry  # noqa: E402
from src.domain.enums import DatasetProvenance, DuplicateCheckState, ReviewStatus  # noqa: E402
from src.domain.golden_dataset import GoldenDataset  # noqa: E402
from src.engines.ollama.adapter import OllamaEngineAdapter  # noqa: E402
from src.evaluation.run_quality import QualityRunOrchestrator  # noqa: E402
from src.persistence.db import get_db_session  # noqa: E402
from src.providers.azure.adapter import AzureProviderAdapter  # noqa: E402
from src.providers.local.adapter import LocalProviderAdapter  # noqa: E402
from src.providers.registry import CompositeProviderAdapter  # noqa: E402
from tests.support.demo_backend import (  # noqa: E402
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


class LocalMemorySession(MemorySession):
    """Adds `GET /catalog` list support on top of the shared test fixture, which
    only supports point lookups by catalog entry ID."""

    def scalars(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is ModelCatalogEntry:
            return FakeScalarResult(
                sorted(self.catalog_entries.values(), key=lambda item: item.catalogEntryId)
            )
        return super().scalars(statement)


def _seed_quality_and_perf_fixtures(session: MemorySession) -> None:
    session.golden_datasets["golden-local"] = GoldenDataset(
        goldenDatasetId="golden-local",
        name="Local Golden",
        version=1,
        cases=[
            {
                "caseId": "case-1",
                "input": "What is the capital of France?",
                "evaluationRule": "contains",
                "expectedOutput": "Paris",
            }
        ],
        duplicateCheckState=DuplicateCheckState.CLEAN,
        provenance=DatasetProvenance.CURATED,
        reviewStatus=ReviewStatus.REVIEWED,
        generationContext=None,
    )
    session.benchmark_definitions["gsm8k"] = BenchmarkDefinition(
        benchmarkId="gsm8k",
        version="presentation-50-seed-42",
        presentationSubset={"task": "gsm8k", "metric": "exact_match,strict-match"},
        passFailThreshold={"baselineScore": 75.0, "regressionThresholdPoints": 5.0},
    )


def build_app(*, ollama_base_url: str) -> FastAPI:
    settings = Settings(ollama_base_url=ollama_base_url)

    session = LocalMemorySession()
    session.seed_defaults()
    _seed_quality_and_perf_fixtures(session)

    session_factory = lambda: MemorySessionContext(session)  # noqa: E731

    http_client = httpx.Client(timeout=60.0)
    engine_adapter = OllamaEngineAdapter(
        settings=settings,
        http_client=http_client,
        session_factory=session_factory,
    )
    local_provider = LocalProviderAdapter(
        session_factory=session_factory,
        settings=settings,
        http_client=http_client,
        engine_adapter=engine_adapter,
    )
    azure_provider = AzureProviderAdapter(
        session_factory=session_factory,
        settings=settings,
        telemetry=None,
    )
    provider_adapter = CompositeProviderAdapter(
        azure=azure_provider,
        local=local_provider,
        session_factory=session_factory,
    )

    from src.api.app import create_app

    app = create_app(settings=settings)
    app.state.provider_adapter = provider_adapter
    app.state.session_factory = session_factory
    app.state.telemetry = None
    app.state.quality_run_orchestrator = QualityRunOrchestrator(
        session_factory=session_factory,
        provider=provider_adapter,
        telemetry=None,
        executor=ThreadPoolExecutor(max_workers=4),
    )

    def override_db_session():
        yield session

    app.dependency_overrides[get_db_session] = override_db_session

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
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    args = parser.parse_args()

    try:
        response = httpx.get(args.ollama_url, timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        print(  # noqa: T201
            f"Warning: could not reach Ollama at {args.ollama_url} ({exc}). "
            "Provisioning will fail until it is reachable."
        )

    import uvicorn

    app = build_app(ollama_base_url=args.ollama_url)
    print(  # noqa: T201
        f"Local Ollama demo backend ready at http://{args.host}:{args.port} "
        f"(demo user: {DEMO_USER_EMAIL}, provider: real LocalProviderAdapter -> "
        f"{args.ollama_url}, persistence: in-memory, no Postgres/Azure required)."
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
