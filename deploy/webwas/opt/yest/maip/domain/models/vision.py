"""비전 검사 도메인 모델.

이 도메인에 **두지 않은 것**이 다섯 가지다. 비전 검사를 다루는 통상의
설계와 다르므로 여기 적어 둔다 — 근거는 docs/DECISIONS.md 의 O-1·O-8 등이다.

- **공정·제품 테이블 없음**. 검사항목은 `vision_data_item` 하나다.
- **검사 이미지는 `ImageAsset` 이 보유**. `vision_inspection` 에
  `image_path` 컬럼을 두지 않고 FK 로 참조한다 — 파일이 두 벌 저장되지 않는다.
- **보존 정책·이관 이력 테이블 없음**.
- **모델 아티팩트는 문자열 경로만**. GPU Runtime 이 범위 밖이라
  파일 업로드·검증을 하지 않는다.
- **검사 전용 사용자 테이블 없음.** 관리자·작업자는 MES `auth_user` 를 쓴다.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from domain.models.data import ImageAsset, InspectionItem


class TimestampMixin(models.Model):
    """vision 원본의 `created_at`/`updated_at` 규약을 유지한다.

    MES `AbstractAuditModel`(`_created`/`_modified`)과 이름이 다르지만, 비전
    테이블은 vision 쪽 계약(API 응답 필드명)에 맞추는 편이 혼란이 적다.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class VisionClient(TimestampMixin):
    """현장 비전검사 클라이언트.

    API Key 는 **SHA-256 해시만** 저장한다. 발급 시 1회 노출하고 다시 볼 수 없다.
    """

    client_id = models.CharField('Client ID', max_length=50, unique=True)
    name = models.CharField('클라이언트 명', max_length=100)
    api_key_hash = models.CharField('API Key 해시', max_length=64)
    active = models.BooleanField('사용', default=True)
    last_seen_at = models.DateTimeField('최근 접속', null=True, blank=True)
    # 이 클라이언트가 보낸 이미지의 업로더로 기록할 계정.
    # 클라이언트 등록 시 자동 생성하며 웹 로그인은 불가능하다.
    service_account = models.OneToOneField(
        settings.AUTH_USER_MODEL, related_name='vision_client',
        null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        db_table = 'vision_client'
        verbose_name = '비전검사 클라이언트'
        ordering = ['client_id']

    def __str__(self):
        return f'{self.client_id} · {self.name}'


class IntegrationClient(TimestampMixin):
    """학습 플랫폼(Wezard) 같은 외부 시스템이 스냅샷을 받아 가는 키(DECISIONS DEC-029).

    VisionClient 와 테이블을 나눈다 — 현장 PC 키 하나가 새어도 학습 데이터 전체가 나가지 않게.
    API Key(`maip_…`)는 SHA-256 해시만 저장하고 해시로 연동처를 찾는다.
    발급은 `manage.py integration_key` — 원문은 그때 한 번만 보인다. `client_id` 는 연동처 이름표다.
    """

    client_id = models.CharField('Client ID', max_length=50, unique=True)
    name = models.CharField('연동 이름', max_length=100)
    api_key_hash = models.CharField('API Key 해시', max_length=64, unique=True)
    active = models.BooleanField('사용', default=True)
    last_seen_at = models.DateTimeField('최근 접속', null=True, blank=True)

    class Meta:
        db_table = 'integration_client'
        verbose_name = '외부 연동 키'
        ordering = ['client_id']

    def __str__(self):
        return f'{self.client_id} · {self.name}'


class VisionModel(TimestampMixin):
    """AI 모델 메타데이터.

    모델은 Wezard 가 소유하고, 여기 행은 매핑에 쓰는 이름표다(`version='latest'`).
    `artifact_path` 는 문자열일 뿐이고 파일 검증은 하지 않는다 — 검증 코드가
    `torch.load` 를 쓰기 때문이다.
    """

    class InspectionType(models.TextChoices):
        CLASSIFICATION = 'CLASSIFICATION', '분류'
        DETECTION = 'DETECTION', '객체 탐지'
        ANOMALY = 'ANOMALY', '이상 탐지'

    name = models.CharField('모델명', max_length=100)
    inspection_type = models.CharField('검사 유형', max_length=16,
                                       choices=InspectionType.choices)
    version = models.CharField('버전', max_length=50)
    artifact_path = models.CharField('아티팩트 경로', max_length=255)
    runtime = models.CharField('런타임', max_length=50)
    threshold = models.FloatField('임계값', null=True, blank=True)
    active = models.BooleanField('사용', default=True)

    class Meta:
        db_table = 'vision_model'
        verbose_name = 'AI 모델'
        ordering = ['name', '-version']
        constraints = [models.UniqueConstraint(fields=['name', 'version'],
                                               name='uq_vision_model_name_version')]

    def __str__(self):
        return f'{self.name} v{self.version}'


class VisionItemModelMapping(TimestampMixin):
    """검사항목 ↔ 모델 매핑.

    `model_code`/`model_version` 을 **비정규화 저장**한다. FK 를 끊을 때
    이 두 컬럼만 남기면 된다.
    """

    item = models.ForeignKey(InspectionItem, related_name='model_mappings',
                             on_delete=models.CASCADE)
    model = models.ForeignKey(VisionModel, related_name='mappings', on_delete=models.PROTECT)
    # FK 를 끊었을 때 쓸 식별자. 매핑 저장 시 model 에서 복사한다.
    model_code = models.CharField('모델 식별자', max_length=100)
    model_version = models.CharField('모델 버전', max_length=50)
    threshold_override = models.FloatField('임계값 재지정', null=True, blank=True)
    active = models.BooleanField('사용', default=True)

    class Meta:
        db_table = 'vision_item_model_mapping'
        verbose_name = '비전검사항목 모델 매핑'
        ordering = ['-active', '-updated_at']
        constraints = [
            # 검사항목당 활성 매핑은 하나다. 과거 매핑은 active=False 로 남겨
            # 이력을 보존하므로 비활성 행은 여러 개 있어도 된다.
            models.UniqueConstraint(fields=['item'], condition=Q(active=True),
                                    name='uq_vision_active_mapping_per_item'),
        ]

    def __str__(self):
        return f'{self.item.code} → {self.model_code} v{self.model_version}'

    def save(self, *args, **kwargs):
        if self.model_id and not self.model_code:
            self.model_code = self.model.name
            self.model_version = self.model.version
        super().save(*args, **kwargs)

    @property
    def effective_threshold(self):
        """매핑에서 재지정한 값이 있으면 그것, 없으면 모델 기본값."""
        return self.threshold_override if self.threshold_override is not None else self.model.threshold


def overlay_upload_path(instance, filename):
    from pathlib import PurePath

    suffix = PurePath(filename).suffix.lower()
    return f'vision/overlays/{instance.item_id}/v{instance.version}{suffix}'


def heatmap_upload_path(instance, filename):
    return f'vision/heatmaps/{instance.id}.jpg'


class VisionOverlay(TimestampMixin):
    """클라이언트 화면에 겹쳐 보여 줄 기준 이미지.

    위치·크기 컬럼(`x`/`y`/`width`/`height`)을 두지 않는다 — 클라이언트가 읽지
    않는다. Overlay 계약은 `version`·`opacity`·`visible`·`image` 네 개뿐이다.
    """

    item = models.OneToOneField(InspectionItem, related_name='overlay', on_delete=models.CASCADE)
    version = models.IntegerField('버전', default=1)
    visible = models.BooleanField('표시', default=True)
    opacity = models.FloatField('불투명도', default=0.7)
    image = models.ImageField('Overlay 이미지', upload_to=overlay_upload_path)

    class Meta:
        db_table = 'vision_overlay'
        verbose_name = 'Overlay'

    def __str__(self):
        return f'{self.item.code} Overlay v{self.version}'


class VisionInspection(TimestampMixin):
    """검사 1건.

    `id` 는 서버가 접수할 때 만드는 UUID, `request_id` 는 클라이언트가 만든 UUID 문자열이다(API 계약).
    DB 자동증가 PK 로 바꾸면 클라이언트의 idempotency 처리가 깨진다.
    """

    class Status(models.TextChoices):
        RECEIVED = 'RECEIVED', '접수됨'
        SUCCESS = 'SUCCESS', '판정 완료'
        FAILED = 'FAILED', '실패'

    id = models.CharField(primary_key=True, max_length=36)
    request_id = models.CharField('요청 ID', max_length=36, unique=True)
    client = models.ForeignKey(VisionClient, related_name='inspections',
                               on_delete=models.PROTECT)
    item = models.ForeignKey(InspectionItem, related_name='inspections',
                             on_delete=models.PROTECT)
    # 검사 이미지의 실체는 데이터 관리 쪽이 갖는다.
    image_asset = models.ForeignKey(ImageAsset, related_name='inspections',
                                    null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField('상태', max_length=20, choices=Status.choices,
                              default=Status.RECEIVED)
    capture_timestamp = models.DateTimeField('촬영 시각', null=True, blank=True)
    client_version = models.CharField('클라이언트 버전', max_length=50, null=True, blank=True)
    camera_vendor = models.CharField('카메라 제조사', max_length=100, null=True, blank=True)
    camera_serial = models.CharField('카메라 일련번호', max_length=100, null=True, blank=True)

    # --- 추론 결과. Wezard 추론이 성공(SUCCESS)해야 채워진다(O-12·DEC-030).
    abnormal = models.BooleanField('이상 판정', null=True, blank=True)
    model_name = models.CharField('사용 모델', max_length=255, null=True, blank=True)
    model_version = models.CharField('모델 버전', max_length=50, null=True, blank=True)
    defects = models.JSONField('탐지 결과', null=True, blank=True)
    anomaly_score = models.FloatField('이상 점수', null=True, blank=True)
    # 분류의 1순위 {label, name, score}. 분류가 아니면 null(DEC-031).
    classification = models.JSONField('분류 결과', null=True, blank=True)
    threshold = models.FloatField('적용 임계값', null=True, blank=True)
    # 치수 측정의 측정점별 결과 [{code,name,value,lower,upper,unit,ok}] — 그때 규격을 함께 남긴다. 치수 측정이 아니면 null.
    measurements = models.JSONField('측정 결과', null=True, blank=True)
    # 클라이언트가 기준물로 정한 배율(metadata.calibration 그대로). 어떤 배율로 쟀는지 되짚는 데 쓴다.
    calibration = models.JSONField('배율 정보', null=True, blank=True)
    inference_ms = models.FloatField('추론 시간(ms)', null=True, blank=True)
    # 이상 탐지 SUCCESS 의 Heatmap — 원본 위에 색 지도를 겹친 원본 크기 JPEG(계약 §8).
    heatmap = models.FileField('Heatmap', upload_to=heatmap_upload_path, null=True, blank=True)
    error_message = models.TextField('오류', null=True, blank=True)

    class Meta:
        db_table = 'vision_inspection'
        verbose_name = '검사 결과'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['item', '-created_at']),
            models.Index(fields=['client', '-created_at']),
            models.Index(fields=['status', '-created_at']),
            # 검사 이력 화면의 기간 조건·최신순 페이지(조건 없이 기간만 거는 기본 조회)
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f'{self.id} · {self.item.code} · {self.status}'

    @property
    def inference_skipped(self):
        """모델이 매핑돼 있는데 추론이 돌지 않은 검사.

        검사 결과 화면이 "추론 미실행 · <사유>"(Wezard 미설정·배포 모델 없음)로 구분해 보여 준다.
        `RECEIVED` 만 보고 "모델이 안 붙었구나"로 오해하지 않게 하기 위함이다.
        """
        return self.status == self.Status.RECEIVED and bool(self.error_message)
