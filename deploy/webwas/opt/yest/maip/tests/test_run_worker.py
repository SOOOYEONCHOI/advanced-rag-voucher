"""run_worker — 처리한 작업을 파일 로그에도 남긴다(systemd 밖에서도 처리 이력을 본다)."""
import io
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.test import TestCase


class RunWorkerLogTest(TestCase):
    def test_처리한_작업은_완료도_실패도_로그에_남는다(self):
        jobs = [SimpleNamespace(job_type='EXPORT', id=7, status='COMPLETED', error_message=''),
                SimpleNamespace(job_type='EXPORT', id=8, status='FAILED', error_message='zip 실패')]
        with mock.patch('domain.management.commands.run_worker.JobService.run_pending', return_value=jobs), \
                self.assertLogs('domain.management.commands.run_worker', 'INFO') as logs:
            call_command('run_worker', once=True, stdout=io.StringIO())
        text = '\n'.join(logs.output)
        self.assertIn('작업 완료: EXPORT #7', text)
        self.assertIn('작업 실패: EXPORT #8 — zip 실패', text)
