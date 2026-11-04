from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from conftest import load_worker_entrypoint

entrypoint = load_worker_entrypoint("export_worker")


def test_run_uploads_json_export_and_completes() -> None:
    callback = MagicMock()
    uploader = MagicMock(return_value="exports/run-1.json")
    report_data = {"resultReportId": "rr-1", "quality": {"cases": [], "aggregate": {}}}

    entrypoint.run(
        workflow_id="wf-1",
        run_id="run-1",
        export_format="json",
        report_data=report_data,
        account_name="acct1",
        container_name="exports",
        callback=callback,
        uploader=uploader,
    )

    uploader.assert_called_once()
    args, kwargs = uploader.call_args
    assert args[0] == "acct1"
    assert args[1] == "exports"
    assert args[2] == "run-1.json"
    assert json.loads(args[3].decode("utf-8")) == report_data
    assert kwargs["content_type"] == "application/json"

    callback.complete_workflow.assert_called_once_with(
        "wf-1",
        status="completed",
        phase="completed",
        diagnostics={"runId": "run-1", "format": "json", "blobPath": "exports/run-1.json"},
    )


def test_run_uploads_csv_export_flattening_cases() -> None:
    callback = MagicMock()
    uploader = MagicMock(return_value="exports/run-2.csv")
    report_data = {
        "quality": {
            "cases": [
                {"caseId": "c1", "status": "pass"},
                {"caseId": "c2", "status": "fail"},
            ]
        }
    }

    entrypoint.run(
        workflow_id="wf-2",
        run_id="run-2",
        export_format="csv",
        report_data=report_data,
        account_name="acct1",
        container_name="exports",
        callback=callback,
        uploader=uploader,
    )

    content = uploader.call_args.args[3].decode("utf-8")
    assert "caseId" in content
    assert "c1" in content and "c2" in content


def test_run_rejects_unsupported_format() -> None:
    callback = MagicMock()
    with pytest.raises(entrypoint.CallbackClientError, match="Unsupported export format"):
        entrypoint.run(
            workflow_id="wf-3",
            run_id="run-3",
            export_format="xml",
            report_data={"a": 1},
            account_name="acct1",
            container_name="exports",
            callback=callback,
        )
    callback.complete_workflow.assert_not_called()


def test_main_fails_gracefully_when_report_data_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKFLOW_ID", "wf-4")
    monkeypatch.setenv("ARTIFACTS_STORAGE_ACCOUNT", "acct1")
    monkeypatch.setenv("EXPORTS_CONTAINER", "exports")
    monkeypatch.setenv("JOB_INPUT_JSON", '{"runId": "run-4", "format": "json", "reportData": {}}')

    callback = MagicMock()
    callback.__enter__ = MagicMock(return_value=callback)
    callback.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(entrypoint, "WorkflowCallbackClient", MagicMock(return_value=callback))

    exit_code = entrypoint.main()

    assert exit_code == 1
    callback.complete_workflow.assert_called_once()
    assert callback.complete_workflow.call_args.kwargs["status"] == "failed"
