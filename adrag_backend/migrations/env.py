"""Alembic 실행 환경 (2026.10.16 Phase 1.5, 설계 7.1).

접속 URL 우선순위: alembic Config의 ``sqlalchemy.url``(테스트·init_database가 지정) >
``app.repositories.database.build_database_url()``(DATABASE_URL 또는 POSTGRES_*).
alembic.ini에는 URL·비밀값을 두지 않는다(DB-ENV-2).
"""
from __future__ import annotations

import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

config = context.config
target_metadata = None  # 명시적 DDL 리비전만 쓴다(autogenerate 미사용)


def _url():
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    from app.repositories.database import build_database_url

    return build_database_url()


def run_migrations_offline() -> None:
    context.configure(url=str(_url()), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
