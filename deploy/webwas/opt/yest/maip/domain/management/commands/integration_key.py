"""외부 연동 키(`maip_…`) 발급·재발급·폐기·목록.

연동처가 Wezard 하나라 화면 대신 이 명령으로 관리한다(DECISIONS DEC-029).

    python manage.py integration_key issue WEZARD --name "Wezard 학습 플랫폼" --output /var/lib/maip/wezard_key.txt
    python manage.py integration_key reissue WEZARD --output /var/lib/maip/wezard_key.txt
    python manage.py integration_key revoke WEZARD
    python manage.py integration_key list

키 원문은 DB 에 남지 않는다(SHA-256 해시만). `--output` 을 주면 원문을 권한 600 파일에만 쓰고 화면에는 끝 4자리만 보인다.
`--output` 이 없으면 화면에 한 번 보인다 — 터미널 기록·로그에 남을 수 있으니 전달용으로는 `--output` 을 쓴다.
`--output` 은 저장소 밖에 둔다 — 저장소 안이면 원문이 커밋될 수 있다. 운영 절차는 docs/DEPLOYMENT.md §8-2.
"""
import hashlib
import os
import secrets

from django.core.management.base import BaseCommand, CommandError

from domain.models.vision import IntegrationClient

KEY_PREFIX = 'maip_'


def new_key():
    """(원문, 해시)."""
    api_key = KEY_PREFIX + secrets.token_urlsafe(32)
    return api_key, hashlib.sha256(api_key.encode('utf-8')).hexdigest()


class Command(BaseCommand):
    help = '외부 연동 키(maip_…)를 발급·재발급·폐기하고 목록을 보인다.'

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest='action', required=True)
        issue = sub.add_parser('issue', help='새 연동처의 키를 발급한다.')
        issue.add_argument('client_id')
        issue.add_argument('--name', required=True, help='연동 이름(100자 이하).')
        issue.add_argument('--output', help='키 원문을 쓸 파일(권한 600).')
        reissue = sub.add_parser('reissue', help='키를 새로 발급한다. 이전 키는 바로 무효다.')
        reissue.add_argument('client_id')
        reissue.add_argument('--output', help='키 원문을 쓸 파일(권한 600).')
        revoke = sub.add_parser('revoke', help='키를 폐기한다(사용 해제).')
        revoke.add_argument('client_id')
        sub.add_parser('list', help='연동처 목록(키는 보이지 않는다).')

    def handle(self, *args, **options):
        action = options['action']
        if action == 'list':
            for row in IntegrationClient.objects.order_by('client_id'):
                self.stdout.write('{}\t{}\t{}\t최근 접속 {}'.format(
                    row.client_id, row.name, '사용' if row.active else '폐기',
                    row.last_seen_at.strftime('%Y-%m-%d %H:%M') if row.last_seen_at else '-'))
            return

        client_id = options['client_id']
        if action == 'issue':
            if len(client_id) > 50 or len(options['name']) > 100:
                raise CommandError('Client ID 는 50자, 이름은 100자 이하여야 합니다.')
            if IntegrationClient.objects.filter(client_id=client_id).exists():
                raise CommandError(f'이미 있는 연동처입니다: {client_id}. 키를 바꾸려면 reissue 를 씁니다.')
            api_key, api_key_hash = new_key()
            IntegrationClient.objects.create(client_id=client_id, name=options['name'], api_key_hash=api_key_hash)
            self._hand_over(client_id, api_key, options.get('output'))
            return

        row = IntegrationClient.objects.filter(client_id=client_id).first()
        if row is None:
            raise CommandError(f'없는 연동처입니다: {client_id}')
        if action == 'revoke':
            row.active = False
            row.save(update_fields=['active', 'updated_at'])
            self.stdout.write(f'{client_id} 키를 폐기했습니다. 이 키의 요청은 401 입니다.')
            return
        api_key, row.api_key_hash = new_key()
        row.active = True
        row.save(update_fields=['api_key_hash', 'active', 'updated_at'])
        self._hand_over(client_id, api_key, options.get('output'))
        self.stdout.write('이전 키는 바로 무효입니다.')

    def _hand_over(self, client_id, api_key, output):
        if not output:
            self.stdout.write(f'{client_id} 키(지금만 보입니다): {api_key}')
            return
        # 만들 때부터 600 이다. 기존 파일이면 덮어쓰기 전에 권한을 좁힌다.
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.chmod(output, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(api_key + '\n')
        self.stdout.write(f'{client_id} 키를 {output} 에 썼습니다(…{api_key[-4:]}).')
