"""기존 SQLite 메타 DB → PostgreSQL 이관 스크립트 (2026.09.29 Phase 1.5).

전제: 대상 PostgreSQL에 ``alembic upgrade 0001_baseline``이 적용되어 있고 업무 테이블이 비어 있다
      (tb_llm_models 기본 시드 4행은 이관 데이터로 교체).
      원본 SQLite는 현행 앱으로 한 번 기동돼 런타임 마이그레이션(옛 컬럼 정리)을 마친 상태여야 한다
      (대상에 없는 원본 컬럼이 있으면 중단). 절차: docs/design/phase-1_5_PostgreSQL_전환_설계.md 6.2
      2026.10.16 수정 - Phase 1.5 재구현 기준(0001_baseline = 현재 schema.sql 24테이블)으로 문구 정리.

동작
1. 테이블 24개를 FK 순서대로 한 트랜잭션에서 복사한다(실패 시 전체 롤백).
2. 컬럼 타입별 변환
   - timestamptz: ``...+09:00`` 등 오프셋이 있는 ISO 문자열은 그대로 해석,
     SQLite ``CURRENT_TIMESTAMP`` 형식(``YYYY-MM-DD HH:MM:SS``, 오프셋 없음)은 **UTC**로 해석
   - jsonb: JSON 파싱 검증 후 저장 / boolean: 0·1 → false·true
3. 테이블별 건수 비교, identity 시퀀스를 SQLite ``sqlite_sequence``(없으면 MAX(id)) 기준으로 재설정
   (삭제된 ID 재사용 방지)
4. 질의 로그 KST 일별 건수를 이관 전후로 비교(시각 변환 검증)

사용법 (adrag_backend 폴더에서)
    python scripts/migrate_sqlite_to_postgres.py                 # 실제 이관
    python scripts/migrate_sqlite_to_postgres.py --dry-run       # 전부 실행 후 롤백(검증만)
    python scripts/migrate_sqlite_to_postgres.py --sqlite <경로>   # 기본: SQLITE_DB_PATH 또는 ./instance/db/db_rag_metadata.db
결과 표는 표준출력(마크다운)으로, ``--report <파일>``을 주면 파일에도 저장한다.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.core.db_config import get_database_settings  # noqa: E402
from app.repositories.database import build_database_url  # noqa: E402

KST = timezone(timedelta(hours=9))
EXPECTED_REVISION = "0001_baseline"

# FK 부모 → 자식 순서
TABLE_ORDER = [
    "tb_departments", "tb_users", "tb_login_history", "tb_collections", "tb_documents",
    "tb_document_events", "tb_user_collection_permissions", "tb_user_security_policies",
    "tb_query_sessions", "tb_query_logs", "tb_query_citations", "tb_llm_models",
    "tb_user_llm_settings", "tb_app_settings", "tb_ingest_jobs", "tb_spreadsheet_resources",
    "tb_spreadsheet_resource_analyses", "tb_eval_datasets", "tb_eval_qa_items", "tb_eval_goldsets",
    "tb_eval_runs", "tb_eval_item_results", "tb_eval_run_metrics", "tb_eval_settings",
]
SEEDED_TABLES = {"tb_llm_models"}


class MigrationError(RuntimeError):
    pass


def parse_timestamp(value, table: str, column: str):
    if value is None or value == "":
        return None
    s = str(value).strip()
    try:
        if "T" not in s and len(s) == 19:
            # SQLite CURRENT_TIMESTAMP: UTC, 오프셋 없음
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MigrationError(f"{table}.{column}: 해석할 수 없는 시각 형식 {s!r}") from exc
    if dt.tzinfo is None:
        raise MigrationError(f"{table}.{column}: 오프셋 없는 ISO 시각 {s!r} (변환 규칙 미정)")
    return dt


def convert(value, pg_type: str, table: str, column: str):
    if value is None:
        return None
    if pg_type == "timestamp with time zone":
        return parse_timestamp(value, table, column)
    if pg_type == "jsonb":
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8")
        try:
            json.loads(value)
        except (TypeError, ValueError) as exc:
            raise MigrationError(f"{table}.{column}: JSON 파싱 실패") from exc
        return value
    if pg_type == "boolean":
        if value not in (0, 1, True, False):
            raise MigrationError(f"{table}.{column}: boolean으로 변환할 수 없는 값 {value!r}")
        return bool(value)
    return value


def pg_columns(conn, table: str) -> dict[str, str]:
    rows = conn.execute(
        text("SELECT column_name, data_type FROM information_schema.columns "
             "WHERE table_schema = 'public' AND table_name = :t ORDER BY ordinal_position"),
        {"t": table},
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def identity_column(conn, table: str) -> str | None:
    row = conn.execute(
        text("SELECT column_name FROM information_schema.columns "
             "WHERE table_schema = 'public' AND table_name = :t AND is_identity = 'YES'"),
        {"t": table},
    ).fetchone()
    return row[0] if row else None


def kst_daily_counts_sqlite(src) -> Counter:
    counter: Counter = Counter()
    for (created_at,) in src.execute("SELECT created_at FROM tb_query_logs"):
        counter[parse_timestamp(created_at, "tb_query_logs", "created_at").astimezone(KST).date().isoformat()] += 1
    return counter


def kst_daily_counts_pg(conn) -> Counter:
    rows = conn.execute(text(
        "SELECT to_char(created_at AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD') AS d, COUNT(*) "
        "FROM tb_query_logs GROUP BY 1"
    )).fetchall()
    return Counter({r[0]: r[1] for r in rows})


def migrate(sqlite_path: Path, target_url, dry_run: bool) -> list[str]:
    if not sqlite_path.is_file():
        raise MigrationError(f"SQLite 파일이 없습니다: {sqlite_path}")
    src = sqlite3.connect(f"file:{sqlite_path.as_posix()}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    src_tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = [t for t in TABLE_ORDER if t not in src_tables]
    if missing:
        raise MigrationError(f"원본에 없는 테이블: {missing}")
    extra = sorted(t for t in src_tables if t.startswith("tb_") and t not in TABLE_ORDER)
    if extra:
        raise MigrationError(f"이관 대상 목록에 없는 원본 테이블: {extra}")
    seq = {r[0]: r[1] for r in src.execute("SELECT name, seq FROM sqlite_sequence")} \
        if "sqlite_sequence" in src_tables else {}
    fk_violations = src.execute("PRAGMA foreign_key_check").fetchall()
    if fk_violations:
        raise MigrationError(f"원본 FK 위반 {len(fk_violations)}건 — 이관 전 정리 필요")

    engine = create_engine(target_url)
    report = ["| 테이블 | SQLite | PostgreSQL | 일치 | identity 다음 값 |", "|---|---:|---:|:---:|---:|"]
    conn = engine.connect()
    trans = conn.begin()
    try:
        revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        if revision != EXPECTED_REVISION:
            raise MigrationError(f"대상 스키마 버전 {revision!r} ≠ {EXPECTED_REVISION} (alembic upgrade 0001_baseline 필요)")
        for table in TABLE_ORDER:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            if count and table not in SEEDED_TABLES:
                raise MigrationError(f"대상 테이블이 비어 있지 않습니다: {table} ({count}행)")

        for table in TABLE_ORDER:
            columns = pg_columns(conn, table)
            src_cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})")]
            unknown = [c for c in src_cols if c not in columns]
            if unknown:
                raise MigrationError(f"{table}: 대상 스키마에 없는 원본 컬럼 {unknown}")
            if table in SEEDED_TABLES:
                conn.execute(text(f"DELETE FROM {table}"))
            rows = src.execute(f"SELECT {', '.join(src_cols)} FROM {table}").fetchall()
            payload = [
                tuple(convert(row[c], columns[c], table, c) for c in src_cols)
                for row in rows
            ]
            if payload:
                placeholders = ", ".join(["%s"] * len(src_cols))
                conn.exec_driver_sql(
                    f"INSERT INTO {table} ({', '.join(src_cols)}) VALUES ({placeholders})", payload
                )
            pg_count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            if pg_count != len(rows):
                raise MigrationError(f"{table}: 건수 불일치 SQLite {len(rows)} / PostgreSQL {pg_count}")

            next_value = "-"
            ident = identity_column(conn, table)
            if ident:
                max_id = conn.execute(text(f"SELECT COALESCE(MAX({ident}), 0) FROM {table}")).scalar()
                last = max(int(seq.get(table, 0) or 0), int(max_id))
                if last > 0:
                    conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}', '{ident}'), :v, true)"), {"v": last})
                else:
                    conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}', '{ident}'), 1, false)"))
                next_value = str(last + 1)
            report.append(f"| {table} | {len(rows)} | {pg_count} | ✅ | {next_value} |")

        before, after = kst_daily_counts_sqlite(src), kst_daily_counts_pg(conn)
        if before != after:
            raise MigrationError(f"질의 로그 KST 일별 건수 불일치: {dict(before)} vs {dict(after)}")
        report.append("")
        report.append(f"질의 로그 KST 일별 건수 일치: {len(after)}일, 합계 {sum(after.values())}건")

        if dry_run:
            trans.rollback()
            report.append("dry-run: 모든 검증 통과 후 롤백함(데이터 미반영)")
        else:
            trans.commit()
            report.append("이관 커밋 완료")
    except Exception:
        trans.rollback()
        raise
    finally:
        conn.close()
        engine.dispose()
        src.close()
    return report


def main() -> int:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sqlite", default=os.environ.get("SQLITE_DB_PATH") or "./instance/db/db_rag_metadata.db")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report")
    args = parser.parse_args()
    try:
        report = migrate(Path(args.sqlite), build_database_url(get_database_settings()), args.dry_run)
    except MigrationError as exc:
        print(f"[이관 실패 — 전체 롤백] {exc}", file=sys.stderr)
        return 1
    output = "\n".join(report)
    print(output)
    if args.report:
        Path(args.report).write_text(output + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
