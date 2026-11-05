# 치수 측정(MEASUREMENT) 유형 구현 계획

> 실행: superpowers:executing-plans 로 이 문서 순서대로 한다. 단계는 체크박스(`- [ ]`)로 표시한다.

**목표:** 비전검사항목 유형에 치수 측정을 더해 측정점을 정의하고, 클라이언트가 보낸 측정값을 서버가 저장·판정한다.

**구조:** 측정점은 새 테넌트 테이블 `vision_data_measurementpoint`(라벨 클래스와 같은 자리). 검사 접수는 치수 측정 항목이면
추론 대신 측정값을 검증·판정하고 `vision_inspection.measurements`·`calibration` 에 남긴다. 화면은 라벨 클래스 자리를 측정점으로 바꾸고,
라벨링·검수·스냅샷은 항목 유형으로 막는다.

**설계:** [docs/superpowers/specs/2026-10-20-measurement-type-design.md](../specs/2026-10-20-measurement-type-design.md)

## 공통 제약

- 모델·마이그레이션은 `migration/measurement-type` 브랜치(모델·마이그레이션 파일만). 공유 개발 DB 에 `migrate` 를 돌리지 않는다 — 사용자가 적용한다
- 작업은 worktree `.worktrees/measurement`(브랜치 `feat/measurement-type`). 8123 개발 서버 폴더는 main 그대로 둔다
- 테스트는 `--settings=configurations.test_settings`, 고친 범위만. e2e 는 마이그레이션 적용 뒤 worktree 서버(8124, `E2E_BASE_URL`)로
- 사용자 문구는 `~합니다` 체. `/api/v1` 을 바꾸면 `docs/client/SERVER_API_CONTRACT.md` 를 함께 고친다
- 값은 화면에 `.text()` 로 넣는다

---

### Task 1: 모델·마이그레이션 (`migration/measurement-type`)

**Files:** `domain/models/data.py`, `domain/models/vision.py`, `domain/migrations/0017_measurement.py`(생성), `tests/test_measurement.py`(생성)

- `InspectionItem.TaskType.MEASUREMENT = 'MEASUREMENT', '치수 측정'`, `CLIENT_INSPECTION_TYPE[MEASUREMENT] = 'MEASUREMENT'`
- `MeasurementPoint(TenantOwnedModel)`: `item`(FK CASCADE, related_name `measurement_points`)·`code`(20)·`name`(100)·`nominal`·`lower`·`upper`(Decimal 18,3)·`unit`(10, 기본 `mm`)·`description`(blank)·`sort_order`(PositiveSmallInteger).
  제약 `uq_measurement_point_code`(tenant,item,code), `ck_measurement_point_range`(lower ≤ nominal ≤ upper). db_table `vision_data_measurementpoint`, ordering `sort_order, id`
- `VisionInspection.measurements`·`calibration` = `JSONField(null=True, blank=True)`
- 마이그레이션 끝에 `run_sql` 로 RLS(ENABLE·FORCE·POLICY `vision_data_measurementpoint_tenant_scope`, 0001 과 같은 식)

- [ ] 실패하는 테스트: 범위 제약(하한 > 기준값이면 IntegrityError), 같은 코드 두 번 IntegrityError
- [ ] 모델 작성 → `makemigrations domain --name measurement` → RLS run_sql 추가 → `sqlmigrate` 로 DDL 확인
- [ ] 테스트 통과, `makemigrations --check`
- [ ] 커밋(모델·마이그레이션 파일만) → 그 커밋에 `migration/measurement-type` 브랜치, 테스트 파일은 다음 커밋

### Task 2: 검사 접수 — 측정값 검증·판정·응답

**Files:** `app/views/api_v1.py`, `domain/services/vision/inspection.py`, `tests/test_client_api.py`

- `parse_metadata`: `measurements` 는 그대로 넘기고(항목을 알아야 검증), `calibration` 은 없거나 null 이면 None, 객체가 아니면 `METADATA_INVALID`, 문자열 값은 50자까지
- `InspectionService.receive_capture(..., measurements=None, calibration=None)`: 항목을 찾은 뒤·이미지를 쓰기 전에 치수 측정이면
  `judge_measurements(points, raw)` → 실패면 `MeasurementInvalid`(→ 422 `MEASUREMENT_INVALID`). 성공이면 생성 시 `status=SUCCESS`·`abnormal`·`measurements`·`calibration` 을 넣고 추론을 부르지 않는다. 다른 유형은 `measurements` 를 무시한다
- `judge_measurements`: 리스트, 원소는 `{code, value}`, 코드는 측정점 전부 정확히 한 번, `value` 는 bool 아닌 유한 숫자. 결과는 측정점 순서로 `{code,name,value,lower,upper,unit,ok}`(소수는 float), `ok = lower ≤ Decimal(str(value)) ≤ upper`
- `serialize_inspection` 에 `measurements` 키(치수 측정이 아니면 null)

- [ ] 실패하는 테스트: 정상 SUCCESS·abnormal false / 경계값(하한·상한 포함) / 하나 벗어남 abnormal true / 빠진 점·모르는 코드·중복·문자열·NaN·bool → 422 이고 이미지·검사 행 0건 / measurements 없음 → 422 / 다른 유형에 보내면 무시·`measurements` null / calibration 저장, 객체가 아니면 422 METADATA_INVALID / 같은 request_id 재전송 200
- [ ] 구현 → 통과 → 커밋

### Task 3: 카탈로그 `include=measurement`

**Files:** `app/views/api_v1.py`, `tests/test_client_api.py`

- `include` 를 쉼표로 나눠 집합으로 본다. `CLASSIFICATION`·`MEASUREMENT` 는 요청한 것만. 치수 측정 항목에 `measurement_points`(코드·이름·기준값·하한·상한·단위·설명, float)
- [ ] 실패하는 테스트: 기본 카탈로그에 없음 / `include=measurement` 에 있음·측정점 / `include=classification,measurement` 둘 다 / 다른 유형에 `measurement_points` 키 없음 / 측정점이 바뀌면 지문이 바뀜
- [ ] 구현 → 통과 → 커밋

### Task 4: 측정점 관리 (비전검사항목 홈)

**Files:** `app/forms/item.py`, `domain/services/data/item.py`, `app/views/item/item_home.py`, `app/templates/data/item.html`, `tests/test_item_api.py`

- `MeasurementPointForm`: code(20, 영문·숫자·`_-`)·name(100)·nominal/lower/upper(Decimal 18,3)·unit(10, 기본 mm)·description. `clean` 에서 하한 ≤ 기준값 ≤ 상한
- `ItemService.create/update/delete_measurement_point` — 라벨 클래스와 같은 모양(권한·감사 기록). 측정 결과에 나온 코드는 바꾸거나 지울 수 없다
- `item_home`: `point_create`·`point_update`·`point_delete`. 치수 측정 항목이 아니면 거절, 치수 측정 항목은 라벨 action 거절. `detail` 에 `points`
- 화면: 치수 측정 항목이면 홈 카드·편집 창 탭 제목을 "측정점"으로, 표는 코드·이름·기준값·하한·상한·단위. 요약 카드는 전체 이미지만
- [ ] 실패하는 테스트: 등록·수정·삭제 / 범위 오류·코드 중복은 400 문구 / 측정 결과가 있는 코드 변경·삭제 거절(이름·규격 수정은 됨) / 다른 유형에 point action 거절 / 치수 측정 항목에 label action 거절 / detail 의 points
- [ ] 구현 → 통과 → 커밋

### Task 5: 라벨 계열 차단과 목록 제외

**Files:** `app/views/item/__init__.py`, `app/views/system/menus.py`, `app/views/api_v1_datasets.py`, `app/views/vision/model_mapping.py`,
`app/views/system/form_edit.py`, `domain/services/dig_form_image.py`, `app/templates/data/item_list.html`, 해당 테스트 파일

- `load_item`: 요청 뷰가 `labeling`·`review`·`snapshot` 이고 항목이 치수 측정이면 `ItemApiError('치수 측정 비전검사항목은 라벨링·검수·스냅샷을 쓰지 않습니다.')`
- 좌측 메뉴: 치수 측정 항목은 홈·데이터 목록만
- 데이터셋 API `task_type=MEASUREMENT` → `invalid`
- 모델 매핑: 목록·모델·저장 모두 치수 측정 항목 제외
- 양식 편집기 `vision_items` 에서 제외, `capture_image` 는 거절
- 등록 창 작업 유형에 "치수 측정"
- [ ] 실패하는 테스트 → 구현 → 통과 → 커밋

### Task 6: 검사 결과/이력 상세

**Files:** `app/views/vision/inspection.py`, `app/templates/vision/inspection.html`, `tests/test_vision_inspection_filters.py`

- `_detail` 에 `measurements` 그대로. 화면은 측정점마다 한 줄 `측정 <코드> · <이름>` / `<값> <단위> (<하한>~<상한>) 합격|불합격`, 불합격은 `text-danger`
- [ ] 테스트 → 구현 → 커밋

### Task 7: 시드 `VIS-ROT-DIM`

**Files:** `domain/management/commands/seed_vision_items.py`, `tests/test_seed_vision_items.py`

- 항목 + 측정점 A·B·C(540±1, 540±1, 154±1). 없는 것만 만든다(기존 값을 덮지 않는다)
- [ ] 테스트 → 구현 → 커밋

### Task 8: 문서

`docs/client/SERVER_API_CONTRACT.md`(§0·§5·§5-1·§6-1·§6-2·§6-3·§6-6·§6-7·§11·§13·§15·§17, 서버 버전 1.1.0 — `APP_VERSION` 확인),
`docs/DATA_MODEL.md`(측정점·컬럼·RLS 14개), `AGENTS.md`(RLS 14개), `docs/DECISIONS.md`(사용자 결정 2026-10-20 치수 측정), `docs/FEATURES.md`, `docs/STATUS.md`(필요 시)
- [ ] 작성 → `verify_links`·`verify_korean_only`·`verify_naming` → 커밋

### Task 9: 마이그레이션 적용 뒤 화면 검증 (사용자 적용 대기)

- [ ] worktree 서버 8124 → e2e: 홈 측정점 CRUD, 등록 창 유형, 메뉴(치수 항목 하위 2개) — `E2E-` 데이터만
- [ ] `verify_buttons`·`verify_modals`·`verify_screen_js`·`verify_permission_map`
- [ ] 계약 문서 §5·§6-3 의 치수 측정 JSON 을 개발 서버 응답으로 바꾼다(지금은 서버 코드를 테스트 DB 로 돌려 떠 온 응답)
