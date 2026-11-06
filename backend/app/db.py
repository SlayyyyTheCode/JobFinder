from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from .config import get_settings

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().db_url, connect_args={"check_same_thread": False})

        @event.listens_for(_engine, "connect")
        def _pragma(conn, _):
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()
    return _engine


def set_engine(engine) -> None:
    """Test hook."""
    global _engine
    _engine = engine


def init_db() -> None:
    from . import models  # noqa: F401
    SQLModel.metadata.create_all(get_engine())


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as s:
        yield s


@contextmanager
def session_scope() -> Iterator[Session]:
    with Session(get_engine()) as s:
        yield s


def get_setting(s: Session, key: str, default: Any = None) -> Any:
    from .models import AppSetting
    row = s.get(AppSetting, key)
    return default if row is None else row.value


def put_setting(s: Session, key: str, value: Any) -> None:
    from .models import AppSetting
    row = s.get(AppSetting, key)
    if row is None:
        s.add(AppSetting(key=key, value=value))
    else:
        row.value = value
        s.add(row)
    s.commit()


__all__ = ["get_engine", "init_db", "get_session", "session_scope", "get_setting", "put_setting", "select"]
