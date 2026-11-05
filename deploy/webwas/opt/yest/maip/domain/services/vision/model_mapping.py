"""비전검사항목 ↔ AI 모델 매핑 — 비전검사항목 관리 상세(`item/item_admin`)가 쓴다.

모델은 Wezard 가 갖는다. Wezard 배포 모델 이름을 고르면 로컬 `VisionModel` 에 이름표(version `latest`)를
맞춘다. AI 모델 등록 화면(`wm_vis_model`)은 2026-10-19, 비전검사항목 모델 매핑 화면(`wm_vis_model_mapping`)은
2026-10-21 지웠다(사용자 결정 — 매핑은 비전검사항목 관리 목록·상세에서 본다).
"""
from django.db import transaction

from domain.models.data import InspectionItem
from domain.models.vision import VisionItemModelMapping, VisionModel
from domain.services.vision.gateway import WezardError, get_inference_gateway

# 검사항목 유형 → Wezard task_type.
WEZARD_TASK = {InspectionItem.TaskType.CLASSIFICATION: 'classification',
               InspectionItem.TaskType.OBJECT_DETECTION: 'detection', InspectionItem.TaskType.ANOMALY_DETECTION: 'anomaly'}


# 치수 측정은 모델 없이 측정값으로 판정한다 — 매핑 대상이 아니다.
def _mappable():
    return InspectionItem.objects.exclude(task_type=InspectionItem.TaskType.MEASUREMENT)


# Wezard 모델은 이름으로 매핑하고 추론 때마다 최신 배포 버전을 찾는다. 로컬 VisionModel 은 이 버전의 이름표다.
LATEST = 'latest'


def active_model_name(item):
    """지금 활성 매핑의 Wezard 모델 이름. 없으면 ''."""
    mapping = VisionItemModelMapping.objects.filter(item=item, active=True).first()
    return mapping.model_code if mapping else ''


def deployed_models(item):
    """(그 검사항목 유형의 Wezard 배포 모델 [{name, version, dataset_external_ref, recommended}], 안내 문구).

    이름마다 최신 버전 하나만 두고, 검사항목 코드 소문자와 같은 이름을 맨 앞에 둔다.
    """
    task = WEZARD_TASK[item.task_type]
    gateway = get_inference_gateway()
    if not gateway.is_configured():
        return [], 'Wezard 연결 설정이 없어 모델 목록을 받을 수 없습니다.'
    try:
        rows = gateway.list_models(task)
    except WezardError as exc:
        reason = {'TIMEOUT': '응답 시간 초과', 'UNREACHABLE': '연결 실패'}.get(exc.code, exc.code)
        return [], f'Wezard 에서 모델 목록을 받지 못했습니다({reason}).'
    models = {}
    for row in rows:  # 최신순이다 — 이름마다 처음 것이 최신 버전
        models.setdefault(row['model_name'], {
            'name': row['model_name'], 'version': row['version'],
            'dataset_external_ref': row.get('dataset_external_ref'),
            'recommended': row['model_name'] == item.code.lower()})
    ordered = sorted(models.values(), key=lambda m: not m['recommended'])
    return ordered, '' if ordered else 'Wezard 에 배포된 모델이 없습니다.'


@transaction.atomic
def save_mapping(posparam):
    """Wezard 배포 모델 이름(`model_name`)으로 매핑한다. 비우면("(매핑 없음)") 활성 매핑을 해제한다.

    기존 매핑은 지우지 않고 비활성으로 남긴다.
    """
    item = _mappable().filter(id=posparam.get('item_id')).first()
    if item is None:
        return {'success': False, 'message': '비전검사항목을 찾을 수 없습니다.'}
    name = (posparam.get('model_name') or '').strip()
    if not name:
        VisionItemModelMapping.objects.filter(item=item, active=True).update(active=False)
        return {'success': True}

    models, message = deployed_models(item)
    if name not in {m['name'] for m in models}:
        return {'success': False, 'message': message or f"'{name}' 모델이 Wezard 에 배포된 {item.get_task_type_display()} 모델에 없습니다."}
    target, _ = VisionModel.objects.update_or_create(
        name=name, version=LATEST,
        defaults={'inspection_type': item.client_inspection_type, 'artifact_path': '', 'runtime': 'wezard',
                  'threshold': None, 'active': True})

    previous = VisionItemModelMapping.objects.filter(item=item, active=True).first()
    # 화면에는 임계값 칸이 없다 — 보내지 않으면 직전 재지정 값을 이어 받는다. 빈 값을 보내면 재지정을 없앤다.
    if 'threshold_override' in posparam:
        override = posparam.get('threshold_override')
        override = float(override) if override not in (None, '') else None
    else:
        override = previous.threshold_override if previous else None
    # 기존 매핑은 지우지 않고 비활성으로 남긴다 — 어떤 모델로 판정했는지 이력이 필요하다.
    VisionItemModelMapping.objects.filter(item=item, active=True).update(active=False)
    mapping = VisionItemModelMapping.objects.create(
        item=item, model=target,
        model_code=target.name, model_version=target.version,
        threshold_override=override,
        active=True)
    return {'success': True, 'id': mapping.id}
