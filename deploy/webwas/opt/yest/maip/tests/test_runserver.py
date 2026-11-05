"""개발 서버 기본 포트는 8123 이다 — `python manage.py runserver` 만 쳐도 문서·e2e 와 같은 포트로 뜬다."""
from django.core.management import get_commands, load_command_class
from django.test import SimpleTestCase


class RunserverDefaultPortTest(SimpleTestCase):
    def test_runserver_는_8123_이_기본이고_정적_파일도_낸다(self):
        app = get_commands()['runserver']
        command = load_command_class(app, 'runserver')
        self.assertEqual(command.default_port, '8123')
        from django.contrib.staticfiles.management.commands.runserver import Command as StaticRunserver
        self.assertIsInstance(command, StaticRunserver)


class RunserverStaticCacheTest(SimpleTestCase):
    """개발 서버의 정적 파일은 매번 다시 확인하게 한다(no-cache, 안 바뀌었으면 304).

    캐시 지시가 없으면 브라우저가 Last-Modified 만 보고 한동안 옛 CSS 를 그대로 쓴다 — 라벨링의 대표 이미지
    겹침이 옛 main.css 로 이미지 아래에 따로 붙었다(2026-10-12). 운영은 해시 이름이라 해당이 없다.
    """

    def test_정적_파일_응답은_no_cache_다(self):
        from django.test import RequestFactory, override_settings
        command = load_command_class(get_commands()['runserver'], 'runserver')
        with override_settings(DEBUG=True):
            handler = command.get_handler(use_static_handler=True, insecure_serving=False)
            response = handler.serve(RequestFactory().get('/static/data/main.css'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-cache')
        response.close()
