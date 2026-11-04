from __future__ import annotations

from sqlalchemy.orm import Session

from src.domain.deployment_revision import DeploymentRevision


class DeploymentRevisionRepository:
    """Read-only lookups for `DeploymentRevision` rows.

    `DeploymentRevision` records are immutable once created (data-model.md
    Validation): a redeploy always creates a brand-new row, and
    `WorkflowReconciliationService._reconcile_deploy` marks the previously
    active revision `SUPERSEDED` rather than mutating it in place (FR-019,
    FR-020). This repository exists so read-only callers - such as the
    comparison builder, which needs a compared report's revision lifecycle
    state without duplicating that lookup - don't need to import the
    reconciliation module or hand-roll a `session.get` call.
    """

    def get(self, session: Session, deployment_revision_id: str) -> DeploymentRevision | None:
        return session.get(DeploymentRevision, deployment_revision_id)
