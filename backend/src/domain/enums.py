from enum import StrEnum


class ProviderType(StrEnum):
    AZURE = "azure"
    LOCAL = "local"


class ModelSizeClass(StrEnum):
    THREE_B = "3b"
    SEVEN_B = "7b"
    SEVENTY_B = "70b"


class ModelFamily(StrEnum):
    GEMMA = "gemma"
    LLAMA = "llama"
    CHINESE_ORIGIN = "chinese-origin"
    PHI = "phi"


class DemoEnvironmentState(StrEnum):
    NOT_PROVISIONED = "not_provisioned"
    PROVISIONING = "provisioning"
    READY = "ready"
    PROVISIONING_FAILED = "provisioning_failed"
    TEARING_DOWN = "tearing_down"
    TORN_DOWN = "torn_down"
    TEARDOWN_FAILED = "teardown_failed"


class DeploymentRevisionState(StrEnum):
    PENDING = "pending"
    DEPLOYING = "deploying"
    READY = "ready"
    DEPLOYMENT_FAILED = "deployment_failed"
    SUPERSEDED = "superseded"


class DuplicateCheckState(StrEnum):
    NOT_CHECKED = "not_checked"
    CLEAN = "clean"
    DUPLICATES_DETECTED = "duplicates_detected"


class DatasetProvenance(StrEnum):
    CURATED = "curated"
    AI_GENERATED = "ai-generated"


class ReviewStatus(StrEnum):
    REVIEWED = "reviewed"
    UNREVIEWED = "unreviewed"


class ExperimentRunType(StrEnum):
    QUALITY_GOLDEN = "quality-golden"
    QUALITY_BENCHMARK = "quality-benchmark"
    PERFORMANCE = "performance"
    INTERACTIVE_PROMPT = "interactive-prompt"


class ExperimentRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


class RetentionClass(StrEnum):
    PERSISTED = "persisted"
    SESSION_EPHEMERAL = "session-ephemeral"


class CompletenessIndicator(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE_MONITORING_DATA = "unavailable-monitoring-data"


class ComparisonStatus(StrEnum):
    COMPARABLE = "comparable"
    NOT_DIRECTLY_COMPARABLE = "not-directly-comparable"


class WorkflowType(StrEnum):
    """Orchestration Workflow types (data-model.md), one per Durable Functions
    orchestrator that the Azure `ProviderAdapter` can start (contracts/
    provider-interface.md Azure Implementation Notes)."""

    PROVISION = "provision"
    DEPLOY = "deploy"
    EVALUATE_GOLDEN = "evaluate-golden"
    EVALUATE_BENCHMARK = "evaluate-benchmark"
    PERFORMANCE_TEST = "performance-test"
    EXPORT = "export"
    TEARDOWN = "teardown"


class WorkflowStatus(StrEnum):
    """Orchestration Workflow status (data-model.md); `completed`/`failed`/
    `cancelled` are terminal states per FR-055."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
