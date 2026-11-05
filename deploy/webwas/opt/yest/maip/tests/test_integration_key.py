"""외부 연동 키 관리 명령 — 키는 발급 때 한 번만, 저장은 해시만."""
import hashlib
import io
import os
import stat
import tempfile

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from domain.models.vision import IntegrationClient


def run(*args):
    out = io.StringIO()
    call_command('integration_key', *args, stdout=out)
    return out.getvalue()


def sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


class IntegrationKeyCommandTest(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.output = os.path.join(folder.name, 'key')

    def key_in_file(self):
        with open(self.output, encoding='utf-8') as handle:
            return handle.read().strip()

    def test_발급하면_maip_키를_파일에만_쓰고_해시만_저장한다(self):
        printed = run('issue', 'WEZARD', '--name', 'Wezard', '--output', self.output)
        key = self.key_in_file()
        self.assertTrue(key.startswith('maip_') and len(key) > 40)
        self.assertNotIn(key, printed)
        self.assertIn(key[-4:], printed)
        self.assertEqual(stat.S_IMODE(os.stat(self.output).st_mode), 0o600)
        self.assertEqual(IntegrationClient.objects.get(client_id='WEZARD').api_key_hash, sha256(key))

    def test_파일을_주지_않으면_화면에_한_번_보인다(self):
        printed = run('issue', 'WEZARD', '--name', 'Wezard')
        row = IntegrationClient.objects.get()
        key = next(word for word in printed.split() if word.startswith('maip_'))
        self.assertEqual(row.api_key_hash, sha256(key))

    def test_같은_이름은_다시_발급하지_않는다(self):
        run('issue', 'WEZARD', '--name', 'Wezard')
        with self.assertRaises(CommandError):
            run('issue', 'WEZARD', '--name', 'Wezard')

    def test_재발급하면_이전_키는_무효이고_다시_사용한다(self):
        run('issue', 'WEZARD', '--name', 'Wezard', '--output', self.output)
        first = self.key_in_file()
        run('revoke', 'WEZARD')
        run('reissue', 'WEZARD', '--output', self.output)
        second = self.key_in_file()
        row = IntegrationClient.objects.get()
        self.assertNotEqual(first, second)
        self.assertEqual((row.api_key_hash, row.active), (sha256(second), True))

    def test_폐기하면_사용하지_않는다(self):
        run('issue', 'WEZARD', '--name', 'Wezard')
        run('revoke', 'WEZARD')
        self.assertFalse(IntegrationClient.objects.get().active)

    def test_목록은_키_없이_보인다(self):
        run('issue', 'WEZARD', '--name', 'Wezard', '--output', self.output)
        printed = run('list')
        self.assertIn('WEZARD', printed)
        self.assertNotIn(self.key_in_file(), printed)

    def test_없는_이름은_오류다(self):
        with self.assertRaises(CommandError):
            run('revoke', 'NOPE')
