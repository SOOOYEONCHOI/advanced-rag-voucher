"""스냅샷 관리 화면(`wm_data_snapshot`) — `/api/item/snapshot`.

등록하면 그 시점의 검수 승인 이미지를 manifest 로 고정하고 워커가 zip 을 만든다.
화면은 목록의 Export 상태를 보고 완료되면 받기 링크(`/media/export/<id>/`)를 띄운다.

| action  | 메서드 | 권한                    |
|---------|--------|-------------------------|
| list    | GET    | item.read               |
| detail  | GET    | item.read               |
| create  | POST   | dataset.snapshot.create |
| rebuild | POST   | dataset.snapshot.create |
"""
from collections import Counter

from django.db.models import Q
from django.http import Http404
from django.urls import reverse

from app.views.item import ItemApiError, load_item, param, whole
from domain.models.data import DatasetVersion, ExportJob, LabelClass
from domain.services.data.export.mvtec import _anomaly_type
from domain.services.data.export import registry
from domain.services.data.item import ItemService
from domain.services.data.item_access import SNAPSHOT_MENU, ItemAccessService
from domain.services.data.job import STALE_MESSAGE, JobService
from domain.services.data.version import DatasetVersionService

READ_ACTIONS = frozenset({'list', 'detail'})

# 저장된 실패 사유 중 화면에서 다르게 보일 것. 원문은 Wezard(`/api/v1/datasets`)에도 그대로 나가므로 고치지 않는다.
SCREEN_ERROR = {STALE_MESSAGE: '파일을 만드는 중 중단되었습니다. 다시 만들기를 눌러 주세요.'}


def snapshot(context):
    """api/item/snapshot"""
    handler = {'list': _list, 'detail': _detail, 'create': _create, 'rebuild': _rebuild}.get(
        context.gparam.get('action', 'list'))
    if handler is None:
        raise ItemApiError('지원하지 않는 기능입니다.')
    return handler(context)


def _versions(item, tenant):
    return DatasetVersion.objects.for_tenant(tenant).filter(dataset__item=item).order_by('-created_at', '-id')


def _latest_exports(tenant, version_ids, wezard=False):
    """버전마다 가장 최근 ExportJob. 버전마다 조회하지 않고 한 번에 읽는다.

    Wezard 전송용(`WEZARD`)과 화면용 고정 형식을 나눠 본다 — 화면은 고정 형식, `/api/v1/datasets` 는 `wezard=True`.
    """
    jobs = ExportJob.objects.for_tenant(tenant).filter(dataset_version_id__in=version_ids)
    wezard_only = Q(format=ExportJob.Format.WEZARD)
    jobs = jobs.filter(wezard_only) if wezard else jobs.exclude(wezard_only)
    latest = {}
    for job in jobs.order_by('created_at', 'id'):
        latest[job.dataset_version_id] = job
    return latest


def _serialize_export(job):
    if job is None:
        return None
    return {
        'id': job.id, 'format': job.format, 'format_label': job.get_format_display(),
        'status': job.status, 'status_label': job.get_status_display(),
        'file_url': reverse('private-export', args=[job.id]) if job.file else '',
        'error_message': SCREEN_ERROR.get(job.error_message, job.error_message),
    }


def _serialize_version(version, export_job):
    manifest = version.manifest or {}
    return {
        'id': version.id, 'version_tag': version.version_tag,
        'created_at': version.created_at.strftime('%Y-%m-%d %H:%M'),
        'image_count': manifest.get('image_count', 0),
        'excluded_image_count': manifest.get('excluded_image_count', 0),
        'export': _serialize_export(export_job),
    }


def _list(context):
    item = load_item(context, 'item.read')
    tenant = context.request.tenant
    rows = list(_versions(item, tenant))
    latest = _latest_exports(tenant, [row.id for row in rows])
    return {
        **whole(rows, lambda row: _serialize_version(row, latest.get(row.id))),
        'item': {'id': item.id, 'name': item.name, 'task_type': item.task_type},
        'can_create': ItemAccessService.can_write(context.request.user, SNAPSHOT_MENU),
    }


def _get_version(context, item):
    try:
        return _versions(item, context.request.tenant).get(pk=int(param(context, 'version_id')))
    except (DatasetVersion.DoesNotExist, TypeError, ValueError) as exc:
        raise Http404('스냅샷을 찾을 수 없습니다.') from exc


def _detail(context):
    item = load_item(context, 'item.read')
    version = _get_version(context, item)
    tenant = context.request.tenant
    latest = _latest_exports(tenant, [version.id])
    wezard = _latest_exports(tenant, [version.id], wezard=True)
    return {'version': _serialize_version(version, latest.get(version.id)),
            'wezard_export': _serialize_export(wezard.get(version.id)),
            'analysis': _screen_analysis(_analyze_manifest(version.manifest, item.task_type), item, tenant)}


def _create(context):
    item = load_item(context, 'dataset.snapshot.create')
    dataset = ItemService.get_or_create_upload_dataset(item)
    try:
        version, export_job = DatasetVersionService.create_snapshot(
            dataset, context.request.user, param(context, 'format'))
    except ValueError as exc:
        # create_snapshot 의 ValueError 는 사용자 문구(승인 0건·직전 스냅샷과 같음·지원하지 않는 형식)뿐이다.
        raise ItemApiError(str(exc)) from exc
    return {'success': True, 'message': '스냅샷을 등록했습니다. 완료되면 목록에서 받을 수 있습니다.',
            'version_id': version.id, 'export_job_id': export_job.id}


def _rebuild(context):
    # 실패한 스냅샷을 다시 만드는 것은 등록의 일부다 — 화면도 등록 권한자에게만 버튼을 보인다.
    item = load_item(context, 'dataset.snapshot.create')
    version = _get_version(context, item)
    # 형식을 고르던 때 다른 형식으로 만든 스냅샷도 다시 만들면 고정 형식이다.
    export_format = registry.ITEM_EXPORT_FORMAT.get(item.task_type)
    if export_format is None:
        raise ItemApiError('이 비전검사항목 유형은 스냅샷 파일을 만들 수 없습니다.')
    tenant = context.request.tenant
    fixed = _latest_exports(tenant, [version.id]).get(version.id)
    wezard = _latest_exports(tenant, [version.id], wezard=True).get(version.id)
    # 실패했거나 없는 것만 다시 적재한다. Wezard zip 이 생기기 전 스냅샷은 이것으로 채운다.
    targets = []
    if fixed is None or fixed.status == ExportJob.Status.FAILED or fixed.format != export_format:
        targets.append(export_format)
    if wezard is None or wezard.status == ExportJob.Status.FAILED:
        targets.append(ExportJob.Format.WEZARD)
    if not targets:
        raise ItemApiError('다시 만들 파일이 없습니다.')
    for target in targets:
        JobService.enqueue_export(version, context.request.user, export_format=target)
    return {'success': True, 'message': '다시 만들기를 등록했습니다.'}


def _screen_analysis(analysis, item, tenant):
    """화면용 분석. 분포의 라벨을 검사항목 라벨 클래스의 표시 이름으로 바꾼다(모르는 이름은 그대로).

    manifest 는 내부 이름(`name`)을 담고, 같은 분석이 Wezard statistics 로도 나가므로 `_analyze_manifest` 는 두고 여기서만 바꾼다.
    이상 탐지는 여러 유형이 섞인 `combined` 를 "여러 결함"으로 보이고, 예전 정상 판정 라벨('정상')은 결함 분포에서 뺀다.
    """
    names = dict(LabelClass.objects.for_tenant(tenant).filter(item=item).values_list('name', 'display_name_ko'))
    names['combined'] = '여러 결함'

    def rename(pairs, drop=()):
        return [(names.get(name) or name, count) for name, count in pairs if name not in drop]

    screen = dict(analysis)
    for key in ('class_distribution', 'class_image_distribution', 'anomaly_type_distribution'):
        if key in screen:
            screen[key] = rename(screen[key], drop=('정상',) if item.task_type == 'ANOMALY_DETECTION' else ())
    return screen


def _label_name(annotation):
    """예전 이상 탐지 스냅샷의 정상 판정에는 label_class가 없어 이름이 빈 값이므로 분포에서 '정상'으로 표시한다."""
    label = annotation.get("label")
    if label:
        return label
    if annotation.get("geometry_type") == "NONE" and not annotation.get("is_anomaly"):
        return "정상"
    return "-"


def _analyze_manifest(manifest, task_type=None):
    """스냅샷 manifest로 상세 화면의 분포 통계를 만든다.

    공통: 이미지 수, 주석 수, 주석이 있는/없는 이미지 수, 클래스별·도형별 분포.
    분류: 이미지당 첫 라벨 기준 분포, 미라벨 수, 한 클래스가 80% 이상이면 불균형 경고.
    이상 탐지: 정상/이상 이미지 수와 이상 유형 분포. 결함 Polygon 이 있으면 이상, 여러 유형이면 `combined`(DEC-032).
    """
    images = manifest.get("images", [])
    class_counts = Counter()
    class_image_counts = Counter()
    geometry_counts = Counter()
    annotation_count = 0
    annotated_image_count = 0
    normal_image_count = 0
    anomaly_type_counts = Counter()
    for image in images:
        annotations = image.get("annotations", [])
        if annotations:
            annotated_image_count += 1
        if task_type == "CLASSIFICATION" and annotations:
            class_image_counts[_label_name(annotations[0])] += 1
        if task_type == "ANOMALY_DETECTION":
            anomaly_type = _anomaly_type(image)
            if anomaly_type:
                anomaly_type_counts[anomaly_type] += 1
            else:
                normal_image_count += 1
        for annotation in annotations:
            annotation_count += 1
            class_counts[_label_name(annotation)] += 1
            geometry_counts[annotation.get("geometry_type", "-")] += 1
    image_count = len(images)
    result = {
        "image_count": image_count,
        "annotation_count": annotation_count,
        "annotated_image_count": annotated_image_count,
        "unannotated_image_count": image_count - annotated_image_count,
        "class_distribution": class_counts.most_common(),
        "geometry_distribution": dict(geometry_counts),
    }
    if task_type == "CLASSIFICATION":
        labeled_count = sum(class_image_counts.values())
        largest_class = max(class_image_counts.values(), default=0)
        result.update({
            "class_image_distribution": class_image_counts.most_common(),
            "unlabeled_image_count": image_count - labeled_count,
            "imbalance_warning": bool(labeled_count and largest_class / labeled_count >= 0.8),
        })
    if task_type == "ANOMALY_DETECTION":
        result.update({
            "normal_image_count": normal_image_count,
            "anomaly_image_count": sum(anomaly_type_counts.values()),
            "anomaly_type_distribution": anomaly_type_counts.most_common(),
        })
    return result
