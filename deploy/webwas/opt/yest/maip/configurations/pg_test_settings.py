"""PostgreSQL 통합 테스트(RLS·raw SQL). DBA 가 만든 maip_test 를 --keepdb 로 다시 쓴다(결정 11).

    python manage.py test tests.pg --settings=configurations.pg_test_settings --keepdb

이 프로젝트 계정에는 DB 생성 권한이 없다 — DBA 가 공유 PostgreSQL 에 빈 maip_test(소유자 = DB_USER)를
먼저 만든다. 운영 DB 를 쓰지 않도록 이름을 강제한다(PG_TEST_DB_NAME 이 maip_test 가 아니면 멈춘다).
경로·캐시·정적 저장소는 test_settings 를 그대로 쓴다.
"""
from django.core.exceptions import ImproperlyConfigured

from configurations.env import env
from configurations.settings import DATABASES as _BASE_DATABASES
from configurations.test_settings import *  # noqa: F401,F403

PG_TEST_DB_NAME = env('PG_TEST_DB_NAME', 'maip_test')
if PG_TEST_DB_NAME != 'maip_test':
    raise ImproperlyConfigured('PG_TEST_DB_NAME 은 maip_test 여야 한다.')

DATABASES = {'default': {**_BASE_DATABASES['default'], 'CONN_MAX_AGE': 0,
                         'TEST': {'NAME': PG_TEST_DB_NAME}}}
TENANT_RLS_ENABLED = True
