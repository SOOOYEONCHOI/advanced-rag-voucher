# 대시보드 — 내 할 일 + 현황 (실제 데이터)

작성 2026-10-23. 근거: 사용자 결정 2026-10-23(이 대화), FEATURES §10, STATUS 7-1.

## 1. 목표

로그인 첫 화면(`wm_dashboard`)을 **위: 지금 처리할 일 / 아래: 현황** 으로 다시 짠다.
예시 값(데모)은 모두 없애고 **실제 데이터만** 보인다. 마이그레이션은 없다.

## 2. 결정

| # | 결정 | 이유 |
|---|---|---|
| D1 | "내 할 일" 카드·표는 **그 메뉴 W 권한**이 있을 때 보인다. 대기 건은 전체를 세고, 내가 작성 중·내가 잡은 건은 따로 숫자로 강조한다 | 담당자 배정이 없다(권한은 메뉴 R·W 뿐, DECISIONS:63). 역할은 권한으로 갈린다 |
| D2 | "현황"은 **그 메뉴 R 권한**만큼 보인다 | 조회는 R(FEATURES §2) |
| D3 | 권한 있는 할 일 카드가 0건이면 **보이되 흐리게** "할 일 없음" | 자리가 흔들리지 않는다 |
| D4 | 카드 이름은 **메뉴 폴더 · 일** — `검사 작업 · 수입검사`, `검사 작업 · 품질검사`, `비전 데이터 · 라벨링`, `비전 데이터 · 검수` | "라벨링"만으로는 무엇의 라벨링인지 모른다 |
| D5 | 라벨링·검수는 **카드 합계 + 비전검사항목별 표**. 행 끝 [라벨링]·[검수] 버튼이 그 항목 탭의 내부 탭을 연다 | 라벨링·검수 화면은 비전검사항목 탭 안의 내부 탭이라 항목을 알아야 갈 수 있다 |
| D6 | 현황은 세 가지만: **최근 7일 검사 완료·부적합 차트**, **최근 7일 비전 데이터 등록 차트**(경로별), **최근 비전 검사 이력 표** | 사용자 선택. 기간은 7일 고정 |
| D7 | 넣지 않는다: 운영 할 일(인터페이스 실패·Export 실패·응답 없는 클라이언트), 비전검사항목 삭제 승인, 승인 대기·작업지시, 오늘 진행 도넛, 오늘 요약 카드, 이상률·양식별·협력사별 차트, 검사 완료 이력 표, 라벨 상태·학습 준비도, 스냅샷 | 사용자 결정. 승인·작업지시는 원천이 없다(STATUS 6 ①②) |
| D8 | 값은 대시보드 자기 API `/api/vision/dashboard`(`action=summary`) 하나가 준다. 다른 메뉴 API 를 부르지 않는다 | 다른 메뉴 API 는 권한 없는 그룹에서 403(FEATURES §10). `gui.py` 매핑 변경 없음 |

## 3. API — `GET /api/vision/dashboard?action=summary`

```text
{
  "todo":   {"incoming": …|null, "outgoing": …|null, "working": […]|null,
             "labeling": …|null, "review": …|null, "items": […]|null},
  "status": {"inspection": …|null, "register": …|null, "vision": […]|null}
}
```

권한이 없는 칸은 `null` — 화면은 그 칸을 감춘다. 지금 `register` 는 `status.register` 로 옮기고 모양을 바꾼다(이 화면만 쓴다).

### 3.1 todo (메뉴 W)

| 키 | 권한 | 값 | 원천 |
|---|---|---|---|
| `incoming` | `wm_dig_form_incoming_write` W | `waiting`(대기 수), `overdue`(입고일이 3일 넘게 지난 대기 수), `working`(작성 중 수), `mine`(그중 내가 작성자), `jobs`(대기 상위 10건 — 입고일 오래된 순: `receipt_no`·`receipt_date`·`wait_days`·`item_code`·`item_name`·`form_title`) | `receipts.jobs(user_id=me)` — 수입검사 작성 목록과 같은 수(좌측 배지는 매핑 안 된 수기 작성을 빼서 작성 중 수가 다를 수 있다) |
| `outgoing` | `wm_dig_form_outgoing_write` W | `working`, `mine` | `DigFormResult` 품질 `State='working'`, 작성자 `_creater_id` |
| `working` | 위 둘 중 하나라도 W | 작성 중 검사 상위 10건 — 내 것 먼저, 마지막 저장 최근 순: `kind_label`(수입/품질)·`form_title`·`work_order_number`·`writer_name`·`value_count`/`input_count`·`saved`·`is_mine`. W 가 있는 구분만 담는다 | `DigFormResult` `State='working'` |
| `labeling` | `wm_data_labeling` W | `queue`(UNLABELED·IN_PROGRESS·REWORK 이미지 수 — 라벨링 대기열과 같은 상태), `rework`(REWORK 수), `mine`(내가 잡은 작업: `LabelingTask` assignee=나, CLAIMED·IN_PROGRESS) | RLS — `tenant_atomic` |
| `review` | `wm_data_review` W | `waiting`(SUBMITTED 이미지 수) | RLS |
| `items` | 라벨링 W 또는 검수 W | 할 일이 있는 비전검사항목(치수 측정 제외, `visible_items`): `id`·`code`·`name`·`queue`·`rework`·`mine`(라벨링 W 일 때)·`review`(검수 W 일 때). 할 일 많은 순 | RLS. 항목별 `label_status` 집계 한 쿼리 + 내 작업 한 쿼리 |

### 3.2 status (메뉴 R)

| 키 | 권한 | 값 |
|---|---|---|
| `inspection` | `wm_dig_form_incoming_result` R 또는 `wm_dig_form_outgoing_result` R | 최근 7일(오늘 포함) `days`(날짜 7개)·`incoming`·`outgoing`(날짜별 완료 수 — R 이 없는 구분은 `null`)·`ng`(날짜별 부적합 항목 수, R 있는 구분만 센다). 완료 시각 = `State='done'` 작성건의 `_modified`(완료한 검사는 고칠 수 없다 — `dig_form.py` save 가 막는다). 부적합 = 항목결과 `ComboResult` 의 판정 코드 `meaning='N'`(`judge_code.OPTION_SQL`) |
| `register` | `wm_data_register` R | 최근 7일 `days`·`total`·`series`(경로별 `{label, counts[7]}`) — `ImageAsset.channel` |
| `vision` | `wm_vis_inspection` R | 최근 10건: `created_at`·`item_name`·`judgement`(정상/이상/판정 전/실패)·`client_name` |

## 4. 화면 (`vision/dashboard.html`)

```text
[대시보드]  설명: "처리할 일과 현황입니다."
── 내 할 일 ─────────────────────────────────────── (todo 칸이 모두 null 이면 섹션 감춤)
[검사 작업 · 수입검사]  [검사 작업 · 품질검사]  [비전 데이터 · 라벨링]  [비전 데이터 · 검수]
 대기 n                  작성 중 n                대기 n · 재작업 n        검수 대기 n
 3일 넘게 n · 작성 중 n  내 것 n                  내 작업 n
 (내 것 n)
[새로 작업할 수입검사 표]          [작성 중인 검사 표(내 것 강조)]
[라벨링·검수할 비전검사항목 표: 항목 | 대기 | 재작업 | 내 작업 | 검수 대기 | [라벨링][검수]]
── 현황 ─────────────────────────────────────────
[최근 7일 검사 완료·부적합 — 수입·품질 누적 막대 + 부적합 선]
[최근 7일 비전 데이터 등록 — 경로별 누적 막대, 제목에 합계]   [최근 비전 검사 이력 표]
```

- 수입·품질 카드와 표 행 → 그 검사작성 메뉴 탭. 등록 차트 카드(`#registerCard`) → 비전 데이터 등록 탭. 비전 검사 이력 → 비전 검사 이력 탭.
  지금 `openRegister` 를 `openMenu(menuCode, query)` 로 넓힌다. 좌측 메뉴에 없으면 열지 않는다
- 항목 표의 [라벨링]·[검수] → 좌측 메뉴의 그 항목 링크(`data-mid^="item<id>_"`)로 항목 탭을 연다.
  링크가 비전검사항목 홈(`item<id>_wm_data_item_detail`)이면 주소에 `screen=<메뉴코드>` 를 붙이고, 이미 열린 탭이면 그 프레임의 `page.showScreen(code)` 를 부른다.
  홈 권한이 없어 링크가 다른 하위 화면이면 그 링크를 그대로 연다
- `data/item.html` 은 처음 그릴 때 `?screen=` 이 권한 있는 내부 탭이면 그 탭을 연다(없거나 권한 없으면 홈)
- 0건 카드: `.is-empty`(흐린 글자, "할 일 없음"). 대기·3일 초과는 `--brand-warning-ink`, 이상은 `--brand-danger`(지금 토큰)
- 값은 `.text()` 로 넣는다(AGENTS [4]). 빈 표·차트는 한 줄 안내("최근 7일 기록이 없습니다." 등)
- 새 라이브러리 없음 — Chart.js 는 지금처럼 이 화면에서만

## 5. 바뀌는 파일

- `app/views/vision/dashboard.py` — 섹션별 함수(권한 확인 → 값). `receipts.jobs`·`judge_code.OPTION_SQL`·`ItemAccessService.visible_items` 재사용
- `app/templates/vision/dashboard.html` — 데모 제거, 위 배치
- `app/templates/data/item.html` — `?screen=` 으로 처음 열 내부 탭
- `tests/test_dashboard_api.py` — 섹션마다 권한 있음/없음·값
- `tests/e2e/test_data_register.py`(대시보드 등록 카드 테스트를 새 카드에 맞춤) + `tests/e2e/test_dashboard.py`(새 — 화면이 오류 없이 뜨고, 수입검사 카드가 탭을 열고, 항목 [라벨링]이 그 항목 탭의 라벨링 내부 탭을 연다)
- 문서: FEATURES §10, STATUS(1·7-1), DECISIONS(사용자 결정 2026-10-23 대시보드)

## 6. 검증

- 단위: `tests.test_dashboard_api`
- e2e: `tests/e2e/test_dashboard.py`, `tests/e2e/test_data_register.py -k 대시보드`, 비전검사항목 탭을 지나는 기존 e2e 파일(`?screen=` 변경)
- 정적: `verify_screen_js`·`verify_response_keys`·`verify_tokens`·`verify_korean_only`·`verify_modals`·`verify_buttons`
- 전체 실행은 하지 않는다(권한·공용 코드 변경 없음)

## 7. 하지 않는 것

D7 의 항목, 내 작업/전체 토글(D1 로 대신), 기간 선택, 자동 새로고침, 할 일 알림.
