"""정적 파일은 해시 이름·gzip 으로 나가고, 템플릿은 /static/ 을 직접 쓰지 않는다."""
import pathlib
import re

from django.test import SimpleTestCase

from configurations import settings as base

TEMPLATES = pathlib.Path(base.BASE_DIR) / 'app' / 'templates'


class StaticStorageTest(SimpleTestCase):
    def test_운영_저장소는_해시_이름과_압축본을_만든다(self):
        self.assertEqual(base.STORAGES['staticfiles']['BACKEND'], 'configurations.storage.StaticStorage')

    def test_템플릿은_static_경로를_직접_쓰지_않는다(self):
        # 직접 쓴 경로는 해시가 붙지 않아 긴 캐시를 받지 못하고, 고칠 때마다 ?v= 를 손으로 올려야 했다.
        offenders = []
        for path in TEMPLATES.rglob('*.html'):
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if re.search(r'''(src|href)=["']/static/''', line):
                    offenders.append(f'{path.relative_to(TEMPLATES)}:{number}')
        self.assertEqual(offenders, [])
