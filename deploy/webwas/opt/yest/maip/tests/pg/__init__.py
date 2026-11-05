"""PostgreSQL 에서만 도는 통합 테스트. `configurations.pg_test_settings` 로 돌린다.

단위 테스트(SQLite)에서는 통째로 건너뛴다.
"""
import unittest

from django.db import connection

if connection.vendor != 'postgresql':
    raise unittest.SkipTest('PostgreSQL 통합 테스트 — --settings=configurations.pg_test_settings 로 돌린다')
