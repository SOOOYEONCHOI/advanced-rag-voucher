# 데이터 모델

테이블·관계·RLS·마이그레이션·시드·파일 저장 경로를 다룬다.
구성 요소와 API 규약은 [ARCHITECTURE.md](ARCHITECTURE.md), 화면별 기능은
[FEATURES.md](FEATURES.md), 실행·검증 명령은 [DEVELOPMENT.md](DEVELOPMENT.md),
"근거:" 줄의 결정 ID 는 [DECISIONS.md](DECISIONS.md) 에 있다.

## 1. 기본 규칙

| 항목 | 값 | 근거 |
|---|---|---|
| DB | PostgreSQL 16 하나. 이름은 `DB_NAME`(기본값 `yest`), 스키마는 `DB_SEARCH_PATH`(기본값 `public`) | `configurations/settings.py` |
| 모델 위치 | `domain/models/` — `basic` · `system` · `user` · `dig_form` · `interface` · `data` · `vision`. app label 은 전부 `domain` | |
| 스키마 관리 | Django 마이그레이션만. SQL 함수·뷰·RLS 도 마이그레이션 안에 있다 | §7 |
| 기본 PK | `BigAutoField`. MES 계열 모델은 PK 를 명시한다 — 대부분 `AutoField`(int4), 로그(`sys_log`·`login_log`·`menu_use_log`)·`seq_maker` 는 `BigAutoField`, `menu_item` 은 `MenuCode`, `user_profile` 은 `User` 1:1 | |
| 시각 | `USE_TZ=False`, `TIME_ZONE='Asia/Seoul'`. 컬럼은 naive `timestamp`(KST)다. `/api/v1` 응답만 `to_utc_z()` 가 UTC `Z` 로 바꾼다 | (DECISIONS DEC-016) |
| 열거형 | PostgreSQL enum 을 쓰지 않는다. `CharField(choices=TextChoices)` | |
| 테스트 DB | `configurations.test_settings` 는 SQLite 메모리 DB 다. PostgreSQL 전용 DDL(§6·§7)은 건너뛴다 | |

### 이름 규칙

| 접두어 | 영역 | 감사 컬럼 |
|---|---|---|
| 접두어 없음 (`user_profile`, `menu_item` …) | 시스템·사용자 (MES 계열) | `AbstractAuditModel`: `_status` · `_created` · `_modified` · `_creater_id` · `_modifier_id` |
| `vision_data_*` | 데이터 관리 | `created_at` / `updated_at` (모델마다 다름) |
| `vision_*` | 비전 검사 | `TimestampMixin`: `created_at` · `updated_at` |
| `dig_form*` | 디지털 양식 (MES 방식) | `AbstractAuditModel` |
| `if_*` | 외부 인터페이스 수신 (MES 방식) | `AbstractAuditModel` |
| `mst_*` | 마스터(master) — 품목·BOM·입고·품목 검사양식, 이후 생산지시 (MES 방식) | `AbstractAuditModel` |
| `integration_client` (예외) | Wezard 연동 키 — 접두어가 없지만 비전 쪽 모델 | `TimestampMixin` |

MES 계열 컬럼은 `PascalCase`(`"MenuCode"`, `"UserGroup_id"`)라 raw SQL 에서 큰따옴표가 필요하다.

## 2. 시스템 · 사용자 · 권한

`domain/models/system.py` · `user.py` · `basic.py`. 사용자는 Django `auth_user` 를
그대로 쓰고 `user_profile` 로 확장한다. 데이터 관리·비전 검사 쪽에 별도 사용자 테이블은 없다.
새 사용자는 `auth_user` `post_save` 시그널이 `UserProfile` 과 `TenantMembership` 을 만든다(`domain/models/user.py`).

| 모델 | db_table | 무엇 | 주요 관계 |
|---|---|---|---|
| `User` (Django) | `auth_user` | 로그인 계정. 비전검사 클라이언트의 서비스 계정도 여기 있다 | |
| `UserProfile` | `user_profile` | 사용자명·사용 언어·소속 | `User` 1:1(PK), `UserGroup`·`Factory`·`Company`·`Depart` FK |
| `UserGroup` | `user_group` | 메뉴 권한 묶음. seed 는 `admin`·`user` 두 개를 만든다 | |
| `UserGroupMenu` | `user_group_menu` | 그룹 × 메뉴코드 → `AuthCode`(`R`/`RW`). **인가는 이것 하나다** | `UserGroup` FK, `MenuCode` 는 문자열 |
| `MenuFolder` / `MenuItem` | `menu_folder` / `menu_item` | 좌측 메뉴. `MenuItem.MenuCode` = `gui.py` 의 gui_code | `MenuFolder.Parent` 자기참조 |
| `Bookmark` | `bookmark` | 즐겨찾기 | `User`, `MenuItem`(`MenuCode` 컬럼) |
| `SystemCode` / `UserCode` | `sys_code` / `user_code` | 코드 마스터. `fn_code_name()` 이 읽는다 | |
| `LabelCode` / `LabelCodeLanguage` | `label_code` / `label_code_lang` | 화면 라벨 다국어 | |
| `GridColumn` / `GridColumnLanguage` | `grid_col` / `grid_col_lang` | 그리드 컬럼 다국어 | |
| `SystemOption` | `sys_option` | 시스템 옵션(`LOGO_TITLE` 등) | |
| `SystemLog` | `sys_log` | 화면 "시스템 로그"의 한 줄. 트레이스는 `LOG_DIR` 파일에 있다 | |
| `LoginLog` | `login_log` | 로그인 시도. `Username`·`UserAgent`·`FailReason` 포함 | `User` FK(null 허용) |
| `MenuUseLog` | `menu_use_log` | 메뉴 사용 이력 | `User` FK |
| `AttachMaster` / `AttachFile` | `attach_master` / `attach_file` | MES 첨부파일. MES 첨부 경로는 2026-10-07 지웠다. 지금은 디지털 양식 참고사진(`TableName='dig_form_section'`·`AttachName='editor'`·`DataPk`=섹션 id, 파일은 `MEDIA_ROOT/dig_form_section/`)과 이미지 칸 사진(`dig_form_item_result`·`cell`·칸 결과 id, `MEDIA_ROOT/dig_form_result/`), 고정 이미지 칸 그림(`dig_form_item`·`ref`·칸 id, `MEDIA_ROOT/dig_form_item/`)만 쓴다(§9) | |
| `Factory` · `Company` · `Depart` · `Unit` | 같은 이름 | `user_profile` FK 대상인 최소 기준정보. `Depart` 는 사용자 소속 부서로 시스템 관리 "부서 정보"에서 관리하고(평면 목록, 코드·이름 각각 고유), 나머지는 메뉴에서 내렸다 | |

그 밖에 `prop_master`·`prop_data`·`class_master`·`class_data`·`seq_maker`·`doc_form`·`doc_result`
가 MES 공통 기반으로 남아 있다.

### 디지털 양식 (`dig_form_*`)

`domain/models/dig_form.py`. 팀원 MES `feature/dig-form` 에서 옮겼다. MES 계열이라 조직 구분·RLS 가 없다.

| 모델 | db_table | 무엇 | 주요 관계 · 제약 |
|---|---|---|---|
| `DigForm` | `dig_form` | 양식(문서헤더). `Code`(`DF`+4자리, 시퀀스 `dig_form_code_seq`)·`Version`·`LayoutType`(`GRID` 칸 단위 / `SECTION` 양식 편집)·`FormType`(`INCOMING` 수입검사 / `OUTGOING` 품질검사, DB 기본값 `OUTGOING`)·`UseYN`·`FixedTopContent`(맨 위 머리글 칸 배치. JSON 문자열을 담는 `TextField`. 머리글을 더 두려면 `HEADER` 섹션) | unique(`Code`, `Version`) |
| `DigFormSection` | `dig_form_section` | 섹션. `SectionType` = `PHOTO`(참고사진, `Content` 는 에디터 HTML) / `INSPECTION`(점검항목 표 하나) / `HEADER`(머리글 섹션, `Content` 는 `FixedTopContent` 와 같은 칸 목록 JSON — 칸 `dig_form_item` 이 없다). GRID 양식은 섹션 1개다 | `DigForm`(PROTECT) |
| `DigFormItem` | `dig_form_item` | 칸. `RowType` H(머리줄)/D(본문)/S(섹션 이미지, §9)·위치·병합·`InputYN`·`ResultType`(T 문자·N 숫자·S 판정·B 체크·I 이미지. R 고정 이미지 — 입력칸이 아니고 `Content`=그림 첨부 id. 섹션 양식 열 제목 칸은 열 종류 표시 — 비면 글자, M 행마다 지정, R 고정 이미지)·`CodeGroup`·상하한·`VisionItem`(이미지 칸에 연결한 비전검사항목, null) | `DigFormSection`(PROTECT)·`DigFormWorkClass`(PROTECT, null)·`InspectionItem`(`VisionItem`, SET_NULL, null). unique(섹션, 행, 열), 입력칸은 `ResultType` 필수, 병합 1 이상 |
| `DigFormWorkClass` | `dig_form_work_class` | 항목별 작업 분류(대·중·소) | |
| `DigFormResult` | `dig_form_result` | 작성건. `WriteDate`(새 작성건을 만든 날 — 서버가 넣고 이어쓰기에서 바꾸지 않는다)·`WorkOrderNumber`(입고번호/WO)·`State`(`working` 작성 중 / `done` 완료, 되돌리지 않는다)·`Round`(같은 양식·번호의 차수 — 완료 뒤 새로 쓰면 오른다)·`HeaderValues`(머리글 입력 항목 값 — JSON `{키: 값}` 문자열을 담는 `TextField`, 키는 양식 머리글·머리글 섹션의 직접 입력 `result.extra.<키>` → `<키>`, 목록 항목 `result.field.<키>` → `field.<키>`(글자)와 `field.<키>@code`(목록에서 고른 코드, 직접 쓴 값이면 없음). 목록 항목은 `domain/services/dig_form_fields.py`) | `DigForm`(PROTECT) |
| `DigFormItemResult` | `dig_form_item_result` | 칸 결과. 칸 유형에 따라 `TextResult`·`NumberResult`·`ComboResult`·`CheckResultYN` 중 하나. 칸의 작업자는 `_modifier_id` | unique(작성건, 칸) |

판정 선택지는 **항목결과 코드**(`user_code`)다 — 묶음 `dig_form_judge_code`(`Parent` 없음) → 그룹(`Code` = 칸 `CodeGroup`) → 결과 코드
(`Code` = 작성 결과 `ComboResult`, `Type` = 판정 의미 `Y` 합격·`N` 불합격·`X` 해당없음, `_order` = 순서). 기본 데이터는 §8 `seed_initial`,
쓰는 곳은 `domain/services/judge_code.py`. 그룹·결과 코드는 문자열로 이어지므로 쓰는 중이면 코드값을 바꾸지 않는다.
옛 `sys_code` `dig_form_okng`·`dig_form_pass_na` 5행은 같은 코드로 옮겼고 지우지 않고 남겼다(읽는 코드는 없다).

### 품목 · BOM (`mst_*`)

근거: DECISIONS 사용자 결정 2026-10-19.

`domain/models/basic.py`. PLM 품목·BOM 수신건(아래 `if_plm_part_bom`)을 `python manage.py apply_interface <수신건 id>`
(`domain/services/plm_bom.py`)가 반영해 만든다. 조회 화면은 기준정보 > 품목·BOM 조회다. MES 계열이라 조직 구분·RLS 가 없다.

| 모델 | db_table | 무엇 | 주요 관계 · 제약 |
|---|---|---|---|
| `Product` | `mst_product` | 품목. `Code` = PLM `Part(ERP)`(품번`.`리비전, 예 `MEC15836.B`) — 리비전이 오르면 새 품목이다. `PartNo`·`Revision`·`Version`(PLM 버전 `B.3`)·`Name`(PLM 이름이 기준. ERP 품목명은 40자에서 잘린다)·`PartType`(FSC·기구 UPGVC·기구·구매품, 선택지로 고정하지 않는다)·`Spec`·`MaterialGroup`·`Material`·`PostProcess`(후처리)·`PartState`·`PlmCreatedDate`·`PlmVersionDate`, 3D(`Model3dType`·`No`·`Version`·`State`·`Modified`)·2D(`Drawing2dNo`·`Version`·`State`·`Modified`). 지우지 않는다 | unique(`Code`) |
| `Bom` | `mst_bom` | 부모-자식 한 쌍. `Qty`(부모 하나에 드는 수량, Decimal 18,3)·`Seq`(원본에서 부모 아래 나온 순서). 장비 트리는 `Parent` 에서 재귀로 펼친다 | `Product`(`Parent`·`Child`, PROTECT). unique(`Parent`, `Child`), `Qty > 0`(`ck_mst_bom_qty_positive`), `Parent ≠ Child`(`ck_mst_bom_not_self`) |
| `Receipt` | `mst_receipt` | 입고. **ERP 구매요청 현황 한 줄 = 입고 한 줄**(구매요청 = 입고의뢰). `ReceiptNo`(입고번호 = 요청번호`-`요청순번, 수입검사 작성건 `WorkOrderNumber` 에 들어간다)·`ReqNo`·`ReqSeq`·`ItemCode`·`ItemName`·`Spec`·`Category`(대분류)·`Unit`·`Qty`·`ReceiptDate`(입고일 — 입고예정일(발주) → 입고예정일(품의) → 요청납기일 중 앞의 값)·`VendorName`·`ProjectNo`·`ProjectName`·`RequesterName`·`EoNo`·`Batch`(마지막으로 바꾼 수신건). 검사 상태는 저장하지 않는다 | `Product`(PROTECT)·`IfBatch`(SET_NULL). unique(`ReceiptNo`) |
| `ProductForm` | `mst_product_form` | 품목 검사양식. 품번(`PartNo`, 리비전 무관)과 수입검사 양식코드(`FormCode`)의 N:M. 검사할 때 그 코드의 사용 중인 최신 버전(가장 높은 버전이 `UseYN='Y'`)을 연다. 매핑된 (입고 × 양식코드) 중 그 양식코드·입고번호 작성건이 없는 것이 수입검사 작성의 **대기 작업**이다 — 저장하지 않고 센다(`domain/services/receipt.py`) | unique(`PartNo`, `FormCode`). 품번·양식코드는 글자로 잇는다(외래키 없음) |

**입고 반영 규칙**(`domain/services/receipt.py`, ERP 구매요청 수신건의 `apply_interface`). 검증이 하나라도 틀리면 아무것도 반영하지 않는다
(요청번호·요청순번(1 이상 숫자)·품목 `품번.리비전`·품목명·수량(발주수량 → 품의수량 → 요청수량 중 앞의 값) 양수·날짜 세 칸 형식(`YYYY-MM-DD`)·파일 안 입고번호 중복). 통과하면 한 트랜잭션으로 ① 품목 마스터에 없는 품목만 구매요청의 이름·규격으로 만든다
(있는 품목은 고치지 않는다 — PLM 이 정본) ② 입고를 입고번호로 찾아 없으면 만들고 값이 달라졌으면 고친다 ③ 파일에 없는 기존 입고는 건드리지 않는다. 건수는 입고 추가·변경, 품목 추가다.

**검사 작업**(저장하지 않고 조회할 때 센다, `domain/services/receipt.py`): 매핑된 (입고 × 양식코드) 중 그 양식코드·입고번호로 쓴 수입검사(`FormType='INCOMING'`)
작성건이 없으면 대기, `working` 이고 `done` 이 없으면 작성 중이다. 좌측 메뉴 배지는 둘을 더한다. 입고 행 자체에는 검사 상태가 없다.

원본의 파생·중복 열(3D·2D 이름, 트리에서 다시 계산되는 열 등)은 넣지 않았다. 원본은 `if_plm_part_bom` 에 남는다.

**반영 규칙**(`domain/services/plm_bom.py`). 검증이 하나라도 틀리면 아무것도 반영하지 않고 몇 번째 행인지 알린다 — `Depth`(첫 행 1, 한 번에 2 이상 깊어지지 않는다)·
`Part(ERP)` = `Part No`.`Part Ver` 리비전 글자·`Part Name` 있음·`Qty` 양수·날짜(`YYYY-MM-DD`)·일시(`YYYY-MM-DD HH:MM:SS`)·같은 품목의 속성이 모두 같음·
같은 조립품을 펼친 곳마다 자식 목록이 같음·한 부모 아래 같은 자식 두 번 없음·자기 조상을 자식으로 갖지 않음. 통과하면 한 트랜잭션으로

1. 품목을 `Code` 로 찾아 없으면 만들고 값이 달라졌으면 고친다
2. 파일에서 하위가 펼쳐진 조립품마다 직속 자식 목록을 파일과 맞춘다(추가·수량/순서 변경·삭제). **파일에 나오지 않은 조립품(다른 장비)은 건드리지 않는다**
3. 하위 없이 나온 품목은 `MAX_EXPORT_DEPTH`(7, 원본 머리글 `Line No ( 7 Depth )`)보다 얕을 때만 자식을 비운다 — 7단계에서는 내보내기가 잘랐을 수 있다
4. 새 자식이 생긴 부모에서 DB 전체 트리를 따라가 순환이 생겼으면 전체를 되돌린다

같은 수신건을 다시 반영해도 결과가 같다. 건수(품목 추가·변경, BOM 추가·변경·삭제)를 출력하고 시스템 로그에 한 줄 남긴다.

### 외부 인터페이스 수신 (`if_*`)

근거: DECISIONS 사용자 결정 2026-10-19.

`domain/models/interface.py`. 외부 시스템이 준 것을 **해석하지 않고 원본 열 그대로** 담는다 — 값은 모두 글자(`TextField`, 빈 칸은 NULL)이고,
칼럼의 `verbose_name` 이 원본 머리글이다. 형 변환·검증과 마스터 반영은 반영 단계가 맡는다 — 품목·BOM·입고 모두 위 `apply_interface` 다. MES 계열이라 조직 구분·RLS 가 없다.

| 모델 | db_table | 무엇 | 주요 관계 · 제약 |
|---|---|---|---|
| `IfBatch` | `if_batch` | 수신건 — 받은 것 하나. 받는 경로와 상관없이 같다. `Kind`(무엇: `PLM_PART_BOM` / `ERP_PURCHASE_REQ`)·`Channel`(어떻게: `FILE` / `API` / `DB`, DB 기본값 `FILE`)·`SourceRef`(출처: 파일명·요청 id·조회 범위)·`RowCount`·`Status`(`RECEIVE_FAILED` 수신 실패 / `RECEIVED` 반영 대기(DB 기본값) / `APPLIED` 반영 완료 / `APPLY_FAILED` 반영 실패)·`Message`(실패 사유)·`AppliedAt`·`ApplyResult`(마지막 반영 건수, JSON). **실패한 수신도 행 없이 남긴다.** 반영 결과는 마지막 한 번만 남는다. 지우지 않고 쌓는다 | |
| `IfPlmPartBom` | `if_plm_part_bom` | PLM `Part BOM 수직 구조` 39열(`Part_Vertical_BOM.xlsx`). 장비 한 대의 BOM 을 위에서 아래로 펼친 행이다 — 부모는 바로 위쪽의 `Depth` 가 하나 작은 행 | `IfBatch`(CASCADE). `RowNo` = 파일 안 순서 |
| `IfErpPurchaseReq` | `if_erp_purchase_req` | ERP 구매요청 현황 39열(`PUOPRQ00400_…_grid.xlsx`). 요청 행 하나 = (`요청번호`, `요청순번`) | `IfBatch`(CASCADE). `RowNo` = 파일 안 순서 |

처리는 `domain/services/interface.py` 한 곳이다 — **경로 어댑터 → 공통 수신 → 종류별 반영**.

- 경로 어댑터는 받은 것을 `[{칼럼: 글자}]` 로 바꾸기만 한다. 지금은 파일(xlsx) 하나(`xlsx_rows`, 명령 `import_interface <plm_part_bom|erp_purchase_req> <xlsx>`)다.
  머리글은 처음 5줄에서 찾고(PLM 파일은 제목 줄·PM 분류 줄 아래 3행) 공백을 빼고 맞춘다. 읽지 못하거나 열이 하나라도 다르면 한 행도 넣지 않는다.
  API·DB 연동은 받는 방법을 정할 때 어댑터를 더한다
- 공통 수신(`receive(kind, rows, channel, source_ref)`)은 경로와 상관없이 수신건 하나와 원본 행을 넣는다. 실패하면 수신건을 `RECEIVE_FAILED`·사유로 남긴다
- 반영(`apply(batch)`, 명령 `apply_interface`)은 종류 등록부 `INTERFACES` 의 반영 함수를 부르고 마지막 결과를 수신건에 남긴다.
  실패하면 마스터는 그대로고 수신건에 `APPLY_FAILED`·사유만 남는다. 반영 함수가 없는 종류(지금은 없다)와 수신 실패 건은 반영하지 않는다
- 새 인터페이스는 원본 행 모델(`if_<종류>`) + `IfBatch.Kinds` 한 줄 + `INTERFACES` 한 줄(행 모델·반영 함수·건수 이름)이다. 이력 화면(시스템 관리 > 인터페이스 이력)은 열을 등록부에서 받으므로 고치지 않는다

칼럼 이름 대응: 모델 칼럼의 `verbose_name`(`domain/models/interface.py`)이 원본 머리글이다.

인가는 메뉴 권한(`user_group_menu`) 하나다.

## 3. 데이터 관리 (`vision_data_*`)

근거: DECISIONS O-8.

`domain/models/data.py`. `Tenant` 를 뺀 14개 모델이 `TenantOwnedModel` 을 상속해
`tenant` FK 를 가진다. 이 14개가 RLS 대상이다(§6).

**비전검사항목 하나가 검사 대상이자 데이터 저장소다** — `InspectionItem` 에 데이터셋·라벨
클래스·스냅샷·Export 가 매달린다. 공정·제품 테이블은 없다.

### 조직 · 권한

근거: DECISIONS DEC-004, Q9.

| 모델 | db_table | 무엇 | 주요 관계 · 제약 |
|---|---|---|---|
| `Tenant` | `vision_data_tenant` | 조직. **한 행만** 있다(`YEST`) | `ck_single_tenant` CHECK 로 id 고정 |
| `TenantMembership` | `vision_data_tenantmembership` | 조직 소속. 모든 사용자가 들어간다 | `User` FK. unique(tenant, user) |
| `ItemDeletionRequest` | `vision_data_itemdeletionrequest` | 비전검사항목 삭제 승인 요청이자 **삭제 기록**. 승인하면 비전검사항목이 지워져 `item` 이 끊기므로 `item_code`·`item_name` 에 무엇을 지웠는지 남는다 | `InspectionItem`(SET_NULL), 요청자·검토자 `User` |
| `ActivityLog` | `vision_data_activitylog` | 데이터 관리 활동 이력(`event_type`·`payload`) | `InspectionItem`(null 허용), `actor` `User` |

### 비전검사항목 · 이미지 · 라벨

근거: DECISIONS 사용자 결정 2026-10-20, DEC-031, DEC-032, O-9, O-14, Q4.

| 모델 | db_table | 무엇 | 주요 관계 · 제약 |
|---|---|---|---|
| `InspectionItem` | `vision_data_item` | 비전검사항목. `code`(전역 unique)·`task_type`(`OBJECT_DETECTION`/`ANOMALY_DETECTION`/`CLASSIFICATION`/`MEASUREMENT`)·`status`(`ACTIVE`/`PAUSED`/`DELETION_PENDING`)·`capture_method`(촬영 방식 `RIG` 고정 거치대 / `TABLET` 태블릿 — 태블릿은 클라이언트 카탈로그에 나오지 않는다)·`category`(소속 중분류 — null 이면 미분류)·`display_order` | `CLASSIFICATION`·`MEASUREMENT` 는 클라이언트가 `include=classification`·`measurement` 를 줄 때만 카탈로그에 나온다. `InspectionCategory`(`category`, PROTECT, null) |
| `InspectionCategory` | `vision_data_category` | 검사 분류. 대분류(`parent` 없음)는 **수입검사 `INCOMING`·품질검사 `OUTGOING`·미분류(빈 값) 셋으로 고정**(`category.FIXED_MAJORS`, `ensure_fixed_majors` 가 맞춘다) › 중분류(대분류 아래, `form_code` 매핑한 디지털 양식 코드 — 버전 무관, 빈 값 = 매핑 없음)·`sort_order`·`description`. 두 단계뿐이고 3단계 금지·양식 검증(같은 구분의 사용 중인 최신 섹션 양식)은 서비스(`domain/services/data/category.py`)가 한다. 대분류는 지우지 않고, 비전검사항목이 있는 중분류도 지우지 않는다 | `parent`(self, PROTECT). `uq_category_major_name`(tenant, name — 대분류)·`uq_category_minor_name`(tenant, parent, name)·`uq_category_form_code`(tenant, form_code — 빈 값 제외, 양식 하나는 중분류 하나에만)·`ck_category_level_fields`(대분류는 `form_code` 없음, 중분류는 `form_type` 없음) |
| `LabelClass` | `vision_data_labelclass` | 라벨 클래스. `is_defect`·`color`·`annotation_shape`(`BBOX`/`POLYGON`) | `InspectionItem`. unique(tenant, item, name) |
| `MeasurementPoint` | `vision_data_measurementpoint` | 치수 측정 항목의 측정점. `code`(클라이언트가 측정값을 돌려보내는 키)·`name`·`nominal`·`lower`·`upper`(Decimal 18,3, 합격 범위 경계 포함)·`unit`(기본 `mm`)·`description`(측정 방법)·`sort_order`. 측정 결과에 나온 코드는 화면에서 바꾸거나 지울 수 없다 | `InspectionItem`(CASCADE). unique(tenant, item, code) `uq_measurement_point_code`, `lower ≤ nominal ≤ upper` `ck_measurement_point_range` |
| `Dataset` | `vision_data_dataset` | 비전검사항목 안의 이미지 묶음. **화면에 보이지 않는 내부 컨테이너**다. 업로드 시 `get_or_create_upload_dataset()` 가 `version='v0.1'` 하나를 만든다 | `InspectionItem`. unique(tenant, item, version) |
| `ImageAsset` | `vision_data_imageasset` | 이미지 1장. `file`·`thumbnail`·`original_file`(편집 전 원본)·`preprocess`(편집 연산)·`sha256`·`label_status`·`ingestion_status`(업로드가 동기로 검증해 늘 `READY`)·`status`(`UPLOADED`·`LABELED`, 라벨 저장 여부만)·`source_inspection_id`·`channel`(등록 경로 `CLIENT`/`FILE`/`CAMERA`/`FORM`, 기본 `FILE`)·`uploaded_by`(등록자 → 사용자, SET_NULL, null 허용) | `Dataset`. `storage_key`(UUID) unique. sha256 unique 제약은 **두지 않는다** — 클라이언트 재촬영 중복을 허용한다 |
| `Annotation` | `vision_data_annotation` | 라벨 1개. `geometry_type`(`NONE`/`BBOX`/`POLYGON`)·`geometry`(JSON). 저장할 때 `label_class` 가 반드시 있다(null 은 옛 이상 판정 행뿐). 정상은 영역 주석이 없는 이미지(객체·이상 탐지)이거나 불량이 아닌 클래스(분류)다 | `ImageAsset`(CASCADE), `LabelClass`(PROTECT) |
| `LabelingTask` | `vision_data_labelingtask` | 라벨링 작업. `READY`→`CLAIMED`→`IN_PROGRESS`→`SUBMITTED`, 임대(`lease_token`·`lease_expires_at`) | `InspectionItem`, `ImageAsset`, `assignee`. **이미지당 활성(`CLAIMED`/`IN_PROGRESS`) 작업 1개** 부분 unique |

### 스냅샷 · Export · 작업 큐

| 모델 | db_table | 무엇 | 주요 관계 · 제약 |
|---|---|---|---|
| `DatasetVersion` | `vision_data_datasetversion` | **스냅샷**. 불변(`is_immutable`)이고 등록 시점의 검수 완료 이미지·주석이 `manifest` JSON 에 있다. 직전 스냅샷과 이미지·주석이 같으면 만들지 않는다. 등록과 함께 `ExportJob` 2개(고정 형식·`WEZARD`)가 적재된다 | `Dataset`. unique(tenant, dataset, version_tag) |
| `ExportJob` | `vision_data_exportjob` | 스냅샷 내보내기. `format` 은 검사 유형마다 하나로 고정(`IMAGEFOLDER`·`COCO`·`MVTEC`, `export/registry.py` `ITEM_EXPORT_FORMAT`)이고, 모든 유형에 Wezard 전송용 `WEZARD`(`wezard-dataset/v1`)를 함께 만든다. 나머지 값(`YOLO`·`CSV`·`CLASSIFICATION_JSON`·`IMAGE_MASK`·`ANOMALY_JSON`)은 그 형식으로 이미 만든 행을 보이려고 남긴다 | `DatasetVersion`(PROTECT). 결과 zip 은 `file`, 그 크기·SHA-256 은 `file_size`·`file_sha256`(만들 때 저장, 그 전 zip 은 처음 조회할 때 `ExportService.ensure_checksum` 이 채운다) |
| `BackgroundJob` | `vision_data_backgroundjob` | 워커 작업 큐이자 **작업 이력**. `job_type` = `EXPORT`. `payload` 는 `export_job_id`(워커가 읽는 값)와 `item_code`·`item_name`·`version_tag`·`format`(이력). 비전검사항목을 지워도 이 행은 남는다(`ExportJob` 은 지워진다) — 그래서 무엇을 만들었는지를 payload 에 남긴다. `attempt_count` 는 워커 고착 복구 횟수다(`next_retry_at` 은 쓰지 않는다) | `run_worker` 가 `SELECT … FOR UPDATE SKIP LOCKED` 로 집는다. 워커는 `python manage.py run_worker`(상주) · `--once`(대기 작업만 처리) |

## 4. 비전 검사 (`vision_*`)

근거: DECISIONS DEC-010, DEC-029, F-4, O-7, O-12, Q3, Q5.

`domain/models/vision.py`. 테넌트 소유가 아니라 RLS 대상이 아니다.

| 모델 | db_table | 무엇 | 주요 관계 · 제약 |
|---|---|---|---|
| `VisionClient` | `vision_client` | 현장 비전검사 클라이언트. API Key 는 **SHA-256 해시만** 저장한다 | `client_id` unique. `service_account` → `User` 1:1 (업로드 행위자, 웹 로그인 불가). 검사 기록이 있으면 지울 수 없고(`vision_inspection.client` PROTECT), 지우면 서비스 계정도 지운다 |
| `IntegrationClient` | `integration_client` | 학습 플랫폼(Wezard) 스냅샷 API 키(`maip_…`). **SHA-256 해시만** 저장하고 해시로 연동처를 찾는다. 관리는 `manage.py integration_key` | `client_id`(연동처 이름표)·`api_key_hash` unique. 서비스 계정·참조가 없다. 폐기(`revoke`)는 행을 지우지 않고 `active=False` 로 둔다 |
| `VisionModel` | `vision_model` | Wezard 모델의 이름표 — 비전검사항목 관리 상세의 AI 모델 칸이 Wezard 배포 모델을 고르면 만든다(`domain/services/vision/model_mapping.py`)(`version='latest'`·`runtime='wezard'`, 추론 때 최신 배포 버전을 찾는다). 매핑의 외래키 대상이고 추론은 `active`·`inspection_type` 을 본다. 매핑에 임계값 재지정이 없으면 `threshold` 를 쓴다. `artifact_path`·`runtime` 은 옛 로컬 추론의 흔적이다. 등록 화면은 없고 테이블 제거는 남은 과제다 | unique(name, version) |
| `VisionItemModelMapping` | `vision_item_model_mapping` | 비전검사항목 ↔ 모델. `model_code`·`model_version` 을 비정규화 저장하고 `threshold_override` 를 둔다 | `InspectionItem`(CASCADE), `VisionModel`(PROTECT). **비전검사항목당 `active=True` 1개** 부분 unique |
| `VisionOverlay` | `vision_overlay` | 클라이언트 화면에 겹칠 기준 이미지. `version`·`visible`·`opacity`·`image` | `InspectionItem` 1:1 |
| `VisionInspection` | `vision_inspection` | 검사 1건. `id` 는 서버가 접수할 때 만드는 UUID, `request_id` 는 클라이언트가 만든 UUID 문자열이다(둘 다 `varchar(36)`). `request_id` 로 재전송을 가려내므로 바꾸면 재전송 처리가 깨진다. 추론 결과 컬럼(`abnormal`·`defects`·`anomaly_score`·`classification` …)은 Wezard 추론이 성공(`SUCCESS`)해야 채워지고, 그때 `model_name`·`model_version` 은 Wezard 가 실제로 쓴 이름·버전이다. Wezard 설정이 없거나 배포 모델이 없으면 `RECEIVED` 로 비어 있다. 치수 측정은 추론 없이 접수 때 `SUCCESS` 로 `measurements`(측정점별 `{code,name,value,lower,upper,unit,ok}` — 그때 규격을 함께 남긴다)·`calibration`(클라이언트가 보낸 배율 그대로)을 채운다(다른 유형은 null) | `VisionClient`(PROTECT), `InspectionItem`(PROTECT), `image_asset` → `ImageAsset`(SET_NULL) |

**검사 이미지는 한 벌만 저장한다**. `vision_inspection` 에 이미지 경로
컬럼이 없다. 접수 시 `domain/services/vision/inspection.py` 가 이미지를 데이터 관리
`ImageAsset` 으로 올리고(`source_inspection_id` = 검사 ID), 그 행을 `image_asset` 으로
가리킨다. 그래서 클라이언트가 찍은 사진은 바로 라벨링 대상이 된다.

더 볼 곳: 응답 모양은 client/SERVER_API_CONTRACT.md.

## 5. 관계 그림

```text
Tenant (1행, YEST)
 └─ (모든 vision_data_* 행이 tenant_id 로 가리킨다)

auth_user ─1:1─ user_profile ─→ user_group ─< user_group_menu (MenuCode, AuthCode)   인가
    │
    └─< TenantMembership

InspectionItem (vision_data_item)
 ├─→ InspectionCategory 중분류 (category, null = 미분류) ─→ 대분류   (vision_data_category, 중분류 form_code ··→ dig_form.Code)
 ├─< LabelClass
 ├─< MeasurementPoint                            (치수 측정 항목만)
 ├─< ItemDeletionRequest · ActivityLog
 ├─< Dataset (내부 컨테이너)
 │    ├─< ImageAsset ─< Annotation >─ LabelClass
 │    │      └─< LabelingTask (InspectionItem 도 가리킨다)
 │    └─< DatasetVersion (스냅샷, manifest) ─< ExportJob ──→ zip 파일
 │
 ├─1:1 VisionOverlay
 ├─< VisionItemModelMapping >─ VisionModel        (활성 1개)
 ├─< dig_form_item.VisionItem                     (디지털 양식 이미지 칸 연결, SET_NULL)
 └─< VisionInspection >─ VisionClient ─1:1─ auth_user (서비스 계정)
          └─ image_asset ──→ ImageAsset           (파일 한 벌)

BackgroundJob (EXPORT) — run_worker 가 처리해 ExportJob 을 채운다
```

## 6. RLS (Row Level Security)

근거: DECISIONS DEC-004.

`domain/migrations/0001_initial.py` 가 `TENANT_TABLES` **14개**에 정책을 건다(옛 이력에서 작업그룹·데이터 표준 5개와 배정 테이블을 지우고 측정점·검사 분류를 더해 18개에서 14개가 됐다). 테이블을 새로 더하면 정책도 새 마이그레이션으로 건다.

```text
vision_data_activitylog        vision_data_imageasset
vision_data_annotation         vision_data_item
vision_data_backgroundjob      vision_data_itemdeletionrequest
vision_data_category           vision_data_labelclass
vision_data_dataset            vision_data_labelingtask
vision_data_datasetversion     vision_data_measurementpoint
vision_data_exportjob          vision_data_tenantmembership
```

각 테이블에 대해:

```sql
ALTER TABLE <t> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <t> FORCE ROW LEVEL SECURITY;      -- 테이블 소유자에게도 적용
CREATE POLICY <t>_tenant_scope ON <t>
  USING      (tenant_id::text = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
```

`vision_data_tenant` 자체는 RLS 대상이 아니다. 대신 `ck_single_tenant` CHECK 가
`id = '00000000-0000-4000-8000-000000000001'` 만 허용한다 — `domain/tenancy.py` 의
`FIXED_TENANT_ID` 와 같은 값이다. 조직을 하나로 두고도 정책을 남긴 이유는 tenant 필터를
빠뜨리는 버그를 DB 가 막고, 조직이 늘 때 스키마를 바꾸지 않기 위해서다.

### 코드에서 지킬 것

읽기·쓰기·사용자 삭제는 `domain.tenancy.tenant_atomic()` 안에서 한다 — 밖에서 읽으면 **예외 없이 0건**이다.
운영은 `TENANT_RLS_ENABLED=True`(기본값)이다. 단위 테스트(SQLite)는 RLS 를 보지 못한다.

더 볼 곳: 진입점·함정은 ARCHITECTURE.md §5, 테스트에서 RLS 를 보는 방법은 DEVELOPMENT.md §2.1-1.

## 7. 마이그레이션

### 규칙

- 스키마는 **Django 마이그레이션으로만** 바꾼다. 모델을 고치고 `python manage.py makemigrations` 로 만든다.
- `migrate --fake`, `--fake-initial`, `django_migrations` 직접 수정은 **금지**다.
- 모델로 표현되지 않는 SQL(함수·뷰·RLS)도 마이그레이션에 넣는다. PostgreSQL 전용 DDL 은
  `domain/migrations/_pgsql.py` 의 `run_sql()` 로 감싼다 — 다른 벤더(SQLite 테스트)에서는 조용히 건너뛴다.
- `domain/_sql/` 에는 스키마 SQL 이 없다. `i18n/`(라벨 시드)만 있다(§8).

### 목록

근거: DECISIONS 사용자 결정 2026-10-12·2026-10-21, DEC-C5, O-13.

| 번호 | 하는 일 |
|---|---|
| `0001_initial` | 스키마 전체 — 시스템·사용자(MES 계열), 디지털 양식(`dig_form*`), 외부 인터페이스(`if_*`)·마스터(`mst_*`), 데이터 관리(`vision_data_*`), 비전 검사(`vision_*`) 테이블과 인덱스·제약·DB 기본값(`db_default`). 이어서 PostgreSQL 전용 객체: 양식코드 시퀀스 `dig_form_code_seq`, SQL 함수 `fn_code_name()`·`fn_class_data_text()`, 좌측 메뉴 트리 재귀 뷰 `v_menu_folder`, `TENANT_TABLES` 14개 RLS 정책 + `ck_single_tenant` |

`0001_initial` 은 옛 `0001`~`0021` 을 하나로 정리한 것이다(2026-10-23). 스키마 정의는 같고(빈 PostgreSQL 두 개로 비교해 차이 0건) 제약·인덱스·시퀀스 이름과 컬럼 순서만 다르다 — 코드는 이를 쓰지 않는다.
파일 없는 옛 기록이 남은 DB(공유 개발 DB 등)는 `python manage.py migrate domain --prune` 으로 지운다 — 스키마는 그대로다.

함수·뷰는 raw SQL 서비스(메뉴 트리, 코드명 조회)가 쓴다.

더 볼 곳: 테스트(SQLite)에 함수·뷰가 없어 생기는 검증 공백은 DEVELOPMENT.md §2.1-1.

## 8. 시드

근거: DECISIONS 사용자 결정 2026-10-20·2026-10-21.

| 명령 | 언제 | 무엇을 만드나 |
|---|---|---|
| `python manage.py seed_initial --admin-password '<비밀번호>'` | 최초 설치 후, 그리고 아래 경우마다 다시 | `sys_option` `LOGO_TITLE`, `sys_code` 옛 디지털 양식 판정 코드 5행(`SYSTEM_CODES`), `user_code` 항목결과 코드 17행(묶음 1·그룹 5·결과 코드 11 — **없을 때만** 넣어 화면에서 고친 값을 덮지 않는다), `user_group` `admin`·`user`, 메뉴폴더 6개·메뉴 29개(`MENU_TREE`), `admin` 그룹 전 메뉴 `RW`, 모든 그룹 대시보드(`wm_dashboard`) `RW`, 옛 품질 검사양식 관리 권한·즐겨찾기를 검사양식 관리로 옮김, 관리자 계정(`--admin-username`, 기본 `admin`), 조직 `YEST` 와 전 사용자 소속 |
| `python manage.py seed_demo` | **개발 전용**(운영은 초기 세팅의 파이프라인 점검으로만, DEPLOYMENT §2-9) | 냉각팬 패널 비전검사항목 3개(`FAN-PANEL-CLS` 분류·`FAN-PANEL` 이상 탐지·`FAN-PANEL-DET` 객체 탐지)와 라벨 클래스, 표본 zip(`domain/management/samples/fan_panel.zip`)이 있으면 비전검사항목마다 이미지 20장·대표 이미지·Overlay, 클라이언트 `CLIENT-001`(+서비스 계정) |
| `python manage.py sample_inspection` | **개발 전용**, 추론 시험 때(운영은 `seed_demo` 와 같다) | 시험 클라이언트 `PIPELINE-TEST`(+서비스 계정, 실행마다 키 재발급·출력 안 함), 표본 zip 이미지로 보낸 검사 기록과 그 `ImageAsset`(라벨링 대기). 기본 비전검사항목 `FAN-PANEL` |
| `python manage.py seed_vision_items` | 최초 설치 후, 검사항목 정의가 바뀌었을 때(**운영 포함**) | 검사 분류 9개(고정 대분류 3개·중분류 6개 — 양식 매핑은 `seed_dig_form`·비전검사항목 관리 화면이 한다. `ensure_fixed_majors` 가 고정 대분류 밖의 대분류는 중분류를 같은 양식 구분의 고정 대분류로 옮기고 지운다)와 NEOCON C2 비전검사항목 16개(고정 거치대 `VIS-` 3개·태블릿 `TAB-` 13개)·라벨 클래스 76개·측정점 3개, 검사항목마다 업로드 데이터셋. 소속이 빈 검사항목만 정해진 중분류에 넣는다. **없는 것만** 만든다(이미 있는 코드·클래스·측정점은 이름·설명·유형·규격을 덮지 않는다). `--update-descriptions` 를 주면 설명만 바꾼다 |
| `python manage.py seed_dig_form` | 최초 설치 후, 양식 데이터 파일이 바뀌었을 때(**운영 포함**). `seed_vision_items` 다음 | 완성된 고객 양식 DF0012~DF0026 15종(검사 분류에 매핑된 양식 포함)의 최신 버전의 양식·섹션·칸·작업분류와 참고사진·고정 이미지 칸 그림(`domain/management/samples/dig_form_forms.json`·`dig_form_images/`, 그림은 새 첨부로 잇는다). 이미지 칸은 비전검사항목 코드로 잇고, 이름이 같은 중분류에 양식을 매핑한다(매핑이 비어 있을 때만). 항목·중분류가 없으면 잇지 않고 알린다. 같은 (양식코드, 버전)이 있으면 건너뛰고(멱등, 운영에서 고친 양식을 덮지 않는다), 양식코드 시퀀스를 기본 양식 다음 번호로 맞춘다. 작성 결과는 넣지 않는다 |
| `python manage.py export_dig_form <파일>` | 고객 양식을 공유 개발 DB 에서 고쳤을 때(**담당자**) | 이 서버 DB 에서 중분류에 매핑된 양식과 `--codes`(기본 `DF0012-DF0026`) 양식의 최신 버전을 `seed_dig_form` 데이터 파일·참고사진 폴더로 뽑는다(DB 는 읽기만) |
| `python manage.py import_interface <종류> <xlsx>` | 외부 인터페이스 파일을 받았을 때 | 수신건(`if_batch`) 하나와 원본 행(`if_plm_part_bom` 또는 `if_erp_purchase_req`). 읽지 못하거나 머리글이 다르면 행 없이 수신 실패로 남는다. 마스터는 만들지 않는다(§2 "외부 인터페이스 수신") |
| `python manage.py apply_interface <수신건 id>` | PLM 수신건을 넣은 뒤 | PLM 수신건은 품목 `mst_product`·BOM `mst_bom`, ERP 구매요청 수신건은 입고 `mst_receipt`(+ 없는 품목)(§2 "품목 · BOM" 반영 규칙)와 수신건의 반영 상태·건수(실패면 사유) |
| `psql … -f domain/_sql/i18n/000_run_i18n.sql` | 배포 시 한 번 | 다국어 라벨·그리드 컬럼·메뉴 번역. psql 이 없는 서버는 같은 세 파일을 `manage.py shell` 로 넣는다(DEPLOYMENT §2-4) |

더 볼 곳: `export_dig_form` 절차는 DEVELOPMENT.md §1.3 "고객 양식 뽑기".

### `seed_initial`

멱등이다(`update_or_create`). 다음 경우 다시 돌린다.

- `MENU_TREE` 나 `domain/gui.py` 의 화면을 바꿨을 때. `gui.py` 에 없는 메뉴코드면 멈춘다.
  `MENU_TREE` 에 없는 `menu_item` 행과 그 `user_group_menu` 권한, `MENU_TREE` 에 없는 폴더는 **지운다**.
- `FIXED_TENANT_NAME` 을 바꿨을 때 — 기존 조직 행의 이름을 맞춘다.
- 시그널 이전에 만들어진 사용자의 조직 소속을 채울 때.

`--admin-password` 를 빼면 관리자 계정을 만들지 않는다.

더 볼 곳: 메뉴 구성은 FEATURES.md.

### `seed_demo`

`vision_inspection` 에 행이 있으면 `--force` 없이는 멈춘다 — 운영 DB 보호용이다.
기본 실행은 돌릴 때마다 `CLIENT-001` API Key 를 새로 정하고 **한 번만** 출력한다. 작업자 계정은 만들지 않는다(사용자 화면에서 만든다).
API Key 는 해시만 저장되므로 놓치면 재발급해야 한다.
`--samples [zip 또는 폴더]` 는 표본 이미지만 다시 넣는다(API Key 는 그대로, 업로더는 첫 superuser). 같은 이미지는 늘지 않는다.

### i18n SQL

`domain/_sql/i18n/000_run_i18n.sql` 만 실행한다. 이 파일이 한 트랜잭션 안에서
`010_template_data_labelcd.sql`(`label_code`)·`020_template_grid_columns.sql`(`grid_col`)·
`030_side_menu_translations.sql`(메뉴 번역)을 순서대로 불러온다.

```bash
psql -X -v ON_ERROR_STOP=1 -h <DB_HOST> -p <DB_PORT> -U <DB_USER> -d <DB_NAME> -f 000_run_i18n.sql
```

010/020/030 은 기존 행을 고치거나 지우지 않는다 — 고유 키가 있으면 건너뛰고(`ON CONFLICT DO NOTHING`) 없는 것만 넣는다.
`*_clean.sql` 은 `000_run_i18n.sql` 이 부르지 않는 정리판이다 — 010 은 같은 키를 덮어쓰고 대체된 생성 라벨·옛 스캐너 오등록 행만 지우고, 030 은 지우지 않고 덮어쓰며, 020 은 `grid_col_lang`·`grid_col` 을 통째로 `TRUNCATE` 해 사용자 컬럼 설정까지 지운다. 스키마와는 무관하다.

## 9. 파일 저장 경로

근거: DECISIONS 사용자 결정 2026-10-07, DEC-019.

모든 업로드·파생 파일은 `STORAGE_ROOT`(비우면 `<프로젝트>/storage`) 아래에만 둔다.
nginx 가 직접 내주지 않고 `MEDIA_URL` 도 없다 — 권한을 확인하는 View 로만 제공한다.

| `STORAGE_ROOT` 아래 | 설정 | 무엇 |
|---|---|---|
| `media/` | `MEDIA_ROOT` | 데이터 관리·비전 검사의 `FileField`/`ImageField`. 디지털 양식 이미지도 여기 있다 — `media/dig_form_section/` 은 **양식 편집**에서 넣는 참고사진, `media/dig_form_item/` 은 양식 편집의 고정 이미지 칸 그림, `media/dig_form_result/` 는 **검사작성 작업**(수입·품질)에서 올리는 이미지 칸·섹션 이미지 사진이다(비전검사항목이 연결된 칸은 비전 데이터 이미지 — §9) |
| `upload/<table_name>/…` | `FILE_UPLOAD_PATH` | MES 첨부(`attach_file`). 첨부 업로드·제공 경로를 2026-10-07 지워 지금은 쓰는 코드가 없다. 디지털 양식 이미지는 여기가 아니라 `media/` 아래다 |
| `upload_temp/` | `FILE_TEMP_UPLOAD_PATH` | 스냅샷 Export zip 을 만드는 임시 파일(`ExportService`). 업로드는 이 경로를 쓰지 않는다 |
| `form/` | `MES_FORM_PATH` | MES 양식 파일 자리. 폴더만 만들고 쓰는 코드는 없다 |
| `cache/` | `CACHES` | 파일 캐시(로그인 실패 횟수를 gunicorn 워커끼리 센다) |
| `logs/` | `LOG_DIR` 기본값 | `app-YYYY-MM-DD.log`. `LOG_DIR` 로 바꿀 수 있다 |

`media`·`upload`·`upload_temp`·`form` 은 설정 로드 시 만들어진다. `storage.resolve()` 는 `..` 가
섞여도 `STORAGE_ROOT` 밖 경로를 `UnsafePathError` 로 거부한다.

### `FileField` 의 `upload_to` (`MEDIA_ROOT` 기준 상대 경로)

함수는 `domain/storage.py`, 비전 검사의 Overlay·Heatmap 은 `domain/models/vision.py` 에 있다.

| 필드 | 함수 | 경로 |
|---|---|---|
| `ImageAsset.file`, `ImageAsset.original_file` | `item_image_upload_path` | `tenants/<tenant_id>/items/<item_id>/images/<storage_key><확장자>` |
| `ImageAsset.thumbnail` | `item_image_thumbnail_upload_path` | `tenants/<tenant_id>/items/<item_id>/thumbnails/<storage_key>.webp` |
| `InspectionItem.cover_image` | `item_cover_upload_path` | `tenants/<tenant_id>/items/<item_id>/cover<확장자>` |
| `ExportJob.file` | `export_upload_path` | `tenants/<tenant_id>/exports/<storage_key>/<파일명>` |
| `VisionOverlay.image` | `overlay_upload_path` | `vision/overlays/<item_id>/v<version><확장자>` |
| `VisionInspection.heatmap` | `heatmap_upload_path` | `vision/heatmaps/<검사 id>.jpg` |

디지털 양식 이미지는 `FileField` 가 아니다 — §2 `attach_file` 행(`AttachMaster` 행의 세 경우)이 위 `MEDIA_ROOT` 하위 폴더의 파일을 가리킨다(`domain/services/dig_form_image.py`).
섹션을 복사하면 첨부 행만 늘고 파일은 같은 것을 쓰므로, 행을 지워도 파일은 지우지 않는다. 이미지 칸의 사진을 바꾸거나 빼면 이전 첨부 행만 지운다(칸 결과 `TextResult` 에 첨부 id).
비전검사항목이 연결된 이미지 칸은 첨부를 만들지 않는다 — 칸 결과 `TextResult` 가 그 항목의 `ImageAsset` id 다.
고정 이미지 칸(`ResultType='R'`)의 칸 `Content` 에 첨부 id 를 둔다. [위 칸과 병합]한 행은 칸 하나(`RowSpan`)라 첨부도 하나다. 칸은 새 버전마다 새로 만들어지므로 저장할 때 새 칸에 같은 파일의 첨부 행을 복제해 연결하고 `Content` 를 새 id 로 바꾼다 — 이전 버전의 칸·첨부는 그대로다.
섹션 이미지도 같은 이미지 칸이다 — 표 밖의 `dig_form_item` 하나(`RowType='S'`·`RowIndex=0`·`ColumnIndex=0`·`ResultType='I'`)로, 이 칸이 있으면 그 섹션에서 켜진 것이다. 행 순번 0 은 이 칸만 쓴다(머리줄·본문은 섹션마다 1부터).

확장자는 소문자로 바꾼다. 파일명은 `storage_key`(UUID)라 원래 이름은 `original_name` 컬럼에만 남는다.
비전검사 클라이언트가 보낸 검사 이미지도 `ImageAsset` 이므로 같은 `images/` 경로에 저장된다.

### 배포물 `DISTRIBUTION_ROOT`

근거: DECISIONS DEC-024.

`STORAGE_ROOT` 와 별개다(비우면 `<프로젝트>/distribution`). 인증 없이 공개한다.

더 볼 곳: 폴더 구성과 반입 절차는 DEPLOYMENT.md §8-1.
