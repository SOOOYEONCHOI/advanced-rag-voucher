"""저장소 경로 가드."""
from pathlib import Path

from django.test import TestCase, override_settings

from domain import storage


class StorageResolveTest(TestCase):
    def test_STORAGE_ROOT_안의_경로는_허용된다(self):
        path = storage.resolve('upload', 'company', 'a.png')
        self.assertTrue(str(path).startswith(str(storage.storage_root().resolve())))

    def test_상위_경로_탈출은_거부한다(self):
        for evil in ('../../etc/passwd', '..', 'upload/../../secret'):
            with self.assertRaises(storage.UnsafePathError, msg=evil):
                storage.resolve(evil)

    def test_절대경로_주입도_거부한다(self):
        with self.assertRaises(storage.UnsafePathError):
            storage.resolve(Path(__file__).resolve())

    def test_MEDIA_ROOT_도_STORAGE_ROOT_아래로_격리된다(self):
        # settings.py 는 MEDIA_ROOT 를 STORAGE_ROOT 로부터 계산한다. test_settings
        # 가 STORAGE_ROOT 만 덮으면 MEDIA_ROOT 는 이미 계산된 실제 경로로 남아,
        # 테스트가 돌 때마다 실제 저장소에 이미지와 썸네일이 쌓인다.
        from django.conf import settings

        self.assertTrue(
            Path(settings.MEDIA_ROOT).is_relative_to(Path(settings.STORAGE_ROOT)),
            f'MEDIA_ROOT({settings.MEDIA_ROOT}) 가 '
            f'STORAGE_ROOT({settings.STORAGE_ROOT}) 밖이다')


class SendfileTest(TestCase):
    """파일 응답 — 운영(FILE_ACCEL_REDIRECT)이면 nginx 에 전송을 넘긴다."""

    def setUp(self):
        from django.conf import settings
        self.file = Path(settings.MEDIA_ROOT) / 'tenants' / 'e2e' / 'export 1.zip'
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_bytes(b'PK')

    def test_개발에서는_Django_가_보낸다(self):
        from app.views.files import sendfile
        response = sendfile(self.file, as_attachment=True)
        self.assertEqual(b''.join(response.streaming_content), b'PK')
        self.assertNotIn('X-Accel-Redirect', response)

    @override_settings(FILE_ACCEL_REDIRECT=True)
    def test_운영에서는_내부_경로만_알려_준다(self):
        from app.views.files import sendfile
        response = sendfile(self.file, as_attachment=True, content_type='application/zip')
        self.assertEqual(response['X-Accel-Redirect'], '/_protected/media/tenants/e2e/export%201.zip')
        self.assertEqual(response['Content-Type'], 'application/zip')
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertEqual(response.content, b'')

    @override_settings(FILE_ACCEL_REDIRECT=True)
    def test_없는_파일과_허용_폴더_밖은_넘기지_않는다(self):
        from app.views.files import sendfile
        with self.assertRaises(FileNotFoundError):
            sendfile(self.file.parent / 'nope.zip')
        with self.assertRaises(FileNotFoundError):
            sendfile(Path(__file__))

    def test_바뀌지_않았으면_304(self):
        # 캐시 헤더가 없어 탭을 열 때마다 이미지를 다시 받았다.
        from django.test import RequestFactory
        from app.views.files import sendfile
        first = sendfile(self.file, request=RequestFactory().get('/'))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first['Cache-Control'], 'private, no-cache')
        again = RequestFactory().get('/', HTTP_IF_MODIFIED_SINCE=first['Last-Modified'])
        self.assertEqual(sendfile(self.file, request=again).status_code, 304)
