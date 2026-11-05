# 검사 분류·검사 작업·거치대 결과 불러오기 — 설계

회의 결과(2026-10-21, 메뉴/화면 개편안·비전 검사 항목 개편안)를 반영한다. 결정은 모두 권장안이다(사용자 결정 2026-10-21, §9).
근거 문서는 `tmp/docs/NEOCON C2 제조 관리 문서 대장.xlsx`(시트 원문 정리 `tmp/docs/NEOCON_C2_문서대장_시트정리/`)·
`tmp/docs/NEOCON 제조-검수 AX 적용 Action List.xlsx`·`tmp/docs/비전검사AX.txt` 이다.

## 1. 범위

| 묶음 | 내용 | 계획 |
|---|---|---|
| 검사 분류 | 대분류 › 중분류(검사 시트, 양식 매핑) › 비전검사항목. 검사 관리 > 검사 분류 관리 화면, 비전 데이터 관리 메뉴 트리, 양식 편집기 연결 보조, 시드 | [plan 1](../plans/2026-10-21-inspection-category.md) |
| 검사 작업 | 품목 검사양식 매핑 N:M(양식 기준 화면), 입고 조회 → 기준정보 > 입고 내역, 수입 검사작성을 검사 작업 목록으로 | [plan 2](../plans/2026-10-21-inspection-jobs.md) |
| 거치대 결과 불러오기 | 디지털 양식 이미지 칸에 거치대 검사 결과를 골라 넣기, 치수 측정 항목 연결 허용(2026-10-20 Q5 변경) | [plan 3](../plans/2026-10-21-rig-result-in-form.md) |

**범위 밖**: 판/가공품 입고 N건을 한 시트의 행 N개로 작성하기(회의안 "행 N개 추가") — 제외. 대분류(판금·가공) 규칙 매핑 — 품번만 매핑한다.
클라이언트 계약(`/api/v1`) — 바뀌지 않는다. 불러온 측정값으로 같은 행 칸 자동 채우기 — 다음 단계.

## 2. 데이터

### 2-1. 검사 분류 `vision_data_category` (새 테이블, 조직 구분·RLS — 다른 `vision_data_*` 와 같다)

대분류와 중분류를 한 테이블에 둔다. 대분류 = `parent` 가 없는 행, 중분류 = 대분류를 `parent` 로 가진 행. 두 단계뿐이다.

| 필드 | 형 | 설명 |
|---|---|---|
| `parent` | FK self, null, PROTECT, related_name `children` | 없으면 대분류 |
| `name` | CharField(100) | 분류 이름 |
| `form_type` | CharField(10), blank | 대분류만: `INCOMING`(수입)·`OUTGOING`(품질). 중분류는 빈 값(대분류를 따른다) |
| `form_code` | CharField(20), blank | 중분류만: 매핑한 디지털 양식 코드(`dig_form.Code`, 버전 무관). 빈 값 = 매핑 없음 |
| `sort_order` | IntegerField(0) | 같은 단계 안 순서 |
| `description` | TextField, blank | |

제약:
- `uq_category_major_name`: (tenant, name) where parent is null
- `uq_category_minor_name`: (tenant, parent, name) where parent is not null
- `uq_category_form_code`: (tenant, form_code) where form_code ≠ '' — 양식 하나는 중분류 하나에만
- `ck_category_level_fields`: parent is null → form_code = '' / parent is not null → form_type = ''

서비스 검증(DB 로 못 거는 것): `parent` 는 대분류여야 한다(3단계 금지). 대분류 `form_type` 은 필수. `form_code` 는 그 대분류 `form_type` 과 같은 구분의
**섹션 양식**(`LayoutType='SECTION'`)이고 가장 높은 버전이 사용 중(`UseYN='Y'`)이어야 한다. 삭제는 아래가 비어 있을 때만(중분류가 있는 대분류, 비전검사항목이 있는 중분류는 막는다).
매핑을 풀어도 양식 이미지 칸의 비전 연결은 그대로다.

### 2-2. 비전검사항목 소속 `vision_data_item.category_id`

`InspectionItem.category` = FK `InspectionCategory`, null(미분류), PROTECT, related_name `items`. 중분류만 가리킨다(서비스 검증).
한 항목은 중분류 하나에 속한다 — 다른 양식에서는 이미지 칸 연결로 재사용한다(Bolt I-Marking 처럼 여러 시트에 반복되는 확인).

### 2-3. 품목 검사양식 매핑 `mst_product_form` — N:M

`unique_together` 를 `[['PartNo']]` → `[['PartNo', 'FormCode']]`. 지금 매핑 0건이라 옮길 데이터가 없다.

### 2-4. 마이그레이션 — `0019_inspection_rework` 하나, 브랜치 `migration/inspection-rework`

모델 3곳(§2-1~2-3) + 끝에 `run_sql` 로 `vision_data_category` RLS(ENABLE·FORCE·POLICY `vision_data_category_tenant_scope`, 0017 과 같은 식).
데이터 단계는 없다 — 분류 행은 `seed_vision_items` 가 넣는다. RLS 테이블은 14개 → 15개.

## 3. 검사 분류 관리 화면 (검사 관리 > 검사 분류 관리)

- 메뉴 코드는 **`wm_data_item` 을 그대로 쓴다**(비전 검사 관리 폴더 → 검사 관리 폴더 맨 끝, 이름 "검사 분류 관리", 템플릿 `data/item_list.html` 을 다시 쓴다).
  메뉴 권한·즐겨찾기·API 매핑(`item/item_admin`)이 그대로 남는다(DECISIONS 2026-10-19 메뉴 재배치와 같은 방식). 플랫폼 관리자 전용 메뉴 목록(`PLATFORM_ADMIN_MENU_CODES`)에서 뺀다
- 모양은 항목결과 코드관리와 같다(DESIGN §5.5): 트리 한 목록(대분류 › 중분류 › 비전검사항목, WeZonGrid `setTreeData`) + 상세 패널. 목록 머리 [대분류 등록]·[중분류 등록]·[비전검사항목 등록]
- 상세는 고른 행 종류로 바뀐다
  - 대분류: 이름·양식 구분·순서·설명. [수정]·[삭제]
  - 중분류: 대분류·이름·**매핑 양식**(같은 구분의 사용 중인 최신 섹션 양식 목록, "(매핑 없음)")·순서·설명. [수정]·[삭제]
  - 비전검사항목: 지금 비전검사항목 관리 상세 그대로(코드·이름·유형·상태·사용 토글·촬영 방식·설명·삭제 요청 승인/반려·배정 인원) + **중분류** 고르기
- 권한(2단계는 그대로):

| 작업 | 권한 |
|---|---|
| 분류 트리 조회 | 메뉴 권한 |
| 대분류·중분류 등록·수정·삭제·양식 매핑 | 메뉴 W(디스패치 훅이 본다) |
| 비전검사항목 등록·수정·중지·중분류 변경·배정·삭제 승인 | 플랫폼 관리자(지금 `item_admin` 검사 그대로). 버튼도 관리자에게만 보인다 |

- API: 분류는 새 모듈 `app/views/item/category.py`(`/api/item/category`, 매핑 `wm_data_item`). 비전검사항목은 지금 `/api/item/item_admin` 에
  `category_id` 를 더한다(create·update·list·detail). 트리 조회(`category?action=tree`)는 분류 행 + 비전검사항목 요약(id·code·name·유형·상태·category_id)을 준다 — 관리자가 아니어도 메뉴 권한이면 본다

## 4. 비전 데이터 관리 메뉴

```text
비전 데이터 관리
├── 수입검사                         ← 대분류 (objId cat<id>)
│   └── Rotor 수입검사 성적서         ← 중분류
│       └── Rotor 표면 결함(수입)     ← 비전검사항목 = 끝 메뉴. 누르면 비전검사항목 홈
└── 미분류                           ← 소속 없는 항목이 있을 때만 (objId cat0)
```

- 볼 수 있는 항목(`ItemAccessService.visible_items`)이 없는 대분류·중분류는 감춘다. 순서는 분류 `sort_order`, 이름 순
- 항목 끝 메뉴 id 는 `item<id>_wm_data_item_detail`(지금 홈 탭 id 와 같다 — 열린 탭이 그대로 이어진다). 홈 메뉴 권한이 없으면 권한 있는 첫 화면을 연다
- 나머지 화면(데이터 목록·라벨링·검수·스냅샷)은 **비전검사항목 홈 위쪽 버튼**으로 연다. 홈 API(`item_home?action=detail`)가 `screens`(권한 있는 하위 화면 코드·이름, 치수 측정은 데이터 목록만)를 준다.
  탭 id 는 지금처럼 `item<id>_<menu_code>`, 탭 제목 "항목명 · 화면명"
- 좌측 메뉴 템플릿을 4단계(폴더 › 대분류 › 중분류 › 항목)로 넓힌다 — 테마 CSS `side-nav-forth-level` 이 있다. 접힌 사이드바는 중분류부터 펼침 메뉴 안에서 아래로 펼친다

## 5. 양식 편집기

- 이미지 칸의 비전검사항목 고르기를 묶는다: 맨 위 "이 양식 분류 — <중분류>" 그룹(그 양식 코드에 매핑된 중분류의 항목), 이어서 "대분류 › 중분류" 그룹들, 마지막 "미분류".
  `optgroup` 으로 만든다. 매핑이 없는 양식이면 맨 위 그룹 없이 안내 한 줄("검사 분류 관리에서 이 양식을 중분류에 매핑하면 그 항목이 먼저 나옵니다.")
- 편집기 위쪽에 "검사 분류: <대분류> › <중분류>"(매핑이 있을 때)
- 점검항목 섹션의 이미지 열에 [이미지 칸 모두 연결] — 고른 항목을 그 섹션의 이미지 칸 전부에 넣는다(바꾸면 새 버전 규칙 그대로)
- 저장할 때 비전검사항목이 없는 이미지 칸이 있으면 개수를 알리고 묻는다(막지 않는다 — 열화상 증빙처럼 비전 대상이 아닌 사진 칸이 있다)

## 6. 검사 작업 (수입)

- **입고 내역**: `wm_receipt` 를 기준정보 폴더로 옮기고 이름 "입고 내역". 검색의 검사 상태·검사 대상만, 목록의 검사양식·검사 상태·[검사 작성] 을 뺀다. 조회 전용
- **품목 검사양식 매핑**: 양식 기준. 왼쪽 수입 양식 목록(사용 중인 최신 버전, 매핑 품목 수) → 오른쪽 그 양식의 품목 목록. [품목 추가](품목 검색 모달, 여러 개 선택)·행 [삭제]
- **수입 검사작성 작업 목록 = 검사 작업**. 한 줄이 작업 하나다
  - 대기: 매핑된 (입고 × 양식코드) 중 그 양식코드·입고번호로 쓴 작성건이 없는 것. 저장하지 않고 센다 — 입고가 반영되면 바로 나온다. 양식의 가장 높은 버전이 사용 중이 아니면 나오지 않는다
  - 작성 중: 지금 작성 중 목록(입고와 무관한 수기 작성 포함)
  - 행 [작성](대기) = 사용 중인 최신 버전·입고번호로 새 작성, [열기](작성 중) = 지금과 같다. [신규 작성] = 수기
- "같은 양식·입고번호 작성 중 하나" 규칙을 양식 **버전** 기준에서 양식 **코드** 기준으로 바꾼다(작업이 코드 기준이라서)
- 검사 대기 배지 = 대기 작업 수 + 작성 중 중 입고에 걸린 작업 수(= 매핑된 쌍 중 완료가 아닌 것). 좌측 메뉴 "수입 검사작성 작업" 옆으로 옮긴다. API 는 `dig_form?action=job_count`
- 자재입고 검색 팝업(수기 작성의 입고번호 채우기)은 그대로 입고 API 를 쓴다(검사 대상만 = 매핑된 품번)

## 7. 거치대 결과 불러오기

- 이미지 칸이 거치대 항목(`capture_method=RIG`)에 연결돼 있으면 작성 화면에 [거치대 결과 불러오기]. 치수 측정 항목은 이 버튼만(사진 넣기 없음). 태블릿 항목은 지금처럼 [사진 넣기]만
- 팝업은 그 항목의 최근 30일 검사 결과(이미지가 있는 것, 최신순 50건): 검사 시각·클라이언트·판정(이상/정상/분류 1순위/치수면 측정점별 값·범위·합불). 썸네일은 두지 않는다 — 고르기 전에는 사진 제공 규칙(세션·저장 값)에 걸리지 않는다.
  고르면 칸 값 = 그 결과의 `ImageAsset` id 이고, 칸의 [보기]로 사진을 본다
- 서버: `dig_form?action=rig_results`(조회)·`use_rig_result`(쓰기 — 그 결과가 칸의 항목 것인지 확인하고 asset id 를 세션 목록 `dig_form_captures` 에 넣는다). 저장 검증(`find_cell_asset`)·사진 제공(`DigFormAssetView`)은 바꾸지 않는다
- 같은 결과를 여러 칸·여러 검사에 넣어도 된다(사진 넣기의 중복 허용과 같다)
- 보기·결과 화면: 칸 값 이미지가 거치대 검사에서 왔으면 칸 아래에 판정(치수면 측정점별 "540.32 mm (539~541) 합격")
- 양식 편집기의 연결 목록에서 치수 측정 항목을 빼던 것을 없앤다. `capture_image` 의 치수 측정 거절은 둔다(측정값 없는 사진은 의미가 없다)

## 8. 비전검사항목 정리 (시드 `seed_vision_items`)

대분류 4개(순서대로 수입검사 `INCOMING`, 조립검사·품질검사·출하검사 `OUTGOING`)와 중분류 6개를 넣고 항목 소속을 정한다. **양식 매핑은 넣지 않는다**(양식 코드가 환경마다 다르다 — 화면에서 매핑).
이미 소속이 있는 항목은 바꾸지 않는다. 분류는 이름으로 찾아 없으면 만든다(멱등).

| 대분류 | 중분류(근거 시트) | 비전검사항목 |
|---|---|---|
| 수입검사 | Rotor 수입검사 성적서(05) | VIS-ROT-SF, VIS-ROT-DIM |
| 수입검사 | 수입검사성적서(가공품)(04) | **TAB-PRT** |
| 수입검사 | 전장 ASSY Check Sheet(06) | TAB-TRM |
| 조립검사 | Module Check Sheet(13) | TAB-IMK, **TAB-EPD**, **TAB-FAN**, **TAB-HTR**, **TAB-SNS**, **TAB-BLT**, **TAB-CFN** |
| 품질검사 | 8계통 Check Sheet(15) | **TAB-CBL** |
| 출하검사 | 출하검수 Sheet(18) | TAB-LBL, VIS-CLN, TAB-ROT, **TAB-EXT** |

배치 원칙: 항목은 **처음 공식 판정하는 시트**의 중분류에 둔다. 09~11 조립 SOP 는 문서 대장(01)에 없는 참고 문서라 조립 항목은 공식 기록 양식 13 Module Check Sheet 에 모은다.
TAB-TRM 은 AX 1.3(원류관리 전장 Assy 검사 "단자 압착 상태 외 29항목")·06 전장 BOX 사전검수에서 처음 판정하므로 수입검사다.

신규 9개(굵게)와 기존 항목의 클래스 추가. 설명은 기존 6개 머리(■ 검사 목적 / ■ 검사 항목 / ■ 검사 기준 / ■ 역할 / ■ 촬영 방법 / ■ 라벨링 기준 / ※ 근거와 결정)로 쓴다.
기존 클래스 이름과 같은 뜻이면 기존 이름을 쓴다.

| 코드 | 이름 | 유형 | 근거 시트 행 | 클래스(이름 · 표시명) |
|---|---|---|---|---|
| TAB-PRT | 판금·가공품 외관(수입) | 객체 탐지 | 04 공통 › 용접 후 외관·제품 외관 6항목, 06 1. No21 ①②③·No22, 08 No2②·No4·5, 16 입고 11행 | scratch Scratch · dent 찍힘 · crack 균열/Broken · contamination 오염/이물 · burr Burr/가공 Chip · corrosion 산화/부식/백화 · weld_defect 용접 결함 · coating_peel 도장 박리 |
| TAB-EPD | EPDM·단열재 부착 | 객체 탐지 | 09 조립 중요 Point 17~20행, 11 No1①·5①·6①, 13 Heater 46행, 16 27·29행 | epdm_gap 이음부 틈 · epdm_missing 미부착 · epdm_torn 찢어짐 |
| TAB-FAN | FAN 장착(볼 마우스·방진고무) | 객체 탐지 | AX 2.1, 02 No3 FAN, 09 중요 Point 13~16행, 13 FAN 31행 | bellmouth_interference 볼 마우스 간섭 · mount_twist 방진고무 뒤틀림 |
| TAB-HTR | Heater 코일·PAD 조립 | 이상 탐지 | 11 No2·3·4, 중요 Point 14~17행, 16 24~26·28행 | coil_tilt 수평 불량 · coil_twist 코일 뒤틀림 · coil_gap 간격 불균일 · pad_bad PAD 이탈/과눌림 |
| TAB-SNS | 센서·컨트롤러 설치 | 객체 탐지 | 09 No8, 11 No1①(Sensor)·No4①, 13 FAN 32·34행, Heater 48행 | seal_tape_missing Teflon Tape 미마감 · cap_not_removed 보호캡 미제거 · controller_lifted 컨트롤러 들뜸 · bolt_direction 고정 볼트 방향 불량 |
| TAB-BLT | Rotor Belt 장착·Tension 표기 | 객체 탐지 | 10 BELT TENSION 절차 1·2·5, SETTING 완료 이미지 칸 | belt_off 위치 이탈 · rivet_interference Rivet 간섭 · tension_mark_missing Tension 수치 미기입 |
| TAB-CFN | Cooling FAN 방향·보호 Cover | 분류 | 11 No7·8, 16 30행, 15 6.4③·6.5① | fan_ok 정상 · fan_reversed 역조립 · cover_missing 보호 Cover 누락 |
| TAB-CBL | 전장 배선 정리·포트 마감 | 객체 탐지 | 14 카드 2·7·10·41·45, 15 1.1④·3.4·5.3~5.11·7.3②③·7.4, 06 1. No10·26~28, 09 No9①, 13 FAN 36·Heater 51행, 16 17행 | tie_uncut Tie 끝단 미절단 · tie_misuse Tie 로 부품 고정 · port_open 미사용 Port/Hole 미마감 · cable_coiled Cable 말아둠 · cable_bent Cable 꺾임/눌림 · connector_loose 커넥터 고정 불량 |
| TAB-EXT | 설비 외관 손상·오염·이물 방치 | 이상 탐지 | 14 카드 11·12·21, 15 1.1⑦·6.2·7.1①③④⑤, 18 Cleaning 구역 "Bolt, Nut, Tie, 이물질 방치" | paint_damage 도장 손상 · dent 찍힘/찌그러짐 · gap_step 틈/단차 · stain 오염/얼룩 · foreign_object 이물 방치 |

기존 항목 클래스 추가: TAB-TRM — connector_loose 커넥터 들뜸/체결 누락 · numbering_bad 넘버링 불량 · terminal_bent 단자 꺾임 · lug_wrong 단자 형식 불량(Y형) · ground_bad 접지 체결 불량 · terminal_foreign 단자 이물 /
TAB-IMK — bolt_missing 볼트 미체결(빈 Hole) · hole_open 미사용 Hole 미마감 · washer_missing 와셔 누락 / TAB-LBL — ems_cover_missing EMS Cover 누락.
기존 항목 이름은 시드가 바꾸지 않는다(관리 화면에서 고친다).

만들지 않는 것: 공압 배관·포장 상태·납땜(근거 부족, 보류). Torque·Tension·Leak·온도·동작·I/O·OCR(명판 내용·SW 버전)은 비전 대상이 아니다.
현업 확인이 남은 것(§9 D21~D25)은 시드 설명의 "※ 근거와 결정"에 "확인 필요"로 적는다.

## 9. 결정 (모두 권장안, 사용자 결정 2026-10-21)

| # | 결정 |
|---|---|
| D1 | 분류는 테이블 하나(대분류·중분류 행), 테넌트·RLS. 비전검사항목에 소속 중분류 FK |
| D2 | 대분류도 화면에서 관리(지난 A안 고정 목록을 바꿈). 처음 4개는 시드, 대분류마다 양식 구분 |
| D3 | 중분류 : 양식 = 1 : 1(양식 하나는 중분류 하나에만). 양식 없는 중분류 허용 |
| D4 | 양식 코드로 매핑(버전 무관), 섹션 양식만 |
| D5 | 아래가 비어야 삭제. 매핑을 풀어도 이미지 칸 연결은 그대로 |
| D6 | 비전검사항목 관리를 새 화면으로 합친다(메뉴 코드 `wm_data_item` 재사용) |
| D7 | 분류는 메뉴 권한(W), 비전검사항목 작업은 플랫폼 관리자만 |
| D8 | 화면은 항목결과 코드관리 모양 |
| D9 | 편집기: 이 양식 분류 항목을 맨 위, 다른 분류도 고를 수 있음. 편집기에서 항목 만들기는 없음 |
| D10 | 이미지 칸 미연결은 막지 않고 경고, [이미지 칸 모두 연결] |
| D11 | 비전 데이터 관리 메뉴: 대분류 › 중분류 › 항목(끝 = 홈), 나머지 화면은 홈 버튼. 빈 분류 감춤 |
| D12 | 품목 검사양식 매핑 N:M, 품번만 |
| D13 | 검사 작업 = 입고 × 매핑 양식, 대기는 계산 |
| D14 | 거치대 결과: 최근 30일, 중복 허용, 치수 측정 항목 연결 허용(Q5 변경) |
| D15 | 행 N개 제외 |
| D16 | 클라이언트 카탈로그에 분류를 내보내지 않는다 |
| D17 | 코드 규칙 VIS-(거치대)/TAB-(태블릿) 유지 |
| D18 | 시드는 분류·소속·신규 9개·클래스 추가. 양식 매핑은 시드하지 않는다 |
| D19 | (담당자·양식 작성자) DF0012 양식 구분 → 수입, DF0016 이미지 열 추가, 8계통은 DF0014 매핑(DF0009 칸 단위 제외), 13·18 시트는 섹션 양식으로 새로 만들어 매핑 |
| D20 | 공압 배관·포장 상태·납땜은 보류 |
| D21~D25 | (현업 확인) I-Marking Cover 기준은 18번을 따름 / TAB-PRT 는 태블릿 / Rotor 는 거치대, 가공품·전장 BOX 는 샘플 검사 때 태블릿 / 누락은 개수를 POINT 수와 비교·볼트는 빈 Hole 클래스 / 18번은 출하검사 |
