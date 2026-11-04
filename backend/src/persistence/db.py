from __future__ import annotations

import logging
from collections.abc import Generator
from threading import Lock

from fastapi import Request
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from src.config import Settings, get_settings

LOGGER = logging.getLogger(__name__)


class DatabaseReadiness:
    """Keep probes independent of the application pool, with at most one DB call in flight."""

    def __init__(self, settings: Settings) -> None:
        self._lock = Lock()
        self._engine = create_engine(
            settings.database_url,
            poolclass=NullPool,
            connect_args={
                "connect_timeout": 2,
                "options": "-c statement_timeout=1000 -c lock_timeout=1000",
            },
        )

    def check(self) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        try:
            with self._engine.connect() as connection:
                return connection.execute(text("SELECT 1")).scalar_one() == 1
        except SQLAlchemyError as error:
            LOGGER.warning("Database readiness failed (%s).", type(error).__name__)
            return False
        finally:
            self._lock.release()

    def close(self) -> None:
        self._engine.dispose()


class Base(DeclarativeBase):
    """Declarative base for all persistence models."""


def create_engine_from_settings(settings: Settings | None = None):
    resolved_settings = settings or get_settings()
    return create_engine(
        resolved_settings.database_url,
        echo=resolved_settings.database_echo,
        future=True,
        pool_pre_ping=True,
    )


def create_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    engine = create_engine_from_settings(settings)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db_session(request: Request) -> Generator[Session, None, None]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session
