# 검사 분류(대분류 › 중분류 › 비전검사항목) 구현 계획

> 실행: superpowers:executing-plans(또는 subagent-driven-development)로 이 문서 순서대로 한다. 단계는 체크박스(`- [ ]`)로 표시한다.

**목표:** 검사 관리 > 검사 분류 관리에서 대분류·중분류(양식 매핑)·비전검사항목을 한 트리로 관리하고, 비전 데이터 관리 메뉴와 양식 편집기의 비전 연결이 그 분류를 따른다.

**구조:** 새 테넌트 테이블 `vision_data_category`(대분류·중분류 행) + `vision_data_item.category_id`. 화면은 메뉴 코드 `wm_data_item` 을 검사 관리로 옮겨
트리 + 상세(항목결과 코드관리 모양)로 다시 쓴다. 분류 API 는 `/api/item/category`, 비전검사항목 API 는 지금 `/api/item/item_admin` 에 `category_id` 를 더한다.

**설계:** [docs/superpowers/specs/2026-10-21-inspection-rework-design.md](../specs/2026-10-21-inspection-rework-design.md) §2-1·2-2·2-4·3·4·5·8·9

## 공통 제약

- 작업은 worktree `.worktrees/inspection-rework`(브랜치 `feat/inspection-rework`, `.env`·`.admin_pw` 심볼릭 링크). 8123 개발 서버 폴더는 main 그대로
- 모델·마이그레이션은 `migration/inspection-rework` 브랜치(모델·마이그레이션 파일만, plan 2 의 `mst_product_form` 변경도 같은 마이그레이션). 공유 개발 DB 에 `migrate`·시드를 돌리지 않는다 — 담당자가 적용한다
- 테스트는 `--settings=configurations.test_settings`, 고친 범위만. e2e 는 마이그레이션 적용 뒤 worktree 서버(8124, `E2E_BASE_URL`)로, `E2E-` 데이터만 만들고 지운다
- 사용자 문구는 `~합니다` 체. 값은 화면에 `.text()`·`$('<option>').text()` 로 넣는다. 조회는 `AjaxUtil.getAsyncData`, 변경은 `postAsyncData`
- `/api/v1` 은 바꾸지 않는다(카탈로그에 분류를 내보내지 않는다)
- 메뉴 행은 `seed_initial` `MENU_TREE` 로 바꾼다(마이그레이션 아님). 반영은 담당자가 `seed_initial` 을 다시 돌린다

---

### Task 0: worktree

- [ ] `git worktree add .worktrees/inspection-rework -b feat/inspection-rework` → `.env`·`.admin_pw` 링크 → 설계·계획 문서 4개를 이 브랜치에 커밋(`docs: 검사 분류·검사 작업·거치대 결과 불러오기 설계와 계획`)

### Task 1: 모델·마이그레이션 (`migration/inspection-rework`)

**Files:** `domain/models/data.py`, `domain/models/basic.py`, `domain/migrations/0019_inspection_rework.py`(생성), `tests/test_inspection_category.py`(생성)

`domain/models/data.py` — `InspectionItem` 위에(앞에서 참조하므로):

```python
class InspectionCategory(TenantOwnedModel):
    """검사 분류. 대분류(parent 없음, 양식 구분) › 중분류(대분류 아래, 디지털 양식 코드 매핑) 두 단계다.

    비전검사항목은 중분류 하나에 속한다(`InspectionItem.category`). 3단계 금지·양식 검증은 서비스(domain/services/data/category.py)가 한다.
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
```

`InspectionItem` 에: `category = models.ForeignKey(InspectionCategory, related_name='items', null=True, blank=True, on_delete=models.PROTECT, verbose_name='검사 분류')`
(주석: 중분류만 가리킨다. null = 미분류).
`ProductForm.Meta.unique_together = [['PartNo', 'FormCode']]`, docstring "품번 하나에 양식 여러 개(N:M)".

- [ ] 실패하는 테스트 `tests/test_inspection_category.py` `CategoryModelTest(TestCase)`(setUp `reset_tenant_cache()`, `tenant_atomic()` 안에서 만든다):
  같은 이름 대분류 두 번 IntegrityError / 다른 대분류 아래 같은 이름 중분류는 된다 / 같은 대분류 아래 같은 이름 IntegrityError /
  같은 `form_code` 두 중분류 IntegrityError, 빈 `form_code` 여럿은 된다 / 대분류에 `form_code` IntegrityError / 중분류에 `form_type` IntegrityError /
  비전검사항목이 있는 중분류 delete → ProtectedError / `ProductForm` 같은 품번 다른 양식 둘 저장, 같은 쌍 두 번 IntegrityError
  (IntegrityError 는 `transaction.atomic()` 안에서 `assertRaises`)
- [ ] 모델 작성 → `makemigrations domain --name inspection_rework` → 파일 끝 operations 에 0017 과 같은 RLS `run_sql`(`from ._pgsql import run_sql`,
  `RLS_TABLE = 'vision_data_category'`, POLICY `vision_data_category_tenant_scope`, reverse 포함) → `sqlmigrate domain 0019` 로 DDL 확인
- [ ] 테스트 통과, `makemigrations --check --dry-run` 변경 없음
- [ ] 커밋(모델 2파일·마이그레이션만, `feat: 검사 분류 테이블·비전검사항목 소속·품목 검사양식 N:M 마이그레이션`) → 그 커밋에 `migration/inspection-rework` 브랜치 → 테스트 파일은 다음 커밋
- [ ] push 는 사용자 요청 때. 담당자에게 알릴 내용: `migrate`(0019) 뒤 `seed_initial`(메뉴, Task 4 이후)·`seed_vision_items`(Task 8 이후)

### Task 2: 분류 서비스·API `/api/item/category`

**Files:** `domain/services/data/category.py`(생성), `app/views/item/category.py`(생성), `domain/gui.py`, `tests/test_inspection_category.py`

서비스(모두 `tenant_atomic()` 안에서 불린다 — `/api/item` 디스패치가 감싼다):

```python
def tree(tenant):
    """대분류 → 그 중분류 → 그 비전검사항목 순서의 평면 목록(트리 그리드용). 미분류 항목은 맨 끝 가상 행(id 'cat0') 아래."""
def save_major(tenant, *, category_id=None, name, form_type, sort_order=0, description=''):
def save_minor(tenant, *, category_id=None, parent_id, name, form_code='', sort_order=0, description=''):
def delete_category(tenant, category_id):
def mappable_forms(form_type):
    """그 구분의 섹션 양식 중 가장 높은 버전이 사용 중인 것 [{code, title, version}] — receipts.latest_forms 와 같은 규칙에 LayoutType='SECTION'."""
```

- 검증 오류는 `ItemApiError`(400)로: 이름 빈 값 "분류 이름을 입력해 주세요." / 대분류 `form_type` 없음 "양식 구분을 골라 주세요." /
  `parent_id` 가 대분류가 아님 "대분류를 골라 주세요." / 양식이 `mappable_forms(parent.form_type)` 에 없음 "같은 구분의 사용 중인 섹션 양식을 골라 주세요." /
  다른 중분류에 매핑된 양식 "<중분류>에 이미 매핑된 양식입니다." / 이름 중복 "같은 이름의 분류가 있습니다." /
  삭제 막힘 "중분류가 있는 대분류는 지울 수 없습니다." · "비전검사항목이 있는 중분류는 지울 수 없습니다."
- 대분류 `form_type` 을 바꿀 때 매핑된 중분류가 있으면 막는다 "양식을 매핑한 중분류가 있어 양식 구분을 바꿀 수 없습니다."
- `tree` 행 키: `id`('cat<id>' 또는 'item<id>'), `parent_id`, `kind`(`major`·`minor`·`item`·`none`), `category_id`, `name`(항목은 "코드 · 이름"), `form_type`·`form_type_label`(대분류),
  `form_code`·`form_title`(중분류, 최신 버전 제목 — 매핑 양식이 사용 중이 아니면 제목 뒤 "(사용 중 아님)"), `sort_order`, `description`, 항목은 `item_id`·`code`·`task_type_label`·`status`·`status_label`·`capture_method_label`

API `app/views/item/category.py`(item 모듈 규약: `READ_ACTIONS = frozenset({'tree', 'forms'})`, 나머지 POST, `context.request.tenant`):
`tree` → `{'rows': tree(...)}` / `forms`(form_type) → `{'forms': [...]}` / `save_major`·`save_minor` → `{'success': True, 'message': '', 'id': n}` / `delete` → `{'success': True, 'message': ''}`.
`domain/gui.py` `taskview_menu_code_map` 에 `m['item/category'] = ['wm_data_item']`.

- [ ] 실패하는 테스트 `CategoryApiTest(ItemApiTestCase)`(`tests/test_item_api.py` 의 베이스를 import, `menus = {'wm_data_item': 'RW'}`):
  트리 순서(대분류 sort_order → 중분류 → 항목, 미분류 가상 행) / 대분류 등록·수정·중복 / 중분류 등록(양식 매핑: 같은 구분 섹션 최신 사용 중만 — 품질 양식을 수입 대분류에 매핑하면 400, GRID 양식 400, 다른 중분류에 매핑된 양식 400) /
  3단계 거절 / 삭제 막힘 2가지·빈 것은 지워짐 / 매핑 풀기(form_code '') / 메뉴 R 만이면 save 403, tree 200 / `forms` 응답
- [ ] 구현 → 통과 → `python scripts/verify/verify_permission_map.py` PASS → 커밋 `feat: 검사 분류 등록·수정·삭제·양식 매핑 API`

### Task 3: 비전검사항목 API 에 소속 중분류

**Files:** `app/views/item/item_admin.py`, `tests/test_item_api.py`

- `_create`·`_update` 에 `category_id`(빈 값 = 미분류). 중분류가 아니면 `ItemApiError('중분류를 골라 주세요.')`. `_update` 는 키가 없으면 지금 값 유지(촬영 방식과 같은 방식)
- `_list` 행·`_detail` 에 `category_id`·`category_label`("대분류 › 중분류", 미분류면 "미분류")
- 플랫폼 관리자 검사는 그대로

- [ ] 실패하는 테스트(`ItemAdminApiTest` 에 더함): 등록 시 소속 / 수정으로 옮기기·미분류로 / 대분류 id 거절 / 키 없으면 유지 / list·detail 키
- [ ] 구현 → 통과 → 커밋 `feat: 비전검사항목에 소속 중분류를 등록·수정한다`

### Task 4: 검사 분류 관리 화면 (`wm_data_item` 재사용)

**Files:** `app/templates/data/item_list.html`(다시 씀), `domain/gui.py`(65행 이름), `domain/management/commands/seed_initial.py`(MENU_TREE), `app/views/system/menus.py`(`PLATFORM_ADMIN_MENU_CODES`), `tests/test_dig_form.py`(SeedInitial 메뉴 확인), `tests/e2e/test_menu.py`, `tests/e2e/test_write_paths.py`, `tests/e2e/test_crud.py`, `tests/e2e/test_inspection_category.py`(생성)

- `gui_dc['wm_data_item'] = cls.gui_item('검사 분류 관리', 'data/item_list.html')`. MENU_TREE: 비전 검사 관리에서 빼고 검사 관리 맨 끝 `('wm_data_item', '검사 분류 관리')`
- `PLATFORM_ADMIN_MENU_CODES` 에서 `wm_data_item` 을 뺀다(남는 코드가 없으면 상수와 그 분기·docstring 문단을 지운다)
- 템플릿(본보기 `app/templates/dig_form/judge_code.html`):
  - 목록 머리 [대분류 등록] `#btnNewMajor`·[중분류 등록] `#btnNewMinor`·[비전검사항목 등록] `#btnNew`(관리자만 보임 — `can_manage_items` 는 `tree` 응답에 `user_is_platform_admin` 으로 싣는다), 그리드 `#main-grid`
    `grid.setTreeData(rows, { treeColumn: 'name', idField: 'id', parentField: 'parent_id', expandAll: true })`. 컬럼: 이름·유형/양식 구분·매핑 양식·촬영 방식·상태
  - 상세 3벌(`.major-only`·`.minor-only`·`.item-only` 로 칸을 보이고 숨김). 대분류·중분류는 `DetailForm` [수정]·[삭제](메뉴 W). 비전검사항목 상세·배정 인원·삭제 승인/반려는 지금 item_list.html 코드를 옮기고 `#category_id` select(중분류 목록, "미분류") 를 더한다
  - 모달 `#majorCreateModal`(이름 필수·양식 구분 필수·순서·설명), `#minorCreateModal`(대분류 필수 — 고른 행의 대분류를 기본값·이름 필수·매핑 양식·순서·설명), `#itemCreateModal`(지금 것 + 중분류, 고른 행의 중분류 기본값)
  - 중분류 매핑 양식 select 는 대분류 `form_type` 으로 `category?action=forms` 를 부른다. 첫 옵션 "(매핑 없음)"
  - 다시 읽은 뒤 `grid.setSelectionByRowId(id)` + `detail.bind(row)`(judge_code.html 197–198행과 같다)
- e2e `created_item` 픽스처는 `#btnNew` 를 그대로 쓰되 트리 화면에 맞춘다(`tests/e2e/test_write_paths.py:80–101`). `test_crud.TestItemDeletionReview._select` 를 트리 행 선택으로
- `tests/e2e/test_menu.py`: `EXPECTED_FOLDERS`·`TestItemAdminMenu`(비전 검사 관리 끝 → 검사 관리 끝, 관리자가 아니어도 메뉴 권한이면 보임)

- [ ] 실패하는 단위 테스트: `seed_initial` 뒤 `wm_data_item` 이 검사 관리 폴더·이름 "검사 분류 관리"(`tests/test_dig_form.py:1071` 본보기)
- [ ] gui·MENU_TREE·menus.py → 통과 → `verify_menu.py`(로컬 DB 는 담당자가 seed 하기 전이라 건너뛰고 보고에 적는다)·`verify_permission_map.py`
- [ ] 템플릿 → `node scripts/verify/verify_screen_js.js` → 실패하는 e2e `tests/e2e/test_inspection_category.py`(마이그레이션 적용 뒤, 8124):
  대분류·중분류(E2E-) 등록→트리에 보임→중분류에 양식 매핑→수정→삭제 / 항목이 있는 중분류 삭제는 안내 / 비전검사항목 등록 시 중분류 / 관리자가 아닌 메뉴 RW 사용자는 [비전검사항목 등록]이 없고 분류는 고친다
- [ ] e2e 통과(`test_inspection_category.py`, `test_menu.py`, `test_write_paths.py -k item`, `test_crud.py -k Item`) → `verify_modals.py`·`verify_buttons.py` → 커밋 `feat: 검사 관리에 검사 분류 관리 화면 — 분류 트리와 비전검사항목 관리를 합친다`

### Task 5: 비전 데이터 관리 메뉴를 분류 트리로

**Files:** `app/views/system/menus.py`, `tests/test_menu_tree.py`

`_item_nodes` 를 바꾼다(docstring 의 트리 그림도):

```python
items = list(ItemAccessService.visible_items(user=user, tenant=current_tenant())
             .order_by('display_order', 'code').values_list('id', 'name', 'task_type', 'category_id'))
categories = {c.id: c for c in InspectionCategory.objects.for_tenant(current_tenant()).select_related('parent')}
```

- 중분류별로 항목을 묶고, 대분류(`sort_order`, 이름) → 중분류(`sort_order`, 이름) 순서로 노드를 만든다. 항목이 없는 중분류·대분류는 만들지 않는다. 소속 없는 항목은 `{'objId': 'cat0', 'objNm': '미분류'}` 아래(맨 끝)
- 분류 노드 `{'objId': 'cat<id>', 'objNm': 이름, 'objUrl': '', 'menuIconCls': None, 'nodes': [...], 'ismanual': False, 'isbookmark': False, 'menuDepth': 2|3}`
- 항목 노드는 끝 메뉴(`nodes: []`, `menuDepth: 4`): 홈 권한이 있으면 `objId 'item<id>_wm_data_item_detail'`·`objUrl '/gui/wm_data_item_detail/?inspection_item=<id>'`,
  없으면 권한 있는 첫 하위 화면(치수 측정은 `MEASUREMENT_CHILD_MENU_CODES` 안에서). 하나도 없으면 항목을 빼고, `tabTitle` 은 항목 이름

- [ ] 실패하는 테스트(`tests/test_menu_tree.py`): 대분류 › 중분류 › 항목 구조와 순서 / 빈 분류 감춤 / 미분류 맨 끝 / 홈 권한 없으면 데이터 목록 URL / 치수 측정 항목에 라벨링 권한만 있으면 노드 없음 / 배정 안 된 항목은 안 보임
- [ ] 구현 → 통과 → 커밋 `feat: 비전 데이터 관리 메뉴를 대분류 › 중분류 › 비전검사항목으로 묶는다`

### Task 6: 좌측 메뉴 4단계·비전검사항목 홈 화면 버튼

**Files:** `app/templates/app/left_menu_class.html`, `app/static/assets/css/SF-Custom.css`(필요하면), `app/views/item/item_home.py`, `app/templates/data/item.html`, `tests/test_item_api.py`, `tests/e2e/test_menu.py`, `tests/e2e/test_data_screens.py`

- 템플릿: 3단계(`side-nav-third-level`)의 `li` 도 `nodes` 가 있으면 폴더로 그리고 그 안에 `<ul class="side-nav-forth-level">` 잎을 그린다(잎 마크업은 지금 40행과 같고 `data-tab-title` 은 `subItem.tabTitle || subName`)
- 접힌 사이드바: 820·967행 선택자에 `.side-nav-forth-level` 을 더한다. 3단계 폴더는 펼침 메뉴 안에서 collapse 로 아래로 펼친다(새 flyout 을 만들지 않는다 — `ponytail:` 주석에 "4단계 flyout 이 필요하면 positionCondensedSubMenuFlyout 를 재귀로")
- 421–424·437–438행 collapse 초기화를 하위 단계까지(`.side-nav-second-level .collapse` 가 이미 자손 전부를 잡는지 확인하고 아니면 넓힌다)
- 홈 API `_detail` 에 `screens`: `ITEM_CHILD_MENUS` 중 홈을 뺀 것 가운데 사용자 메뉴 권한(`AccountService.check_user_auth`)이 있고 치수 측정이면 `MEASUREMENT_CHILD_MENU_CODES` 안인 것 `[{code, name}]`
- 홈 템플릿 머리에 버튼 줄(`#screenButtons`, 버튼마다 `data-tab=code`, href `/gui/<code>/?inspection_item=<id>`) — 지금 `openTab` 이 연다. `openTab` 의 제목을 "항목명 · 화면명"으로

- [ ] 실패하는 테스트: 홈 `screens` — 권한 있는 것만, 치수 측정은 데이터 목록만
- [ ] 구현 → 통과 → `verify_screen_js.js` → e2e(마이그레이션 적용 뒤): `test_menu.py` `TestItemSubtree` 를 4단계로(대분류 펼침 → 중분류 펼침 → 항목 클릭 = 홈 탭) /
  접힌 사이드바에서 같은 경로로 연다 / 홈 버튼으로 데이터 목록 탭이 "항목명 · 데이터 목록"으로 열린다(`test_data_screens.py:91` 본보기)
- [ ] CSS 를 고쳤으면 `scripts/verify/verify_layout_stable.py`(절차는 docs/DEVELOPMENT.md) → 커밋 `feat: 좌측 메뉴 4단계와 비전검사항목 홈의 화면 버튼`

### Task 7: 양식 편집기 — 분류로 묶은 연결·모두 연결·미연결 경고

**Files:** `app/views/system/form_edit.py`(117–124행), `app/templates/system/form_edit.html`(823·1034–1044·2588–2601행 부근), `tests/test_dig_form.py`(`FormEditVersionTest`), `tests/e2e/test_dig_form.py`

- `vision_items` 에 `form_code` 파라미터. 응답 `items` 행에 `category_id`·`group`("대분류 › 중분류" 또는 "미분류"), 그리고 `mapped`(그 코드에 매핑된 중분류 `{id, label}` 또는 null) 를 함께 준다
  (`items` 와 나란히 `mapped` 키 — `verify_response_keys.py` 로 확인). 정렬: 대분류·중분류 순서 → `display_order` → 코드
- JS: `FORM_EDIT_VISION_ITEMS` 를 양식마다 다시 읽는다(편집기를 열 때 `form_code` 와 함께). `.it-vision` 은 "비전 연결 없음" → `mapped` 그룹 `optgroup`("이 양식 분류 — <label>") → 나머지 `group` 별 `optgroup`. 중지 항목 규칙(1040행)은 그대로
- 편집기 위쪽 한 줄: 매핑이 있으면 "검사 분류: <label>", 없으면 안내 "검사 분류 관리에서 이 양식을 중분류에 매핑하면 그 항목이 먼저 나옵니다."
- 점검항목 섹션의 이미지 열이 있으면 섹션 도구줄에 [이미지 칸 모두 연결](select + 적용) — 그 섹션 `.it-vision` 전부에 같은 값
- 저장 전: `.it-vision` 값이 빈 이미지 칸 수를 세어 0보다 크면 `Alert.confirm('비전검사항목이 연결되지 않은 이미지 칸이 N개 있습니다. 그대로 저장합니까?')`
- 이 계획에서는 치수 측정 제외(`.exclude(task_type=MEASUREMENT)`)를 그대로 둔다 — 없애는 것은 plan 3

- [ ] 실패하는 테스트: `vision_items` 의 `group`·정렬·`mapped`(매핑 있음/없음/다른 코드)
- [ ] 구현 → 통과 → e2e(`tests/e2e/test_dig_form.py` 에 더함): 매핑한 양식 편집기에서 맨 위 그룹이 그 중분류 항목 / [이미지 칸 모두 연결] 후 저장하면 새 버전·모든 칸 연결 / 미연결 칸이 있으면 확인창
- [ ] `verify_modals.py`·`verify_buttons.py`·`verify_dig_form_width.py` → 커밋 `feat: 양식 편집기의 비전 연결을 검사 분류로 묶고 섹션 전체 연결·미연결 경고를 둔다`

### Task 8: 시드 — 분류·소속·신규 비전검사항목

**Files:** `domain/management/commands/seed_vision_items.py`, `tests/test_seed_vision_items.py`

- `CATEGORIES = [(대분류, form_type, [중분류...]), ...]` — 설계 §8 표 순서. `ITEMS` 튜플에 중분류 이름을 더한다: `(code, name, type, minor, classes)`
- handle: 대분류는 `get_or_create(tenant, parent=None, name=…, defaults={form_type, sort_order})`, 중분류는 `get_or_create(tenant, parent=major, name=…, defaults={sort_order})`(양식 매핑 없음).
  항목은 지금처럼 `get_or_create`; 새로 만들면 `category=minor`, 이미 있으면 `category_id` 가 null 일 때만 채운다. 출력에 분류 만든 수
- 신규 9개(TAB-PRT·EPD·FAN·HTR·SNS·BLT·CFN·CBL·EXT)와 클래스·기존 항목 클래스 추가는 설계 §8 표 그대로. 색은 기존 팔레트에서 고르고 `is_defect` 는 정상 클래스(`fan_ok`)만 False
- `DESCRIPTIONS` 에 신규 9개 — 기존 설명과 같은 머리 7개(`text()`·`RIG` 상수 쓰는 방식 그대로). 근거 시트 원문은 `tmp/docs/NEOCON_C2_문서대장_시트정리/` 의 해당 시트에서 인용하고 시트 번호·행을 적는다.
  "■ 촬영 방법" 의 높이·거리 같은 값은 "사용자 결정 — 현장 시험 촬영 뒤 고침"으로 표시. 현업 확인 남은 것(설계 §9 D21~D25)은 "※ 근거와 결정"에 "확인 필요"
- 기존 항목 설명은 고치지 않는다(이름 변경도 관리 화면에서)

- [ ] 실패하는 테스트: 분류 4·6개와 form_type / 각 항목 소속(설계 §8 표) / 두 번 돌려도 같음 / 이미 소속이 있는 항목은 그대로 / 신규 9개 유형·클래스 / 기존 항목 클래스 추가 / 새 설명도 `SECTIONS` 머리를 모두 가짐 / 양식 매핑 없음
- [ ] 구현 → 통과 → 커밋 `feat: 검사 분류 기본 데이터와 비전검사항목 9개를 시드에 더한다`

### Task 9: 문서·검증·병합

**Files:** `docs/DATA_MODEL.md`(새 테이블·`vision_data_item.category_id`·`mst_product_form` N:M·마이그레이션 0019 행·RLS 15개 목록), `AGENTS.md`(RLS 14개 → 15개 문장), `docs/DECISIONS.md`(사용자 결정 2026-10-21 행: 검사 분류 구조 — 설계 §9 D1~D11·D16~D18, 근거 링크),
`docs/FEATURES.md`(§1 메뉴 트리·비전검사항목 관리 절 → 검사 분류 관리·비전 데이터 관리 트리·양식 편집기 연결), `docs/STATUS.md`, `tests/pg/test_rls_and_raw_sql.py`(14 → 15)

- [ ] 문서 → `verify_links.py`·`verify_korean_only.py`·`verify_naming.py`·`verify_tokens.py`·`verify_response_keys.py`·`verify_menu.py`·`verify_permission_map.py`
- [ ] 고친 범위 단위 테스트(`tests.test_inspection_category tests.test_item_api tests.test_menu_tree tests.test_dig_form tests.test_seed_vision_items`) 통과
- [ ] 권한·메뉴 템플릿·마이그레이션을 바꿨으므로 전체 단위(`manage.py test tests`, 약 2~3분)를 돌려도 되는지 사용자에게 묻는다
- [ ] 커밋 `docs: 검사 분류를 데이터 모델·결정·기능 문서에 적는다` → 최신 main 을 받아 합치고 사용자 요청 때 main 병합·push
