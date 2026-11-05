"""화면(gui_code) 정의와 API 권한 매핑.

- `menu_init()`      : gui_code → 화면 템플릿. `/gui/<gui_code>/` 가 참조한다.
- `taskview_menu_code_map()` : `<task>/<view>` → 필요한 menu_code 목록.
  원본 MES에서는 정의만 있고 호출되지 않던 죽은 코드였다. 지금은
  `ApiModuleView.dispatch()` 인가 훅이 이 맵을 사용한다.
"""
from domain import init_once

# 디지털 양식(CheckList) 화면 — 수입검사·품질검사 × 검사양식·검사작성·검사결과(사용자 결정 2026-10-16).
# 참고사진(`/media/dig-form-image/`)과 작성·조회 API 의 읽기는 이 중 하나의 권한이면 된다. 쓰기는 모듈이
# 양식 구분의 메뉴 W 로 좁힌다. `@init_once` 가 import 때 매핑을 만들므로 클래스보다 위에 둔다.
DIG_FORM_TYPES = {'INCOMING': '수입', 'OUTGOING': '품질'}
DIG_FORM_TYPE_LABELS = {'INCOMING': '수입검사', 'OUTGOING': '품질검사'}
# 검사양식 관리 — 수입·품질 양식을 한 화면(목록의 구분 열)에서 다룬다. W 하나로 두 구분을 고친다.
# 코드는 수입 검사양식 관리 시절 그대로다 — 메뉴권한·즐겨찾기가 남는다(사용자 결정 2026-10-21)
DIG_FORM_EDIT_MENU = 'wm_dig_form_incoming_form'
# 화면 이름은 "<구분>검사 <이름>"(수입검사 작성·품질검사 결과, 사용자 결정 2026-10-21)
DIG_FORM_SCREENS = (('write', '작성', 'dig_form/dig_form_write.html'),
                    ('result', '결과', 'dig_form/dig_form_result.html'))


def dig_form_menu_code(form_type, kind):
    return 'wm_dig_form_{}_{}'.format(form_type.lower(), kind)


DIG_FORM_MENU_CODES = (DIG_FORM_EDIT_MENU,) + tuple(
    dig_form_menu_code(t, kind) for t in DIG_FORM_TYPES for kind, _n, _t in DIG_FORM_SCREENS)


@init_once
class GUIConfiguration():

    __dic_gui__ = {}
    __dic_view_menu__ = {}

    @classmethod
    def __static_init__(cls):
        cls.__dic_gui__ = cls.menu_init()
        cls.taskview_menu_code_map()
        return

    @classmethod
    def gui_item(cls, name, template, site=''):
        return {
            'name': name,
            'templates': {'default': template},
            'site': site,
            'popup': 'N',
            'params': {},
        }

    @classmethod
    def menu_init(cls):
        gui_dc = {}

        # 시스템 관리
        # 부서 정보 — 옛 기준정보 화면을 사용자 소속 부서로 다시 올렸다(사용자 결정 2026-10-26)
        gui_dc['wm_depart'] = cls.gui_item('부서 정보', 'system/depart.html')
        gui_dc['wm_user'] =cls.gui_item('사용자', 'system/user.html')
        gui_dc['wm_user_group'] = cls.gui_item('사용자 그룹', 'system/usergroup.html')
        gui_dc['wm_user_group_menu'] = cls.gui_item('메뉴 권한', 'system/usergroup_menu.html')
        gui_dc['wm_multi_language'] = cls.gui_item('다국어 설정', 'system/multi_language.html')
        gui_dc['wm_menu_language'] = cls.gui_item('메뉴명 설정', 'system/menu_language.html')
        gui_dc['wm_prop_master'] = cls.gui_item('프라퍼티마스터', 'system/prop_master.html')
        gui_dc['wm_login_log'] = cls.gui_item('로그인 로그', 'system/login_log.html')
        gui_dc['wm_menu_log'] = cls.gui_item('메뉴 로그', 'system/menu_log.html')
        gui_dc['wm_system_log'] = cls.gui_item('시스템 로그', 'system/system_log.html')

        # 데이터 관리
        # Export 는 스냅샷 화면의 기능이다. 별도 메뉴로 두면 같은 화면이 여러 경로로 열리므로 화면을 두지 않는다.
        # 비전검사항목 관리(검사 관리) — 대분류 › 중분류(양식 매핑) › 비전검사항목 트리
        gui_dc['wm_data_item'] = cls.gui_item('비전검사항목 관리', 'data/item_list.html')
        gui_dc['wm_data_register'] = cls.gui_item('비전 데이터 등록', 'data/register.html')
        # 라벨 클래스·측정점은 검사항목 홈 안에서 관리한다.
        gui_dc['wm_data_item_detail'] = cls.gui_item('비전검사항목 홈', 'data/item.html')
        gui_dc['wm_data_image'] = cls.gui_item('데이터 목록', 'data/image.html')
        gui_dc['wm_data_labeling'] = cls.gui_item('라벨링 작업', 'data/labeling.html')
        gui_dc['wm_data_review'] = cls.gui_item('검수 작업', 'data/review.html')
        gui_dc['wm_data_snapshot'] = cls.gui_item('스냅샷 관리', 'data/snapshot.html')

        # 대시보드 — 로그인 첫 화면(main_menu 기본값). 지금은 예시 값만 보이는 데모다(사용자 결정 2026-10-21)
        gui_dc['wm_dashboard'] = cls.gui_item('대시보드', 'vision/dashboard.html')

        # 비전 검사 — 결과는 검사 작업, 클라이언트·Overlay 는 검사 관리 폴더에 있다
        gui_dc['wm_vis_client'] = cls.gui_item('비전검사 클라이언트 관리', 'vision/client.html')
        gui_dc['wm_vis_overlay'] = cls.gui_item('비전검사 Overlay 관리', 'vision/overlay.html')
        gui_dc['wm_vis_inspection'] = cls.gui_item('비전 검사 이력', 'vision/inspection.html')

        # 디지털 양식(CheckList) — 검사작성·검사결과는 같은 화면을 양식구분(form_type)별 메뉴로 쓴다. params 는 gparam 으로 간다.
        # 수입·품질이 한 폴더(검사 작업)에 있어 화면 이름·탭 이름에 구분을 붙인다(app/views/system/menus.py).
        gui_dc[DIG_FORM_EDIT_MENU] = cls.gui_item('검사양식 관리', 'system/form_edit.html')
        for form_type, prefix in DIG_FORM_TYPES.items():
            for kind, name, template in DIG_FORM_SCREENS:
                code = dig_form_menu_code(form_type, kind)
                gui_dc[code] = cls.gui_item(prefix + '검사 ' + name, template)
                gui_dc[code]['params'] = {'form_type': form_type}
                gui_dc[code]['tab_title'] = prefix + '검사 ' + name
        # 검사양식 코드 관리 — 판정 칸 선택지(사용자코드)의 그룹·결과 코드·판정 의미. 수입·품질이 같이 쓰는 기준이라 검사 관리 폴더에 둔다
        gui_dc['wm_dig_form_judge_code'] = cls.gui_item('검사양식 코드 관리', 'dig_form/judge_code.html')

        # 기준정보
        gui_dc['wm_code'] = cls.gui_item('코드정보', 'definition/code_info.html')
        gui_dc['wm_unit'] = cls.gui_item('단위정보', 'definition/unit.html')
        gui_dc['wm_company'] = cls.gui_item('업체정보', 'definition/company.html')
        # 품목·BOM — PLM 인터페이스로만 들어오는 조회 전용 화면(DECISIONS 사용자 결정 2026-10-19)
        gui_dc['wm_product_bom'] = cls.gui_item('품목·BOM 조회', 'definition/product_bom.html')
        # 외부 인터페이스 수신건·반영 결과·원본 행 — 조회 전용(DECISIONS 사용자 결정 2026-10-19). 메뉴는 시스템 관리 맨 위다
        gui_dc['wm_interface_log'] = cls.gui_item('인터페이스 이력', 'definition/interface_log.html')
        # 입고 — ERP 구매요청(= 입고의뢰) 한 줄이 입고 한 줄. 검사 대상·상태를 보고 수입검사 작성을 연다
        gui_dc['wm_receipt'] = cls.gui_item('입고 내역', 'definition/receipt.html')
        # 수입검사 품목 지정 — 수입검사 양식마다 검사할 품번. 지정된 품목의 입고가 검사 대상이 된다
        gui_dc['wm_product_form'] = cls.gui_item('수입검사 품목 지정', 'system/product_form.html')

        # 권한 없는 사용자의 기본 진입 화면
        gui_dc['wm_noauth_default'] = cls.gui_item('기본', 'app/default.html')

        return gui_dc

    @classmethod
    def get_gui_list(cls):
        return cls.__dic_gui__

    @classmethod
    def get_gui_info(cls, code):
        return cls.__dic_gui__.get(code, None)

    @classmethod
    def taskview_menu_code_map(cls):
        """`<task>/<view>` 와 menu_code를 매핑한다.

        빈 목록 `[]` 은 '메뉴 권한 없이 호출 가능'을 뜻한다(공통 조회 API).
        """
        m = {}

        # 시스템 관리
        m['system/user'] = ['wm_user']
        m['system/user_code'] = ['wm_code']
        m['system/usergroup'] = ['wm_user_group']
        m['system/usergroupmenu'] = ['wm_user_group_menu']
        m['system/labelcode'] = ['wm_multi_language']
        m['system/menu_language'] = ['wm_menu_language']
        m['system/property_master'] = ['wm_prop_master']
        m['system/loginlog'] = ['wm_login_log']
        m['system/menulog'] = ['wm_menu_log']
        m['system/systemlog'] = ['wm_system_log']
        m['system/code'] = ['wm_code']
        m['system/depart'] = ['wm_depart']

        # 공통 조회 — 메뉴 권한을 요구하지 않는다(로그인은 필요).
        m['system/bookmark'] = []
        m['system/combo'] = []
        m['system/grid_setting'] = []
        m['system/gui'] = []
        m['system/menu_setup'] = []
        m['system/menus'] = []
        m['system/myinfo'] = []
        m['system/system_code'] = []
        m['system/system_option'] = []
        m['system/systemcode_setup'] = []

        # 기준정보
        m['definition/code_info'] = ['wm_code']
        m['definition/company'] = ['wm_company']
        m['definition/unit'] = ['wm_unit']
        m['definition/product_bom'] = ['wm_product_bom']
        m['definition/interface_log'] = ['wm_interface_log']
        # 수입검사 작성의 자재입고 검색 팝업도 입고를 읽는다 — 다른 메뉴 API 를 부르면 그 권한이 없는 그룹이 403 이다
        m['definition/receipt'] = ['wm_receipt', dig_form_menu_code('INCOMING', 'write')]
        m['system/product_form'] = ['wm_product_form']

        # 비전 검사
        m['vision/dashboard'] = ['wm_dashboard']
        m['vision/client'] = ['wm_vis_client']
        m['vision/inspection'] = ['wm_vis_inspection']
        m['vision/overlay'] = ['wm_vis_overlay']

        # 디지털 양식 — 조회는 아무 디지털 양식 메뉴의 R. 쓰기는 모듈이 양식 구분의 메뉴 W 로 다시 본다
        # (작성·완료·삭제는 검사작성, 양식 편집·칸 설정은 검사양식 관리).
        m['dig_form/dig_form'] = list(DIG_FORM_MENU_CODES)
        m['system/form_edit'] = [DIG_FORM_EDIT_MENU]
        # 검사양식 코드 관리는 자기 메뉴만. DIG_FORM_MENU_CODES 에 넣지 않는다 — 넣으면 이 권한만으로 양식·사진 조회가 열린다.
        m['dig_form/judge_code'] = ['wm_dig_form_judge_code']

        # 데이터 관리 — 화면 하나에 모듈 하나(app/views/item/, DECISIONS DEC-028).
        # 검사항목 권한(2단계)은 모듈이 load_item 으로 본다.
        m['item/item_admin'] = ['wm_data_item']
        m['item/category'] = ['wm_data_item']           # 비전검사항목 관리 — 분류 트리·등록(메뉴 W)
        m['item/register'] = ['wm_data_register']
        m['item/item_home'] = ['wm_data_item_detail']
        m['item/image'] = ['wm_data_image']
        m['item/review'] = ['wm_data_review']
        m['item/labeling'] = ['wm_data_labeling']
        m['item/snapshot'] = ['wm_data_snapshot']

        # 공통/파일/팝업
        m['common/labels'] = []

        cls.__dic_view_menu__ = m
        return m

    @classmethod
    def get_page_menu_code(cls, folder, template_name):
        """`/page/<folder>/<template>` 에 대응하는 menu_code 목록.

        미등록이면 None, 빈 목록이면 로그인만 요구한다.
        """
        return PAGE_PERMISSION_MAP.get(folder + '/' + template_name)

    @classmethod
    def get_menu_code_by_taskview(cls, task_name, view_name):
        """`task/view` 에 대응하는 menu_code 목록을 돌려준다.

        매핑 자체가 없으면 None(= 미등록), 빈 목록이면 권한 불요.
        """
        return cls.__dic_view_menu__.get(task_name + '/' + view_name)


# 검사항목 하위 메뉴. 좌측 트리에서 **검사항목 노드 아래에만** 나타난다.
#
# 메뉴 행(`menu_item`)은 지우지 않고 남긴다. 이 코드들이 두 곳의 인가 기준점이다.
#   1. `taskview_menu_code_map()` 의 `item/<view>` 매핑 — 행을 지우면 데이터 API 가 전부 403 이 된다
#   2. 메뉴권한 화면 — "이 그룹이 라벨링을 할 수 있는가"를 거기서 부여한다
# 비전검사항목은 모두 보이고(배정은 없앴다), 화면마다 할 수 있는 일은 이 메뉴 권한이 정한다.
#
# 각 화면이 주소의 `?inspection_item=<검사항목 id>` 를 읽는다는 전제다.
ITEM_CHILD_MENUS = [
    ('wm_data_item_detail', '비전검사항목 홈'),
    ('wm_data_image', '데이터 목록'),
    ('wm_data_labeling', '라벨링 작업'),
    ('wm_data_review', '검수 작업'),
    ('wm_data_snapshot', '스냅샷 관리'),
]

# 위 하위 메뉴의 코드. 폴더 최상단에서는 감춘다(`app/views/system/menus.py`).
ITEM_CHILD_MENU_CODES = frozenset(code for code, _name in ITEM_CHILD_MENUS)


# `/page/<folder>/<template>` 권한 매핑.
# 빈 목록은 '로그인만 요구'를 뜻한다. `apiPermissionMap` 과 같은 규칙이다.
PAGE_PERMISSION_MAP = {
    'account/myinfo': [],
    'account/language': [],
    'popup/label': [],
}
