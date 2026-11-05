"""Real HTTP/PostgreSQL/Ollama flow; no in-memory repository or inference mocks."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.engine import make_url
from src.config import Settings
from src.domain.enums import DatasetProvenance, DuplicateCheckState, ReviewStatus
from src.domain.golden_dataset import GoldenDataset
from src.domain.performance_workload import PerformanceWorkload
from src.persistence.db import create_session_factory

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("LIVE_API_URL"),
        reason="Requires explicit loopback API, disposable PostgreSQL and real Ollama.",
    ),
]


def _wait(client: httpx.Client, path: str, field: str, expected: str) -> dict:
    deadline = monotonic() + 180
    last = {}
    while monotonic() < deadline:
        response = client.get(path)
        response.raise_for_status()
        last = response.json()
        if last.get(field) == expected:
            return last
        assert last.get(field) not in {"failed", "incomplete", "deployment_failed"}, last
        sleep(0.25)
    pytest.fail(f"Timed out waiting for {path}: {last}")


def test_real_local_api_flow() -> None:
    api_url = os.environ["LIVE_API_URL"]
    ollama_url = os.environ["OLLAMA_BASE_URL"]
    database_url = os.environ["TEST_DATABASE_URL"]
    for url in (api_url, ollama_url):
        parsed = urlparse(url)
        assert parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
    db = make_url(database_url)
    assert db.host in {"localhost", "127.0.0.1"} and db.database == "llmserving_ci"

    model_tag = "qwen2.5:0.5b-instruct"
    tags = httpx.get(f"{ollama_url}/api/tags", timeout=10).raise_for_status().json()
    model = next(item for item in tags["models"] if item["name"] == model_tag)
    print(f"MODEL_DIGEST={model['digest']}")
    expected_digest = os.environ["OLLAMA_EXPECTED_DIGEST"]
    assert model["digest"] == expected_digest
    evidence = {
        "commit": os.getenv("GITHUB_SHA", "unrecorded"),
        "model": model,
        "ollamaVersion": httpx.get(f"{ollama_url}/api/version").json(),
        "scope": "CPU-only real API; not browser, Azure, LLMPerf or benchmark acceptance",
        "reports": {},
        "passed": False,
    }
    session_factory = create_session_factory(Settings(database_url=database_url))
    prefix = f"live-{uuid4().hex[:8]}"
    with session_factory() as session:
        for suffix, count in (("golden", 2), ("cancel", 50)):
            session.add(
                GoldenDataset(
                    goldenDatasetId=f"{prefix}-{suffix}",
                    name=f"Live {suffix}",
                    version=1,
                    cases=[
                        {
                            "caseId": f"case-{index}",
                            "input": f"Compute {index}+1. Reply with one number.",
                            "evaluationRule": "exact-match",
                            "expectedOutput": str(index + 1),
                            "parameters": {"max_tokens": 8, "temperature": 0.0},
                        }
                        for index in range(count)
                    ],
                    duplicateCheckState=DuplicateCheckState.CLEAN,
                    provenance=DatasetProvenance.CURATED,
                    reviewStatus=ReviewStatus.REVIEWED,
                )
            )
        for concurrency, count in ((1, 2), (10, 10)):
            session.add(
                PerformanceWorkload(
                    workloadId=f"{prefix}-perf-{concurrency}",
                    version=1,
                    warmup={"requestCount": 1},
                    inputProfile={
                        "prompt": "Count from one to five.",
                        "meanOutputTokens": 8,
                        "meanInputTokens": 8,
                        "stddevInputTokens": 0,
                        "stddevOutputTokens": 0,
                    },
                    concurrency=concurrency,
                    durationOrRequestCount={"requestCount": count},
                    safetyLimits={
                        "maxRequests": count,
                        "maxConcurrency": concurrency,
                        "timeoutSeconds": 120,
                    },
                    completionCriteria={"targetCompletedRequests": count},
                )
            )
        session.commit()

    environment_id = None
    with httpx.Client(
        base_url=api_url, headers={"X-Demo-User": "presenter@example.com"}, timeout=120
    ) as client:

        def post(path: str, payload: dict, status: int) -> dict:
            response = client.post(path, json=payload)
            assert response.status_code == status, response.text
            return response.json()

        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 200
        assert httpx.get(f"{api_url}/providers").status_code == 401
        try:
            post("/environments/preview", {"profileId": "local-ollama"}, 200)
            environment_id = post("/environments", {"profileId": "local-ollama"}, 202)[
                "environmentId"
            ]
            base = f"/environments/{environment_id}"
            _wait(client, base, "lifecycleState", "ready")
            model_config = post(
                f"{base}/model-configurations",
                {
                    "catalogEntryId": "qwen2.5-0.5b-instruct",
                    "resolvedCheckpointRef": model_tag,
                    "modelSettings": {"digest": model["digest"]},
                },
                201,
            )
            inference = post(
                f"{base}/inference-configurations",
                {
                    "engineId": "ollama",
                    "servingSettings": {},
                    "generationSettings": {"temperature": 0.0, "max_tokens": 8},
                },
                201,
            )
            deployment = post(
                f"{base}/deployments",
                {
                    "modelConfigId": model_config["modelConfigId"],
                    "inferenceConfigId": inference["inferenceConfigId"],
                },
                202,
            )
            revision = deployment["deploymentRevisionId"]
            _wait(client, f"{base}/deployments/{revision}", "lifecycleState", "ready")
            deployed_models = (
                httpx.get(f"{ollama_url}/api/tags", timeout=10).raise_for_status().json()["models"]
            )
            assert next(
                item["digest"] for item in deployed_models if item["name"] == model_tag
            ) == (expected_digest)
            prompt = post(
                f"{base}/prompts",
                {
                    "prompt": "Say hello.",
                    "parameters": {"max_tokens": 8, "temperature": 0.0},
                },
                200,
            )
            assert prompt["responseText"].strip()
            assert prompt["timing"]["ttftMs"] > 0
            evidence["prompt"] = prompt
            if os.getenv("LIVE_BROWSER_ENABLED") == "1":
                subprocess.run(
                    ["npm", "test", "--", "--config=playwright.live.config.ts"],
                    cwd=Path(__file__).resolve().parents[3] / "e2e",
                    env={
                        **os.environ,
                        "LIVE_ENVIRONMENT_ID": environment_id,
                        "LIVE_DEPLOYMENT_REVISION_ID": revision,
                    },
                    check=True,
                    timeout=180,
                )
                browser = json.loads(Path(os.environ["LIVE_BROWSER_EVIDENCE_FILE"]).read_text())
                assert browser["passed"] and browser["revisionId"] == revision
                assert browser["model"]["digest"] == expected_digest
                evidence["browser"] = browser
                evidence["scope"] = (
                    "CPU-only real browser/API; local-demo, not Azure SSO, LLMPerf "
                    "or benchmark acceptance"
                )
            golden_id = None
            for kind, definition in (
                ("quality-golden", f"{prefix}-golden"),
                ("performance", f"{prefix}-perf-1"),
                ("performance", f"{prefix}-perf-10"),
            ):
                run = post(f"{base}/runs", {"runType": kind, "testDefinitionRef": definition}, 202)
                run_path = f"{base}/runs/{run['runId']}"
                _wait(client, run_path, "status", "completed")
                report = client.get(f"{run_path}/report").raise_for_status().json()
                evidence["reports"][definition] = report
                if kind == "quality-golden":
                    golden_id = run["runId"]
                    aggregate = report["quality"]["aggregate"]
                    assert aggregate["totalCases"] == 2 and aggregate["errored"] == 0
                    assert aggregate["passed"] + aggregate["failed"] == 2
                else:
                    perf = report["performance"]
                    count = 2 if definition.endswith("-1") else 10
                    assert perf["requestFailures"]["total"] == count
                    assert perf["requestFailures"]["count"] == 0
                    assert perf["metrics"]["throughputTokensPerSec"] > 0
                    assert perf["metrics"]["timeToFirstTokenMs"]["p50"] > 0
            updated = post(
                f"{base}/inference-configurations",
                {
                    "engineId": "ollama",
                    "generationSettings": {"temperature": 0.2},
                },
                201,
            )
            assert updated["version"] == 2 and inference["version"] == 1
            prior = client.get(f"{base}/runs/{golden_id}/report").raise_for_status().json()
            assert prior["configuration"]["generationSettings"]["temperature"] == 0.0
            cancel = post(
                f"{base}/runs",
                {
                    "runType": "quality-golden",
                    "testDefinitionRef": f"{prefix}-cancel",
                },
                202,
            )
            cancel_path = f"{base}/runs/{cancel['runId']}"
            post(f"{cancel_path}/cancel", {}, 200)
            _wait(client, cancel_path, "status", "cancelled")
            cancelled = client.get(f"{cancel_path}/report").raise_for_status().json()
            assert cancelled["quality"]["aggregate"]["skipped"] > 0
            evidence["cancelled"] = cancelled
            evidence["apiFlowPassed"] = True
        finally:
            try:
                if environment_id:
                    base = f"/environments/{environment_id}"
                    preview = post(f"{base}/teardown/preview", {}, 200)
                    post(f"{base}/teardown", {"previewToken": preview["previewToken"]}, 202)
                    _wait(client, base, "lifecycleState", "torn_down")
                    evidence["teardownVerified"] = True
                    evidence["passed"] = bool(evidence.get("apiFlowPassed"))
            finally:
                destination = os.getenv("FULLSTACK_EVIDENCE_FILE")
                if destination:
                    Path(destination).write_text(json.dumps(evidence, indent=2))
