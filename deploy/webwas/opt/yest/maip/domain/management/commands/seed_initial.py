"""통합 플랫폼 초기 데이터 생성.

멱등이다. 여러 번 실행해도 같은 결과가 된다.

    python manage.py seed_initial --admin-password '...'
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from domain.gui import DIG_FORM_EDIT_MENU, GUIConfiguration
from domain.models.data import Tenant, TenantMembership
from domain.models.system import Bookmark, MenuFolder, MenuItem, SystemCode, SystemOption
from domain.models.user import UserGroup, UserGroupMenu, UserProfile
from domain.services import judge_code
from domain.tenancy import FIXED_TENANT_ID, FIXED_TENANT_NAME, tenant_atomic

# 폴더명 → [(MenuCode, 메뉴명)] — gui.py 의 화면 정의와 짝을 이룬다.
# 폴더 순서가 좌측 메뉴 순서다.
MENU_TREE = [
    # 업무 흐름 기준으로 묶는다(사용자 결정 2026-10-21) — 현장 검사 작업이 맨 위, 그 기준(검사 관리)과 학습 데이터(비전 데이터 관리)가
    # 다음, 조회·운영이 아래다(순서는 사용자 결정 2026-10-22).
    # 메뉴 코드는 옛 화면 그대로다 — 메뉴권한·즐겨찾기가 남는다. 이름은 단어 단위로 띄우고 검사 종류는 "수입검사"·"품질검사"로 붙인다.
    # 대시보드 — 메뉴 하나뿐인 폴더라 좌측 메뉴는 폴더 없이 1단계 링크로 보인다(menus.TOP_LEVEL_MENU_CODES). 로그인 첫 화면이다
    ('대시보드', 'uil-chart-line', [
        ('wm_dashboard', '대시보드'),
    ]),
    # 검사 작업 — 현장 검사원. 수입검사 흐름 → 품질검사 흐름 → 비전 검사 이력. 결과 화면을 한 폴더에 둔다
    # 작업지시 관리는 품질검사 작성의 검사 작업 목록에 합쳤다(사용자 결정 2026-10-21)
    # 디지털 양식(CheckList)은 작성·결과를 같은 화면을 양식구분(form_type)별로 쓴다(gui.py params).
    ('검사 작업', 'uil-clipboard-alt', [
        # 매핑된 입고가 대기 작업으로 나온다. 검사 대기 배지가 붙는다(설계 2026-10-21 §6)
        ('wm_dig_form_incoming_write', '수입검사 작성'),
        ('wm_dig_form_incoming_result', '수입검사 결과'),
        ('wm_dig_form_outgoing_write', '품질검사 작성'),
        ('wm_dig_form_outgoing_result', '품질검사 결과'),
        ('wm_vis_inspection', '비전 검사 이력'),
    ]),
    # 검사 관리 — 검사 기준과 비전 검사 설정. 위 셋은 양식 쪽(양식 → 판정 선택지 → 검사할 품목), 아래 셋은 비전 쪽
    # (분류·비전검사항목(AI 모델) → 촬영 가이드 → 장비 등록)이다(사용자 결정 2026-10-22)
    ('검사 관리', 'uil-layer-group', [
        # 수입·품질 양식을 한 화면에서 — 코드는 수입 검사양식 관리 시절 그대로다
        ('wm_dig_form_incoming_form', '검사양식 관리'),
        # 디지털 양식 판정 칸 선택지 — 수입·품질이 같이 쓴다
        ('wm_dig_form_judge_code', '검사양식 코드 관리'),
        # 수입검사 양식마다 검사할 품번 — 입고의 검사 대상을 정한다
        ('wm_product_form', '수입검사 품목 지정'),
        # 대분류 › 중분류(양식 매핑) › 비전검사항목(설계 2026-10-21 §3). AI 모델 매핑도 여기서 한다
        ('wm_data_item', '비전검사항목 관리'),
        ('wm_vis_overlay', '비전검사 Overlay 관리'),
        ('wm_vis_client', '비전검사 클라이언트 관리'),
    ]),
    # 비전 데이터 관리 — 검사 분류 › 비전검사항목 트리(동적, app/views/system/menus.py)
    ('비전 데이터 관리', 'uil-database', [
        # 검사항목을 골라 카메라·파일로 등록하고 최근 데이터를 본다(사용자 결정 2026-10-23). 트리의 분류 노드보다 위에 보인다
        ('wm_data_register', '비전 데이터 등록'),
        # 이 5개는 좌측 트리에서 검사항목 노드 아래에만 보인다
        # (`domain.gui.ITEM_CHILD_MENUS`). 메뉴 행은 메뉴권한·API 인가의
        # 기준점이라 남긴다.
        ('wm_data_item_detail', '비전검사항목 홈'),
        ('wm_data_image', '데이터 목록'),
        ('wm_data_labeling', '라벨링 작업'),
        ('wm_data_review', '검수 작업'),
        ('wm_data_snapshot', '스냅샷 관리'),
    ]),
    # 품목·BOM(PLM)·입고(ERP 구매요청) — 조회 전용(사용자 결정 2026-10-19). 옛 MES 기준정보 화면(RETIRED_FROM_MENU)과는 다르다
    ('기준정보', 'uil-box', [
        ('wm_product_bom', '품목·BOM 조회'),
        # 입고 — ERP 구매요청(= 입고의뢰). 조회 전용, 검사 정보는 없다(설계 2026-10-21 §6)
        ('wm_receipt', '입고 내역'),
    ]),
    # 인터페이스 이력과 계정(부서·사용자)·권한·로그만 둔다. 인터페이스 이력은 PLM·ERP 수신 기록이라 맨 위다(사용자 결정 2026-10-22)
    ('시스템 관리', 'uil-cog', [
        ('wm_interface_log', '인터페이스 이력'),
        # 사용자가 고르는 소속 부서라 사용자 앞에 둔다(사용자 결정 2026-10-26)
        ('wm_depart', '부서 정보'),
        ('wm_user', '사용자'),
        ('wm_user_group', '사용자 그룹'),
        ('wm_user_group_menu', '메뉴 권한'),
        ('wm_menu_language', '메뉴명 설정'),
        ('wm_login_log', '로그인 로그'),
        ('wm_menu_log', '메뉴 로그'),
        ('wm_system_log', '시스템 로그'),
    ]),
]

# 메뉴에서 내린 화면. MES 에서 넘어온 기준정보로, 데이터관리·비전검사 어디에서도
# 참조하지 않는다(API 도 자기 화면만 호출한다). 메뉴 행을 지우면 UserGroupMenu
# 권한이 함께 사라져 접근이 막힌다. 화면 정의·테이블·코드 마스터는 남긴다 —
# 프라퍼티마스터·사용자 화면이 코드 마스터(`fn_code_name`)를 쓴다.
# 부서정보(`wm_depart`)는 사용자 소속 부서로 시스템 관리에 다시 올렸다(사용자 결정 2026-10-26).
RETIRED_FROM_MENU = ['wm_code', 'wm_unit', 'wm_company']

# 쓰지 않기로 해 메뉴에서 내린 화면(사용자 결정, 2026-10-06). 위와 같은 방식이다.
#
# - AI 모델(`wm_vis_model`): 이때 내렸고, 모델은 Wezard 배포 목록에서 고르게 되어 2026-10-19 화면·API 를 지웠다
# - 다국어 설정 · 프라퍼티마스터: 운영에 쓰지 않는다. 다국어는
#   내부 기능으로만 남긴다(라벨 편집 팝업은 `/api/common/labels` 를 쓴다)
#
# superuser 는 메뉴 권한과 무관하게 `RW` 라 주소로는 열 수 있다
# (`AccountService.check_user_auth`). 관리자 그룹 사용자는 막힌다.
RETIRED_FROM_MENU += ['wm_multi_language', 'wm_prop_master']

# 검사양식 관리(DIG_FORM_EDIT_MENU)로 합친 옛 품질 검사양식 관리 — 권한·즐겨찾기를 옮기고 지운다(사용자 결정 2026-10-21)
MERGED_FORM_MENU = 'wm_dig_form_outgoing_form'

# 공통코드 — 디지털 양식 판정 선택지의 옛 자리. 지금 선택지는 사용자코드(항목결과 코드, judge_code.ensure_defaults)에서
# 읽는다. 같은 코드로 옮겼고 이 행은 지우지 않고 남긴다.
SYSTEM_CODES = [
    ('dig_form_okng', 'Y', 'OK', '디지털 양식 판정 OK', 1),
    ('dig_form_okng', 'N', 'NG', '디지털 양식 판정 NG', 2),
    ('dig_form_pass_na', 'Y', '합격', '디지털 양식 판정 합격', 1),
    ('dig_form_pass_na', 'N', '불합격', '디지털 양식 판정 불합격', 2),
    ('dig_form_pass_na', 'X', 'N/A', '디지털 양식 판정 해당 없음', 3),
]

DASHBOARD_MENU = 'wm_dashboard'

USER_GROUPS = [
    ('admin', '관리자'),
    ('user', '일반사용자'),
]


class Command(BaseCommand):
    help = '사용자그룹·메뉴·관리자 계정 초기 데이터를 생성한다(멱등).'

    def add_arguments(self, parser):
        parser.add_argument('--admin-username', default='admin')
        parser.add_argument('--admin-password', default=None,
                            help='생략하면 관리자 계정을 만들지 않는다.')

    @transaction.atomic
    def handle(self, *args, **options):
        GUIConfiguration.__static_init__()
        gui_codes = set(GUIConfiguration.menu_init())

        SystemOption.objects.update_or_create(
            Code='LOGO_TITLE', defaults={'Value': 'Manufacturing AI Platform'})

        for code_type, code, value, description, order in SYSTEM_CODES:
            SystemCode.objects.update_or_create(
                CodeType=code_type, Code=code,
                defaults={'Value': value, 'Description': description, '_ordering': order})

        # 항목결과 코드 — 없을 때만 넣는다(검사양식 코드 관리 화면에서 고친 값을 덮지 않는다)
        judge_codes = judge_code.ensure_defaults()

        groups = {}
        for order, (code, name) in enumerate(USER_GROUPS):
            groups[code], _ = UserGroup.objects.update_or_create(
                Code=code, defaults={'Name': name})

        menu_codes = []
        for folder_order, (folder_name, icon, items) in enumerate(MENU_TREE):
            folder, _ = MenuFolder.objects.update_or_create(
                FolderName=folder_name,
                defaults={'IconCSS': icon, '_order': folder_order, 'Parent': None})
            for item_order, (code, name) in enumerate(items):
                if code not in gui_codes:
                    raise SystemExit(f'gui.py 에 없는 메뉴코드다: {code}')
                MenuItem.objects.update_or_create(
                    MenuCode=code,
                    defaults={'MenuName': name, 'MenuFolder': folder,
                              'Url': f'/gui/{code}/default', '_order': item_order})
                menu_codes.append(code)

        # 품질 검사양식 관리는 검사양식 관리로 합쳤다(사용자 결정 2026-10-21) — 지우기 전에 권한(둘 다 있으면 높은 쪽)·즐겨찾기를 옮긴다
        merged_menu = MenuItem.objects.get(MenuCode=DIG_FORM_EDIT_MENU)
        for old in UserGroupMenu.objects.filter(MenuCode=MERGED_FORM_MENU):
            merged, created = UserGroupMenu.objects.get_or_create(
                UserGroup=old.UserGroup, MenuCode=DIG_FORM_EDIT_MENU, defaults={'AuthCode': old.AuthCode})
            if not created and 'W' in old.AuthCode and 'W' not in merged.AuthCode:
                merged.AuthCode = old.AuthCode
                merged.save(update_fields=['AuthCode'])
        for bookmark in Bookmark.objects.filter(MenuItem__MenuCode=MERGED_FORM_MENU):
            Bookmark.objects.get_or_create(User=bookmark.User, MenuItem=merged_menu)
        UserGroupMenu.objects.filter(MenuCode=MERGED_FORM_MENU).delete()

        # 화면이 없어진 메뉴는 지운다. 남겨 두면 눌렀을 때 404가 나고
        # verify_menu.py 가 계속 FAIL한다.
        stale = MenuItem.objects.exclude(MenuCode__in=menu_codes)
        if stale.exists():
            codes = sorted(stale.values_list('MenuCode', flat=True))
            UserGroupMenu.objects.filter(MenuCode__in=codes).delete()
            stale.delete()
            self.stdout.write(self.style.WARNING(
                '화면 없는 메뉴 {}건 제거: {}'.format(len(codes), ', '.join(codes))))

        stale_folders = MenuFolder.objects.exclude(
            FolderName__in=[name for name, _icon, _items in MENU_TREE])
        if stale_folders.exists():
            names = sorted(stale_folders.values_list('FolderName', flat=True))
            stale_folders.delete()
            self.stdout.write(self.style.WARNING(
                '빈 메뉴폴더 {}건 제거: {}'.format(len(names), ', '.join(names))))

        # 관리자 그룹은 전 메뉴 읽기·쓰기
        for code in menu_codes:
            UserGroupMenu.objects.update_or_create(
                UserGroup=groups['admin'], MenuCode=code, defaults={'AuthCode': 'RW'})
        # 대시보드는 로그인 첫 화면이라 모든 그룹이 읽기·쓰기다(사용자 결정 2026-10-21)
        for group in UserGroup.objects.all():
            UserGroupMenu.objects.update_or_create(
                UserGroup=group, MenuCode=DASHBOARD_MENU, defaults={'AuthCode': 'RW'})

        password = options['admin_password']
        if password:
            username = options['admin_username']
            user, created = User.objects.get_or_create(
                username=username, defaults={'is_staff': True, 'is_superuser': True})
            user.set_password(password)
            user.is_active = True
            user.save()
            UserProfile.objects.filter(User=user).update(
                UserGroup=groups['admin'], Name='관리자')
            self.stdout.write(f'관리자 계정 {"생성" if created else "갱신"}: {username}')

        # 조직은 YEST 하나다(사용자 결정, 2026-10-06). 새 사용자는 User 시그널이
        # 넣지만, 그 전에 만들어진 사용자는 소속이 빠져 있을 수 있어 여기서 채운다.
        tenant, _ = Tenant.objects.update_or_create(
            id=FIXED_TENANT_ID, defaults={'name': FIXED_TENANT_NAME})
        joined = 0
        with tenant_atomic(tenant):
            for user in User.objects.all():
                _, created = TenantMembership.objects.get_or_create(tenant=tenant, user=user)
                joined += created

        self.stdout.write(self.style.SUCCESS(
            f'사용자그룹 {len(groups)}개 / 메뉴폴더 {len(MENU_TREE)}개 / 메뉴 {len(menu_codes)}개'
            f' / 조직 {tenant.name} (소속 추가 {joined}명) / 항목결과 코드 추가 {judge_codes}건'))
