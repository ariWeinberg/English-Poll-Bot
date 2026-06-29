from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Any, Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine, Result
from sqlalchemy.orm import declarative_base


Base = declarative_base()


class DriverResult:
    def __init__(self, result: Result[Any]) -> None:
        self._result = result

    def fetchone(self) -> dict[str, Any] | None:
        row = self._result.mappings().first()
        return dict(row) if row is not None else None

    def fetchall(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._result.mappings().all()]


class DbConnection:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    class _Cursor:
        def __init__(self, connection: Connection) -> None:
            self._connection = connection

        def __enter__(self) -> "DbConnection._Cursor":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def executemany(self, sql: str, param_sets: list[tuple[Any, ...]] | list[list[Any]]) -> None:
            for params in param_sets:
                self._connection.exec_driver_sql(sql, tuple(params))

    def execute(self, sql: str, params: Any | None = None) -> DriverResult:
        if params is None and ";" in sql.strip().rstrip(";"):
            result: Result[Any] | None = None
            for statement in [part.strip() for part in sql.split(";") if part.strip()]:
                result = self._connection.exec_driver_sql(statement)
            if result is None:
                result = self._connection.exec_driver_sql("SELECT 1 WHERE 0 = 1")
        elif params is None:
            result = self._connection.exec_driver_sql(sql)
        elif isinstance(params, list):
            result = self._connection.exec_driver_sql(sql, tuple(params))
        else:
            result = self._connection.exec_driver_sql(sql, params)
        return DriverResult(result)

    def cursor(self) -> "DbConnection._Cursor":
        return self._Cursor(self._connection)

    def close(self) -> None:
        self._connection.close()


@dataclass
class EngineRegistry:
    engines: dict[str, Engine]
    lock: Lock


_REGISTRY = EngineRegistry(engines={}, lock=Lock())


def normalize_database_url(database_url: str) -> str:
    stripped = database_url.strip()
    if stripped.startswith("postgresql://"):
        return "postgresql+psycopg://" + stripped[len("postgresql://") :]
    if stripped.startswith("postgres://"):
        return "postgresql+psycopg://" + stripped[len("postgres://") :]
    return stripped


def get_engine(database_url: str) -> Engine:
    normalized_url = normalize_database_url(database_url)
    with _REGISTRY.lock:
        engine = _REGISTRY.engines.get(normalized_url)
        if engine is None:
            engine = create_engine(normalized_url, future=True, pool_pre_ping=True)
            _REGISTRY.engines[normalized_url] = engine
        return engine


def connect(database_url: str) -> DbConnection:
    return DbConnection(get_engine(database_url).connect())


@contextmanager
def db_session(database_url: str) -> Iterator[DbConnection]:
    connection = get_engine(database_url).connect()
    transaction = connection.begin()
    wrapped = DbConnection(connection)
    try:
        yield wrapped
        transaction.commit()
    except Exception:
        transaction.rollback()
        raise
    finally:
        wrapped.close()
