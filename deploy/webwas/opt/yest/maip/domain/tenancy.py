"""테넌트 컨텍스트와 PostgreSQL RLS 연결.

**단일 조직 고정**이다(DEC-004 B).

- `TenantMiddleware` 는 이식하지 않는다. 조직 선택 화면이 없고 조직이 하나뿐이라
  요청마다 세션에서 조직을 골라 검증할 이유가 없다.
- 대신 `current_tenant()` 가 항상 같은 행을 돌려준다.
- **RLS 정책은 그대로 둔다.** 조직이 하나여도 `SET LOCAL app.tenant_id` 가 빠지면
  RLS가 전부 막아 버리므로, 데이터 접근은 반드시 `tenant_atomic()` 안에서 한다.
"""
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.db import connection, transaction

# 조직이 하나뿐이므로 UUID를 고정한다. 마이그레이션 seed 와 같은 값이어야 한다.
# UUID 로 둔다. get_or_create 가 행을 만들 때 넘긴 값을 그대로 id 로 남기므로,
# 문자열이면 그 프로세스의 tenant.id 가 str 이 되어 item.tenant_id(UUID) 와 같지 않다.
FIXED_TENANT_ID = uuid.UUID('00000000-0000-4000-8000-000000000001')
# 조직 이름. 화면에는 보이지 않는다(사용자 결정, 2026-10-06). 바꾸면 기존 행은
# `seed_initial` 이 맞춘다 — get_or_create 의 defaults 는 생성 때만 쓰인다.
FIXED_TENANT_NAME = 'YEST'

_current_tenant = ContextVar('map_current_tenant', default=None)
_cached_tenant = None


def current_tenant():
    """고정 조직을 돌려준다. 한 번 읽은 뒤에는 캐시한다."""
    global _cached_tenant
    scoped = _current_tenant.get()
    if scoped is not None:
        return scoped
    if _cached_tenant is None:
        from domain.models.data import Tenant

        _cached_tenant, _ = Tenant.objects.get_or_create(
            id=FIXED_TENANT_ID, defaults={'name': FIXED_TENANT_NAME})
    return _cached_tenant


def reset_tenant_cache():
    """테스트에서 DB가 바뀔 때 캐시를 비운다."""
    global _cached_tenant
    _cached_tenant = None


def set_database_tenant(tenant):
    if tenant and getattr(settings, 'TENANT_RLS_ENABLED', False):
        with connection.cursor() as cursor:
            cursor.execute('SET LOCAL app.tenant_id = %s', [str(tenant.id)])


@contextmanager
def tenant_atomic(tenant=None):
    """조직 컨텍스트를 세우고 트랜잭션을 연다."""
    tenant = tenant or current_tenant()
    previous = _current_tenant.get()
    token = _current_tenant.set(tenant)
    try:
        with transaction.atomic():
            set_database_tenant(tenant)
            try:
                yield tenant
            finally:
                # SET LOCAL 은 savepoint가 아니라 바깥 트랜잭션 끝까지 유지된다.
                # 중첩 호출이 있으면 savepoint를 닫기 전에 호출한 쪽 값으로 되돌린다.
                set_database_tenant(previous)
    finally:
        _current_tenant.reset(token)
