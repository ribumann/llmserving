"""Unit tests for T138's `workflowId` correlation-ID propagation
(backend/src/api/correlation.py, FR-086)."""

from __future__ import annotations

import logging

from src.api.correlation import (
    WorkflowIdLogFilter,
    configure_monitoring,
    current_workflow_id,
    workflow_correlation,
)


def test_workflow_correlation_binds_and_restores() -> None:
    assert current_workflow_id() is None

    with workflow_correlation("wf-1"):
        assert current_workflow_id() == "wf-1"

        with workflow_correlation("wf-2"):
            assert current_workflow_id() == "wf-2"

        assert current_workflow_id() == "wf-1"

    assert current_workflow_id() is None


def test_workflow_id_log_filter_stamps_active_workflow_id() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    filt = WorkflowIdLogFilter()

    with workflow_correlation("wf-123"):
        assert filt.filter(record) is True
        assert record.workflowId == "wf-123"  # type: ignore[attr-defined]

    assert filt.filter(record) is True
    assert record.workflowId is None  # type: ignore[attr-defined]


def test_configure_monitoring_is_a_noop_without_connection_string(monkeypatch) -> None:
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    # Must not raise even though no Application Insights connection string is
    # configured (local dev/tests/CI never set one).
    configure_monitoring()


def test_configure_monitoring_never_raises_on_exporter_failure(monkeypatch) -> None:
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=fake")
    # No real azure-monitor-opentelemetry setup will succeed against a fake
    # connection string in a test environment with no network access to
    # Azure - configure_monitoring() must swallow that failure rather than
    # blocking app startup.
    configure_monitoring()
