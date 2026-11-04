"""Unit tests for T138's jobs-side `workflowId` correlation-ID propagation
(jobs/common/telemetry.py, FR-086)."""

from __future__ import annotations

import logging

from common.telemetry import configure_job_telemetry


def test_configure_job_telemetry_stamps_workflow_id_on_records() -> None:
    logger = configure_job_telemetry("wf-123", logger_name="test-telemetry-stamp")

    record = logging.LogRecord(
        name=logger.name,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    for handler_or_filter in logger.filters:
        assert handler_or_filter.filter(record) is True
    assert record.workflowId == "wf-123"  # type: ignore[attr-defined]


def test_configure_job_telemetry_is_a_noop_without_connection_string(monkeypatch) -> None:
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    # Must not raise even though no Application Insights connection string is
    # configured (local dev/tests/CI never set one).
    configure_job_telemetry("wf-noop", logger_name="test-telemetry-noop")


def test_configure_job_telemetry_never_raises_on_exporter_failure(monkeypatch) -> None:
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=fake")
    # No real azure-monitor-opentelemetry setup will succeed against a fake
    # connection string in a test environment with no network access to
    # Azure - configure_job_telemetry() must swallow that failure rather than
    # blocking the job from doing its actual work.
    configure_job_telemetry("wf-fake", logger_name="test-telemetry-fake")
