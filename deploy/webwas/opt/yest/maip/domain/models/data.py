"""데이터 관리 도메인 모델.

통합하며 정한 것 둘을 적어 둔다.

1. **검사항목 단일화** (docs/DECISIONS.md O-8)
   데이터 관리의 과제(Project)와 비전 검사의 검사항목을 하나로 합쳤다.
   `InspectionItem`(테이블 `vision_data_item`)이 **검사항목이자 데이터 저장소**다.
   vision 의 공정·제품 계층은 만들지 않는다.

2. **사용자·권한은 MES 것을 쓴다**
   데이터 관리 쪽 `UserProfile`/`UserGroup`/`UserGroupMenu`/`AuthenticationLog`
   는 두지 않는다. `domain/services/account.py` 의 함수 5종이 MES 모델 위에서
   같은 계약을 제공한다.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from domain.storage import (
    export_upload_path,
    item_cover_upload_path,
    item_image_thumbnail_upload_path,
    item_image_upload_path,
)


# --------------------------------------------------------------------------
# 테넌시
# --------------------------------------------------------------------------

class Tenant(models.Model):
    """조직. 이번 범위에서는 **한 행만** 존재한다(DEC-004 B).

    테이블과 RLS 정책을 그대로 두는 이유: 나중에 다중 조직이 필요해졌을 때
    스키마 변경 없이 제약만 풀면 되고, 지금 걷어내면 데이터 관리 서비스 46개를
    전부 뜯어고쳐야 한다.
    """

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', '활성'
        SUSPENDED = 'SUSPENDED', '일시 중지'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField('조직명', max_length=140)
    description = models.TextField('설명', blank=True)
    status = models.CharField('상태', max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vision_data_tenant'
        verbose_name = '조직'
        ordering = ['name']

    def __str__(self):
        return self.name


class TenantScopedQuerySet(models.QuerySet):
    def for_tenant(self, tenant):
        return self.filter(tenant=tenant)


class TenantScopedManager(models.Manager.from_queryset(TenantScopedQuerySet)):
    pass


class TenantOwnedModel(models.Model):
    tenant = models.ForeignKey(Tenant, related_name='%(class)s_records', on_delete=models.PROTECT)
    objects = TenantScopedManager()

    class Meta:
        abstract = True


class TenantMembership(TenantOwnedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='tenant_memberships',
                             on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vision_data_tenantmembership'
        verbose_name = '조직 소속'
        constraints = [models.UniqueConstraint(fields=['tenant', 'user'],
                                               name='unique_tenant_membership')]
        indexes = [
            models.Index(fields=['tenant', 'is_active', 'user']),
            models.Index(fields=['user', 'is_active', 'tenant']),
        ]


# --------------------------------------------------------------------------
# 검사항목 (= 데이터 저장소)
# --------------------------------------------------------------------------

class InspectionCategory(TenantOwnedModel):
    """검사 분류. 대분류(parent 없음, 양식 구분) › 중분류(대분류 아래, 디지털 양식 코드 매핑) 두 단계다.

    비전검사항목은 중분류 하나에 속한다(`InspectionItem.category`). 3단계 금지·양식 검증은
    서비스(domain/services/data/category.py)가 한다(설계 2026-10-21 §2-1).
    """

    class FormType(models.TextChoices):
        INCOMING = 'INCOMING', '수입'
        OUTGOING = 'OUTGOING', '품질'

    parent = models.ForeignKey('self', related_name='children', null=True, blank=True, on_delete=models.PROTECT)
    name = models.CharField('분류 이름', max_length=100)
    # 대분류만 — 이 대분류의 중분류에 매핑할 수 있는 양식 구분(dig_form.FormType)
    form_type = models.CharField('양식 구분', max_length=10, choices=FormType.choices, blank=True, default='')
    # 중분류만 — 매핑한 디지털 양식 코드(dig_form.Code, 버전 무관). 빈 값 = 매핑 없음
    form_code = models.CharField('매핑 양식 코드', max_length=20, blank=True, default='')
    sort_order = models.IntegerField('순서', default=0)
    description = models.TextField('설명', blank=True)

    class Meta:
        db_table = 'vision_data_category'
        verbose_name = '검사 분류'
        ordering = ['sort_order', 'name']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'name'], condition=Q(parent__isnull=True),
                                    name='uq_category_major_name'),
            models.UniqueConstraint(fields=['tenant', 'parent', 'name'], condition=Q(parent__isnull=False),
                                    name='uq_category_minor_name'),
            models.UniqueConstraint(fields=['tenant', 'form_code'], condition=~Q(form_code=''),
                                    name='uq_category_form_code'),
            models.CheckConstraint(condition=(Q(parent__isnull=True) & Q(form_code=''))
                                   | (Q(parent__isnull=False) & Q(form_type='')),
                                   name='ck_category_level_fields'),
        ]

    def __str__(self):
        return self.name


class InspectionItem(TenantOwnedModel):
    """검사항목. 비전 검사의 대상이자 데이터 저장소다.

    Client가 카탈로그에서 고르는 대상이고, 그 검사항목으로 찍은 사진이 여기에
    쌓인다. 데이터셋·라벨 클래스·작업자 배정·품질·Export 가 전부 여기 매달린다.
    """

    class TaskType(models.TextChoices):
        OBJECT_DETECTION = 'OBJECT_DETECTION', '객체 탐지'
        CLASSIFICATION = 'CLASSIFICATION', '분류'
        ANOMALY_DETECTION = 'ANOMALY_DETECTION', '이상 탐지'
        # 클라이언트가 잰 치수를 받아 측정점 규격으로 판정한다. 라벨 클래스·모델 매핑을 쓰지 않는다.
        MEASUREMENT = 'MEASUREMENT', '치수 측정'

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', '사용'
        PAUSED = 'PAUSED', '중지'
        DELETION_PENDING = 'DELETION_PENDING', '삭제 승인 대기'

    class CaptureMethod(models.TextChoices):
        # 고정 거치대 PC 의 비전검사 클라이언트가 찍는다 — 카탈로그(/api/v1)에 나오는 것은 이것뿐이다
        RIG = 'RIG', '고정 거치대'
        # 태블릿으로 디지털 양식 "사진 넣기"로 찍는다 — 거치대 클라이언트는 보지 않는다
        TABLET = 'TABLET', '태블릿'

    # Client `InspectionType`. 분류·치수 측정은 Client 가 카탈로그에 `include=classification`·`measurement` 를
    # 줄 때만 내보낸다(DEC-031).
    CLIENT_INSPECTION_TYPE = {
        TaskType.CLASSIFICATION: 'CLASSIFICATION',
        TaskType.OBJECT_DETECTION: 'DETECTION',
        TaskType.ANOMALY_DETECTION: 'ANOMALY',
        TaskType.MEASUREMENT: 'MEASUREMENT',
    }

    code = models.CharField('비전검사항목코드', max_length=50, unique=True)
    name = models.CharField('비전검사항목명', max_length=140)
    task_type = models.CharField('유형', max_length=32, choices=TaskType.choices,
                                 default=TaskType.OBJECT_DETECTION)
    status = models.CharField('상태', max_length=16, choices=Status.choices, default=Status.ACTIVE)
    # db_default 는 이 컬럼을 모르는 코드가 넣어도 되게 한다(공유 개발 DB)
    capture_method = models.CharField('촬영 방식', max_length=16, choices=CaptureMethod.choices,
                                      default=CaptureMethod.RIG, db_default=CaptureMethod.RIG)
    description = models.TextField('설명', blank=True)
    # 소속 중분류(대분류가 아니라 중분류만 가리킨다). null = 미분류
    category = models.ForeignKey(InspectionCategory, related_name='items', null=True, blank=True,
                                 on_delete=models.PROTECT, verbose_name='검사 분류')
    cover_image = models.ImageField('대표 이미지', upload_to=item_cover_upload_path,
                                    null=True, blank=True)
    display_order = models.IntegerField('표시 순서', default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='created_items',
                                   null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vision_data_item'
        verbose_name = '비전검사항목'
        ordering = ['display_order', 'name']
        indexes = [
            models.Index(fields=['tenant', '-updated_at']),
            models.Index(fields=['tenant', 'status', 'display_order']),
        ]

    def __str__(self):
        return f'{self.code} · {self.name}'

    @property
    def client_inspection_type(self):
        """Client 에 내보내는 유형(`CLASSIFICATION`·`DETECTION`·`ANOMALY`)."""
        return self.CLIENT_INSPECTION_TYPE.get(self.task_type)


class ItemDeletionRequest(TenantOwnedModel):
    """검사항목 삭제 승인. 삭제는 데이터·라벨까지 지우므로 승인 절차를 둔다."""

    class Status(models.TextChoices):
        REQUESTED = 'REQUESTED', '승인 대기'
        APPROVED = 'APPROVED', '승인됨'
        REJECTED = 'REJECTED', '반려됨'
        CANCELED = 'CANCELED', '취소됨'

    item = models.ForeignKey(InspectionItem, related_name='deletion_requests',
                             null=True, blank=True, on_delete=models.SET_NULL)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='item_deletion_requests',
                                     null=True, blank=True, on_delete=models.SET_NULL)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='reviewed_item_deletions',
                                    null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REQUESTED)
    # 승인하면 item 이 끊기므로(SET_NULL) 무엇을 지웠는지 요청할 때 적어 둔다.
    # db_default 는 이 컬럼을 모르는 코드가 넣어도 되게 한다(공유 개발 DB).
    item_code = models.CharField('비전검사항목 코드', max_length=50, blank=True, default='', db_default='')
    item_name = models.CharField('비전검사항목명', max_length=140, blank=True, default='', db_default='')
    reason = models.TextField('사유', blank=True)
    review_note = models.TextField('검토 의견', blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'vision_data_itemdeletionrequest'
        verbose_name = '비전검사항목 삭제 요청'
        ordering = ['-requested_at', '-id']
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'item', 'status']),
        ]


class LabelClass(TenantOwnedModel):
    class AnnotationShape(models.TextChoices):
        BBOX = 'BBOX', 'Bounding box'
        POLYGON = 'POLYGON', 'Polygon mask'

    item = models.ForeignKey(InspectionItem, related_name='label_classes', on_delete=models.CASCADE)
    name = models.CharField('클래스명', max_length=64)
    display_name_ko = models.CharField('표시명', max_length=64)
    color = models.CharField('색상', max_length=7, default='#16A5A3')
    is_defect = models.BooleanField('불량 여부', default=True)
    sort_order = models.PositiveSmallIntegerField('순서', default=0)
    annotation_shape = models.CharField('도형', max_length=16, choices=AnnotationShape.choices,
                                        default=AnnotationShape.BBOX)

    class Meta:
        db_table = 'vision_data_labelclass'
        verbose_name = '라벨 클래스'
        constraints = [models.UniqueConstraint(fields=['tenant', 'item', 'name'],
                                               name='unique_label_class_in_tenant_item')]
        indexes = [models.Index(fields=['tenant', 'item', 'sort_order'])]
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f'{self.item.name} · {self.display_name_ko}'


class MeasurementPoint(TenantOwnedModel):
    """치수 측정 비전검사항목의 측정점. 클라이언트가 이 코드로 측정값을 돌려보내고 서버가 하한·상한으로 판정한다."""

    item = models.ForeignKey(InspectionItem, related_name='measurement_points', on_delete=models.CASCADE)
    code = models.CharField('측정점 코드', max_length=20)
    name = models.CharField('측정점 이름', max_length=100)
    nominal = models.DecimalField('기준값', max_digits=18, decimal_places=3)
    # 합격 범위(경계 포함). 기준값±공차를 풀어 저장한다.
    lower = models.DecimalField('하한', max_digits=18, decimal_places=3)
    upper = models.DecimalField('상한', max_digits=18, decimal_places=3)
    unit = models.CharField('단위', max_length=10, default='mm')
    description = models.TextField('측정 방법', blank=True)
    sort_order = models.PositiveSmallIntegerField('순서', default=0)

    class Meta:
        db_table = 'vision_data_measurementpoint'
        verbose_name = '측정점'
        ordering = ['sort_order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'item', 'code'], name='uq_measurement_point_code'),
            models.CheckConstraint(condition=Q(lower__lte=F('nominal')) & Q(nominal__lte=F('upper')),
                                   name='ck_measurement_point_range'),
        ]

    def __str__(self):
        return f'{self.item.code} · {self.code}'


class ActivityLog(TenantOwnedModel):
    item = models.ForeignKey(InspectionItem, related_name='activities',
                             null=True, blank=True, on_delete=models.CASCADE)
    event_type = models.CharField(max_length=48)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='audit_events',
                              on_delete=models.SET_NULL, null=True, blank=True)
    actor_name = models.CharField(max_length=80, default='일반 사용자')
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'vision_data_activitylog'
        verbose_name = '활동 이력'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', '-created_at']),
            models.Index(fields=['tenant', 'event_type']),
            models.Index(fields=['tenant', 'item', '-created_at']),
        ]


# --------------------------------------------------------------------------
# 데이터셋 · 이미지 · 어노테이션
# --------------------------------------------------------------------------

class Dataset(TenantOwnedModel):
    """검사항목 안의 이미지 묶음.

    **화면에 노출하지 않는 내부 컨테이너다**. 업로드는 검사항목 단위로
    하고 `get_or_create_upload_dataset()` 가 알아서 하나를 만든다. 사용자가
    인지하는 "데이터셋으로 묶기"는 `DatasetVersion`(불변 스냅샷) 쪽이다.
    """

    class Status(models.TextChoices):
        RAW = 'RAW', 'RAW · 수집됨'
        VALIDATED = 'VALIDATED', 'VALIDATED · 점검됨'
        LABELED = 'LABELED', 'LABELED · 라벨링됨'
        CURATED = 'CURATED', 'CURATED · 검수됨'
        EXPORTED = 'EXPORTED', 'EXPORTED · 내보냄'

    item = models.ForeignKey(InspectionItem, related_name='datasets', on_delete=models.CASCADE)
    name = models.CharField(max_length=160)
    version = models.CharField(max_length=32, default='v0.1')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RAW)
    source_type = models.CharField(max_length=32, default='DIGITAL_UPLOAD')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vision_data_dataset'
        verbose_name = '데이터셋'
        ordering = ['-updated_at', '-id']
        constraints = [models.UniqueConstraint(fields=['tenant', 'item', 'version'],
                                               name='unique_dataset_version_in_tenant_item')]
        indexes = [models.Index(fields=['tenant', 'item', '-updated_at'])]

    def __str__(self):
        return f'{self.item.name} · {self.name}'


class ImageAsset(TenantOwnedModel):
    class IngestionStatus(models.TextChoices):
        UPLOADING = 'UPLOADING', '업로드 중'
        VALIDATING = 'VALIDATING', '검증 중'
        READY = 'READY', '준비됨'
        REJECTED = 'REJECTED', '거부됨'

    class LabelStatus(models.TextChoices):
        UNLABELED = 'UNLABELED', '미작업'
        IN_PROGRESS = 'IN_PROGRESS', '작업중'
        SUBMITTED = 'SUBMITTED', '제출됨'
        REWORK = 'REWORK', '재작업 필요'
        APPROVED = 'APPROVED', '작업완료'

    class Status(models.TextChoices):
        UPLOADED = 'UPLOADED', '업로드됨'
        LABELED = 'LABELED', '라벨 저장됨'

    class Channel(models.TextChoices):
        CLIENT = 'CLIENT', '클라이언트'
        FILE = 'FILE', '파일 업로드'
        CAMERA = 'CAMERA', '카메라 촬영'
        FORM = 'FORM', '양식 사진 넣기'

    dataset = models.ForeignKey(Dataset, related_name='images', on_delete=models.CASCADE)
    storage_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    file = models.ImageField(upload_to=item_image_upload_path)
    thumbnail = models.ImageField(upload_to=item_image_thumbnail_upload_path,
                                  null=True, blank=True, editable=False)
    # 편집(회전·원근 보정·크롭·크기 조정) 전 원본. 편집한 적 없으면 비어 있다.
    original_file = models.ImageField(upload_to=item_image_upload_path,
                                      null=True, blank=True, editable=False)
    # 원본에 순서대로 적용한 편집 연산 목록.
    preprocess = models.JSONField(default=list, blank=True)
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=80)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    file_size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UPLOADED)
    ingestion_status = models.CharField(max_length=16, choices=IngestionStatus.choices,
                                        default=IngestionStatus.READY)
    label_status = models.CharField(max_length=16, choices=LabelStatus.choices,
                                    default=LabelStatus.UNLABELED)
    rework_reason = models.TextField(blank=True, default='')
    # 어느 검사에서 들어온 이미지인지. 사람이 화면에서 올린 것은 null이다.
    source_inspection_id = models.CharField('원 검사 ID', max_length=36, null=True, blank=True)
    # 어떻게·누가 들였는지(사용자 결정 2026-10-23). 옛 행은 Client 수신이면 CLIENT, 아니면 FILE, 등록자는 비어 있다
    channel = models.CharField('등록 경로', max_length=16, choices=Channel.choices, default=Channel.FILE, db_default=Channel.FILE)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='등록자', related_name='uploaded_images',
                                    null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vision_data_imageasset'
        verbose_name = '이미지'
        ordering = ['-created_at', '-id']
        # (tenant, dataset, sha256) unique 를 두지 않는다. Client 가 보낸 검사
        # 이미지는 같은 장면을 다시 찍는 일이 있어 중복을 허용해야 하므로
        # DB 제약 대신 서비스 계층에서 판단한다.
        indexes = [
            models.Index(fields=['tenant', 'dataset', 'label_status', '-updated_at', '-id'],
                         name='image_list_dataset_label_idx'),
            models.Index(fields=['tenant', 'ingestion_status', 'label_status', '-updated_at', '-id'],
                         name='image_queue_status_label_idx'),
            models.Index(fields=['tenant', 'dataset', 'sha256'], name='image_sha256_idx'),
            models.Index(fields=['source_inspection_id'], name='image_source_inspection_idx'),
        ]

    def __str__(self):
        return self.original_name


class Annotation(TenantOwnedModel):
    class GeometryType(models.TextChoices):
        NONE = 'NONE', '없음'
        BBOX = 'BBOX', 'Bounding box'
        POLYGON = 'POLYGON', 'Polygon'

    image = models.ForeignKey(ImageAsset, related_name='annotations', on_delete=models.CASCADE)
    label_class = models.ForeignKey(LabelClass, related_name='annotations',
                                    on_delete=models.PROTECT, null=True, blank=True)
    geometry_type = models.CharField(max_length=16, choices=GeometryType.choices,
                                     default=GeometryType.NONE)
    geometry = models.JSONField(null=True, blank=True)
    attributes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vision_data_annotation'
        verbose_name = '어노테이션'
        ordering = ['id']
        indexes = [models.Index(fields=['tenant', 'image', 'label_class'])]

    def __str__(self):
        label = self.label_class.display_name_ko if self.label_class else '정상'
        return f'{self.image.original_name} · {label}'


# --------------------------------------------------------------------------
# 라벨링 작업
# --------------------------------------------------------------------------

class LabelingTask(TenantOwnedModel):
    class Status(models.TextChoices):
        READY = 'READY', '대기'
        CLAIMED = 'CLAIMED', '할당됨'
        IN_PROGRESS = 'IN_PROGRESS', '작업중'
        SUBMITTED = 'SUBMITTED', '제출됨'

    item = models.ForeignKey(InspectionItem, related_name='labeling_tasks', on_delete=models.CASCADE)
    image = models.ForeignKey(ImageAsset, related_name='labeling_tasks', on_delete=models.CASCADE)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='labeling_tasks',
                                 null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.READY)
    lease_token = models.UUIDField(null=True, blank=True, editable=False)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_saved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vision_data_labelingtask'
        verbose_name = '라벨링 작업'
        ordering = ['created_at', 'id']
        constraints = [
            # 이미지 하나에 활성 작업은 하나뿐이다. 둘이 동시에 잡으면 서로의
            # 어노테이션을 덮어쓴다.
            models.UniqueConstraint(
                fields=['tenant', 'image'],
                condition=Q(status__in=['CLAIMED', 'IN_PROGRESS']),
                name='unique_active_labeling_task_per_image',
            )
        ]
        indexes = [
            models.Index(fields=['tenant', 'item', 'status']),
            models.Index(fields=['tenant', 'assignee', 'status']),
        ]


# --------------------------------------------------------------------------
# 스냅샷 · Export · 비동기 작업
# --------------------------------------------------------------------------

class DatasetVersion(TenantOwnedModel):
    """불변 스냅샷. 한 번 만들면 담긴 이미지를 지울 수 없다."""

    dataset = models.ForeignKey(Dataset, related_name='versions', on_delete=models.CASCADE)
    version_tag = models.CharField(max_length=32)
    manifest = models.JSONField(default=dict)
    is_immutable = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'vision_data_datasetversion'
        verbose_name = '스냅샷'
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['tenant', 'dataset', 'version_tag'],
                                               name='unique_dataset_version_per_tenant')]
        indexes = [models.Index(fields=['tenant', 'dataset', '-created_at'])]


class ExportJob(TenantOwnedModel):
    class Format(models.TextChoices):
        COCO = 'COCO', 'COCO Detection'
        YOLO = 'YOLO', 'YOLO Detection'
        IMAGEFOLDER = 'IMAGEFOLDER', 'ImageFolder'
        CSV = 'CSV', 'Classification CSV'
        CLASSIFICATION_JSON = 'CLASSIFICATION_JSON', 'Classification JSON'
        MVTEC = 'MVTEC', 'MVTec AD'
        IMAGE_MASK = 'IMAGE_MASK', 'Image + Mask'
        ANOMALY_JSON = 'ANOMALY_JSON', 'Anomaly JSON'
        # Wezard 업로드 형식(wezard-dataset/v1). 스냅샷마다 고정 형식과 함께 만들고 /api/v1/datasets 가 내려준다.
        WEZARD = 'WEZARD', 'Wezard 학습 데이터셋'

    class Status(models.TextChoices):
        QUEUED = 'QUEUED', '대기 중'
        RUNNING = 'RUNNING', '생성 중'
        COMPLETED = 'COMPLETED', '완료'
        FAILED = 'FAILED', '실패'

    dataset_version = models.ForeignKey(DatasetVersion, related_name='exports',
                                        on_delete=models.PROTECT)
    storage_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    format = models.CharField(max_length=24, choices=Format.choices, default=Format.COCO)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    file = models.FileField(upload_to=export_upload_path, null=True, blank=True, max_length=512)
    # 받은 쪽이 대조할 값. 예전 zip 은 비어 있고 처음 조회할 때 채운다(ExportService.ensure_checksum).
    file_size = models.BigIntegerField(null=True, blank=True)
    file_sha256 = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'vision_data_exportjob'
        verbose_name = 'Export'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['tenant', 'status', '-created_at'])]


class BackgroundJob(TenantOwnedModel):
    """워커가 집어 가는 작업 큐.

    `MIGRATION` 유형은 두지 않는다 — 검사 이미지는 접수 시점에 동기로 연계한다.
    """

    class JobType(models.TextChoices):
        EXPORT = 'EXPORT', 'Export 생성'

    class Status(models.TextChoices):
        QUEUED = 'QUEUED', '대기 중'
        RUNNING = 'RUNNING', '실행 중'
        COMPLETED = 'COMPLETED', '완료'
        FAILED = 'FAILED', '실패'

    job_type = models.CharField(max_length=16, choices=JobType.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    payload = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    error_message = models.TextField(blank=True)
    attempt_count = models.PositiveSmallIntegerField('시도 횟수', default=0)
    next_retry_at = models.DateTimeField('다음 재시도', null=True, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'vision_data_backgroundjob'
        verbose_name = '백그라운드 작업'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['tenant', 'status', 'created_at']),
            models.Index(fields=['status', 'next_retry_at']),
        ]
