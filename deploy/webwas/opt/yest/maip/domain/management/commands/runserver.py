"""개발 서버 기본 포트를 8123 으로 둔다. `python manage.py runserver` 만 쳐도 8123 으로 뜬다.

정적 파일 제공(django.contrib.staticfiles 의 runserver)은 그대로 이어받는다. INSTALLED_APPS 에서 domain 이
staticfiles 보다 앞이라 이 명령이 우선한다. 다른 PC 에서 열려면 `runserver 0.0.0.0:8123`.

정적 파일에는 `Cache-Control: no-cache` 를 붙인다. 개발에서는 파일 이름에 해시가 없어(collectstatic 전) 캐시 지시가
없으면 브라우저가 Last-Modified 만 보고 한동안 옛 CSS·JS 를 그대로 쓴다. no-cache 면 매번 확인하고 안 바뀌었으면 304 다.
"""
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.contrib.staticfiles.management.commands.runserver import Command as StaticRunserver


class NoCacheStaticFilesHandler(StaticFilesHandler):
    def serve(self, request):
        response = super().serve(request)
        response['Cache-Control'] = 'no-cache'
        return response


class Command(StaticRunserver):
    default_port = '8123'

    def get_handler(self, *args, **options):
        handler = super().get_handler(*args, **options)
        if isinstance(handler, StaticFilesHandler):
            return NoCacheStaticFilesHandler(handler.application)
        return handler
