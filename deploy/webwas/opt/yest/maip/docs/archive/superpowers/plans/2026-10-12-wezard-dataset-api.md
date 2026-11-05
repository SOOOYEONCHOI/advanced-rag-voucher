# Wezard 스냅샷 연동 API 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wezard(학습 플랫폼)가 전용 키로 스냅샷 목록·정보를 보고 zip 을 이어받기·SHA-256 검증까지 해서 가져갈 수 있게 API 3개, 키 관리 화면, 정본 문서를 만든다.

**Architecture:** `/api/v1` 의 `ClientApiView`(인증·봉투·tenant_atomic)를 그대로 쓰되 대조 테이블만 `IntegrationClient` 로 바꾼 `DatasetApiView` 를 새 모듈 `app/views/api_v1_datasets.py` 에 둔다.
스냅샷 조회는 스냅샷 관리 화면의 `_latest_exports`·`_analyze_manifest` 를 재사용하고, 다운로드는 배포물 다운로드의 Range 처리를 함수로 뽑아 함께 쓴다.
zip 의 크기·SHA-256 은 `ExportJob` 에 저장한다(새 zip 은 만들 때, 예전 zip 은 처음 부를 때).

**Tech Stack:** Django 5.2 / PostgreSQL 16(RLS) / jQuery + WeZonGrid / Playwright e2e

**Spec:** [docs/superpowers/specs/2026-10-12-wezard-dataset-api-design.md](../specs/2026-10-12-wezard-dataset-api-design.md)

## Global Constraints

- 사용자에게 보이는 문구(API `message`·알림·확인창·화면 안내)는 `~합니다` 체.
- API Key 원문은 저장·로그·오류 메시지에 남기지 않는다. 해시(SHA-256)만 저장, 발급 응답에서 한 번만 보인다. 로그에는 `client_id` 만.
- 새 `/api/v1/...` 라우트는 `configurations/urls.py` 의 `api/v1` catch-all(`V1NotFoundView`) **앞**에 둔다.
- RLS 를 우회하지 않는다. 테넌트 테이블은 `tenant_atomic()` 안에서 읽는다(`ClientApiView` 가 열어 준다).
- 파일은 `sendfile()` 로 낸다(운영은 nginx `FILE_ACCEL_REDIRECT`). 공개 경로를 만들지 않는다.
- 사용자 값은 화면에 `.text()` 로 넣는다.
- 마이그레이션은 `makemigrations` 로만 만든다. `--fake`·`django_migrations` 직접 수정 금지.
- 테스트: `.venv/bin/python manage.py test <대상> --settings=configurations.test_settings`.
- 커밋 메시지는 한국어, Conventional type 영문(`feat:`·`docs:`·`test:`). `main` 에 직접 커밋하지 않는다 — 브랜치 `feat/wezard-dataset-api`.
- 문서는 `docs/Wezard/maip-api.md` 를 정본으로 하고, 다른 문서에는 같은 내용을 반복하지 않고 링크한다.

## 파일 지도

| 파일 | 책임 |
|---|---|
| `domain/models/vision.py` | `IntegrationClient` 모델 추가 |
| `domain/models/data.py` | `ExportJob.file_size`·`file_sha256` |
| `domain/migrations/0002_*.py` | 위 둘(생성) |
| `domain/services/data/export/__init__.py` | Export 시 크기·SHA-256 저장, `ExportService.ensure_checksum` |
| `app/views/api_v1.py` | `ClientApiView` 의 키 테이블을 클래스 속성으로, Range 응답을 함수 `ranged_file_response` 로 추출 |
| `app/views/api_v1_datasets.py` | 새 모듈 — 스냅샷 목록·정보·다운로드 |
| `configurations/urls.py` | 라우트 3개 |
| `app/views/system/integration_client.py` | 새 모듈 — 키 관리 API |
| `app/templates/system/integration_client.html` | 새 화면 |
| `domain/gui.py` · `domain/management/commands/seed_initial.py` · `app/views/system/menus.py` | 화면·API 매핑, 메뉴, 플랫폼 관리자 전용 |
| `scripts/verify_buttons.py` | 화면 목록에 추가 |
| `tests/test_dataset_api.py` · `tests/test_integration_client.py` · `tests/e2e/test_integration_client.py` | 테스트(생성) |
| `docs/Wezard/maip-api.md` | 정본 문서(생성) |
| `docs/README.md` · `docs/client/SERVER_API_CONTRACT.md` · `docs/DECISIONS.md` · `docs/ARCHITECTURE.md` · `docs/FEATURES.md` · `docs/DATA_MODEL.md` · `docs/STATUS.md` · `AGENTS.md` | 링크·결정·표 갱신 |

---

### Task 1: 스키마 — `IntegrationClient` 와 `ExportJob` 크기·SHA-256

**Files:**
- Modify: `domain/models/vision.py` (VisionClient 클래스 바로 아래)
- Modify: `domain/models/data.py` (`ExportJob` 필드)
- Create: `domain/migrations/0002_integration_client_export_checksum.py` (생성 명령으로)

**Interfaces:**
- Produces: `domain.models.vision.IntegrationClient(client_id, name, api_key_hash, active, last_seen_at, created_at, updated_at)`, `ExportJob.file_size: int|None`, `ExportJob.file_sha256: str`('' = 아직 없음)

- [ ] **Step 1: 모델 추가** — `domain/models/vision.py` 의 `VisionClient` 아래:

```python
class IntegrationClient(TimestampMixin):
    """학습 플랫폼(Wezard) 같은 외부 시스템이 스냅샷을 받아 가는 키(DECISIONS DEC-029).

    VisionClient 와 테이블을 나눈다 — 현장 PC 키 하나가 새어도 학습 데이터 전체가 나가지 않게.
    API Key 는 SHA-256 해시만 저장한다. 발급 시 1회 노출하고 다시 볼 수 없다.
    """

    client_id = models.CharField('Client ID', max_length=50, unique=True)
    name = models.CharField('연동 이름', max_length=100)
    api_key_hash = models.CharField('API Key 해시', max_length=64)
    active = models.BooleanField('사용', default=True)
    last_seen_at = models.DateTimeField('최근 접속', null=True, blank=True)

    class Meta:
        db_table = 'integration_client'
        verbose_name = '외부 연동 키'
        ordering = ['client_id']

    def __str__(self):
        return f'{self.client_id} · {self.name}'
```

`domain/models/data.py` `ExportJob` 의 `file = ...` 아래:

```python
    # 받은 쪽이 대조할 값. 예전 zip 은 비어 있고 처음 조회할 때 채운다(ExportService.ensure_checksum).
    file_size = models.BigIntegerField(null=True, blank=True)
    file_sha256 = models.CharField(max_length=64, blank=True)
```

- [ ] **Step 2: 마이그레이션 생성**

Run: `.venv/bin/python manage.py makemigrations domain --name integration_client_export_checksum`
Expected: `domain/migrations/0002_integration_client_export_checksum.py` — `CreateModel IntegrationClient`, `AddField exportjob.file_size`, `AddField exportjob.file_sha256` 셋만. 다른 연산이 섞이면 멈추고 원인을 본다.

- [ ] **Step 3: 확인**

Run: `.venv/bin/python manage.py makemigrations --check --dry-run` → `No changes detected`
Run: `.venv/bin/python manage.py test tests.test_export_formats tests.test_snapshot_job --settings=configurations.test_settings` → OK

- [ ] **Step 4: 커밋**

```bash
git add domain/models/vision.py domain/models/data.py domain/migrations/0002_integration_client_export_checksum.py
git commit -m "feat: 외부 연동 키 테이블과 Export zip 크기·SHA-256 칸을 더한다"
```

---

### Task 2: Export zip 의 크기·SHA-256 저장

**Files:**
- Modify: `domain/services/data/export/__init__.py`
- Create: `tests/test_dataset_api.py` (이 Task 는 체크섬 테스트와 공통 픽스처만)

**Interfaces:**
- Consumes: Task 1 의 `ExportJob.file_size`·`file_sha256`
- Produces: `ExportService.ensure_checksum(export_job) -> ExportJob` — 비어 있으면 파일을 읽어 채우고 저장. 파일이 없으면 `FileNotFoundError`, 파일 필드가 비면 아무것도 안 한다. `tests.test_dataset_api.DatasetApiTestCase`(픽스처: `self.item`(객체 탐지, 결함 라벨 1개), `self.snapshot(item=None, run=True) -> (version, export)`, `self.get(path, **extra)`)

- [ ] **Step 1: 실패하는 테스트** — `tests/test_dataset_api.py`

```python
"""학습 플랫폼(Wezard)용 스냅샷 API — `/api/v1/datasets/...`.

정본은 `docs/Wezard/maip-api.md` 다. 키는 IntegrationClient 로 대조한다(DECISIONS DEC-029).
"""
import hashlib
import secrets
import tempfile

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from domain.models.data import ExportJob, ImageAsset, InspectionItem, LabelClass
from domain.models.vision import IntegrationClient
from domain.services.data.export import ExportService
from domain.services.data.image import ImageService
from domain.services.data.item import ItemService
from domain.services.data.version import DatasetVersionService
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic
from tests.test_data_services import make_image


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


class DatasetApiTestCase(TestCase):
    def setUp(self):
        reset_tenant_cache()
        self.tenant = current_tenant()
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_superuser('dataset-api-admin', password='x')
        self.api_key = secrets.token_urlsafe(24)
        IntegrationClient.objects.create(client_id='WEZARD-TEST', name='Wezard',
                                         api_key_hash=sha256(self.api_key.encode()))
        with tenant_atomic(self.tenant):
            self.item = InspectionItem.objects.create(
                tenant=self.tenant, code='API-DET', name='검출',
                task_type=InspectionItem.TaskType.OBJECT_DETECTION)
            # COCO 는 결함 라벨 클래스가 있어야 만들어진다(CocoExporter.validate).
            LabelClass.objects.create(tenant=self.tenant, item=self.item, name='dent',
                                      display_name_ko='찍힘', is_defect=True)
        self.http = Client()

    def snapshot(self, item=None, run=True):
        """승인 이미지 1장으로 스냅샷을 만든다. run=False 면 Export 는 QUEUED 로 남는다."""
        item = item or self.item
        with tenant_atomic(self.tenant):
            dataset = ItemService.get_or_create_upload_dataset(item)
            ImageService.upload_images(item, [make_image()], actor=self.user)
            ImageAsset.objects.for_tenant(self.tenant).filter(dataset=dataset).update(
                label_status=ImageAsset.LabelStatus.APPROVED)
            version, export = DatasetVersionService.create_snapshot(dataset, self.user)
            if run:
                ExportService.run(export)
                export.refresh_from_db()
                self.assertEqual(export.status, ExportJob.Status.COMPLETED, export.error_message)
        return version, export

    def get(self, path, **extra):
        return self.http.get(path, HTTP_X_CLIENT_ID='WEZARD-TEST', HTTP_X_API_KEY=self.api_key, **extra)


class ChecksumTest(DatasetApiTestCase):
    def test_Export_하면_zip_크기와_SHA256_을_저장한다(self):
        _, export = self.snapshot()
        raw = export.file.read()
        self.assertEqual((export.file_size, export.file_sha256), (len(raw), sha256(raw)))

    def test_비어_있으면_처음_부를_때_계산해_저장한다(self):
        _, export = self.snapshot()
        expected = (export.file_size, export.file_sha256)
        with tenant_atomic(self.tenant):
            ExportJob.objects.for_tenant(self.tenant).filter(pk=export.pk).update(file_size=None, file_sha256='')
            export.refresh_from_db()
            ExportService.ensure_checksum(export)
            export.refresh_from_db()
        self.assertEqual((export.file_size, export.file_sha256), expected)
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python manage.py test tests.test_dataset_api --settings=configurations.test_settings`
Expected: 첫 테스트 `AssertionError: (None, '') != (…)`, 둘째 `AttributeError: … has no attribute 'ensure_checksum'`

- [ ] **Step 3: 구현** — `domain/services/data/export/__init__.py`

`import hashlib` 추가. `run` 의 `handle.seek(0)` 부분을 아래로 바꾼다:

```python
            handle.seek(0)
            # 받는 쪽(Wezard)이 대조할 값. 저장소에 올린 뒤 다시 읽지 않도록 임시 파일에서 계산한다.
            export_job.file_sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
            export_job.file_size = handle.tell()
            handle.seek(0)
            export_job.file.save(f"{export_job.dataset_version.version_tag}_{export_job.format.lower()}.zip", File(handle), save=False)
```

`export_job.save(update_fields=["file", "status", "completed_at"])` → `["file", "file_size", "file_sha256", "status", "completed_at"]`.

`_fail` 위에 추가:

```python
    @staticmethod
    def ensure_checksum(export_job):
        """크기·SHA-256 이 비어 있으면(이 칸이 생기기 전 zip) 파일을 읽어 채운다. 파일이 없으면 FileNotFoundError."""
        if export_job.file_sha256 or not export_job.file:
            return export_job
        with open(export_job.file.path, "rb") as handle:
            export_job.file_sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
            export_job.file_size = handle.tell()
        export_job.save(update_fields=["file_size", "file_sha256"])
        return export_job
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python manage.py test tests.test_dataset_api tests.test_export_formats tests.test_snapshot_job --settings=configurations.test_settings` → OK

- [ ] **Step 5: 커밋**

```bash
git add domain/services/data/export/__init__.py tests/test_dataset_api.py
git commit -m "feat: Export zip 의 크기와 SHA-256 을 저장하고 예전 zip 은 처음 조회 때 채운다"
```

---

### Task 3: 인증 분리 + 스냅샷 목록·정보 API

**Files:**
- Modify: `app/views/api_v1.py` (`ClientApiView`)
- Create: `app/views/api_v1_datasets.py`
- Modify: `configurations/urls.py`
- Test: `tests/test_dataset_api.py`

**Interfaces:**
- Consumes: `DatasetApiTestCase`, `ExportService.ensure_checksum`, `app.views.item.snapshot._latest_exports(tenant, version_ids) -> {version_id: ExportJob}`, `_analyze_manifest(manifest, task_type) -> dict`
- Produces: `ClientApiView.client_model`·`client_attr` 속성(기본 `VisionClient`·`'vision_client'`), `app.views.api_v1_datasets.DatasetApiView`, `_snapshots()`(최근 Export 상태 `export_status` 주석이 붙은 최신순 queryset), `_find(snapshot_id) -> (version|None, job|None)`, `_serialize(version, job) -> dict`, `SnapshotListView`·`SnapshotDetailView`

- [ ] **Step 1: 실패하는 테스트** — `tests/test_dataset_api.py` 끝에 추가. 파일 위 import 에 `from domain.models.vision import VisionClient` 를 더한다.

```python
LIST = '/api/v1/datasets/snapshots'


class AuthTest(DatasetApiTestCase):
    def test_키가_없으면_401_AUTH_REQUIRED(self):
        response = self.http.get(LIST)
        self.assertEqual((response.status_code, response.json()['error']['code']), (401, 'AUTH_REQUIRED'))

    def test_검사_클라이언트_키로는_받을_수_없다(self):
        key = secrets.token_urlsafe(24)
        VisionClient.objects.create(client_id='FIELD-PC', name='현장', api_key_hash=sha256(key.encode()))
        response = self.http.get(LIST, HTTP_X_CLIENT_ID='FIELD-PC', HTTP_X_API_KEY=key)
        self.assertEqual((response.status_code, response.json()['error']['code']), (401, 'AUTH_INVALID'))

    def test_연동_키로는_검사_API_를_부를_수_없다(self):
        response = self.get('/api/v1/catalog')
        self.assertEqual((response.status_code, response.json()['error']['code']), (401, 'AUTH_INVALID'))

    def test_사용을_끈_키는_401(self):
        IntegrationClient.objects.update(active=False)
        self.assertEqual(self.get(LIST).status_code, 401)

    def test_인증하면_최근_접속을_남긴다(self):
        self.get(LIST)
        self.assertIsNotNone(IntegrationClient.objects.get().last_seen_at)


class SnapshotListTest(DatasetApiTestCase):
    def setUp(self):
        super().setUp()
        self.done, self.done_export = self.snapshot()
        with tenant_atomic(self.tenant):
            self.other = InspectionItem.objects.create(
                tenant=self.tenant, code='API-CLS', name='분류',
                task_type=InspectionItem.TaskType.CLASSIFICATION)
        self.queued, _ = self.snapshot(self.other, run=False)

    def test_최신순으로_검사항목과_Export_를_함께_준다(self):
        body = self.get(LIST).json()['data']
        self.assertEqual((body['total'], body['page'], body['page_size']), (2, 1, 50))
        first, second = body['items']
        self.assertEqual((first['id'], second['id']), (self.queued.id, self.done.id))
        self.assertEqual(second['item'], {'id': self.item.id, 'code': 'API-DET', 'name': '검출',
                                          'task_type': 'OBJECT_DETECTION'})
        self.assertEqual(second['image_count'], 1)
        self.assertTrue(second['created_at'].endswith('Z'))
        export = second['export']
        self.assertEqual((export['status'], export['format'], export['format_label']),
                         ('COMPLETED', 'COCO', 'COCO Detection'))
        self.assertEqual((export['size_bytes'], export['sha256']),
                         (self.done_export.file_size, self.done_export.file_sha256))
        self.assertEqual(export['download_url'], f'/api/v1/datasets/snapshots/{self.done.id}/download')
        self.assertIsNone(first['export']['download_url'])  # 아직 대기 중

    def test_검사항목_유형_상태로_거른다(self):
        def ids(query):
            return [row['id'] for row in self.get(LIST + query).json()['data']['items']]
        self.assertEqual(ids('?item_code=API-DET'), [self.done.id])
        self.assertEqual(ids('?task_type=CLASSIFICATION'), [self.queued.id])
        self.assertEqual(ids('?status=COMPLETED'), [self.done.id])
        self.assertEqual(ids('?status=QUEUED'), [self.queued.id])
        self.assertEqual(ids('?created_after=2999-01-01T00:00:00Z'), [])

    def test_페이지를_나눈다(self):
        body = self.get(LIST + '?page=2&page_size=1').json()['data']
        self.assertEqual(([row['id'] for row in body['items']], body['total']), ([self.done.id], 2))

    def test_잘못된_쿼리는_400_INVALID_PARAMETER(self):
        for query in ('?page=0', '?page=x', '?page_size=201', '?status=DONE',
                      '?task_type=SEGMENT', '?created_after=어제'):
            response = self.get(LIST + query)
            self.assertEqual((response.status_code, response.json()['error']['code']),
                             (400, 'INVALID_PARAMETER'), query)


class SnapshotDetailTest(DatasetApiTestCase):
    def test_목록_행에_통계와_제외_이미지_수를_더한다(self):
        version, export = self.snapshot()
        body = self.get(f'{LIST}/{version.id}').json()['data']
        self.assertEqual(body['export']['sha256'], export.file_sha256)
        self.assertEqual(body['excluded_image_count'], 0)
        self.assertEqual(body['statistics']['image_count'], 1)
        self.assertIsNone(body['export']['error_message'])

    def test_예전_zip_은_정보를_볼_때_SHA256_을_채운다(self):
        version, export = self.snapshot()
        expected = export.file_sha256
        with tenant_atomic(self.tenant):
            ExportJob.objects.for_tenant(self.tenant).filter(pk=export.pk).update(file_size=None, file_sha256='')
        self.assertEqual(self.get(f'{LIST}/{version.id}').json()['data']['export']['sha256'], expected)

    def test_없는_스냅샷은_404_SNAPSHOT_NOT_FOUND(self):
        response = self.get(f'{LIST}/999999')
        self.assertEqual((response.status_code, response.json()['error']['code']), (404, 'SNAPSHOT_NOT_FOUND'))
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python manage.py test tests.test_dataset_api --settings=configurations.test_settings`
Expected: 목록·정보 테스트는 `404 NOT_FOUND` 봉투로 실패(라우트 없음), `test_연동_키로는_검사_API_를_부를_수_없다` 는 이미 401 이라 통과할 수 있다 — 이 하나는 Step 3 뒤에도 통과해야 하는 회귀 방지용이다.

- [ ] **Step 3: `ClientApiView` 의 키 테이블을 속성으로** — `app/views/api_v1.py`

`use_tenant = True` 아래에:

```python
    # 키를 대조할 테이블과 인증된 행을 실을 request 속성. 학습 플랫폼 API 는 IntegrationClient 를 본다
    # (app/views/api_v1_datasets.py). 테이블이 달라 한쪽 키로 다른 쪽 API 를 부를 수 없다.
    client_model = VisionClient
    client_attr = 'vision_client'
```

`dispatch` 의 `request.vision_client = client` → `setattr(request, self.client_attr, client)`.
`_authenticate` 를 `@classmethod def _authenticate(cls, request):` 로 바꾸고 본문의 `VisionClient.objects` 두 곳을 `cls.client_model.objects` 로 바꾼다. 로그 문구는 그대로.

Run: `.venv/bin/python manage.py test tests.test_client_api --settings=configurations.test_settings` → OK (기존 계약 그대로)

- [ ] **Step 4: 새 모듈** — `app/views/api_v1_datasets.py`

```python
"""학습 플랫폼(Wezard)용 스냅샷 API — `/api/v1/datasets/...`.

정본은 `docs/Wezard/maip-api.md` 다. 응답 모양·오류 코드·경로를 바꾸면 그 문서를 함께 고친다.
인증 헤더·봉투·시각 형식은 `/api/v1` 과 같고 키 테이블만 다르다(IntegrationClient, DECISIONS DEC-029).
기준 Export 는 스냅샷마다 가장 최근 ExportJob 이다 — 스냅샷 관리 화면과 같다.
"""
from django.db.models import OuterRef, Subquery

from app.views.api_v1 import ClientApiView, data, error, parse_utc, to_utc_z
from app.views.item.snapshot import _analyze_manifest, _latest_exports
from domain.models.data import DatasetVersion, ExportJob, InspectionItem
from domain.models.vision import IntegrationClient
from domain.services.data.export import ExportService
from domain.tenancy import current_tenant

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class DatasetApiView(ClientApiView):
    client_model = IntegrationClient
    client_attr = 'integration_client'
    http_method_names = ['get']


def invalid(message):
    return error('INVALID_PARAMETER', message, 400)


def _snapshots():
    latest = ExportJob.objects.filter(dataset_version=OuterRef('pk')).order_by('-created_at', '-id')
    return (DatasetVersion.objects.for_tenant(current_tenant())
            .select_related('dataset__item')
            .annotate(export_status=Subquery(latest.values('status')[:1]))
            .order_by('-created_at', '-id'))


def _find(snapshot_id):
    version = _snapshots().filter(pk=snapshot_id).first()
    if version is None:
        return None, None
    return version, _latest_exports(current_tenant(), [version.id]).get(version.id)


def _serialize(version, job):
    item = version.dataset.item
    completed = job is not None and job.status == ExportJob.Status.COMPLETED
    return {
        'id': version.id,
        'version_tag': version.version_tag,
        'created_at': to_utc_z(version.created_at),
        'item': {'id': item.id, 'code': item.code, 'name': item.name, 'task_type': item.task_type},
        'image_count': (version.manifest or {}).get('image_count', 0),
        'export': None if job is None else {
            'status': job.status,
            'format': job.format,
            'format_label': job.get_format_display(),
            'size_bytes': job.file_size,
            'sha256': job.file_sha256 or None,
            'completed_at': to_utc_z(job.completed_at),
            'download_url': f'/api/v1/datasets/snapshots/{version.id}/download' if completed else None,
        },
    }


class SnapshotListView(DatasetApiView):
    def get(self, request):
        query = request.GET
        try:
            page = int(query.get('page', 1))
            page_size = int(query.get('page_size', DEFAULT_PAGE_SIZE))
            created_after = parse_utc(query.get('created_after'))
        except (TypeError, ValueError):
            return invalid('page·page_size 는 정수, created_after 는 ISO 8601 시각이어야 합니다.')
        if page < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
            return invalid(f'page 는 1 이상, page_size 는 1~{MAX_PAGE_SIZE} 여야 합니다.')
        task_type, status = query.get('task_type'), query.get('status')
        if task_type and task_type not in InspectionItem.TaskType.values:
            return invalid('task_type 값이 올바르지 않습니다.')
        if status and status not in ExportJob.Status.values:
            return invalid('status 값이 올바르지 않습니다.')

        queryset = _snapshots()
        if query.get('item_code'):
            queryset = queryset.filter(dataset__item__code=query['item_code'])
        if task_type:
            queryset = queryset.filter(dataset__item__task_type=task_type)
        if status:
            queryset = queryset.filter(export_status=status)
        if created_after:
            queryset = queryset.filter(created_at__gt=created_after)

        total = queryset.count()
        rows = list(queryset[(page - 1) * page_size:page * page_size])
        latest = _latest_exports(current_tenant(), [row.id for row in rows])
        return data({'items': [_serialize(row, latest.get(row.id)) for row in rows],
                     'page': page, 'page_size': page_size, 'total': total})


class SnapshotDetailView(DatasetApiView):
    def get(self, request, snapshot_id):
        version, job = _find(snapshot_id)
        if version is None:
            return error('SNAPSHOT_NOT_FOUND', '스냅샷을 찾을 수 없습니다.', 404)
        if job is not None and job.status == ExportJob.Status.COMPLETED:
            try:
                ExportService.ensure_checksum(job)
            except FileNotFoundError:
                pass  # 정보는 준다. 받기에서 EXPORT_FILE_NOT_FOUND 로 알린다.
        body = _serialize(version, job)
        if body['export'] is not None:
            body['export']['error_message'] = job.error_message or None
        manifest = version.manifest or {}
        body['excluded_image_count'] = manifest.get('excluded_image_count', 0)
        body['statistics'] = _analyze_manifest(manifest, version.dataset.item.task_type)
        return data(body)
```

- [ ] **Step 5: 라우트** — `configurations/urls.py`

import 에 `from app.views.api_v1_datasets import SnapshotDetailView, SnapshotListView` 추가. `api/v1/overlays/<int:inspection_item_id>/image` 경로 아래, catch-all 주석 **앞**에:

```python
    # 학습 플랫폼(Wezard)용 스냅샷 API. 정본은 docs/Wezard/maip-api.md(DECISIONS DEC-029).
    path('api/v1/datasets/snapshots', SnapshotListView.as_view(), name='v1-dataset-snapshots'),
    path('api/v1/datasets/snapshots/<int:snapshot_id>', SnapshotDetailView.as_view(),
         name='v1-dataset-snapshot'),
```

- [ ] **Step 6: 통과 확인**

Run: `.venv/bin/python manage.py test tests.test_dataset_api tests.test_client_api --settings=configurations.test_settings` → OK

- [ ] **Step 7: 커밋**

```bash
git add app/views/api_v1.py app/views/api_v1_datasets.py configurations/urls.py tests/test_dataset_api.py
git commit -m "feat: 학습 플랫폼 전용 키로 스냅샷 목록과 정보를 조회하는 API 를 더한다"
```

---

### Task 4: 스냅샷 zip 다운로드(이어받기·감사 로그)

**Files:**
- Modify: `app/views/api_v1.py` (`DistributionDownloadView.get` 의 응답 부분을 `ranged_file_response` 로 추출)
- Modify: `app/views/api_v1_datasets.py`
- Modify: `configurations/urls.py`
- Test: `tests/test_dataset_api.py`

**Interfaces:**
- Consumes: `_find`, `ExportService.ensure_checksum`, `AuditService.record(*, tenant, item=None, actor=None, event_type, payload=None)`
- Produces: `app.views.api_v1.ranged_file_response(request, path: Path, size: int, filename: str) -> HttpResponse` (200 / 206 / 416 봉투), `SnapshotDownloadView`

- [ ] **Step 1: 실패하는 테스트** — `tests/test_dataset_api.py` 끝에. import 에 `from domain.models.data import ActivityLog` 를 더한다(`ActivityLog` 는 `domain.models.data` 에 있다 — 없으면 `grep -n "class ActivityLog" domain/models` 로 위치 확인).

```python
class SnapshotDownloadTest(DatasetApiTestCase):
    def url(self, version):
        return f'{LIST}/{version.id}/download'

    def body(self, response):
        return b''.join(response.streaming_content)

    def downloads(self):
        with tenant_atomic(self.tenant):
            return ActivityLog.objects.for_tenant(self.tenant).filter(event_type='SNAPSHOT_DOWNLOADED').count()

    def test_전체를_받으면_SHA256_이_정보와_같다(self):
        version, export = self.snapshot()
        response = self.get(self.url(version))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sha256(self.body(response)), export.file_sha256)
        self.assertIn(f'snapshot-{version.id}-{version.version_tag}-coco.zip', response['Content-Disposition'])
        self.assertEqual(response['Accept-Ranges'], 'bytes')

    def test_Range_로_이어받는다(self):
        version, export = self.snapshot()
        raw = export.file.read()
        response = self.get(self.url(version), HTTP_RANGE='bytes=10-')
        self.assertEqual(response.status_code, 206)
        self.assertEqual(self.body(response), raw[10:])
        self.assertEqual(response['Content-Range'], f'bytes 10-{len(raw) - 1}/{len(raw)}')

    def test_파일_밖_범위는_416(self):
        version, export = self.snapshot()
        response = self.get(self.url(version), HTTP_RANGE=f'bytes={export.file_size + 5}-')
        self.assertEqual((response.status_code, response.json()['error']['code']),
                         (416, 'RANGE_NOT_SATISFIABLE'))

    def test_받기_시작만_감사_로그에_남긴다(self):
        version, _ = self.snapshot()
        self.body(self.get(self.url(version)))
        self.body(self.get(self.url(version), HTTP_RANGE='bytes=10-'))
        self.assertEqual(self.downloads(), 1)

    def test_대기_중이면_409_EXPORT_NOT_READY_재시도_가능(self):
        version, _ = self.snapshot(run=False)
        error = self.get(self.url(version)).json()['error']
        self.assertEqual((error['code'], error['retryable']), ('EXPORT_NOT_READY', True))

    def test_실패했으면_409_EXPORT_FAILED(self):
        version, export = self.snapshot(run=False)
        with tenant_atomic(self.tenant):
            ExportJob.objects.for_tenant(self.tenant).filter(pk=export.pk).update(status=ExportJob.Status.FAILED)
        response = self.get(self.url(version))
        self.assertEqual((response.status_code, response.json()['error']['code']), (409, 'EXPORT_FAILED'))

    def test_파일이_사라졌으면_404_EXPORT_FILE_NOT_FOUND(self):
        version, export = self.snapshot()
        export.file.storage.delete(export.file.name)
        response = self.get(self.url(version))
        self.assertEqual((response.status_code, response.json()['error']['code']), (404, 'EXPORT_FILE_NOT_FOUND'))

    def test_없는_스냅샷은_404(self):
        self.assertEqual(self.get(f'{LIST}/999999/download').json()['error']['code'], 'SNAPSHOT_NOT_FOUND')
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python manage.py test tests.test_dataset_api.SnapshotDownloadTest --settings=configurations.test_settings`
Expected: 전부 `404 NOT_FOUND` 봉투(라우트 없음)로 FAIL

- [ ] **Step 3: Range 응답 추출** — `app/views/api_v1.py`

`DistributionDownloadView` 위에 함수를 두고, `DistributionDownloadView.get` 은 파일을 찾은 뒤 `return ranged_file_response(request, found['path'], found['size_bytes'], found['name'])` 한 줄로 바꾼다(응답 조립 코드는 그대로 옮긴다).

```python
def ranged_file_response(request, path, size, filename):
    """파일 전체(200) 또는 단일 Range(206). 범위가 파일 밖이면 416 봉투(계약 §10-2).

    운영은 Range 까지 nginx 가 처리한다(sendfile).
    """
    requested = _parse_range(request.headers.get('Range'), size)
    if requested == 'invalid':
        response = error('RANGE_NOT_SATISFIABLE', '요청한 범위가 파일 밖입니다.', 416)
        response['Content-Range'] = 'bytes */{}'.format(size)
        response['Accept-Ranges'] = 'bytes'
        return response
    if requested is None or settings.FILE_ACCEL_REDIRECT:
        response = sendfile(path, as_attachment=True, filename=filename)
        response['Accept-Ranges'] = 'bytes'
        return response
    start, length = requested
    response = StreamingHttpResponse(_file_chunks(path, start, length), status=206,
                                     content_type='application/octet-stream')
    response['Content-Range'] = 'bytes {}-{}/{}'.format(start, start + length - 1, size)
    response['Content-Length'] = str(length)
    response['Accept-Ranges'] = 'bytes'
    response['Content-Disposition'] = 'attachment; filename="{}"'.format(filename)
    return response
```

Run: `.venv/bin/python manage.py test tests.test_client_api --settings=configurations.test_settings` → OK (배포물 다운로드 회귀 없음)

- [ ] **Step 4: 다운로드 뷰** — `app/views/api_v1_datasets.py`

import 추가: `from pathlib import Path`, `from app.views.api_v1 import ranged_file_response, _parse_range`(기존 import 줄에 합친다), `from domain.services.data.audit import AuditService`.

```python
class SnapshotDownloadView(DatasetApiView):
    def get(self, request, snapshot_id):
        version, job = _find(snapshot_id)
        if version is None:
            return error('SNAPSHOT_NOT_FOUND', '스냅샷을 찾을 수 없습니다.', 404)
        if job is None or job.status in (ExportJob.Status.QUEUED, ExportJob.Status.RUNNING):
            return error('EXPORT_NOT_READY', 'Export 를 만드는 중입니다. 잠시 뒤 다시 요청해 주세요.', 409,
                         retryable=True)
        if job.status == ExportJob.Status.FAILED:
            return error('EXPORT_FAILED', 'Export 를 만들지 못했습니다. 플랫폼에서 다시 만들어야 합니다.', 409)
        try:
            ExportService.ensure_checksum(job)
            path = Path(job.file.path)
            size = path.stat().st_size
        except (FileNotFoundError, ValueError):  # ValueError: 파일 필드가 빈 행
            return error('EXPORT_FILE_NOT_FOUND', '저장소에 zip 파일이 없습니다.', 404)

        # 이어받기 조각마다 남기지 않는다. 받기를 시작한 요청(전체 또는 0 바이트부터)만 남긴다.
        requested = _parse_range(request.headers.get('Range'), size)
        if requested is None or (requested != 'invalid' and requested[0] == 0):
            AuditService.record(
                tenant=current_tenant(), item=version.dataset.item, event_type='SNAPSHOT_DOWNLOADED',
                payload={'dataset_version_id': version.id, 'export_job_id': job.id,
                         'client_id': request.integration_client.client_id})
        filename = f'snapshot-{version.id}-{version.version_tag}-{job.format.lower()}.zip'
        return ranged_file_response(request, path, size, filename)
```

라우트(`configurations/urls.py`, Task 3 의 두 줄 아래):

```python
    path('api/v1/datasets/snapshots/<int:snapshot_id>/download', SnapshotDownloadView.as_view(),
         name='v1-dataset-snapshot-download'),
```

import 에 `SnapshotDownloadView` 추가.

- [ ] **Step 5: 통과 확인**

Run: `.venv/bin/python manage.py test tests.test_dataset_api tests.test_client_api --settings=configurations.test_settings` → OK

- [ ] **Step 6: 커밋**

```bash
git add app/views/api_v1.py app/views/api_v1_datasets.py configurations/urls.py tests/test_dataset_api.py
git commit -m "feat: 스냅샷 zip 을 이어받기로 내려주고 받기 시작을 감사 로그에 남긴다"
```

---

### Task 5: 외부 연동 키 관리 화면

**Files:**
- Create: `app/views/system/integration_client.py`
- Create: `app/templates/system/integration_client.html`
- Modify: `domain/gui.py` (화면 정의 `gui_dc`, API 매핑 `m`)
- Modify: `domain/management/commands/seed_initial.py` (`MENU_TREE` 시스템 관리)
- Modify: `app/views/system/menus.py` (`PLATFORM_ADMIN_MENU_CODES`)
- Modify: `scripts/verify_buttons.py` (`SCREENS`)
- Test: `tests/test_integration_client.py`, `tests/e2e/test_integration_client.py`

**Interfaces:**
- Consumes: `IntegrationClient`, `user_is_platform_admin(user)`
- Produces: `/api/system/integration_client?action=list|save|reissue_key|delete`, 화면 `wm_integration_client`

- [ ] **Step 1: 실패하는 단위 테스트** — `tests/test_integration_client.py`

```python
"""외부 연동 키 관리 — 발급 키는 응답에서 한 번만, 저장은 해시만. 플랫폼 관리자 전용."""
import hashlib
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from app.views.system.integration_client import integration_client
from domain.models.vision import IntegrationClient
from domain.tenancy import reset_tenant_cache


class IntegrationClientTest(TestCase):
    def setUp(self):
        reset_tenant_cache()
        self.admin = User.objects.create_superuser('ic-admin', password='x')

    def call(self, action, user=None, **posparam):
        return integration_client(SimpleNamespace(request=SimpleNamespace(user=user or self.admin),
                                                  gparam={'action': action}, posparam=posparam))

    def test_등록하면_키를_한_번_주고_해시만_저장한다(self):
        result = self.call('save', client_id='WEZARD', name='Wezard')
        row = IntegrationClient.objects.get(client_id='WEZARD')
        self.assertEqual(row.api_key_hash, hashlib.sha256(result['api_key'].encode()).hexdigest())
        self.assertNotIn(result['api_key'], str(self.call('list')))

    def test_재발급하면_기존_키는_무효다(self):
        first = self.call('save', client_id='WEZARD', name='Wezard')['api_key']
        row = IntegrationClient.objects.get()
        second = self.call('reissue_key', id=row.id)['api_key']
        row.refresh_from_db()
        self.assertNotEqual(first, second)
        self.assertEqual(row.api_key_hash, hashlib.sha256(second.encode()).hexdigest())

    def test_수정은_이름과_사용_여부만_바꾼다(self):
        self.call('save', client_id='WEZARD', name='Wezard')
        row = IntegrationClient.objects.get()
        self.call('save', id=row.id, client_id='OTHER', name='바뀐 이름', active='0')
        row.refresh_from_db()
        self.assertEqual((row.client_id, row.name, row.active), ('WEZARD', '바뀐 이름', False))

    def test_같은_Client_ID_는_거절한다(self):
        self.call('save', client_id='WEZARD', name='Wezard')
        self.assertEqual(self.call('save', client_id='WEZARD', name='둘째')['success'], False)

    def test_삭제한다(self):
        self.call('save', client_id='WEZARD', name='Wezard')
        self.assertTrue(self.call('delete', id=IntegrationClient.objects.get().id)['success'])
        self.assertFalse(IntegrationClient.objects.exists())

    def test_플랫폼_관리자가_아니면_거부한다(self):
        user = User.objects.create_user('ic-user', password='x')
        with self.assertRaises(PermissionDenied):
            self.call('list', user=user)
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python manage.py test tests.test_integration_client --settings=configurations.test_settings`
Expected: `ModuleNotFoundError: No module named 'app.views.system.integration_client'`

- [ ] **Step 3: API 모듈** — `app/views/system/integration_client.py`

```python
"""외부 연동 키 관리(`wm_integration_client`) — 학습 플랫폼(Wezard)이 스냅샷을 받아 가는 키.

비전검사 클라이언트 관리(`vision/client.py`)와 같은 모양이다. 서비스 계정은 만들지 않는다 — 데이터를 올리지 않는다.
학습 데이터 전체를 여는 키라 플랫폼 관리자만 다룬다(DECISIONS DEC-029). API 는 docs/Wezard/maip-api.md.
"""
import hashlib
import secrets

from django.core.exceptions import PermissionDenied

from domain.models.vision import IntegrationClient
from domain.services.account import user_is_platform_admin

NOT_FOUND = {'success': False, 'message': '연동 키를 찾을 수 없습니다.'}


def integration_client(context):
    """api/system/integration_client"""
    if not user_is_platform_admin(context.request.user):
        raise PermissionDenied('플랫폼 관리자만 사용할 수 있습니다.')
    action = context.gparam.get('action', 'list')
    posparam = context.posparam
    if action == 'list':
        return [_row(row) for row in IntegrationClient.objects.order_by('client_id')]
    if action == 'save':
        return _save(posparam)
    if action == 'reissue_key':
        return _reissue_key(posparam.get('id'))
    if action == 'delete':
        deleted, _ = IntegrationClient.objects.filter(id=posparam.get('id')).delete()
        return {'success': True, 'message': '삭제되었습니다.'} if deleted else NOT_FOUND
    return {'success': False, 'message': '지원하지 않는 기능입니다.'}


def _row(row):
    return {'id': row.id, 'client_id': row.client_id, 'name': row.name, 'active': row.active,
            'last_seen_at': row.last_seen_at.strftime('%Y-%m-%d %H:%M:%S') if row.last_seen_at else '',
            'created_at': row.created_at.strftime('%Y-%m-%d %H:%M:%S')}


def _new_key():
    """(원문, 해시). 원문은 발급 응답에서 한 번만 나간다."""
    api_key = secrets.token_urlsafe(32)
    return api_key, hashlib.sha256(api_key.encode('utf-8')).hexdigest()


def _save(posparam):
    client_id = (posparam.get('client_id') or '').strip()
    name = (posparam.get('name') or '').strip()
    if not client_id or not name:
        return {'success': False, 'message': 'Client ID 와 이름을 입력해 주세요.'}
    if len(client_id) > 50 or len(name) > 100:
        return {'success': False, 'message': 'Client ID 는 50자, 이름은 100자 이하여야 합니다.'}
    active = posparam.get('active') not in ('0', 'false', 'False')

    if posparam.get('id'):
        row = IntegrationClient.objects.filter(id=posparam['id']).first()
        if row is None:
            return NOT_FOUND
        row.name, row.active = name, active
        row.save(update_fields=['name', 'active', 'updated_at'])
        return {'success': True, 'id': row.id}

    if IntegrationClient.objects.filter(client_id=client_id).exists():
        return {'success': False, 'message': '이미 등록된 Client ID 입니다.'}
    api_key, api_key_hash = _new_key()
    row = IntegrationClient.objects.create(client_id=client_id, name=name, active=active,
                                           api_key_hash=api_key_hash)
    return {'success': True, 'id': row.id, 'api_key': api_key,
            'message': 'API Key 는 지금만 확인할 수 있습니다. 안전한 곳에 보관해 주세요.'}


def _reissue_key(row_id):
    row = IntegrationClient.objects.filter(id=row_id).first()
    if row is None:
        return NOT_FOUND
    api_key, row.api_key_hash = _new_key()
    row.save(update_fields=['api_key_hash', 'updated_at'])
    return {'success': True, 'api_key': api_key,
            'message': '기존 키는 즉시 무효가 됩니다. Wezard 설정의 키를 바꿔야 합니다.'}
```

Run: `.venv/bin/python manage.py test tests.test_integration_client --settings=configurations.test_settings` → OK

- [ ] **Step 4: 화면·메뉴 등록**

`domain/gui.py` — 시스템 화면 정의 근처(`gui_dc['wm_system_log']` 아래):

```python
        # 학습 플랫폼(Wezard) 스냅샷 API 키. 플랫폼 관리자 전용(DECISIONS DEC-029).
        gui_dc['wm_integration_client'] = cls.gui_item('외부 연동 키', 'system/integration_client.html')
```

API 매핑(`m['system/systemlog']` 아래): `m['system/integration_client'] = ['wm_integration_client']`

`domain/management/commands/seed_initial.py` `MENU_TREE` 시스템 관리 목록의 `('wm_data_item', '검사항목 관리'),` 아래: `('wm_integration_client', '외부 연동 키'),`. 위 주석 "플랫폼 관리자 전용(...)" 을 두 메뉴에 걸리게 그대로 둔다.

`app/views/system/menus.py`: `PLATFORM_ADMIN_MENU_CODES = frozenset({'wm_data_item', 'wm_integration_client'})` 과 위 주석을 "플랫폼 관리자 전용 화면(검사항목 관리·외부 연동 키)" 으로.

`scripts/verify_buttons.py` `SCREENS` 에 `'wm_integration_client'` 추가(시스템 화면들 옆).

- [ ] **Step 5: 화면** — `app/templates/system/integration_client.html`

`app/templates/vision/client.html` 을 복사해 아래만 바꾼다(나머지 구조·클래스·DetailForm 사용은 그대로 — UI_GUIDE §4 를 따르는 화면이다):

- 제목·`data-labelCd`: `외부 연동 키`
- `#screenDescription`: `학습 플랫폼(Wezard)이 스냅샷을 받아 가는 API Key를 발급하고 사용 여부를 관리합니다.`
- 목록 제목: `연동 키 목록`, 그리드 `name` 열 머리말: `연동 이름`, 상세의 `name` 라벨: `연동 이름`
- `#btnPackages` 버튼, `#clientPackageModal` 모달, `openPackages()` 와 그 클릭 연결을 지운다
- 등록 모달 id·제목: `clientCreateModal` 은 그대로 두고 제목만 `연동 키 등록`. `#createClientId` 의 `maxlength="50"`
- `/api/vision/client` 네 곳 → `/api/system/integration_client`
- 삭제 확인: `"'" + row.client_id + "' 연동 키를 삭제하시겠습니까? 이 키로는 더 이상 스냅샷을 받을 수 없으며 되돌릴 수 없습니다."`
- 재발급 확인: `'기존 키는 즉시 무효가 됩니다. Wezard 설정의 키도 바꿔야 합니다. 계속하시겠습니까?'`
- 주석 `// 배포본 zip 목록 …` 블록 삭제

- [ ] **Step 6: e2e** — `tests/e2e/test_integration_client.py`

```python
"""외부 연동 키 화면 — 등록하면 키 모달이 한 번 뜨고, 목록에 남고, 지우면 사라진다.

테스트가 만든 `E2E-IC-` 키만 고치고 끝나면 지운다.
"""
import time

from tests.e2e.conftest import login
from tests.e2e.test_crud import mes
from tests.e2e.test_write_paths import confirm_ok, open_gui

API = '/api/system/integration_client'


def keys(page):
    return {row['client_id']: row['id'] for row in mes(page, f'{API}?action=list')
            if row['client_id'].startswith('E2E-IC-')}


def test_등록하면_키를_한_번_보이고_삭제한다(page, base_url, admin_password):
    login(page, base_url, 'admin', admin_password)
    open_gui(page, base_url, 'wm_integration_client')
    client_id = f'E2E-IC-{int(time.time() * 1000)}'
    try:
        page.click('#btnNew')
        page.fill('#createClientId', client_id)
        page.fill('#createName', client_id)
        page.click('#btnCreateClient')
        page.wait_for_selector('#apiKeyModal.show')
        assert len(page.input_value('#issuedKey')) >= 40
        page.click('#apiKeyModal .btn-close')
        page.get_by_text(client_id, exact=True).click()
        page.click('#btnDelete')
        confirm_ok(page)
        page.wait_for_timeout(800)
        assert client_id not in keys(page)
    finally:
        for row_id in keys(page).values():
            mes(page, f'{API}?action=delete', {'id': row_id})
```

`confirm_ok`·`mes`·`open_gui` 는 기존 헬퍼다 — 시그니처는 `tests/e2e/test_write_paths.py`·`test_crud.py` 에서 확인하고 맞춘다. `tests/e2e/test_workflow.py` 의 화면 목록(`('wm_vis_client', '클라이언트 관리')` 가 있는 리스트)에 `('wm_integration_client', '외부 연동 키')` 를 더한다.

- [ ] **Step 7: 개발 DB 메뉴 반영과 확인** (실제 DB 를 바꾼다 — 실행 전 사용자 확인)

Run: `.venv/bin/python manage.py migrate` → `Applying domain.0002_integration_client_export_checksum... OK`
Run: `.venv/bin/python manage.py seed_initial` (비밀번호 없이 — 메뉴·권한만 갱신, 멱등)
Run: `.venv/bin/python scripts/verify_menu.py && .venv/bin/python scripts/verify_permission_map.py` → PASS
서버(127.0.0.1:8123)가 떠 있는 상태에서: `.venv/bin/python -m pytest tests/e2e/test_integration_client.py tests/e2e/test_workflow.py -q` → passed, `.venv/bin/python scripts/verify_buttons.py` → PASS

- [ ] **Step 8: 커밋**

```bash
git add app/views/system/integration_client.py app/templates/system/integration_client.html domain/gui.py \
  domain/management/commands/seed_initial.py app/views/system/menus.py scripts/verify_buttons.py \
  tests/test_integration_client.py tests/e2e/test_integration_client.py tests/e2e/test_workflow.py
git commit -m "feat: 플랫폼 관리자가 외부 연동 키를 발급·재발급·삭제하는 화면을 더한다"
```

---

### Task 6: 정본 문서 `docs/Wezard/maip-api.md` 와 현행 문서 갱신

**Files:**
- Create: `docs/Wezard/maip-api.md`
- Modify: `docs/README.md`, `docs/client/SERVER_API_CONTRACT.md`, `docs/DECISIONS.md`, `docs/ARCHITECTURE.md`, `docs/FEATURES.md`, `docs/DATA_MODEL.md`, `docs/STATUS.md`, `AGENTS.md`

독자는 **Wezard 개발을 맡은 AI 에이전트**다. 이 문서만 읽고 코드를 짤 수 있어야 하므로 서버 내부(테이블·모듈 이름)는 쓰지 않고, 요청·응답은 **Task 7 에서 실제로 받은 응답**으로 채운다(Step 2).

- [ ] **Step 1: 문서 작성** — 절 구성(이 순서, 각 절 내용 필수)

1. **개요** — 무엇을 받는가(검수 승인 이미지로 고정한 스냅샷 zip), 스냅샷은 불변, 검사 유형별 고정 형식 표(분류 → ImageFolder `IMAGEFOLDER` / 객체 탐지 → COCO `COCO` / 이상 탐지 → MVTec AD `MVTEC`). 옛 스냅샷은 `YOLO` 등 다른 `format` 값을 가질 수 있다 — 모르는 형식은 건너뛴다.
2. **연결** — base URL(`http://<서버>:8123` 개발 / 운영 주소는 운영자에게 받는다), 키 발급 절차(플랫폼 관리자가 "시스템 관리 > 외부 연동 키"에서 발급, 키는 한 번만 보임), 헤더 `X-Client-ID`·`X-API-Key`, 키를 코드·로그에 남기지 않는다.
3. **공통 규약** — 봉투(`{"data"}` / `{"error":{"code","message","retryable"}}`), 시각 UTC `Z`, 모두 GET.
4. **`GET /api/v1/datasets/snapshots`** — 쿼리 표(`item_code`·`task_type`·`status`·`created_after`·`page`·`page_size` 기본/최대), 응답 전체 예, 필드 표(특히 `export` 가 `null` 일 수 있음, `download_url` 은 `COMPLETED` 일 때만, `sha256`·`size_bytes` 는 예전 스냅샷이면 목록에서 `null` — 정보 API 를 부르면 채워진다).
5. **`GET /api/v1/datasets/snapshots/{id}`** — 응답 예, `statistics` 필드 설명(`class_distribution` 은 `[[이름, 수], ...]`, 이상 탐지는 `normal_image_count`·`anomaly_image_count`·`anomaly_type_distribution`, 분류는 `class_image_distribution`·`imbalance_warning`), `export.error_message`.
6. **`GET /api/v1/datasets/snapshots/{id}/download`** — 200/206, `Range: bytes=N-` 이어받기, `Content-Disposition` 파일명 규칙, 받은 뒤 정보 API 의 `sha256` 과 대조. `curl` 예: `curl -fSL -C - -H "X-Client-ID: …" -H "X-API-Key: …" -o s.zip <url>` + `sha256sum s.zip`.
7. **오류 코드와 재시도** — 설계 문서의 오류 표 그대로 + 401 은 재시도하지 말고 키를 확인, 409 `EXPORT_NOT_READY` 는 1분 이상 간격으로 다시, 5xx `INTERNAL_ERROR` 는 `retryable=true`.
8. **zip 구조** — 형식별 트리와 파일 설명. Task 7 Step 2 에서 실제 zip 을 `unzip -l` 해 확인한 그대로 쓴다. 공통 `manifest.json` 필드(`export_version`·`item_id`·`task_type`·`dataset_version`·`format`·통계), MVTec 의 `metadata.json`(`images[]`: `image_id`·`file_name`·`is_anomaly`·`anomaly_type`·`mask_available`), COCO 의 `annotations.json`, ImageFolder 의 클래스 폴더.
9. **권장 수집 절차** — ① `status=COMPLETED&created_after=<마지막 수집 시각>` 로 목록 ② 새 `id` 마다 정보 → `sha256` 기억 ③ 받기(끊기면 Range 로 이어받기) ④ SHA-256 대조, 다르면 지우고 처음부터 ⑤ `(id, sha256)` 를 수집 기록으로 남겨 중복 수집 방지 ⑥ `format` 별 로더로 데이터셋 생성. 의사코드(파이썬, `requests`) 한 덩어리.
10. **변경 이력** — `2026-10-12 최초 작성`. "응답 모양·오류 코드·경로를 바꾸면 이 문서를 먼저 고쳐 전달한다".

- [ ] **Step 2: 현행 문서 갱신** (같은 내용을 반복하지 않고 링크한다)

- `docs/README.md`: "비전검사 클라이언트와 주고받는 문서" 표 아래에 절 `## 학습 플랫폼(Wezard)과 주고받는 문서 (\`Wezard/\`)` — 표 1행: `[Wezard/maip-api.md](Wezard/maip-api.md) | 서버(우리) | 스냅샷 목록·정보·다운로드 API 정본` + "바꾸면 함께 고치고 전달한다" 한 줄.
- `docs/client/SERVER_API_CONTRACT.md` §1 "제공하지 않는 것" 끝에: `` `/api/v1/datasets/...` 는 학습 플랫폼(Wezard)용이다. 비전검사 클라이언트 키로는 401 이며 이 계약에 들지 않는다(docs/Wezard/maip-api.md). ``
- `docs/DECISIONS.md` §6 표에 `DEC-029` 행: 결정 = 학습 플랫폼 스냅샷 API 를 `/api/v1/datasets` 에 두고 전용 키(`IntegrationClient`, 플랫폼 관리자 화면 발급, 전체 검사항목)로 연다. 정본 `docs/Wezard/maip-api.md` / 이유 = 현장 PC 키가 새도 학습 데이터 전체가 나가지 않게, `/api/v1` 의 인증·봉투를 재사용해 클라이언트가 같은 방식으로 다룬다 / (사용자 결정 2026-10-12).
- `docs/ARCHITECTURE.md` API 규약 표(`/api/v1/...` 행 아래)에 `/api/v1/datasets/...` 행: 학습 플랫폼 스냅샷 API, 호출자 Wezard, 인증 `X-Client-ID`+`X-API-Key`(`IntegrationClient`), 구현 `app/views/api_v1_datasets.py`. "고칠 때 보는 곳" 표에도 한 줄.
- `docs/FEATURES.md`: 메뉴 트리 시스템 관리에 "외부 연동 키(플랫폼 관리자)", 화면 기능 한 줄, 스냅샷 절(§4.6)에 "Wezard 가 API 로 받아 간다 → Wezard/maip-api.md".
- `docs/DATA_MODEL.md`: `integration_client` 행(조직 소유 아님·RLS 대상 아님), `ExportJob` 행에 `file_size`·`file_sha256`, 마이그레이션 목록에 `0002`.
- `docs/STATUS.md`: 되는 것에 "학습 플랫폼 스냅샷 API(목록·정보·이어받기 다운로드)", 남은 일에 "웹훅(완료 알림) — 필요해지면".
- `AGENTS.md` [2] 표에 `/api/v1/datasets/...` 행(호출자 Wezard, 인증 `IntegrationClient` 키, 정본 `docs/Wezard/maip-api.md`) + 불릿 "`/api/v1/datasets` 응답·오류·경로를 바꾸면 `docs/Wezard/maip-api.md` 를 함께 고친다".

- [ ] **Step 3: 확인**

Run: `.venv/bin/python scripts/verify_links.py && .venv/bin/python scripts/verify_naming.py && .venv/bin/python scripts/verify_korean_only.py` → PASS

- [ ] **Step 4: 커밋**

```bash
git add docs/Wezard/maip-api.md docs/README.md docs/client/SERVER_API_CONTRACT.md docs/DECISIONS.md \
  docs/ARCHITECTURE.md docs/FEATURES.md docs/DATA_MODEL.md docs/STATUS.md AGENTS.md
git commit -m "docs: Wezard 스냅샷 API 정본 문서를 두고 현행 문서에 연결한다"
```

---

### Task 7: 전체 검증과 실측

- [ ] **Step 1: 전체 테스트·검증 스크립트**

```bash
.venv/bin/python manage.py test tests --settings=configurations.test_settings
node scripts/verify_screen_js.js
for s in verify_menu verify_permission_map verify_response_keys verify_tokens verify_korean_only verify_links verify_naming; do .venv/bin/python scripts/$s.py || echo "FAIL $s"; done
# 서버 필요
.venv/bin/python scripts/verify_modals.py
.venv/bin/python scripts/verify_buttons.py
.venv/bin/python -m pytest tests/e2e -q
```

Expected: 단위 OK(273 + 새 테스트), e2e 전부 passed, 스크립트 전부 PASS. 실패하면 고치고 다시.

- [ ] **Step 2: 실측(개발 서버·워커)** — 화면에서 `E2E-WEZARD` 키를 발급하고(끝나면 삭제), COMPLETED 스냅샷이 없으면 FAN-PANEL 에서 하나 만든 뒤 `run_worker` 로 완료시킨다.

```bash
H=(-H "X-Client-ID: E2E-WEZARD" -H "X-API-Key: $KEY")   # 키는 셸 변수로만. 파일·로그에 남기지 않는다
curl -s "${H[@]}" "http://127.0.0.1:8123/api/v1/datasets/snapshots?status=COMPLETED" | python -m json.tool
curl -s "${H[@]}" "http://127.0.0.1:8123/api/v1/datasets/snapshots/<id>" | python -m json.tool
curl -fSL "${H[@]}" -r 0-999 -o s.zip "http://127.0.0.1:8123/api/v1/datasets/snapshots/<id>/download"
curl -fSL -C - "${H[@]}" -o s.zip "http://127.0.0.1:8123/api/v1/datasets/snapshots/<id>/download"
sha256sum s.zip; unzip -l s.zip
```

확인: 정보의 `sha256` == `sha256sum`, 이어받은 파일이 온전, 감사 로그 1건(`SNAPSHOT_DOWNLOADED`). 받은 응답과 `unzip -l` 결과로 `maip-api.md` 의 예시를 실제 값으로 맞추고(키·내부 경로 제외) 문서 커밋을 보완한다. 실측 산출물(`s.zip`)은 scratchpad 에 두고 저장소에 넣지 않는다. 끝나면 `E2E-WEZARD` 키를 화면에서 삭제한다.

- [ ] **Step 3: 마무리** — superpowers:finishing-a-development-branch 로 main 병합 여부를 사용자에게 묻는다. push 는 하지 않는다.
