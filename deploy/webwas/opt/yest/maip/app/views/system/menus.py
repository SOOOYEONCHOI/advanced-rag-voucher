"""좌측 메뉴 트리.

`menu_folder` · `menu_item` 을 트리로 만들고, **비전 데이터 관리 폴더에는 검사 분류와
비전검사항목을 동적으로 끼워 넣는다**. 둘 다 메뉴 행이 아니라 데이터라서 시드로 만들 수 없다.

    비전 데이터 관리
    └── 수입검사                       ← 대분류 (동적, objId cat<id>)
        └── Rotor 수입검사 성적서       ← 중분류
            └── Rotor 표면 결함(수입)   ← 비전검사항목 = 끝 메뉴 /gui/wm_data_item_detail/?inspection_item=1
    └── 미분류                         ← 고정 대분류(수입검사·품질검사·미분류). 소속 없는 항목은 그 중분류 뒤에 붙는다
                                          (미분류 대분류가 아직 없으면 가상 폴더 cat0)

비전검사항목은 모두 보인다(삭제 승인 대기는 플랫폼 관리자만 — 비전검사항목 배정은 없앴다, 사용자 결정 2026-10-21).
항목을 누르면 그 항목의 탭 하나가 열리고, 나머지 화면(domain.gui.ITEM_CHILD_MENUS)은 그 탭 안의 내부 탭으로 연다 —
메뉴권한을 받은 것만.
볼 항목이 없는 분류는 감춘다(설계 2026-10-21 §4).

하위가 없는 폴더는 내보내지 않는다(`drop_empty_folders`). 대시보드처럼 메뉴 하나뿐인 폴더는 1단계 링크다(`top_level_leaves`).
"""
import logging

from domain.gui import ITEM_CHILD_MENUS, ITEM_CHILD_MENU_CODES, GUIConfiguration
from domain.services.system import SystemService

logger = logging.getLogger(__name__)

# 치수 측정 비전검사항목 아래에 두는 하위 메뉴(라벨링·검수·스냅샷은 API 도 거절한다 — app/views/item LABELED_VIEWS).
MEASUREMENT_CHILD_MENU_CODES = frozenset({'wm_data_item_detail', 'wm_data_image'})


# 폴더 없이 좌측 메뉴 1단계에 바로 보이는 메뉴 — 시드에서는 이 메뉴 하나뿐인 폴더다(폴더의 아이콘을 쓴다)
TOP_LEVEL_MENU_CODES = frozenset({'wm_dashboard'})


def top_level_leaves(folders):
    """메뉴 하나뿐인 폴더 중 그 메뉴가 TOP_LEVEL_MENU_CODES 면 폴더를 1단계 링크(`leaf`)로 내보낸다."""
    for folder in folders:
        nodes = folder['nodes']
        if len(nodes) == 1 and nodes[0]['objId'] in TOP_LEVEL_MENU_CODES:
            folder['leaf'] = nodes[0]
    return folders


def drop_empty_folders(folders):
    """메뉴가 하나도 남지 않은 폴더를 뺀다. 숨긴 메뉴만 있던 폴더가 빈 채로 보이지 않게."""
    return [folder for folder in folders if folder['nodes']]


def menus(context):

    user = context.request.user
    gparam = context.gparam
    lang_code = gparam.get('lang_code')
    systemservice = SystemService()
    items = []
    if user.is_authenticated:
        items = systemservice.get_web_menu_list(user, lang_code)

    dic_folder = {}
    menu_items = []
    # 검사항목 하위 메뉴 중 이 사용자가 권한을 받은 것. 메뉴 행은 트리에서 감추고
    # 검사항목 노드 아래에만 쓴다.
    granted_child_codes = set()
    anchor_folder = None

    for m in items:
        id = m.get('id')
        menu_code = m.get('menu_code')
        pid = m.get('pid')
        name = m.get('name')
        isbookmark = m.get('isbookmark')
        depth = m.get('depth')

        url = ''
        css = m.get('css')
        if id:
            # 폴더인 경우.
            # objId 는 폴더 PK 로 만든다. 폴더명(한글·공백)을 DOM id 로 쓰면
            # `[^\w-]` 치환 뒤 글자 수가 같은 폴더끼리 id 가 겹쳐(예: '데이터 관리'
            # 와 '시스템 관리' 가 모두 `fld_______`) Bootstrap collapse 가 둘을
            # 함께 토글한다.
            folder = {
                'objId': 'f{}'.format(id),
                'objNm': name,
                'objUrl': url,
                'menuIconCls': css,
                'nodes': [],
                'ismanual': False,
                'isbookmark': False,
                'menuDepth': depth,
            }

            dic_folder[id] = folder
            if not pid:  # 1 레벨 폴더
                menu_items.append(folder)
            else:
                p_folder = dic_folder.get(pid)
                if p_folder is not None:
                    p_folder['nodes'].append(folder)
        else:
            # 메뉴인 경우
            p_folder = dic_folder.get(pid)

            if menu_code in ITEM_CHILD_MENU_CODES:
                granted_child_codes.add(menu_code)
                # 검사항목 노드는 하위 메뉴와 같은 폴더에 붙인다. 특정 메뉴를
                # 기준으로 삼으면 그 메뉴 권한이 없는 그룹은 하위 트리 전체를 잃는다.
                if p_folder is not None:
                    anchor_folder = p_folder
                continue  # 폴더 최상단에는 내보내지 않는다

            item = {
                'objId': menu_code,
                'objNm': name,
                'objUrl': '/gui/' + menu_code,
                'menuIconCls': css,
                'nodes': [],
                'ismanual': False,
                'isbookmark': isbookmark,
                'menuDepth': 2,
                # 이름이 같은 메뉴(수입·품질의 검사작성 등)는 탭 이름으로 구분한다. 없으면 셸이 메뉴 이름을 쓴다.
                'tabTitle': (GUIConfiguration.get_gui_info(menu_code) or {}).get('tab_title', ''),
            }
            if p_folder is not None:
                p_folder['nodes'].append(item)

    if anchor_folder is not None:
        anchor_folder['nodes'].extend(_item_nodes(user, granted_child_codes))

    return top_level_leaves(drop_empty_folders(menu_items))


def _item_nodes(user, granted_child_codes):
    """사용자가 볼 수 있는 비전검사항목을 대분류(2) › 중분류(3) › 비전검사항목(4, 끝 메뉴) 노드로 만든다.

    항목 끝 메뉴는 홈을 연다. 홈 권한이 없으면 권한 있는 첫 하위 화면, 그것도 없으면 노드를 만들지 않는다.
    """
    children = [code for code, _name in ITEM_CHILD_MENUS if code in granted_child_codes]
    if not children:
        return []

    # 트리는 모든 화면 요청에서 그려진다. 조회가 실패해도 메뉴 전체가 죽지 않도록 여기서 막는다.
    try:
        from domain.models.data import InspectionCategory
        from domain.services.data.category import UNCLASSIFIED
        from domain.services.data.item_access import ItemAccessService
        from domain.tenancy import current_tenant, tenant_atomic

        # RLS 때문에 tenant_atomic() 안에서 읽어야 한다. 밖에서 읽으면 예외 없이
        # 빈 결과가 돌아와 비전검사항목이 조용히 사라진다.
        with tenant_atomic():
            tenant = current_tenant()
            items = list(ItemAccessService.visible_items(user=user, tenant=tenant)
                         .order_by('display_order', 'code').values_list('id', 'name', 'task_type', 'category_id'))
            categories = list(InspectionCategory.objects.for_tenant(tenant))
    except Exception:
        logger.exception('좌측 메뉴의 비전검사항목 목록을 만들지 못했다 (user=%s)', user)
        return []

    by_category = {}
    for item_id, item_name, task_type, category_id in items:
        # 치수 측정 항목은 라벨링을 하지 않는다 — 홈·데이터 목록만
        allowed = [code for code in children if task_type != 'MEASUREMENT' or code in MEASUREMENT_CHILD_MENU_CODES]
        if allowed:
            by_category.setdefault(category_id, []).append(_leaf(item_id, item_name, allowed[0]))

    minors = {}
    for category in categories:
        if category.parent_id:
            minors.setdefault(category.parent_id, []).append(category)
    # 중분류가 아닌 곳(없음·대분류)을 가리키는 항목은 미분류다
    minor_ids = {c.id for c in categories if c.parent_id}
    loose = [leaf for category_id, leaves in by_category.items() if category_id not in minor_ids for leaf in leaves]
    majors = [c for c in categories if not c.parent_id]   # 모델 ordering: 순서, 이름
    none_major = next((c for c in majors if c.name == UNCLASSIFIED), None)
    nodes = []
    for major in majors:
        children = [_folder(minor, 3, by_category[minor.id]) for minor in minors.get(major.id, []) if minor.id in by_category]
        if major is none_major:
            children += loose
        if children:
            nodes.append(_folder(major, 2, children))
    if loose and none_major is None:
        nodes.append(_folder(None, 2, loose))
    return nodes


def _folder(category, depth, nodes):
    return {'objId': 'cat{}'.format(category.id if category else 0), 'objNm': category.name if category else '미분류',
            'objUrl': '', 'menuIconCls': None, 'nodes': nodes, 'ismanual': False, 'isbookmark': False,
            'menuDepth': depth}


def _leaf(item_id, item_name, code):
    """비전검사항목 끝 메뉴. 탭 id 는 홈 화면이 다른 화면을 열 때 쓰는 `item<id>_<menu_code>` 와 같다."""
    return {'objId': 'item{}_{}'.format(item_id, code), 'objNm': item_name,
            'objUrl': '/gui/{}/?inspection_item={}'.format(code, item_id), 'menuIconCls': None, 'nodes': [],
            'ismanual': False, 'isbookmark': False, 'menuDepth': 4, 'tabTitle': item_name}
