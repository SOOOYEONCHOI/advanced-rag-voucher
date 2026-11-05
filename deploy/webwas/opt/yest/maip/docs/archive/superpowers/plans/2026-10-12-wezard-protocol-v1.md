# Wezard 통신 규약 v1 — 제조AI플랫폼 쪽 반영 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wezard 가 가져오기(W1)를 바로 시험할 수 있게 방향 ① API 를 규약 v1 로 맞춘다.

**Architecture:** `DatasetApiView` 가 인증(`X-API-Key` 하나)·`X-Request-ID`·오류 `request_id` 를 맡는다. 스냅샷 등록 때 고정 형식 Export 와 함께 `WEZARD` 형식 Export 를 하나 더 적재하고, API 는 `WEZARD` Export 만, 화면은 고정 형식만 본다. 키 관리 화면을 지우고 관리 명령으로 바꾼다.

**Tech Stack:** Django 5.2 / PostgreSQL 16

**Spec:** [docs/Wezard/integration-protocol.md](../../../Wezard/integration-protocol.md) §3·§4·§5·§7·§9-2·§10, Wezard 작업 요청서(`maip-work-request.md`, 2026-10-12 반영 완료 후 삭제) §9

## Global Constraints

- 사용자 문구 `~합니다` 체. 키 원문은 저장·로그·출력 금지(발급 시 1회).
- 테스트 `--settings=configurations.test_settings`. 마이그레이션은 `makemigrations` 로만.
- 비전검사 클라이언트 `/api/v1`(VisionClient·`X-Client-ID`) 동작은 바꾸지 않는다 — `tests.test_client_api` 가 그대로 통과해야 한다.
- 방향 ②(추론 게이트웨이 HTTP 구현)는 이 계획 밖이다(STATUS 4-1 다음 단계).

## Tasks

### Task 1: 인증 `X-API-Key` 하나 + 키 관리 명령, 화면 삭제
- `IntegrationClient.api_key_hash` 에 `unique=True`(마이그레이션 `0003`). `client_id` 는 연동 이름표로 남긴다.
- `DatasetApiView._authenticate`: `X-API-Key` 만 읽어 해시로 찾는다. 없으면 `AUTH_REQUIRED`, 없는 해시·비활성은 `AUTH_INVALID`. `X-Client-ID` 는 무시한다.
- 키 형식 `maip_` + `token_urlsafe(32)`.
- `manage.py integration_key issue <client_id> --name … [--output 파일]` · `reissue <client_id> [--output]` · `revoke <client_id>` · `list`. `--output` 이 있으면 키를 권한 600 파일에만 쓰고 화면에는 끝 4자리만.
- 지움: `app/views/system/integration_client.py`, `app/templates/system/integration_client.html`, gui·seed_initial·menus 등록, `verify_buttons`·e2e 화면 항목, `tests/test_integration_client.py`(명령 테스트로 대체).
- 테스트: 키 하나로 200, `X-Client-ID` 만 있으면 401 `AUTH_REQUIRED`, 검사 클라이언트 키 401, 명령 발급·재발급·폐기·목록.

### Task 2: `X-Request-ID` · 오류 `request_id` · `limit`/`offset`
- 형식 `^[A-Za-z0-9._-]{1,64}$` 이면 그 값, 아니면 `uuid4().hex`. 응답 헤더로 돌려주고 오류 JSON 최상위에 `request_id`, 감사 로그 `request_id` 에 넣는다.
- 목록: `limit`(1~200, 기본 50)·`offset`(≥0), 응답 `items`·`total`·`limit`·`offset`.

### Task 3: `wezard-dataset/v1` Exporter + 최소 조건 사전 검사
- `ExportJob.Format.WEZARD`. `WezardExporter`: 규약 §9-2 변환. `validate()` 가 Wezard §12.3 최소 조건을 Wezard §12.4 배정식(기본 비율 0.8/0.1/0.1)으로 미리 계산해 검사한다.
- `registry.get_exporter_class`: `WEZARD` 는 모든 유형에서 허용.
- `create_snapshot` 이 고정 형식과 `WEZARD` 를 함께 적재. 화면 `_latest_exports` 는 `WEZARD` 를 빼고, 상세에 "Wezard 전송용 zip" 상태·실패 사유 한 줄. [다시 만들기]는 고정 형식 실패 **또는** Wezard zip 없음·실패일 때 보이고, 해당하는 것만 다시 적재한다(예전 스냅샷 채우기 겸용).

### Task 4: API 가 `WEZARD` Export 를 본다
- 목록·정보·다운로드의 기준 Export = 스냅샷의 최근 `WEZARD` ExportJob. 파일명 `snapshot-<id>-<버전>-wezard.zip`.

### Task 5: 문서
- `maip-api.md` 를 규약 v1 로 다시 쓴다(실측 응답). 규약 §12 적용 현황, FEATURES·DATA_MODEL·STATUS·ARCHITECTURE·AGENTS 를 맞춘다.

### Task 6: 개발 DB·실측·검증 (DB 변경은 실행 전 사용자 확인)
- `migrate`(0003), `seed_initial`(화면 메뉴 행 제거), Wezard 용 `maip_` 키 발급 → `CONNECTION.local.md`, FAN-PANEL 스냅샷의 `WEZARD` zip 생성·`curl` 실측(목록 → 정보 → 이어받기 → `sha256sum` → `dataset.json` 확인).
- 전체 단위·e2e·검증 스크립트 → main 병합 → Wezard 세션에 요청서 전달.
