# 디지털 양식 이미지 칸에 거치대 결과 불러오기 구현 계획

> 실행: superpowers:executing-plans(또는 subagent-driven-development)로 이 문서 순서대로 한다. 단계는 체크박스(`- [ ]`)로 표시한다.

**목표:** 거치대 비전검사항목에 연결된 이미지 칸에서 그 항목의 최근 검사 결과를 골라 넣고, 보기·결과 화면에서 그 판정(치수면 측정점별 값)을 칸 아래에 보인다. 치수 측정 항목도 이미지 칸에 연결한다.

**구조:** 칸 값은 지금처럼 `ImageAsset` id 다. 고른 결과의 asset id 를 세션 목록 `dig_form_captures` 에 넣으면 저장 검증(`find_cell_asset`)과
사진 제공(`DigFormAssetView`)이 바뀌지 않고 받는다(거치대 이미지도 그 항목의 업로드 데이터셋에 있다). 판정 문구는 비전 검사 결과 화면의 것을 서비스로 뽑아 같이 쓴다.
마이그레이션 없음.

**설계:** [docs/superpowers/specs/2026-10-21-inspection-rework-design.md](../specs/2026-10-21-inspection-rework-design.md) §7·9(D14)

## 공통 제약

- 같은 worktree·브랜치(`.worktrees/inspection-rework`, `feat/inspection-rework`). plan 1·2 와 독립 — 마이그레이션 적용을 기다리지 않고 해도 된다
- 테스트는 `--settings=configurations.test_settings`, 고친 범위만. e2e 는 8124 로, `E2E-` 데이터만(검사 결과·클라이언트·이미지 포함 지운다)
- 사용자 문구 `~합니다` 체, 값은 `.text()`. `/api/v1` 은 바꾸지 않는다
- 권한: 조회는 그 구분의 검사작성 메뉴 권한, 넣기는 그 구분의 검사작성 `W`(사진 넣기와 같다 — 비전검사항목 배정은 보지 않는다, DECISIONS 2026-10-19)

---

### Task 1: 판정 문구를 서비스로

**Files:** `domain/services/vision/inspection.py`, `app/views/vision/inspection.py`(99–122 `_detail`), `tests/test_vision_inspection_filters.py`

```python
def judgement_text(inspection):
    """화면 한 줄 판정 — 처리 중·실패면 상태 이름, 분류는 '<이름> (<점수>)', 그 밖은 '이상'·'정상'."""
def measured_rows(inspection):
    """치수 측정 측정점별 [{label: '<이름> (<코드>)', text: '540.32 mm (539~541) 합격', ok}] — 측정이 아니면 []."""
```

- `_detail` 의 `measured`·분류 문구가 이 함수를 부른다(응답은 그대로)

- [ ] 실패하는 테스트: `judgement_text` 4가지(RECEIVED·FAILED·분류·이상/정상), `measured_rows` 형식(기존 `test_치수_측정은_측정점마다_값_범위_합불을_준다` 기대값 그대로)
- [ ] 구현 → 통과(기존 `tests.test_vision_inspection_filters` 포함) → 커밋 `refactor: 비전 검사 판정 문구를 서비스 함수로 뽑는다`

### Task 2: 치수 측정 항목 연결 허용·칸 연결 정보

**Files:** `app/views/system/form_edit.py`(117–124), `domain/services/dig_form_image.py`(`vision_links` 125–141), `tests/test_dig_form.py`

- `vision_items` 의 `.exclude(task_type=MEASUREMENT)` 와 Q5 주석을 지운다(주석: "치수 측정 항목은 거치대 결과 불러오기로만 넣는다(2026-10-21)")
- `vision_links` 가 칸마다 `task_type`·`capture_method` 를 더 준다
- `capture_image` 의 치수 측정 거절은 둔다

- [ ] 실패하는 테스트: `test_치수_측정_항목은_연결_목록에_없다`(863–868) → `…목록에_있다` 로 바꿈 / 치수 측정 항목을 연결한 양식 저장 성공 / `detail` 칸의 `vision_item` 에 `task_type`·`capture_method` / 치수 측정 칸 capture 는 여전히 거절(665–671 그대로)
- [ ] 구현 → 통과 → 커밋 `feat: 디지털 양식 이미지 칸에 치수 측정 비전검사항목을 연결한다`

### Task 3: 거치대 결과 API

**Files:** `app/views/dig_form/dig_form.py`, `domain/services/dig_form_image.py`, `tests/test_dig_form.py`(`DigFormRigResultTest` 생성)

서비스:

```python
RIG_RESULT_DAYS = 30
RIG_RESULT_LIMIT = 50

def rig_results(vision_item_id):
    """그 항목의 최근 30일 검사 결과 중 이미지가 있는 것, 최신순 50건 —
    [{id, created, client_name, status, judgement, measured, asset_id, abnormal}] (judgement·measured 는 Task 1 함수)."""

def rig_result_asset(vision_item_id, inspection_id):
    """그 항목의 검사 결과면 ImageAsset id, 아니면 ValueError('불러올 검사 결과를 찾을 수 없습니다.').
    기간은 보지 않는다(목록을 연 뒤 30일이 지나도 넣는다)."""
```

API(`WRITE_ACTIONS` 에 `use_rig_result` 를 더한다):
- `rig_results`(item_id = 칸 id) — 칸이 비전 연결 이미지 칸이 아니면 "비전검사항목이 연결된 이미지 칸이 아닙니다."(capture 와 같은 문구), 연결 항목이 거치대(`RIG`)가 아니면 "거치대 비전검사항목이 연결된 칸이 아닙니다." → `{'rows': [...]}`
- `use_rig_result`(item_id, inspection_id) — 같은 칸 검사 + `require_write(user, [양식 구분])` → asset id 를 세션 `CAPTURE_SESSION_KEY` 목록에 넣는다(capture 의 359–361행과 같은 식) → `{'success': True, 'message': '', 'asset_id': n}`
- `result_values`(295–317)·`detail` 의 저장 값 응답에, 비전 연결 이미지 칸 값이 거치대 검사 결과의 이미지면 `vision_result: {judgement, measured, created}` 를 붙인다(`VisionInspection.objects.filter(image_asset_id__in=…)` 한 번)

- [ ] 실패하는 테스트(`DigFormVisionCaptureTest` setUp 본보기 + `tests/test_vision_inspection_filters.py:94–109` 의 VisionInspection 만들기):
  목록 — 그 항목 것만·30일 밖 제외·이미지 없는 것 제외·최신순·치수면 measured / 태블릿 항목 칸·연결 없는 칸 거절 /
  use → 세션에 들어가고 그 값으로 save 성공·칸 값 = asset id / 다른 항목 결과 거절 / 쓰기 권한 없으면 403 / GET 으로 use 403 /
  같은 결과를 두 칸에 넣기 성공 / 결과 보기 응답에 `vision_result`(치수면 측정점 문구)
- [ ] 구현 → 통과 → `verify_response_keys.py` → 커밋 `feat: 디지털 양식 이미지 칸에 거치대 검사 결과를 불러온다`

### Task 4: 화면 — 불러오기 팝업·칸 아래 판정

**Files:** `app/templates/dig_form/dig_form_capture.html`(같은 파일에 `DigFormRigResult` 클래스), `app/templates/dig_form/dig_form_renderer.html`(371–378 `makeImageInput`·601–611 보기·713–724 이벤트), `tests/e2e/test_dig_form.py`

- `makeImageInput(cell)`: 칸의 `vision_item` 이
  - 치수 측정 → [거치대 결과 불러오기]만
  - 거치대(`capture_method === 'RIG'`) → [사진 올리기]·[거치대 결과 불러오기]
  - 태블릿·연결 없음 → 지금 그대로
- `DigFormRigResult(cell, fnUse)`: `PopupDraggable('거치대 결과 불러오기')` — 표(검사 시각·클라이언트·판정·측정값, 썸네일 없음 — 고르기 전에는 `DigFormAssetView` 가 내주지 않는다),
  행 [선택] → `use_rig_result` → `fnUse(asset_id)` → 닫음(이제 세션에 있어 칸의 [보기]가 사진을 연다). 결과가 없으면 "최근 30일 거치대 검사 결과가 없습니다."
- 보기 모드(611행 자리): `vision_result` 가 있으면 판정 한 줄과 측정점 줄(합격·불합격 색은 기존 토큰)
- 이벤트: `.dig-form-rig-result` 클릭 → 팝업 → `setImage($box, assetId)` + `change`(사진 넣기와 같은 흐름)

- [ ] `verify_screen_js.js` → 실패하는 e2e(픽스처: `manage_shell` 로 E2E- 거치대 항목·VisionClient·이미지·VisionInspection(치수 측정 하나 포함)과 그 항목을 연결한 E2E 양식, finally 에서 지움):
  거치대 칸에 [거치대 결과 불러오기] → 고르면 칸에 이미지 → 저장 → 보기에서 판정 줄 / 치수 측정 칸은 사진 올리기가 없고 측정점 줄이 보인다 / 태블릿 칸은 불러오기 버튼이 없다
- [ ] 통과 → `verify_modals.py`·`verify_buttons.py`·`verify_dig_form_width.py` → 커밋 `feat: 검사작성 이미지 칸의 거치대 결과 불러오기와 판정 표시`

### Task 5: 문서

**Files:** `docs/DECISIONS.md`(사용자 결정 2026-10-21 행: 거치대 결과 불러오기·치수 측정 연결 허용 — 43행 "디지털 양식 이미지 칸에는 연결하지 못한다" 를 이 행이 바꾼다고 적는다), `docs/FEATURES.md`(139·401·403–406행), `docs/STATUS.md`(남은 일: 불러온 측정값으로 같은 행 칸 채우기)

- [ ] 문서 → `verify_links.py`·`verify_korean_only.py` → 커밋 `docs: 거치대 결과 불러오기와 치수 측정 이미지 칸 연결을 문서에 적는다`
