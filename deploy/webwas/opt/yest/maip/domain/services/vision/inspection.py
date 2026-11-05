"""검사 수신 서비스.

Client 가 촬영한 이미지를 받아 **데이터 관리 쪽 이미지로 저장하고**, 검사항목에
활성 모델 매핑이 있으면 추론을 시도한다.

두 가지가 통상의 접수 흐름과 다르다.

1. **이미지는 `ImageService.upload_images()` 로 들어간다**.
   접수 즉시 라벨링 대상이 되고, 별도 이관 단계가 없다. 파일은 한 벌만 남는다.
2. **공정·제품 검증을 하지 않는다**. Client 는 여전히
   `process_id`/`product_id` 를 보내지만 서버가 합성한 고정값이라 의미가 없다.
"""
import logging
import math
from decimal import Decimal
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction

from domain.models.data import ImageAsset, InspectionItem, LabelClass, MeasurementPoint
from domain.models.vision import VisionInspection, VisionItemModelMapping
from domain.services.data.image import ImageService
from domain.services.vision.gateway import GpuNotConfiguredError, get_inference_gateway
from domain.tenancy import current_tenant

logger = logging.getLogger(__name__)

# Heatmap 의 색 지도 불투명도. 결함 자리는 색으로 보이고 제품 모양은 그대로 알아볼 수 있는 값이다.
HEATMAP_ALPHA = 0.45


def judgement_text(inspection):
    """화면 한 줄 판정 — 처리 전·실패면 상태 이름, 분류는 '<이름> (<점수>)', 그 밖은 '이상'·'정상'(판정 없음 '-').

    비전 검사 이력 화면과 디지털 양식 이미지 칸의 거치대 결과가 같이 쓴다.
    """
    if inspection.status != VisionInspection.Status.SUCCESS:
        return inspection.get_status_display()
    if inspection.classification:
        return '{} ({:.2f})'.format(inspection.classification['name'], inspection.classification['score'])
    if inspection.abnormal is None:
        return '-'
    return '이상' if inspection.abnormal else '정상'


def measured_rows(inspection):
    """치수 측정 측정점마다 [{label: '<이름> (<코드>)', text: '540.32 mm (539~541) 합격', ok}] — 측정이 아니면 [].

    값·범위는 받은 숫자 그대로(:g)다.
    """
    return [{'label': '{} ({})'.format(m['name'], m['code']),
             'text': '{:g} {} ({:g}~{:g}) {}'.format(m['value'], m['unit'], m['lower'], m['upper'], '합격' if m['ok'] else '불합격'),
             'ok': m['ok']} for m in inspection.measurements or []]


class InspectionItemNotFound(Exception):
    pass


class RequestIdConflict(Exception):
    """다른 Client 가 이미 쓴 request_id."""


class MeasurementInvalid(Exception):
    """치수 측정 항목의 `measurements` 가 측정점과 맞지 않는다. 422 `MEASUREMENT_INVALID` 다."""


def judge_measurements(item, raw):
    """`[{code, value}]` → 측정점 순서의 `[{code,name,value,lower,upper,unit,ok}]`.

    측정점 전부가 한 번씩 있어야 한다 — 빠진 점이 있으면 판정이 무의미하다(설계 Q1). 값은 bool 이 아닌 유한한 숫자다.
    """
    points = list(MeasurementPoint.objects.filter(item=item))
    if not isinstance(raw, list) or not all(isinstance(m, dict) for m in raw):
        raise MeasurementInvalid('measurements 는 {code, value} 객체의 배열이어야 합니다.')
    values = {}
    for m in raw:
        code, value = m.get('code'), m.get('value')
        if not isinstance(code, str):
            raise MeasurementInvalid('측정점 code 는 글자여야 합니다.')
        if code in values:
            raise MeasurementInvalid(f'측정점 {code} 이 두 번 있습니다.')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise MeasurementInvalid(f'측정점 {code} 의 값은 숫자여야 합니다.')
        values[code] = value
    expected = {p.code for p in points}
    if set(values) != expected:
        raise MeasurementInvalid('측정점 {} 을 한 번씩 보내야 합니다.'.format(', '.join(p.code for p in points)))
    return [{'code': p.code, 'name': p.name, 'value': values[p.code], 'lower': float(p.lower),
             'upper': float(p.upper), 'unit': p.unit, 'ok': p.lower <= Decimal(str(values[p.code])) <= p.upper}
            for p in points]


class InspectionService:
    """검사 1건을 접수한다."""

    def __init__(self, gateway=None):
        self._gateway = gateway or get_inference_gateway()

    def receive_capture(self, *, client, request_id, inspection_item_id, image_bytes,
                        capture_timestamp=None, client_version=None,
                        camera_vendor=None, camera_serial=None, measurements=None, calibration=None):
        """저장된 검사와, 이번 호출에서 새로 생겼는지 여부를 돌려준다.

        같은 `request_id` 로 재요청(Client Retry)하면 새로 저장하지 않고 기존
        레코드를 그대로 돌려준다.
        """
        existing = VisionInspection.objects.filter(request_id=request_id).first()
        if existing is not None:
            return self._owned_retry(existing, client), False

        tenant = current_tenant()
        item = (InspectionItem.objects.for_tenant(tenant)
                .filter(pk=inspection_item_id, status=InspectionItem.Status.ACTIVE).first())
        if item is None:
            raise InspectionItemNotFound(f'검사항목을 찾을 수 없습니다: {inspection_item_id}')
        # 치수 측정은 추론 대신 클라이언트가 잰 값을 판정한다. 이미지를 쓰기 전에 거절한다. 다른 유형은 measurements 를 무시한다.
        judged = {}
        if item.task_type == InspectionItem.TaskType.MEASUREMENT:
            results = judge_measurements(item, measurements)
            judged = {'status': VisionInspection.Status.SUCCESS, 'abnormal': not all(r['ok'] for r in results),
                      'measurements': results, 'calibration': calibration}

        inspection_id = str(uuid4())
        # 파일명·Content-Type 을 Client 가 보낸 값 그대로 믿지 않는다. 실제 바이트에서
        # 형식을 판정해 이름을 새로 만든다 — 원본 vision Server 의
        # `validate_and_get_extension()` 과 같은 취지다.
        extension, mime = self._detect_format(image_bytes)
        upload = SimpleUploadedFile(f'{inspection_id}.{extension}', image_bytes,
                                    content_type=mime)

        # 이미지 파일은 행을 만들 때 저장소에 바로 써진다. 아래에서 실패하면 행은 롤백되고
        # 파일만 남으므로 지운다. 요청 트랜잭션(ClientApiView)째 롤백되는 추론 단계 실패도 같다.
        written = []
        try:
            try:
                with transaction.atomic():
                    # 원본 이미지는 무조건 저장한다. 모델 매핑 유무·추론 성공 여부와 무관하다.
                    # Client 가 같은 장면을 다시 찍어 보낼 수 있으므로 중복을 허용한다.
                    result = ImageService.upload_images(
                        item, [upload],
                        actor=client.service_account,
                        requires_labeling=True,
                        allow_duplicate=True,
                        source_inspection_id=inspection_id,
                    )
                    if result['rejected']:
                        raise ValueError(result['rejected'][0].get('reason', '이미지를 저장하지 못했습니다.'))

                    asset = (ImageAsset.objects.for_tenant(tenant)
                             .filter(source_inspection_id=inspection_id).first())
                    written = [asset.file.name, asset.thumbnail.name] if asset else []

                    inspection = VisionInspection.objects.create(
                        id=inspection_id,
                        request_id=request_id,
                        client=client,
                        item=item,
                        image_asset=asset,
                        capture_timestamp=capture_timestamp,
                        client_version=client_version,
                        camera_vendor=camera_vendor,
                        camera_serial=camera_serial,
                        **judged,
                    )
            except IntegrityError:
                # 같은 request_id 가 동시에 들어와 위 확인을 둘 다 통과한 경우다.
                # 먼저 들어간 행이 기준이므로 그 행으로 재전송과 똑같이 답한다.
                ImageService.delete_files(written)
                winner = VisionInspection.objects.filter(request_id=request_id).first()
                if winner is None:
                    raise
                return self._owned_retry(winner, client), False

            if not judged:
                self._run_inference(inspection, item, image_bytes, written)
        except Exception:
            ImageService.delete_files(written)
            raise
        return inspection, True

    @staticmethod
    def _detect_format(image_bytes):
        """이미지 바이트에서 (확장자, MIME)을 판정한다. 지원하지 않으면 ValueError."""
        from io import BytesIO

        from PIL import Image, UnidentifiedImageError

        try:
            with Image.open(BytesIO(image_bytes)) as image:
                fmt = (image.format or '').upper()
        # DecompressionBombError 를 놓치면 500 retryable 이 되어 Client 가 같은 이미지를 계속 다시 보낸다
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError('이미지를 읽을 수 없습니다.') from exc
        if fmt == 'JPEG':
            return 'jpg', 'image/jpeg'
        if fmt == 'PNG':
            return 'png', 'image/png'
        raise ValueError(f'지원하지 않는 이미지 형식입니다: {fmt or "알 수 없음"}')

    @staticmethod
    def _owned_retry(existing, client):
        """`request_id` 는 전역 UNIQUE 다.

        소유자를 보지 않고 돌려주면 남의 `request_id` 만 알아도 그 검사 결과가
        나간다. 결과는 싣지 않고 충돌로만 알린다.
        """
        if existing.client_id != client.id:
            logger.warning('request_id 충돌: client=%s owner=%s', client.id, existing.client_id)
            raise RequestIdConflict('다른 클라이언트가 이미 사용한 request_id 입니다.')
        return existing

    def _run_inference(self, inspection, item, image_bytes, written):
        """활성 모델 매핑이 있으면 추론한다. 새로 쓴 파일(Heatmap)은 `written` 에 더해 실패 때 지우게 한다.

        매핑이 없으면 `RECEIVED` 그대로다 — 원본 vision Server 와 같은 동작이다.
        매핑이 있는데 GPU 가 없으면 역시 `RECEIVED` 지만 `error_message` 에
        사유를 남긴다. 검사 결과 화면이 그것으로 "추론 미실행"을 구분한다.
        """
        mapping = (VisionItemModelMapping.objects
                   .filter(item=item, active=True).select_related('model').first())
        if mapping is None or not mapping.model.active:
            return inspection

        inspection.model_name = mapping.model_code
        inspection.model_version = mapping.model_version
        try:
            result = self._gateway.infer(
                inspection_type=mapping.model.inspection_type,
                model_code=mapping.model_code,
                model_version=mapping.model_version,
                threshold=mapping.effective_threshold,
                image_bytes=image_bytes,
                request_id=inspection.request_id,
            )
        except GpuNotConfiguredError as exc:
            logger.warning('%s — 검사 %s 는 접수만 됐다(모델 %s v%s 매핑됨)',
                           exc.code, inspection.id, mapping.model_code, mapping.model_version)
            inspection.error_message = exc.code
            inspection.save(update_fields=['model_name', 'model_version', 'error_message'])
            return inspection
        except Exception as exc:
            logger.exception('추론 실패: inspection=%s model=%s',
                             inspection.id, mapping.model_code)
            inspection.status = VisionInspection.Status.FAILED
            # Admin 전용 진단 정보다 — Client 응답에는 넣지 않는다(내부 경로 노출).
            inspection.error_message = f'{type(exc).__name__}: {exc}'
            inspection.save(update_fields=['status', 'model_name', 'model_version',
                                           'error_message'])
            return inspection

        inspection.status = VisionInspection.Status.SUCCESS
        # 매핑은 이름만 갖는다(version `latest`). 기록은 Wezard 가 실제로 쓴 이름·버전이다.
        inspection.model_name = result.model_name or inspection.model_name
        inspection.model_version = result.model_version or inspection.model_version
        inspection.abnormal = result.abnormal
        if result.classification:
            # 1순위 클래스가 불량 클래스면 이상이다. 검사항목에 없는 라벨은 이상으로 본다(DEC-031).
            label = result.classification['label']
            known = LabelClass.objects.filter(item=item, name=label).first()
            inspection.abnormal = known.is_defect if known else True
            inspection.classification = {'label': label, 'name': known.display_name_ko if known else label,
                                         'score': result.classification['score']}
        if result.defects:
            # 표시 이름은 분류와 같다 — 검사항목 라벨의 표시명, 없는 라벨은 코드 그대로(R19).
            names = dict(LabelClass.objects.filter(item=item).values_list('name', 'display_name_ko'))
            inspection.defects = [{**d.__dict__, 'name': names.get(d.class_name, d.class_name)} for d in result.defects]
        else:
            inspection.defects = None
        inspection.anomaly_score = result.anomaly_score
        inspection.threshold = result.threshold
        inspection.inference_ms = result.inference_ms
        if result.heatmap_png:
            self._save_heatmap(inspection, image_bytes, result.heatmap_png, written)
        inspection.save()
        return inspection

    @staticmethod
    def _save_heatmap(inspection, image_bytes, heatmap_png, written):
        """원본 위에 색 지도를 겹친 원본 크기 JPEG 를 저장한다(계약 §8). 못 만들면 판정만 남긴다."""
        from io import BytesIO

        from django.core.files.base import ContentFile
        from PIL import Image, ImageOps, UnidentifiedImageError

        try:
            with Image.open(BytesIO(image_bytes)) as source, Image.open(BytesIO(heatmap_png)) as colors:
                # Wezard 는 EXIF 방향을 적용한 원본 크기로 준다. 다르면 원본에 맞춘다.
                base = ImageOps.exif_transpose(source).convert('RGB')
                overlay = colors.convert('RGB')
                if overlay.size != base.size:
                    overlay = overlay.resize(base.size, Image.BILINEAR)
                buffer = BytesIO()
                Image.blend(base, overlay, HEATMAP_ALPHA).save(buffer, format='JPEG', quality=90)
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            logger.warning('Heatmap 을 만들지 못했다: inspection=%s', inspection.id, exc_info=True)
            return
        inspection.heatmap.save(f'{inspection.id}.jpg', ContentFile(buffer.getvalue()), save=False)
        written.append(inspection.heatmap.name)
