from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

_engine = None
_SessionFactory: sessionmaker[Session] | None = None


def init_engine(database_url: str) -> None:
    global _engine
    _engine = create_engine(database_url, pool_pre_ping=True, future=True)


def init_session_factory() -> None:
    global _SessionFactory
    if _engine is None:
        raise RuntimeError("DB engine is not initialized")
    _SessionFactory = sessionmaker(
        bind=_engine, expire_on_commit=False, autoflush=False, future=True
    )


@contextmanager
def db_session() -> Iterator[Session]:
    if _SessionFactory is None:
        raise RuntimeError("Session factory is not initialized")
    s = _SessionFactory()
    try:
        yield s
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_engine():
    if _engine is None:
        raise RuntimeError("DB engine is not initialized")
    return _engine
