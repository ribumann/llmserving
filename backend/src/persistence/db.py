from __future__ import annotations

from collections.abc import Generator

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.config import Settings, get_settings


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
