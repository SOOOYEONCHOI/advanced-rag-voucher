# SCREEN_MAPPING — 화면 이관 매핑표

- 기준일: 2026-09-30
- 근거: `01_CURRENT_STATE_ANALYSIS.md`, `USER_DECISIONS.md` §1·§1.5·**§1.6**, Backbone 프롬프트 §4~§8·§13·§16
- **rev.2 (2026-09-30)**: 사용자 지시로 검사항목을 단일 엔티티로 통합하고 공정·제품·보존정책·이관 기능을 제외했다.
  정본은 `USER_DECISIONS.md` **§1.6**이다.
- **rev.3 (2026-10-01)**: 메뉴 구조를 재편했다 — 폴더 순서(비전→데이터→시스템), 기준정보 메뉴 제거,
  남의 화면을 가리키던 중복 메뉴 4개 제거, **데이터 관리에 검사항목별 3단 메뉴 도입**. §1 참고.
  아래 §2·§3 표는 이관 시점의 계획표다(상태 TODO 는 갱신하지 않았다). 실제 진행은
  `IMPLEMENTATION_STATUS.md` 가 정본이다.
- 목적: **AIDataHub와 vision-inspection Server의 모든 업무 화면이 ManufacturingAIPlatform에 빠짐없이 포함되었는지 검증한다.** (Backbone §16)
- 원칙: **화면을 임의로 제외하지 않는다.** 미이관은 "MES 기능으로 대체", "업무 화면이 아님", **"사용자 지시로 기능 자체를 제외"** 세 가지 사유만 허용하며, 사유를 명시한다.

## 표기

| 이식 방식 | 뜻 |
|---|---|
| `REUSE_LOGIC` | 전문 로직(JS 모듈·알고리즘)을 그대로 재사용 |
| `ADAPT` | 로직 재사용 + MES 패턴에 맞게 조정 |
| `REWRITE` | 기능 개념만 유지하고 MES 구조(View 함수 + WeZonGrid 템플릿)로 재작성 |
| `REPLACE_WITH_MES` | MES 공통 기능으로 대체 → 이관하지 않음 |
| `EXCLUDE_GPU_RUNTIME` | GPU Runtime이라 이번 범위 제외 |

| 상태 | 뜻 |
|---|---|
| `TODO` | 미착수 |
| `IN_PROGRESS` / `DONE` / `BLOCKED` | 구현 단계에서 갱신 |

## 화면 주소 규약 (MES 계승)

```text
화면   /gui/<gui_code>/                → app/templates/<folder>/<screen>.html
API    /api/<task>/<view>              → app/views/<task>/<view>.py  의 동명 함수
팝업   /page/<folder>/<template_name>  → app/templates/page/<folder>/<name>.html
메뉴   menu_folder / menu_item(MenuCode=gui_code) + domain/gui.py GUI_ITEMS + apiPermissionMap
```

---

## 1. 최종 메뉴 트리

rev.3 (2026-10-01). 폴더 순서가 좌측 메뉴 순서다.

```text
ManufacturingAIPlatform
│
├── 비전 검사 관리                    (menu_folder id=4)
│   ├── 검사 결과/이력                wm_vis_inspection
│   ├── 검사 Client                   wm_vis_client
│   ├── Overlay 관리                  wm_vis_overlay
│   ├── AI 모델                       wm_vis_model
│   └── 검사항목 모델 매핑            wm_vis_model_mapping
│       ※ 검사항목 등록은 데이터 관리 > 검사항목 목록 한 곳에서 한다(§1.6 O-8·O-13)
│
├── 데이터 관리                       (menu_folder id=3)
│   ├── 검사항목 목록                 wm_data_item
│   ├── 작업 대기열                   wm_data_queue
│   └── <검사항목명>                  (동적 — InspectionItem 행마다 하나)
│       ├── 검사항목 홈               wm_data_item_detail  ?project=<id>
│       ├── 데이터 목록               wm_data_image        ?project=<id>
│       ├── 라벨링 작업               wm_data_labeling     ?project=<id>
│       ├── 검수 작업                 wm_data_review       ?project=<id>
│       └── 스냅샷 관리               wm_data_snapshot     ?project=<id>
│
└── 시스템 관리                       (menu_folder id=1 — MES 기존)
    ├── 사용자                        wm_user
    ├── 사용자그룹                    wm_user_group
    ├── 메뉴권한                      wm_user_group_menu
    ├── 다국어 설정                   wm_multi_language
    ├── 메뉴명 설정                   wm_menu_language
    ├── 프라퍼티마스터                wm_prop_master
    ├── 로그인로그                    wm_login_log
    ├── 메뉴로그                      wm_menu_log
    └── 시스템로그                    wm_system_log
```

### 검사항목 하위 메뉴 (동적)

검사항목은 메뉴 행이 아니라 데이터(`InspectionItem`)다. `app/views/system/menus.py`
가 트리를 만들 때 `wm_data_item` 이 속한 폴더 아래에 끼워 넣는다.

- **어느 검사항목이 보이나** — `ItemAccessService.visible_items()`. 메뉴권한이 아니라
  **검사항목 배정**이 정한다. RLS 때문에 `tenant_atomic()` 안에서 읽는다.
- **하위 5개 중 무엇이 보이나** — 메뉴권한을 받은 것만(`domain.gui.ITEM_CHILD_MENUS`).
- 이 5개의 `menu_item` 행은 **지우지 않는다**. `DATA_API_MENUS` 와 메뉴권한 화면의
  기준점이다. 폴더 최상단에서만 감춘다.
- 탭 이름은 `data-tab-title`("검사항목명 · 잎 이름")을 쓴다. 잎 이름만으로는
  검사항목이 둘일 때 `라벨링 작업` 탭이 두 개 생겨 구분이 안 된다.

### 메뉴에서 내린 화면

| 코드 | 사유 |
|---|---|
| `wm_data_quality` · `wm_data_export` | 품질 점검·Export 는 스냅샷 화면의 기능이다. 화면 정의도 지웠다 |
| `wm_data_activity` | 통계·활동이력은 작업 대기열 화면의 구역이다. 화면 정의도 지웠다 |
| `wm_vis_dashboard` | `vision/inspection.html` 을 가리키던 중복. 화면 정의도 지웠다 |
| `wm_code` · `wm_unit` · `wm_company` · `wm_depart` | MES 기준정보. 데이터관리·비전검사가 참조하지 않는다. **메뉴 행만** 제거하고 화면 정의·테이블은 남겼다(`seed_initial.RETIRED_FROM_MENU`) |

`wm_data_quality`·`wm_data_export`·`wm_data_activity` 를 지우면서 `DATA_API_MENUS` 의
`quality-runs`·`exports`·`activity-log` 기준점을 주인 화면으로 옮겼다. 그대로 두면
메뉴 행과 함께 권한이 사라져 **스냅샷 화면의 Export·품질 점검 버튼이 403** 이 된다.

---

## 2. AIDataHub → 데이터 관리

| Source | 기존 화면 | 기능 | Target Menu | Target View | 이식 방식 | 상태 |
|---|---|---|---|---|---|---|
| AIDataHub | `home/index.html` (`HOME`) — 참여 검사항목 | 참여 과제 카드, 통계, 라벨링 대기열, 최근 활동 | 데이터 관리 > 작업 대기열 (`wm_data_queue`) + 데이터 통계/활동이력 (`wm_data_activity`) | `app/views/data/queue.py`, `app/views/data/activity.py` / `templates/data/queue.html`, `data/activity.html` | `ADAPT` — 로그인 후 첫 화면은 MES `index.html`이므로 홈 카드 UI는 두 화면으로 분리 | TODO |
| AIDataHub | `project/home/index.html` (`MENU_PROJECT_HOME`) — 검사항목 홈 | 검사항목 개요·진행률·인원 배정 현황 | 데이터 관리 > 검사항목 (`wm_data_item`) 상세 탭 | `app/views/data/project.py` / `templates/data/project.html` | `REWRITE` | TODO |
| AIDataHub | `project/home/modal_edit.html` | 과제 편집(이름·유형·설명·대표이미지·업로드 가이드) | 위 화면 내 모달 | `templates/page/data/project_edit.html` | `REWRITE` (MES `modal.open({iframe})` 패턴) | TODO |
| AIDataHub | `project/home/modal_add_assignment.html` | 과제 인원 배정(PROJECT_MANAGER / WORKER) | 데이터 관리 > 검사항목 > 인원 배정 | `templates/page/data/project_assign.html` | `REWRITE` | TODO |
| AIDataHub | `system/projects/index.html` (`MENU_PLATFORM_PROJECTS`) | 검사항목 목록·검색 | 데이터 관리 > 검사항목 (`wm_data_item`) | `app/views/data/project.py` (`action=list`) | `REWRITE` (WeZonGrid) | TODO |
| AIDataHub | `system/projects/detail.html` | 과제 상세 + 멤버 관리 | 위 화면 상세 영역 | 동상 | `REWRITE` | TODO |
| AIDataHub | `system/projects/modal_create.html` | 과제 생성 | 위 화면 신규 모달 | `templates/page/data/project_edit.html` | `REWRITE` | TODO |
| AIDataHub | `system/projects/modal_add_member.html` | 과제 멤버 추가 | 위 인원 배정 화면과 통합 | `templates/page/data/project_assign.html` | `REWRITE` | TODO |
| AIDataHub | (화면 없음 — 과제 삭제 요청/승인 API) | 과제 삭제 승인 워크플로 | 데이터 관리 > 검사항목 (삭제요청/승인 탭) | `app/views/data/project_deletion.py` / `templates/data/project_deletion.html` | `ADAPT` — 기존에 전용 화면이 없어 **신규 화면 1개 추가** | TODO |
| AIDataHub | (과제 화면 내 라벨 클래스 CRUD) | LabelClass 등록·색상·`is_defect`·`annotation_shape`·정렬 | 데이터 관리 > 라벨 클래스 (`wm_data_labelclass`) | `app/views/data/label_class.py` / `templates/data/label_class.html` | `REWRITE` — 과제 종속 목록. **독립 메뉴로 승격** | TODO |
| AIDataHub | `project/data_manage/index.html` (`MENU_DATASET_UPLOAD`) | 이미지 목록·검색·썸네일·상세·삭제 | 데이터 관리 > 데이터 관리(이미지) (`wm_data_image`) | `app/views/data/image.py` / `templates/data/image.html` | `REWRITE` (목록은 WeZonGrid + 썸네일 그리드 병행) | TODO |
| AIDataHub | `project/data_manage/modal_upload.html` | 이미지 다중 업로드(중복 sha256 차단) | 위 화면 업로드 모달 | `templates/page/data/image_upload.html` | `ADAPT` — 업로드 JS는 재사용, 서버는 MES `files/` 패턴 | TODO |
| AIDataHub | `project/data_manage/modal_preprocess.html` | 데이터 정제 — 회전·원근 보정·크롭·크기 조정(원본 보존) | 데이터 관리 > 데이터 관리(이미지) > 정제 모달 | `templates/page/data/image_preprocess.html` | `REUSE_LOGIC` — Canvas 편집 JS 그대로 재사용 | TODO |
| AIDataHub | `project/labeling/index.html` (`MENU_DATASET_LABELING`) | **라벨링 Canvas** — 분류 / BBOX / POLYGON / 이상탐지, Zoom·Pan, claim·heartbeat·draft·submit | 데이터 관리 > 라벨링 작업 (`wm_data_labeling`) | `app/views/data/labeling.py` / `templates/data/labeling.html` | **`REUSE_LOGIC`** — Canvas JS 모듈 최대한 보존, 진입 구조만 MES Shell로 (Backbone §6) | TODO |
| AIDataHub | `project/review/index.html` (`MENU_DATASET_REVIEW`) | **검수 Canvas** — 승인 / 재작업(사유 입력), 어노테이션 확인 | 데이터 관리 > 검수 작업 (`wm_data_review`) | `app/views/data/review.py` / `templates/data/review.html` | **`REUSE_LOGIC`** — 동상 | TODO |
| AIDataHub | `project/snapshot/index.html` (`MENU_DATASET_VERSION`) — 품질점검 영역 | 데이터 품질 점검 4종 실행·결과(readiness, findings) | 데이터 관리 > 데이터 품질 점검 (`wm_data_quality`) | `app/views/data/quality.py` / `templates/data/quality.html` | `ADAPT` — **화면 분리**(한 화면에 3기능이 섞여 있었음) | TODO |
| AIDataHub | `project/snapshot/index.html` — 스냅샷 영역 | 불변 DatasetVersion 생성·manifest 조회 | 데이터 관리 > 스냅샷 관리 (`wm_data_snapshot`) | `app/views/data/snapshot.py` / `templates/data/snapshot.html` | `ADAPT` | TODO |
| AIDataHub | `project/snapshot/index.html` — Export 영역 | Export 8포맷 생성·진행 폴링·다운로드 | 데이터 관리 > Export (`wm_data_export`) | `app/views/data/export.py` / `templates/data/export.html` | `REUSE_LOGIC`(exporter 8종) + `REWRITE`(화면) | TODO |
| AIDataHub | (전용 화면 없음 — `DataStandard`/`StandardImage` 모델) | 데이터 표준 정의·표준 이미지 등록 | 데이터 관리 > 데이터 표준 (`wm_data_standard`) | `app/views/data/data_standard.py` / `templates/data/data_standard.html` | `ADAPT` — **신규 화면 1개 추가**(품질 점검이 참조하는 기준) | TODO |
| AIDataHub | `/media/image/<id>/`, `/thumbnail/`, `/project-cover/<id>/`, `/export/<id>/` | 권한 확인 후 파일 제공 | (화면 아님) | `app/views/files/data_image.py` 등 | `ADAPT` — MES `FilesView` 패턴으로 | TODO |
| AIDataHub | `system/organizations/index.html` + 모달 3종 (`MENU_PLATFORM_ORGANIZATIONS`) | 조직(Tenant) 관리·멤버·작업그룹·검사항목 접근권한 | **미이관** | — | `REPLACE_WITH_MES` — Backbone §5 명시. DEC-004로 단일 조직 고정이므로 조직 관리 UI 불필요. **작업그룹 기반 검사항목 접근권한은 `wm_data_item` 인원 배정 화면으로 흡수** | N/A |
| AIDataHub | `system/users/index.html` + 모달 3종 (`MENU_PLATFORM_USERS`) | 사용자 관리·조직 소속·검사항목 배정 | **미이관** (사용자 CRUD) | MES `wm_user` | `REPLACE_WITH_MES` — Backbone §5. 단 **검사항목 배정 기능은 `wm_data_item` 인원 배정으로 이관** | N/A |
| AIDataHub | `system/groups/index.html` + `modal_create.html` (`MENU_PLATFORM_GROUPS`) | 사용자그룹·메뉴권한 | **미이관** | MES `wm_user_group`, `wm_user_group_menu` | `REPLACE_WITH_MES` — Backbone §5 | N/A |
| AIDataHub | `app/login.html`, `account/tenant_select.html`, `account/password_change.html`, `common/_password_dialog.html`, `common/auth_base.html` | 로그인·조직 선택·비밀번호 변경 | **미이관** | MES `app/login.html`, `/page/account/myinfo` | `REPLACE_WITH_MES` — Backbone §5. 조직 선택은 DEC-004로 불필요 | N/A |
| AIDataHub | `app/layout.html`, `spa.js` | SPA Shell | **미이관** | MES `app/index.html` + `layout_page.html` | `REPLACE_WITH_MES` — Backbone §20-3 명시 금지 | N/A |
| AIDataHub | `403.html`, `404.html`, `500.html` | 오류 화면 | **미이관** | MES `403.html`/`404.html`/`error.html` | `REPLACE_WITH_MES` | N/A |

### AIDataHub 화면 이관 집계

| 구분 | 수 |
|---|---|
| 업무 화면 이관 (신규 메뉴) | **11** (`wm_data_*`) |
| 그중 기존 화면에서 분리·승격된 것 | 스냅샷 화면 1개 → 품질/스냅샷/Export 3개 |
| 그중 신규 추가 화면 | 2 (데이터 표준, 검사항목 삭제 승인) |
| 그중 vision에서 흡수 | 1 (검사 항목 → `wm_data_item`, §1.6 O-8) |
| 제안했다가 철회 | 1 (데이터셋 전용 화면 — Dataset은 내부 컨테이너다, §1.6 O-9) |
| MES로 대체(미이관) | 5 영역 (조직·사용자·사용자그룹·로그인/계정·SPA Shell/오류) |
| **누락** | **0** |

---

## 3. vision-inspection Server → 비전 검사 관리

| Source | 기존 화면 | 기능 | Target Menu | Target View | 이식 방식 | 상태 |
|---|---|---|---|---|---|---|
| vision | `dashboard.html` (`GET /admin/`) | 검사 건수·이상률·Client 상태 요약 | 비전 검사 관리 > 검사 현황 (`wm_vis_dashboard`) | `app/views/vision/dashboard.py` / `templates/vision/dashboard.html` | `REWRITE` — Backbone §17에 따라 **이관 확정**(이전 분석의 `[REPLACE]` 취소) | TODO |
| vision | `inspection_items/list.html` (`GET /admin/inspection-items`) | 검사 항목 목록(제품별), 검사 순서(`display_order`) | 비전 검사 관리 > 검사 항목 (`wm_vis_item`) | `app/views/vision/inspection_item.py` / `templates/vision/inspection_item.html` | `REWRITE` | TODO |
| vision | `inspection_items/form.html` | 검사 항목 등록·수정 | **데이터 관리 > 검사항목(`wm_data_item`)에 흡수** | `app/views/data/item.py` | `REWRITE` — §1.6 O-8. 검사항목과 저장소가 한 엔티티다 | TODO |
| vision | `inspection_items/model_mapping.html` (`/{id}/model`) | **검사항목 ↔ 모델 매핑**(활성 매핑 1개, 이력 보존) | **시스템 관리 > 검사항목 ↔ 모델 매핑** (`wm_sys_model_mapping`) + 검사 항목 화면에서 바로가기 | `app/views/system/model_mapping.py` / `templates/system/model_mapping.html` | `ADAPT` + `threshold_override` 컬럼 추가 (DEC-010, §1.5 O-2) | TODO |
| vision | `inspection_items/overlay.html` (`/{id}/overlay`) | Overlay 이미지 등록·삭제·`visible`·`opacity`·`version` 증가 | 비전 검사 관리 > Overlay 관리 (`wm_vis_overlay`) | `app/views/vision/overlay.py` / `templates/vision/overlay.html` | `ADAPT` — **독립 메뉴로 승격**(검사 항목 화면에서도 진입) | TODO |
| vision | `GET /admin/inspection-items/{id}/overlay/image` | Overlay 이미지 조회 | (화면 아님) | `app/views/files/vision_overlay.py` | `ADAPT` | TODO |
| vision | `models/list.html` (`GET /admin/models`) | AI 모델 목록 | 비전 검사 관리 > AI 모델 (`wm_vis_model`) | `app/views/vision/model.py` / `templates/vision/model.html` | `ADAPT` — Backbone §8. **메타데이터 전용** | TODO |
| vision | `models/form.html` (`/new`, `/{id}/edit`) | 모델 등록·수정 (`name`,`inspection_type`,`version`,`artifact_path`,`runtime`,`threshold`,`active`) | 위 화면 | 동상 | `ADAPT` + **아티팩트 파일 업로드·검증은 `EXCLUDE_GPU_RUNTIME`** (`artifact_path` 문자열만 입력) | TODO |
| vision | `POST /admin/models/{id}/active` | 모델 활성/비활성 | 위 화면 | 동상 | `ADAPT` | TODO |
| vision | `clients/list.html` (`GET /admin/clients`) | 검사 Client(장치) 목록·`last_seen_at` | 비전 검사 관리 > 검사 Client (`wm_vis_client`) | `app/views/vision/client.py` / `templates/vision/client.html` | `REWRITE` | TODO |
| vision | `clients/form.html` (`/new`) | Client 등록(`client_id`,`name`) | 위 화면 | 동상 | `REWRITE` | TODO |
| vision | `clients/created.html` | **API Key 1회 노출 화면**(재조회 불가) | 위 화면 발급 결과 모달 | `templates/page/vision/client_apikey.html` | `ADAPT` — 1회 노출 규칙 유지, 해시만 저장 | TODO |
| vision | `POST /admin/clients/{pk}/api-key` | API Key 재발급 | 위 화면 | 동상 (`action=reissue_key`) | `ADAPT` | TODO |
| vision | `POST /admin/clients/{pk}/active` | Client 활성/비활성 | 위 화면 | 동상 | `ADAPT` | TODO |
| vision | `inspections/list.html` (`GET /admin/inspections`) + `admin/filters.py` | 검사 이력 목록·필터(기간·Client·검사항목·판정·상태) | 비전 검사 관리 > 검사 결과/이력 (`wm_vis_inspection`) | `app/views/vision/inspection.py` / `templates/vision/inspection.html` | `REWRITE` | TODO |
| vision | `inspections/detail.html` (`/{id}`) | 검사 상세 — 판정·모델·`defects`·`anomaly_score`·capture 메타·원본/결과 이미지 | 위 화면 상세 영역 | 동상 (`action=detail`) | `REWRITE` + bbox 오버레이 렌더는 `REUSE_LOGIC` | TODO |
| vision | `GET /admin/inspections/{id}/image`, `/heatmap` | 검사 이미지·Heatmap 조회 | (화면 아님) | `app/views/files/vision_image.py` | `ADAPT` | TODO |
| vision | `POST /admin/inspections/{id}/delete` | 검사 기록 삭제 | 위 화면 | 동상 (`action=delete`) | `ADAPT` | TODO |
| vision | `login.html` (`GET/POST /admin/login`), `POST /admin/logout` | Admin 로그인 | **미이관** | MES `app/login.html` | `REPLACE_WITH_MES` — DEC-018. **`login_throttle`·세션 DB 재확인 로직은 MES 로그인에 이식** | N/A |
| vision | `base.html`, `_macros.html`, `admin.css`(`--vi-*` 토큰) | Admin Shell·공통 조각 | **미이관** | MES `layout_page.html` + WeZonGrid | `REPLACE_WITH_MES` — Backbone §7·§20-4 | N/A |
| vision | `error.html` | 오류 화면 | **미이관** | MES `403/404/error.html` | `REPLACE_WITH_MES` | N/A |
| vision | `cli.py create-admin` | 관리자 계정 생성 | **미이관** | MES `wm_user` | `REPLACE_WITH_MES` | N/A |
| vision | `cli.py create-client` | Client 생성 | **미이관**(화면으로 대체) | `wm_vis_client` | `REPLACE_WITH_MES` | N/A |
| vision | `cli.py seed-catalog` | 기준정보 시드 | (화면 아님) | `manage.py seed_vision_catalog` | `ADAPT` | TODO |
| vision | `cli.py fit-anomaly`, `export-detection` | PatchCore fit / 학습용 export | **미이관** | — | `EXCLUDE_GPU_RUNTIME` — DEC-027 (§1.5 O-1) | N/A |
| vision | `GET /api/v1/licenses/sources[/{f}]`, `/client-packages[/{f}]` | 무인증 배포물 다운로드 | **미이관** | — | 업무 화면이 아님 + Public Subnet 무인증 노출 위험 (DEC-024) | N/A |

### vision-inspection 화면 이관 집계

| 구분 | 수 |
|---|---|
| Admin 업무 화면 이관 | **5** (`wm_vis_dashboard`, `wm_vis_client`, `wm_vis_overlay`, `wm_vis_model`, `wm_vis_inspection`) + `wm_sys_model_mapping` |
| 데이터 관리로 흡수 | 1 (검사 항목 → `wm_data_item`, §1.6 O-8) |
| 사용자 지시로 제외 | 4 (검사 공정·검사 대상 제품 — §1.6 O-8 / 보존 정책 — O-10 / 데이터셋 이관 — O-9) |
| 그중 독립 메뉴로 승격 | Overlay(검사항목 하위 → 독립), 모델 매핑(검사항목 하위 → 시스템 관리) |
| MES로 대체(미이관) | 4 (로그인·Shell·오류화면·CLI 계정관리) |
| GPU Runtime 제외 | 2 CLI (`fit-anomaly`, `export-detection`) + 모델 아티팩트 업로드·검증 |
| 업무 화면 아님(미이관) | 2 배포물 엔드포인트 |
| **업무 화면 누락** | **0** |

---

## 4. MES → 시스템 관리 (유지 대상)

DEC-023 Option B에 따라 **시스템관리 + 최소 기준정보만** 유지한다. 아래 화면은 이관이 아니라 **MES 원본을 그대로 계승**하며, `gui.py`에서 항목만 정리한다.

| gui_code | 화면명 | Template | 처리 |
|---|---|---|---|
| `wm_user` | 사용자 | `system/user.html` | 유지 + 초기 비밀번호 `'1'` 하드코딩 제거 |
| `wm_user_group` | 사용자그룹 | `system/usergroup.html` | 유지 |
| `wm_user_group_menu` | 메뉴권한 | `system/usergroup_menu.html` | 유지 |
| `wm_code` | 코드정보 | `definition/code.html` | 유지 |
| `wm_unit` | 단위정보 | `definition/unit.html` | 유지 |
| `wm_company` | 업체정보 | `definition/company.html` | 유지(`UserProfile.Company` FK) |
| `wm_depart` | 부서정보 | `person/depart.html` | 유지(`UserProfile.Depart` FK) |
| `wm_multi_language` | 다국어 설정 | `system/multi_language.html` | 유지(인프라, DEC-021) |
| `wm_menu_language` | 메뉴명 설정 | `system/menu_language.html` | 유지 |
| `wm_prop_master` | 프라퍼티마스터 | `system/prop_master.html` | 유지 |
| `wm_login_log` | 로그인로그 | `system/login_log.html` | 유지 + IP·User-Agent·실패사유 컬럼 보강(DEC-018) |
| `wm_menu_log` | 메뉴로그 | `system/menu_log.html` | 유지 |
| `wm_system_log` | 시스템로그 | `system/system_log.html` | 유지 |
| `wm_batch_log` | 배치로그 | `system/batch_log.html` | 유지 + 조회 대상을 `BackgroundJob`으로 변경(DEC-022) |
| `wm_sys_model_mapping` | 검사항목 ↔ 모델 매핑 | `system/model_mapping.html` | **신규**(vision에서 이관) |
| (공장 설정) | `system/factory_setup.py` API | — | 화면 없음. `UserProfile.Factory` FK용 최소 유지 |

**제거 대상 gui 항목**: 위 목록과 `wm_noauth_default` 외의 MES GUI 항목 **약 359개**를 `domain/gui.py`에서 제거한다(영업·수주·생산·재고·LOT·출하·HACCP·설비보전·인원위생·DAS/태그·대시보드·전시회·AI/MLOps·고객사 전용·샘플).

---

## 5. 검증 체크리스트 (Backbone §16·§19)

Phase 9(통합 기능 검증)에서 이 표를 근거로 확인한다.

- [ ] AIDataHub 업무 화면 12개가 전부 `데이터 관리` 메뉴에서 접근된다
- [ ] vision Admin 업무 화면 10개가 전부 `비전 검사 관리`·`시스템 관리` 메뉴에서 접근된다
- [ ] 미이관 항목이 전부 "MES 기능으로 대체" 또는 "업무 화면 아님" 사유를 갖는다
- [ ] 라벨링·검수 Canvas의 BBox·Polygon·Mask·Zoom·Pan·Claim·Heartbeat·Draft·Submit이 동작한다
- [ ] Export 8포맷이 전부 생성된다
- [ ] 모든 화면이 `menu_item` + `user_group_menu`로 권한 통제된다
- [ ] 모든 `/api/<task>/<view>`가 `apiPermissionMap`에 등록되어 있다
- [ ] VisionInspectionClient API 6종이 응답한다
- [ ] 추론이 필요한 경로가 `GPU_INFERENCE_NOT_CONFIGURED`로 명확히 처리된다
