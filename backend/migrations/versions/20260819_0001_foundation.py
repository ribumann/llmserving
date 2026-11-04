"""Create foundational backend schema."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260819_0001"
down_revision = None
branch_labels = None
depends_on = None

provider_type = sa.Enum("azure", name="provider_type", native_enum=False, length=32)
model_size_class = sa.Enum("3b", "7b", "70b", name="model_size_class", native_enum=False, length=16)
model_family = sa.Enum(
    "gemma",
    "llama",
    "chinese-origin",
    name="model_family",
    native_enum=False,
    length=32,
)
environment_state = sa.Enum(
    "not_provisioned",
    "provisioning",
    "ready",
    "provisioning_failed",
    "tearing_down",
    "torn_down",
    "teardown_failed",
    name="demo_environment_state",
    native_enum=False,
    length=32,
)
deployment_state = sa.Enum(
    "pending",
    "deploying",
    "ready",
    "deployment_failed",
    "superseded",
    name="deployment_revision_state",
    native_enum=False,
    length=32,
)
duplicate_check_state = sa.Enum(
    "not_checked",
    "clean",
    "duplicates_detected",
    name="duplicate_check_state",
    native_enum=False,
    length=32,
)
run_type = sa.Enum(
    "quality-golden",
    "quality-benchmark",
    "performance",
    "interactive-prompt",
    name="experiment_run_type",
    native_enum=False,
    length=32,
)
run_status = sa.Enum(
    "queued",
    "running",
    "completed",
    "cancelled",
    "failed",
    "incomplete",
    name="experiment_run_status",
    native_enum=False,
    length=32,
)
retention_class = sa.Enum(
    "persisted",
    "session-ephemeral",
    name="retention_class",
    native_enum=False,
    length=32,
)
completeness_indicator = sa.Enum(
    "complete",
    "partial",
    "unavailable-monitoring-data",
    name="completeness_indicator",
    native_enum=False,
    length=32,
)
comparison_status = sa.Enum(
    "comparable",
    "not-directly-comparable",
    name="comparison_status",
    native_enum=False,
    length=32,
)


def upgrade() -> None:
    op.create_table(
        "cloud_deployment_profiles",
        sa.Column("profile_id", sa.String(length=100), primary_key=True),
        sa.Column("provider", provider_type, nullable=False),
        sa.Column("model_size_class", model_size_class, nullable=False),
        sa.Column("eligible_regions", postgresql.ARRAY(sa.String(length=100)), nullable=False),
        sa.Column("vm_sku", sa.String(length=100), nullable=False),
        sa.Column("capacity_assumptions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("configurable_inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("known_limitations", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )

    op.create_table(
        "model_catalog_entries",
        sa.Column("catalog_entry_id", sa.String(length=100), primary_key=True),
        sa.Column("family", model_family, nullable=False),
        sa.Column("size_class", model_size_class, nullable=False),
        sa.Column("hugging_face_repo_id", sa.String(length=200), nullable=False),
        sa.Column("checkpoint_ref", sa.String(length=200), nullable=False),
        sa.Column("is_gated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("license", sa.String(length=200), nullable=False),
        sa.Column(
            "compatible_profile_ids", postgresql.ARRAY(sa.String(length=100)), nullable=False
        ),
        sa.Column("quantization_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
    )

    op.create_table(
        "inference_engines",
        sa.Column("engine_id", sa.String(length=50), primary_key=True),
        sa.Column("adapter_contract_version", sa.String(length=32), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )

    op.create_table(
        "demo_environments",
        sa.Column("environment_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(length=100),
            sa.ForeignKey("cloud_deployment_profiles.profile_id"),
            nullable=False,
        ),
        sa.Column("provider", provider_type, nullable=False),
        sa.Column("region", sa.String(length=100), nullable=False),
        sa.Column("region_recommendation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("lifecycle_state", environment_state, nullable=False),
        sa.Column("active_deployment_revision_id", sa.String(length=100), nullable=True),
        sa.Column("active_operation_id", sa.String(length=100), nullable=True),
        sa.Column("provider_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("last_modified_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "model_configurations",
        sa.Column("model_config_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "catalog_entry_id",
            sa.String(length=100),
            sa.ForeignKey("model_catalog_entries.catalog_entry_id"),
            nullable=False,
        ),
        sa.Column("resolved_checkpoint_ref", sa.String(length=200), nullable=False),
        sa.Column("model_settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "inference_configurations",
        sa.Column("inference_config_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "engine_id",
            sa.String(length=50),
            sa.ForeignKey("inference_engines.engine_id"),
            nullable=False,
        ),
        sa.Column("serving_settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("generation_settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "deployment_revisions",
        sa.Column("deployment_revision_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "environment_id",
            sa.String(length=100),
            sa.ForeignKey("demo_environments.environment_id"),
            nullable=False,
        ),
        sa.Column(
            "model_config_id",
            sa.String(length=100),
            sa.ForeignKey("model_configurations.model_config_id"),
            nullable=False,
        ),
        sa.Column(
            "inference_config_id",
            sa.String(length=100),
            sa.ForeignKey("inference_configurations.inference_config_id"),
            nullable=False,
        ),
        sa.Column(
            "engine_id",
            sa.String(length=50),
            sa.ForeignKey("inference_engines.engine_id"),
            nullable=False,
        ),
        sa.Column("lifecycle_state", deployment_state, nullable=False),
        sa.Column("active_period", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_foreign_key(
        "fk_demo_environments_active_deployment_revision",
        "demo_environments",
        "deployment_revisions",
        ["active_deployment_revision_id"],
        ["deployment_revision_id"],
    )

    op.create_table(
        "golden_datasets",
        sa.Column("golden_dataset_id", sa.String(length=100), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("cases", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "duplicate_check_state",
            duplicate_check_state,
            nullable=False,
            server_default="not_checked",
        ),
    )

    op.create_table(
        "benchmark_definitions",
        sa.Column("benchmark_id", sa.String(length=100), primary_key=True),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("presentation_subset", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("pass_fail_threshold", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )

    op.create_table(
        "performance_workloads",
        sa.Column("workload_id", sa.String(length=100), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("warmup", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("concurrency", sa.Integer(), nullable=False),
        sa.Column(
            "duration_or_request_count", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("safety_limits", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("completion_criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )

    op.create_table(
        "experiment_runs",
        sa.Column("run_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "deployment_revision_id",
            sa.String(length=100),
            sa.ForeignKey("deployment_revisions.deployment_revision_id"),
            nullable=False,
        ),
        sa.Column("run_type", run_type, nullable=False),
        sa.Column("test_definition_ref", sa.String(length=100), nullable=True),
        sa.Column("status", run_status, nullable=False),
        sa.Column(
            "environment_context_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("event_log_ref", sa.String(length=100), nullable=True),
        sa.Column("cancellation_requests", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("retention_class", retention_class, nullable=False),
    )

    op.create_table(
        "result_reports",
        sa.Column("result_report_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=100),
            sa.ForeignKey("experiment_runs.run_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("quality", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("performance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("completeness_indicator", completeness_indicator, nullable=False),
        sa.Column("reference_execution_profile_ref", sa.String(length=100), nullable=True),
    )

    op.create_table(
        "comparisons",
        sa.Column("comparison_id", sa.String(length=100), primary_key=True),
        sa.Column("result_report_ids", postgresql.ARRAY(sa.String(length=100)), nullable=False),
        sa.Column("configuration_diff", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quality_diff", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("performance_diff", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failure_diff", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("utilization_diff", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("comparability_status", comparison_status, nullable=False),
        sa.Column("comparability_reasons", postgresql.ARRAY(sa.Text()), nullable=False),
    )

    op.create_table(
        "audit_log_entries",
        sa.Column("audit_log_id", sa.String(length=36), primary_key=True),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("actor_email", sa.String(length=255), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_audit_log_entries_request_id", "audit_log_entries", ["request_id"])

    op.create_table(
        "operation_events",
        sa.Column("event_id", sa.String(length=36), primary_key=True),
        sa.Column("operation_id", sa.String(length=100), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("environment_id", sa.String(length=100), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_operation_events_operation_id", "operation_events", ["operation_id"])
    op.create_index("ix_operation_events_request_id", "operation_events", ["request_id"])

    op.execute(
        sa.text(
            """
            INSERT INTO inference_engines (engine_id, adapter_contract_version, capabilities)
            VALUES (
                'vllm',
                '2026-08-19',
                '{
                  "deploymentImage": "vllm/vllm-openai",
                  "openAiCompatible": true,
                  "quantizationModes": ["awq", "gptq", "fp8", "int4", "gguf"],
                  "metricsEndpoints": ["/metrics", "/health"],
                  "maxModelSizeClass": "70b"
                }'::jsonb
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_operation_events_request_id", table_name="operation_events")
    op.drop_index("ix_operation_events_operation_id", table_name="operation_events")
    op.drop_table("operation_events")

    op.drop_index("ix_audit_log_entries_request_id", table_name="audit_log_entries")
    op.drop_table("audit_log_entries")

    op.drop_table("comparisons")
    op.drop_table("result_reports")
    op.drop_table("experiment_runs")
    op.drop_table("performance_workloads")
    op.drop_table("benchmark_definitions")
    op.drop_table("golden_datasets")

    op.drop_constraint(
        "fk_demo_environments_active_deployment_revision", "demo_environments", type_="foreignkey"
    )
    op.drop_table("deployment_revisions")
    op.drop_table("inference_configurations")
    op.drop_table("model_configurations")
    op.drop_table("demo_environments")
    op.drop_table("inference_engines")
    op.drop_table("model_catalog_entries")
    op.drop_table("cloud_deployment_profiles")
