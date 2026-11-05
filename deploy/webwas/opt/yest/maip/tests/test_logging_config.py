"""시스템 로그는 LOG_DIR 에 날짜별 파일(app-YYYY-MM-DD.log)로 쌓인다(사용자 요구, 2026-10-06)."""
import datetime
import logging
import tempfile
import time
from pathlib import Path

from django.test import SimpleTestCase, TestCase

from configurations.log import DailyFileHandler
from domain.models.system import SystemLog
from domain.services.logging import LogWriter


def record(message, day):
    """`day` 정오에 찍힌 것처럼 만든 로그 기록."""
    rec = logging.LogRecord('t', logging.INFO, __file__, 1, message, None, None)
    rec.created = time.mktime(datetime.datetime.combine(day, datetime.time(12)).timetuple())
    return rec


class DailyFileHandlerTest(SimpleTestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.handler = DailyFileHandler(self.dir, retention_days=30)
        self.handler.setFormatter(logging.Formatter('%(message)s'))
        self.addCleanup(self.handler.close)

    def files(self):
        return sorted(p.name for p in self.dir.iterdir())

    def test_그날_파일에_쓰고_날짜가_바뀌면_새_파일로_넘어간다(self):
        self.handler.handle(record('첫째 날', datetime.date(2026, 10, 6)))
        self.handler.handle(record('둘째 날', datetime.date(2026, 10, 7)))

        self.assertEqual(self.files(), ['app-2026-10-06.log', 'app-2026-10-07.log'])
        self.assertEqual((self.dir / 'app-2026-10-06.log').read_text(encoding='utf-8'), '첫째 날\n')

    def test_보존_기간이_지난_로그만_지운다(self):
        (self.dir / 'app-2026-09-05.log').write_text('31일 전')
        (self.dir / 'app-2026-09-06.log').write_text('30일 전')
        (self.dir / 'notes.txt').write_text('로그가 아니다')

        self.handler.handle(record('오늘', datetime.date(2026, 10, 6)))

        self.assertEqual(self.files(), ['app-2026-09-06.log', 'app-2026-10-06.log', 'notes.txt'])

    def test_보존_기간이_0이면_지우지_않는다(self):
        handler = DailyFileHandler(self.dir, retention_days=0)
        self.addCleanup(handler.close)
        (self.dir / 'app-2020-01-01.log').write_text('오래된 로그')

        handler.handle(record('오늘', datetime.date(2026, 10, 6)))

        self.assertIn('app-2020-01-01.log', self.files())

    def test_폴더가_없으면_만든다(self):
        handler = DailyFileHandler(self.dir / 'nested' / 'logs')
        self.addCleanup(handler.close)

        handler.handle(record('오늘', datetime.date(2026, 10, 6)))

        self.assertTrue((self.dir / 'nested' / 'logs' / 'app-2026-10-06.log').exists())


class LogSettingsTest(SimpleTestCase):
    """운영 설정(configurations.settings)이 날짜별 파일 핸들러를 LOG_DIR 에 건다."""

    def _settings(self, **environ):
        import importlib
        import os
        from unittest.mock import patch

        import configurations.settings as module
        self.addCleanup(importlib.reload, module)
        with patch.dict(os.environ, environ):
            return importlib.reload(module)

    def test_LOG_DIR_을_비우면_STORAGE_ROOT_아래_logs_다(self):
        s = self._settings(LOG_DIR='')
        self.assertEqual(Path(s.LOG_DIR), Path(s.STORAGE_ROOT) / 'logs')

    def test_파일_핸들러는_LOG_DIR_에_보존_기간대로_쓴다(self):
        s = self._settings(LOG_DIR='/tmp/mfg-log-test', LOG_RETENTION_DAYS='7')
        handler = s.LOGGING['handlers']['file']
        self.assertEqual(handler['()'], 'configurations.log.DailyFileHandler')
        self.assertEqual(handler['directory'], '/tmp/mfg-log-test')
        self.assertEqual(handler['retention_days'], 7)
        self.assertIn('file', s.LOGGING['root']['handlers'])


class DbLogMirrorTest(TestCase):
    """화면의 '시스템 로그'(DB)는 한 줄뿐이다. 파일에는 트레이스까지 남긴다."""

    def test_DB_시스템_로그는_파일_로그에도_트레이스와_함께_남는다(self):
        try:
            raise ValueError('boom')
        except ValueError as ex:
            with self.assertLogs('system', level='ERROR') as captured:
                LogWriter.add_dblog('error', 'unit : action-x', ex)

        self.assertIn('unit : action-x boom', captured.output[0])
        self.assertIn('Traceback', captured.output[0])
        self.assertTrue(SystemLog.objects.filter(Source='unit : action-x').exists())
