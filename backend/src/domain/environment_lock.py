from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.environment import DemoEnvironment


class EnvironmentLockError(Exception):
    """Base error for environment lock operations."""


class EnvironmentNotFoundError(EnvironmentLockError):
    """Raised when the target environment does not exist."""


class EnvironmentLockedError(EnvironmentLockError):
    def __init__(self, environment_id: str, active_operation_id: str) -> None:
        super().__init__(
            "Environment "
            f"'{environment_id}' is already locked by operation '{active_operation_id}'."
        )
        self.environment_id = environment_id
        self.active_operation_id = active_operation_id


@dataclass(slots=True, frozen=True)
class EnvironmentLockState:
    environment_id: str
    operation_id: str | None
    acquired: bool


class EnvironmentLockService:
    """Acquire and release the DemoEnvironment.activeOperationId single-writer lock."""

    def acquire(
        self, session: Session, *, environment_id: str, operation_id: str
    ) -> EnvironmentLockState:
        statement = (
            select(DemoEnvironment)
            .where(DemoEnvironment.environmentId == environment_id)
            .with_for_update()
        )
        environment = session.execute(statement).scalar_one_or_none()
        if environment is None:
            raise EnvironmentNotFoundError(environment_id)

        # FOR UPDATE locks the row but does not refresh an existing identity-map entry.
        session.refresh(environment, attribute_names=["activeOperationId"])
        if environment.activeOperationId and environment.activeOperationId != operation_id:
            raise EnvironmentLockedError(environment_id, environment.activeOperationId)

        environment.activeOperationId = operation_id
        session.flush()
        return EnvironmentLockState(
            environment_id=environment_id, operation_id=operation_id, acquired=True
        )

    def release(
        self,
        session: Session,
        *,
        environment_id: str,
        operation_id: str,
        force: bool = False,
    ) -> EnvironmentLockState:
        statement = (
            select(DemoEnvironment)
            .where(DemoEnvironment.environmentId == environment_id)
            .with_for_update()
        )
        environment = session.execute(statement).scalar_one_or_none()
        if environment is None:
            raise EnvironmentNotFoundError(environment_id)

        session.refresh(environment, attribute_names=["activeOperationId"])
        if environment.activeOperationId == operation_id or force:
            environment.activeOperationId = None
            session.flush()
            return EnvironmentLockState(
                environment_id=environment_id, operation_id=None, acquired=False
            )

        raise EnvironmentLockedError(environment_id, environment.activeOperationId or "")

    def current(self, session: Session, *, environment_id: str) -> EnvironmentLockState:
        environment = session.get(DemoEnvironment, environment_id)
        if environment is None:
            raise EnvironmentNotFoundError(environment_id)
        return EnvironmentLockState(
            environment_id=environment_id,
            operation_id=environment.activeOperationId,
            acquired=environment.activeOperationId is not None,
        )
