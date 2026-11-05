"""표본 이미지로 현장 검사 파이프라인을 끝까지 시험한다. 검사 기록이 남는다.

    python manage.py sample_inspection [--item FAN-PANEL] [--defect 2] [--normal 2] [--seed N]

표본 zip(seed_demo 와 같은 것)에서 결함·정상 이미지를 따로 뽑아, 비전검사 클라이언트처럼
`POST /api/v1/inspections` 로 보낸다. 인증·검사 접수·모델 매핑·Wezard 추론·응답까지 실제 코드를 지난다
(프로세스 안 테스트 클라이언트라 네트워크·gunicorn 은 빠진다). 정답은 `SAMPLE_DEFECT_FILES` 다.

시험 전용 클라이언트 `PIPELINE-TEST` 로 보낸다. 실행마다 키를 새로 만들어 해시만 저장하고 출력하지 않는다.
보낸 이미지는 현장 검사와 똑같이 그 검사항목의 라벨링 대기에 쌓인다. `SUCCESS` 가 아닌 검사가 있으면 실패로 끝난다.
"""
import hashlib
import json
import random
import secrets
import uuid

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test import Client
from django.utils import timezone

from app.views.vision.client import _create_service_account
from domain.management.commands.seed_demo import SAMPLE_DEFECT_FILES, SAMPLE_IMAGE_FILES, SAMPLE_ZIP, _read_samples
from domain.models.data import InspectionItem
from domain.models.vision import VisionClient, VisionInspection
from domain.tenancy import tenant_atomic

CLIENT_ID = 'PIPELINE-TEST'
CLIENT_NAME = '파이프라인 시험 클라이언트'
NORMAL_FILES = [name for name in SAMPLE_IMAGE_FILES if name not in SAMPLE_DEFECT_FILES]


class Command(BaseCommand):
    help = '표본 이미지(결함·정상)를 /api/v1/inspections 로 보내 추론 결과까지 시험한다. 검사 기록이 남는다.'

    def add_arguments(self, parser):
        parser.add_argument('--item', default='FAN-PANEL', help='비전검사항목 코드')
        parser.add_argument('--defect', type=int, default=2, help=f'결함 표본 수(0~{len(SAMPLE_DEFECT_FILES)})')
        parser.add_argument('--normal', type=int, default=2, help=f'정상 표본 수(0~{len(NORMAL_FILES)})')
        parser.add_argument('--seed', type=int, help='같은 표본을 다시 뽑을 때. 빼면 무작위')

    def handle(self, *args, **options):
        defect, normal = options['defect'], options['normal']
        if not (0 <= defect <= len(SAMPLE_DEFECT_FILES) and 0 <= normal <= len(NORMAL_FILES) and defect + normal):
            raise CommandError(f'결함은 0~{len(SAMPLE_DEFECT_FILES)}, 정상은 0~{len(NORMAL_FILES)}장, 합은 1장 이상이어야 합니다.')
        if not SAMPLE_ZIP.is_file():
            raise CommandError(f'표본 zip 이 없습니다: {SAMPLE_ZIP}')
        with tenant_atomic():
            item = InspectionItem.objects.filter(code=options['item']).first()
            if item is None:
                raise CommandError(f'비전검사항목을 찾을 수 없습니다: {options["item"]}')
            item_id, item_label = item.id, f'{item.code}(id={item.id}, {item.get_task_type_display()})'

        seed = options['seed'] if options['seed'] is not None else random.randrange(10000)
        rng = random.Random(seed)
        picks = ([(name, True) for name in rng.sample(SAMPLE_DEFECT_FILES, defect)]
                 + [(name, False) for name in rng.sample(NORMAL_FILES, normal)])
        files = _read_samples(SAMPLE_ZIP, [name for name, _ in picks])

        # 테스트 클라이언트 기본 호스트 `testserver` 는 ALLOWED_HOSTS 에 없어 400 이 난다. 허용된 이름으로 보낸다.
        host = next((h.lstrip('.') for h in settings.ALLOWED_HOSTS if h != '*'), 'localhost')
        http = Client(headers={'X-Client-ID': CLIENT_ID, 'X-API-Key': self._issue_key()}, HTTP_HOST=host)
        self.stdout.write(f'{item_label} / 결함 {defect}장 · 정상 {normal}장 / seed={seed}')
        results = [self._inspect(http, item_id, name, files[name], expected) for name, expected in picks]

        succeeded = [r for r in results if r['status'] == 'SUCCESS']
        for expected, label in ((True, '결함'), (False, '정상')):
            # 판정 정확도는 추론이 된(SUCCESS) 것만 센다.
            rows = [r for r in succeeded if r['expected'] is expected]
            if rows:
                self.stdout.write(f'{label} {len(rows)}장 중 {sum(r["abnormal"] is expected for r in rows)}장 맞힘')
        failed = len(results) - len(succeeded)
        if failed:
            raise CommandError(f'SUCCESS 가 아닌 검사 {failed}건 — 위 사유를 확인합니다.')
        self.stdout.write(self.style.SUCCESS(f'SUCCESS {len(succeeded)}/{len(results)}'))

    def _inspect(self, http, item_id, name, image, expected):
        """검사 1건을 보내고 한 줄로 찍는다. {'status', 'expected', 'abnormal'}."""
        request_id = str(uuid.uuid4())
        response = http.post('/api/v1/inspections', {
            'image': SimpleUploadedFile(name, image, content_type='image/png'),
            'metadata': json.dumps({'request_id': request_id, 'inspection_item_id': item_id,
                                    'capture_timestamp': timezone.now().isoformat(),
                                    'client_version': 'sample_inspection'}),
        })
        if response.get('Content-Type') != 'application/json':
            raise CommandError(f'/api/v1/inspections 가 JSON 이 아닌 응답을 줬습니다(HTTP {response.status_code}).')
        body = response.json()
        truth = '결함' if expected else '정상'
        if 'data' not in body:
            self.stdout.write(f'{name:<7} {truth}  HTTP {response.status_code} {body["error"]["code"]}  {request_id}')
            return {'status': body['error']['code'], 'expected': expected, 'abnormal': None}

        result = body['data']
        status = result['status']
        if status == 'SUCCESS':
            verdict = '이상' if result['abnormal'] else '정상'
            mark = '일치' if result['abnormal'] is expected else '불일치'
            if result['classification']:
                score = f'분류 {result["classification"]["name"]} {result["classification"]["score"]:.2f}'
            elif result['anomaly_score'] is not None:
                score = f'점수 {result["anomaly_score"]:.2f}/{result["threshold"]:.2f}'
            else:
                score = f'탐지 {len(result["defects"])}건'
            detail = f'{verdict} {mark}  {score}  {result["inference_ms"]:.0f}ms  v{result["model"]["version"]}'
        else:
            with tenant_atomic():
                reason = VisionInspection.objects.filter(pk=result['id']).values_list('error_message', flat=True).first()
            detail = reason or '모델 매핑 없음'
        self.stdout.write(f'{name:<7} {truth}  {status}  {detail}  {request_id}')
        return {'status': status, 'expected': expected, 'abnormal': result['abnormal']}

    @staticmethod
    @transaction.atomic
    def _issue_key():
        """시험 클라이언트의 키를 새로 만든다(해시만 저장). 현장 클라이언트 키는 건드리지 않는다."""
        api_key = secrets.token_urlsafe(32)
        digest = hashlib.sha256(api_key.encode('utf-8')).hexdigest()
        client = VisionClient.objects.filter(client_id=CLIENT_ID).first()
        if client is None:
            VisionClient.objects.create(client_id=CLIENT_ID, name=CLIENT_NAME, api_key_hash=digest,
                                        service_account=_create_service_account(CLIENT_ID, CLIENT_NAME))
        else:
            client.api_key_hash = digest
            client.active = True
            client.save(update_fields=['api_key_hash', 'active', 'updated_at'])
        return api_key
