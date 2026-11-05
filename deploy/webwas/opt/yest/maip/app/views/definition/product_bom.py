"""품목·BOM 조회 (`wm_product_bom`) — 조회 전용. 품목·BOM 은 PLM 인터페이스 반영(`apply_interface`)으로만 들어온다.

트리 행은 setTreeData 의 평평한 형식({tree_id, tree_pid})이다. tree_id 는 위치 경로라
같은 하위 조립품이 두 곳에 나와도 겹치지 않는다.
"""
from django.db.models import Q

from app.views.item import paged
from domain.models.basic import Bom, Product
from domain.services.logging import LogWriter

# 펼치는 깊이 한도. 반영이 순환을 막지만 조회가 끝나지 않는 일은 따로 막는다
MAX_DEPTH = 30


def product_bom(context):
    """api/definition/product_bom"""
    gparam = context.gparam
    action = gparam.get('action', 'list')
    try:
        if action == 'list':
            return _list(gparam)
        if action == 'part_types':
            return list(Product.objects.exclude(PartType=None).order_by('PartType')
                        .values_list('PartType', flat=True).distinct())
        if action == 'detail':
            return _detail(Product.objects.get(id=gparam.get('id')))
        if action in ('tree', 'where_used'):
            return _tree(Product.objects.get(id=gparam.get('id')), down=action == 'tree')
        raise ValueError('action: ' + str(action))
    except Exception as ex:
        LogWriter.add_dblog('error', 'definition/product_bom : action-{}'.format(action), ex)
        return {'success': False, 'message': '품목 정보를 불러오지 못했습니다.'}


def _list(gparam):
    queryset = Product.objects.order_by('Code')
    keyword = (gparam.get('keyword') or '').strip()
    if keyword:
        queryset = queryset.filter(Q(Code__icontains=keyword) | Q(Name__icontains=keyword))
    if gparam.get('part_type'):
        queryset = queryset.filter(PartType=gparam['part_type'])
    if gparam.get('root_only') == 'Y':
        # 최상위 품목 = 장비. 부모 없이 자식이 있다
        queryset = queryset.filter(bom_children__isnull=False, bom_parents__isnull=True).distinct()
    return paged(queryset, gparam, lambda p: {
        'id': p.id, 'code': p.Code, 'name': p.Name, 'part_type': p.PartType, 'spec': p.Spec,
        'part_state': p.PartState, 'version': p.Version}, default_size=50)


def _when(value, fmt):
    return value.strftime(fmt) if value else ''


def _detail(p):
    return {
        'id': p.id, 'code': p.Code, 'part_no': p.PartNo, 'revision': p.Revision, 'version': p.Version, 'name': p.Name,
        'part_type': p.PartType, 'spec': p.Spec, 'material_group': p.MaterialGroup, 'material': p.Material,
        'post_process': p.PostProcess, 'part_state': p.PartState,
        'plm_created_date': _when(p.PlmCreatedDate, '%Y-%m-%d'), 'plm_version_date': _when(p.PlmVersionDate, '%Y-%m-%d'),
        'model3d_type': p.Model3dType, 'model3d_no': p.Model3dNo, 'model3d_version': p.Model3dVersion,
        'model3d_state': p.Model3dState, 'model3d_modified': _when(p.Model3dModified, '%Y-%m-%d %H:%M:%S'),
        'drawing2d_no': p.Drawing2dNo, 'drawing2d_version': p.Drawing2dVersion, 'drawing2d_state': p.Drawing2dState,
        'drawing2d_modified': _when(p.Drawing2dModified, '%Y-%m-%d %H:%M:%S'),
    }


def _num(value):
    return format(value.normalize(), 'f') if value is not None else ''


def _tree(product, down):
    """하위 BOM(down) 또는 사용처(up)를 평평한 트리 행(DFS 순서)으로 준다.

    단계마다 한 번 조회한다. 사용처의 qty 는 그 상위 품목 하나에 이 품목이 드는 수량이고 소요량은 없다.
    """
    near, far = ('Parent', 'Child') if down else ('Child', 'Parent')
    edges, level, seen = {}, {product.id}, {product.id}
    for _ in range(MAX_DEPTH):
        if not level:
            break
        boms = list(Bom.objects.filter(**{near + '_id__in': level}).select_related(far)
                    .order_by(near + '_id', 'Seq' if down else far + '__Code'))
        for bom in boms:
            edges.setdefault(getattr(bom, near + '_id'), []).append((getattr(bom, far), bom.Qty))
        level = {getattr(bom, far + '_id') for bom in boms} - seen
        seen |= level

    rows = []

    def walk(item, tree_id, tree_pid, qty, total, ancestors):
        rows.append({'tree_id': tree_id, 'tree_pid': tree_pid, 'id': item.id, 'code': item.Code, 'name': item.Name,
                     'part_type': item.PartType, 'spec': item.Spec, 'post_process': item.PostProcess,
                     'qty': _num(qty), 'total_qty': _num(total) if down else ''})
        if len(ancestors) >= MAX_DEPTH:
            return
        for no, (other, edge_qty) in enumerate(edges.get(item.id, []), 1):
            if other.id not in ancestors:
                walk(other, f'{tree_id}.{no}', tree_id, edge_qty, (total or 1) * edge_qty, ancestors | {other.id})

    walk(product, '0', None, None, None, {product.id})
    return rows
