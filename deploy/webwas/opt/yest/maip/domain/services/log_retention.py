"""DB 로그 보존. 워커가 하루 한 번 부른다(run_worker). 파일 로그는 configurations/log.py 가 따로 지운다.

시스템로그는 장애 분석용이라 90일, 로그인·메뉴 로그는 접속 감사용이라 365일(사용자 결정 2026-10-07).
만료된 로그인 세션(`django_session`)도 지운다 — Django 는 만료된 세션을 쓰지 않을 뿐 행을 지우지 않는다.
"""
from datetime import timedelta

from django.contrib.sessions.models import Session
from django.utils import timezone

from domain.models.system import LoginLog, MenuUseLog, SystemLog

RETENTION_DAYS = ((SystemLog, 90), (LoginLog, 365), (MenuUseLog, 365))


def purge(now=None):
    """보존 기간이 지난 행을 지우고 {테이블: 지운 수} 를 돌려준다."""
    now = now or timezone.now()
    deleted = {}
    for model, days in RETENTION_DAYS:
        count, _ = model.objects.filter(_created__lt=now - timedelta(days=days)).delete()
        deleted[model._meta.db_table] = count
    deleted[Session._meta.db_table], _ = Session.objects.filter(expire_date__lt=now).delete()
    return deleted
