"""PostgreSQL 전용 DDL을 실행하는 migration 헬퍼.

테스트는 SQLite로 돌기 때문에(`configurations.test_settings`) 다른 벤더에서는
조용히 건너뛴다. 해당 SQL에 의존하는 raw SQL 서비스는 PostgreSQL에서만 검증된다.
"""
from django.db import migrations


def _runner(sql):
    def run(apps, schema_editor):
        if schema_editor.connection.vendor == 'postgresql':
            schema_editor.execute(sql)
    return run


def run_sql(forward_sql, reverse_sql):
    return migrations.RunPython(_runner(forward_sql), _runner(reverse_sql))
