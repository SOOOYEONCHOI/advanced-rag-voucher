"""PostgreSQL 연결·트랜잭션과 기존 저장소 코드와의 호환 계층 (2026.10.16 Phase 1.5).

설계: docs/design/phase-1_5_PostgreSQL_전환_설계.md 3장 (DB-01, N-9, N-10)

- SQLAlchemy 엔진(``postgresql+psycopg``)의 커넥션 풀을 쓴다. 스키마는 Alembic(``migrations/``)으로만 바꾼다.
- 기존 저장소가 쓰던 ``DatabaseManager`` 인터페이스(get_connection / execute_query / execute_update /
  execute_many)를 그대로 제공한다.
- 호환 변환
  * SQL의 ``?`` 자리표시자 → ``%s`` (``to_driver_sql``)
  * 결과 값: timestamptz → KST ISO 문자열(``YYYY-MM-DDTHH:MM:SS+09:00``), json/jsonb → JSON 문자열, boolean → 1/0
  * 결과 행: ``Row`` (이름·순번 접근, ``dict(row)``)
- 같은 실행 흐름에서 ``get_connection()``을 중첩 호출하면 같은 트랜잭션을 공유하고, 가장 바깥 블록이 끝날 때 커밋한다.
"""
# 2026.10.16 Phase 1.5 - SQLite DatabaseManager(스레드별 연결 + 기동 시 런타임 마이그레이션)를 대체

from __future__ import annotations

import contextvars
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional, Sequence
from zoneinfo import ZoneInfo

import psycopg
from psycopg.adapt import Loader
from psycopg.types.datetime import TimestamptzLoader
from sqlalchemy import create_engine, event
from sqlalchemy.exc import DBAPIError
from sqlalchemy.engine import URL, Engine, make_url

from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
MIGRATIONS_DIR = BACKEND_ROOT / "migrations"


# ── 설정 → 접속 URL ────────────────────────────────────────────────────────────

def build_database_url(settings=None) -> URL:
    """``DATABASE_URL``이 있으면 그 값, 없으면 ``POSTGRES_*``로 접속 URL을 만든다."""
    if settings is None:
        from app.core.db_config import get_database_settings

        settings = get_database_settings()
    if settings.database_url:
        url = make_url(settings.database_url)
        if url.drivername in ("postgresql", "postgres"):
            url = url.set(drivername="postgresql+psycopg")
        return url
    return URL.create(
        "postgresql+psycopg",
        username=settings.postgres_user,
        password=settings.postgres_password or None,
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
    )


# ── 자리표시자 변환 ─────────────────────────────────────────────────────────────

def to_driver_sql(sql: str) -> str:
    """SQLite식 ``?``를 psycopg ``%s``로 바꾸고 ``%``를 ``%%``로 이스케이프한다.

    작은따옴표 문자열·큰따옴표 식별자·주석 안의 ``?``는 그대로 둔다(``%``는 모든 곳에서 이스케이프 —
    psycopg는 파라미터가 있으면 질의 전체에서 ``%``를 해석한다). PostgreSQL JSON 연산자 ``?``·``?|``·``?&``는
    이 계층을 거치면 자리표시자로 바뀌므로 쓰지 않는다(필요하면 ``jsonb_exists`` 함수 사용).
    """
    out: list[str] = []
    i, n = 0, len(sql)
    state = None  # None | "'" | '"' | "--" | "/*"
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if ch == "%":
            out.append("%%")
            i += 1
            continue
        if state is None:
            if ch == "?":
                out.append("%s")
            elif ch in ("'", '"'):
                state = ch
                out.append(ch)
            elif ch == "-" and nxt == "-":
                state = "--"
                out.append("--")
                i += 1
            elif ch == "/" and nxt == "*":
                state = "/*"
                out.append("/*")
                i += 1
            else:
                out.append(ch)
        elif state in ("'", '"'):
            out.append(ch)
            if ch == state:
                if nxt == state:  # '' 또는 "" 이스케이프
                    out.append(nxt)
                    i += 1
                else:
                    state = None
        elif state == "--":
            out.append(ch)
            if ch == "\n":
                state = None
        else:  # "/*"
            out.append(ch)
            if ch == "*" and nxt == "/":
                out.append("/")
                i += 1
                state = None
        i += 1
    return "".join(out)


# ── 값 변환 (연결마다 등록) ─────────────────────────────────────────────────────

class _KstIsoTimestamptzLoader(TimestamptzLoader):
    """timestamptz → ``YYYY-MM-DDTHH:MM:SS+09:00`` (기존 SQLite 저장 형식)."""

    def load(self, data):
        value: datetime = super().load(data)
        return value.astimezone(KST).isoformat(timespec="seconds")


class _JsonTextLoader(Loader):
    """json/jsonb → JSON 문자열 (저장소가 ``json.loads``로 직접 파싱한다)."""

    def load(self, data):
        return bytes(data).decode("utf-8")


class _BoolIntLoader(Loader):
    """boolean → 1/0 (기존 0/1 정수 컬럼과 같은 값)."""

    def load(self, data):
        return 1 if bytes(data) == b"t" else 0


def _register_loaders(dbapi_connection) -> None:
    adapters = dbapi_connection.adapters
    adapters.register_loader("timestamptz", _KstIsoTimestamptzLoader)
    adapters.register_loader("json", _JsonTextLoader)
    adapters.register_loader("jsonb", _JsonTextLoader)
    adapters.register_loader("bool", _BoolIntLoader)


# ── 결과 행 ─────────────────────────────────────────────────────────────────────

class Row(Sequence):
    """``sqlite3.Row``와 같은 사용 방식(``row["col"]``, ``row[0]``, ``dict(row)``, ``row.keys()``)."""

    __slots__ = ("_keys", "_values", "_index")

    def __init__(self, keys: Sequence[str], values: Sequence[Any]):
        self._keys = tuple(keys)
        self._values = tuple(int(v) if isinstance(v, bool) else v for v in values)
        self._index = {key: i for i, key in enumerate(self._keys)}

    def keys(self) -> list[str]:
        return list(self._keys)

    def __getitem__(self, item):
        if isinstance(item, str):
            return self._values[self._index[item]]
        return self._values[item]

    def __len__(self) -> int:
        return len(self._values)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __repr__(self) -> str:
        return f"Row({dict(zip(self._keys, self._values))!r})"


def _wrap_error(statement: str, params: Any, exc: psycopg.Error) -> DBAPIError:
    """드라이버 예외를 SQLAlchemy 예외(IntegrityError·OperationalError 등, 원본은 ``.orig``)로 감싼다.
    엔진 경로(Alembic·이관 스크립트)와 호환 계층 경로가 같은 예외 타입을 내도록 한다."""
    return DBAPIError.instance(statement, params, exc, psycopg.Error)


class _Cursor:
    """psycopg 커서 래퍼: ``?`` 변환, ``Row`` 반환, ``lastrowid`` 거부."""

    def __init__(self, cursor) -> None:
        self._cursor = cursor

    def execute(self, sql: str, params: Optional[Iterable[Any]] = None) -> "_Cursor":
        # 파라미터가 없어도 빈 튜플을 넘겨 '%%' 이스케이프가 항상 같은 규칙으로 처리되게 한다
        statement = to_driver_sql(sql)
        values = tuple(params) if params is not None else ()
        try:
            self._cursor.execute(statement, values)
        except psycopg.Error as exc:
            raise _wrap_error(statement, values, exc) from exc
        return self

    def executemany(self, sql: str, params_list: Iterable[Iterable[Any]]) -> "_Cursor":
        statement = to_driver_sql(sql)
        values = [tuple(p) for p in params_list]
        try:
            self._cursor.executemany(statement, values)
        except psycopg.Error as exc:
            raise _wrap_error(statement, values, exc) from exc
        return self

    def _columns(self) -> list[str]:
        return [column.name for column in self._cursor.description or ()]

    def fetchone(self) -> Optional[Row]:
        row = self._cursor.fetchone()
        return None if row is None else Row(self._columns(), row)

    def fetchall(self) -> list[Row]:
        columns = self._columns()
        return [Row(columns, row) for row in self._cursor.fetchall()]

    def __iter__(self) -> Iterator[Row]:
        return iter(self.fetchall())

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def description(self):
        return self._cursor.description

    @property
    def lastrowid(self):
        raise NotImplementedError("PostgreSQL에서는 lastrowid 대신 INSERT … RETURNING을 사용한다.")

    def close(self) -> None:
        self._cursor.close()


class _Connection:
    """트랜잭션 하나에 묶인 연결 래퍼. 커밋·롤백은 ``DatabaseManager.get_connection``이 맡는다."""

    def __init__(self, manager: "DatabaseManager", raw) -> None:
        self.manager = manager
        self.thread_id = threading.get_ident()
        self._raw = raw

    def cursor(self) -> _Cursor:
        return _Cursor(self._raw.cursor())

    def execute(self, sql: str, params: Optional[Iterable[Any]] = None) -> _Cursor:
        return self.cursor().execute(sql, params)

    def executemany(self, sql: str, params_list: Iterable[Iterable[Any]]) -> _Cursor:
        return self.cursor().executemany(sql, params_list)


_current_connection: contextvars.ContextVar[Optional[_Connection]] = contextvars.ContextVar(
    "adrag_db_connection", default=None
)


# ── DatabaseManager ────────────────────────────────────────────────────────────

class DatabaseManager:
    """PostgreSQL 커넥션 풀과 트랜잭션을 관리하는 싱글톤."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        from app.core.db_config import get_database_settings

        settings = get_database_settings()
        self.url = build_database_url(settings)
        self.engine = _create_engine(self.url, settings)
        self._initialized = True
        logger.info(
            "Database manager initialized: %s",
            self.url.render_as_string(hide_password=True),
        )

    @contextmanager
    def get_connection(self) -> Iterator[_Connection]:
        current = _current_connection.get()
        if current is not None and current.manager is self and current.thread_id == threading.get_ident():
            yield current
            return
        raw = self.engine.raw_connection()
        connection = _Connection(self, raw)
        token = _current_connection.set(connection)
        try:
            yield connection
            raw.commit()
        except BaseException as exc:
            raw.rollback()
            if not isinstance(exc, (GeneratorExit, KeyboardInterrupt)):
                logger.error(f"Database transaction failed: {exc}")
            raise
        finally:
            _current_connection.reset(token)
            raw.close()  # 풀로 반환

    def execute_query(self, query: str, params: Iterable[Any] = ()) -> list[Row]:
        with self.get_connection() as conn:
            return conn.execute(query, params).fetchall()

    def execute_update(self, query: str, params: Iterable[Any] = ()) -> int:
        with self.get_connection() as conn:
            return conn.execute(query, params).rowcount

    def execute_many(self, query: str, params_list: list) -> int:
        with self.get_connection() as conn:
            return conn.executemany(query, params_list).rowcount

    def close_all_connections(self) -> None:
        self.engine.dispose()
        logger.info("Database connections closed")


def _create_engine(url: URL, settings) -> Engine:
    options = ["-c timezone=Asia/Seoul"]
    if settings.db_statement_timeout_ms > 0:
        options.append(f"-c statement_timeout={settings.db_statement_timeout_ms}")
    engine = create_engine(
        url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        connect_args={"application_name": settings.db_application_name, "options": " ".join(options)},
    )
    event.listen(engine, "connect", lambda dbapi_connection, _record: _register_loaders(dbapi_connection))
    return engine


_db_manager: Optional[DatabaseManager] = None


def get_database_manager() -> DatabaseManager:
    """애플리케이션에서 공유하는 DatabaseManager 싱글톤."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


def close_database_manager() -> None:
    """엔진을 닫고 싱글톤을 해제한다(앱 종료·테스트 종료)."""
    global _db_manager
    manager = DatabaseManager._instance
    if manager is not None and getattr(manager, "_initialized", False):
        manager.close_all_connections()
    _db_manager = None
    DatabaseManager._instance = None


# ── 스키마 버전 (Alembic) ──────────────────────────────────────────────────────

def alembic_config():
    from alembic.config import Config

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def alembic_head() -> str:
    from alembic.script import ScriptDirectory

    heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Alembic head가 1개가 아닙니다: {heads}")
    return heads[0]


def ensure_schema_ready() -> str:
    """DB 스키마가 코드의 Alembic head인지 확인한다. 아니면 RuntimeError(운영은 자동 upgrade 하지 않는다, N-10)."""
    head = alembic_head()
    try:
        rows = get_database_manager().execute_query("SELECT version_num FROM alembic_version")
    except Exception as exc:
        raise RuntimeError(f"DB 스키마 버전을 읽을 수 없습니다(alembic upgrade head 필요): {exc}") from exc
    current = rows[0][0] if rows else None
    if current != head:
        raise RuntimeError(f"DB 스키마 버전 {current!r} ≠ 코드 {head!r} — alembic upgrade head 필요")
    return head


def initialize_database() -> DatabaseManager:
    """개발 환경 초기화: ``alembic upgrade head`` 후 스키마 버전을 확인한다(init_database.py)."""
    from alembic import command

    manager = get_database_manager()
    config = alembic_config()
    # ConfigParser 보간 문자(%) 이스케이프
    config.set_main_option("sqlalchemy.url", manager.url.render_as_string(hide_password=False).replace("%", "%%"))
    command.upgrade(config, "head")
    ensure_schema_ready()
    logger.info("Database initialized at revision %s", alembic_head())
    return manager
