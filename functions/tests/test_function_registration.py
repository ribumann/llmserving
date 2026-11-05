from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import azure.durable_functions as df
import azure.functions as func
import function_app
import pytest


@pytest.mark.asyncio
async def test_registered_starter_uses_v2_while_v1_remains_available(monkeypatch) -> None:
    registered = {
        function.get_function_name(): function for function in function_app.app.get_functions()
    }
    assert {
        "generic_orchestrator",
        "generic_orchestrator_v2",
        "finalize_workflow",
    } <= registered.keys()
    monkeypatch.setattr(function_app, "resolve_job_name", lambda _kind: "owned-job")
    start = AsyncMock(return_value="instance-1")
    expected = func.HttpResponse(status_code=202)
    response = MagicMock(return_value=expected)
    monkeypatch.setattr(df.DurableOrchestrationClient, "__init__", lambda self, *args: None)
    monkeypatch.setattr(df.DurableOrchestrationClient, "start_new", start)
    monkeypatch.setattr(df.DurableOrchestrationClient, "create_check_status_response", response)
    request = func.HttpRequest(
        method="POST",
        url="https://functions.example/api/orchestrations",
        body=json.dumps({"workflowId": "wf-1", "workflowType": "provision"}).encode(),
    )

    result = await registered["http_start"].get_user_function()(req=request, client="{}")

    assert result is expected
    start.assert_awaited_once_with(
        "generic_orchestrator_v2",
        client_input={
            "workflowId": "wf-1",
            "workflowType": "provision",
            "jobName": "owned-job",
            "jobInput": {},
            "preDispatchedExecutionName": None,
        },
    )
