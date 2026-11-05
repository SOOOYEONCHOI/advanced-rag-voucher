"""백그라운드 작업 워커.

스냅샷 Export 는 이미지 수천 건을 읽고 ZIP을 만든다. 웹 요청 안에서 하면
타임아웃이 나고 워커 하나가 그 시간 동안 묶인다. `BackgroundJob` 큐에 넣고
이 프로세스가 집어 간다.

    python manage.py run_worker                 # 계속 돈다
    python manage.py run_worker --once          # 대기 작업만 비우고 끝낸다

운영에서는 systemd service 로 `--interval 5` 정도로 띄운다.
여러 개 띄워도 `SELECT ... FOR UPDATE SKIP LOCKED` 로 같은 작업을 두 번 잡지 않는다.
"""
import logging
import signal
import time

from django.core.management.base import BaseCommand

from domain.services import log_retention
from domain.services.data.job import JobService

logger = logging.getLogger(__name__)


# DB 로그 보존 정리 간격. 워커가 2개면 둘 다 지우지만 같은 조건의 DELETE 라 결과가 같다.
PURGE_INTERVAL_SECONDS = 24 * 3600


class Command(BaseCommand):
    help = '백그라운드 작업(스냅샷 Export)을 처리한다.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='대기 작업만 처리하고 끝낸다.')
        parser.add_argument('--interval', type=float, default=5.0, help='폴링 간격(초).')
        parser.add_argument('--limit', type=int, default=20, help='한 번에 처리할 작업 수.')

    def handle(self, *args, **options):
        self._stop = False
        # SIGTERM(systemd stop)을 받으면 지금 작업을 끝내고 나간다.
        # 중간에 죽이면 RUNNING 으로 남은 작업이 다시 집히지 않는다.
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._request_stop)

        last_purge = None
        while not self._stop:
            processed = JobService.run_pending(limit=options['limit'])
            # 하루 한 번(첫 반복 포함) DB 로그를 보존 기간에 맞춰 지운다 — 실패해도 작업 처리는 계속한다.
            if last_purge is None or time.monotonic() - last_purge >= PURGE_INTERVAL_SECONDS:
                try:
                    logger.info('DB 로그 보존 정리: %s', log_retention.purge())
                except Exception:
                    logger.exception('DB 로그 보존 정리 실패')
                last_purge = time.monotonic()
            for job in processed:
                self.stdout.write('{} #{} → {}'.format(job.job_type, job.id, job.status))
                if job.status == 'FAILED':
                    logger.warning('작업 실패: %s #%s — %s',
                                   job.job_type, job.id, job.error_message)
                else:
                    logger.info('작업 완료: %s #%s', job.job_type, job.id)
            if options['once']:
                self.stdout.write(self.style.SUCCESS(f'{len(processed)}건 처리'))
                return
            if not processed:
                time.sleep(options['interval'])

        self.stdout.write(self.style.WARNING('종료 신호를 받아 멈춘다.'))

    def _request_stop(self, signum, frame):
        self._stop = True
