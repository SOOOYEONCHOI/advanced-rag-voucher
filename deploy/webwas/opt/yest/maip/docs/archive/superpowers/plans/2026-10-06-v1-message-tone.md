# 비전검사 API(`/api/v1`) 메시지 어조 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/api/v1` 오류 응답의 `message` 를 `~합니다` 체로 바꾸고, 그 문구를 인용하는 계약 문서를 같은 커밋 묶음에서 고친다.

**Architecture:** 문자열만 바꾼다. 응답 모양·`code`·HTTP 상태는 그대로다. 클라이언트는 `code` 로 분기하므로 동작이 바뀌지 않는다.

**선행 조건:** **R10~R16 계획(`2026-10-06-client-api-r10-r16.md`)이 `main` 에 병합된 뒤 시작한다.** 그 계획이 `api_v1.py` 의 metadata 검증을 `parse_metadata` 로 옮기고 계약 문서 §5·§6·§13·§15·§16·§17 을 고친다 — 먼저 하면 둘이 같은 줄을 다툰다. (2026-10-06 기준 R10~R16 은 착수 전이다.)

## Global Constraints

- **`SERVER_API_CONTRACT.md` 를 함께 고친다**(AGENTS.md [2]). 그 문서가 계약 정본이다
- `code`·상태·응답 키는 바꾸지 않는다
- 오류 메시지에 내부 진단 정보(예외 원문·경로)를 넣지 않는다 — 문구를 다듬다 끼워 넣지 않는다
- 로그·주석·docstring 은 대상이 아니다
- 어조 검사 스크립트는 만들지 않는다(사용자 결정, 2026-10-06)

## 범위 (2026-10-06 실측, R10~R16 뒤 다시 센다)

`app/views/api_v1.py` 19건 · `domain/services/vision/inspection.py` 4건(형식 문자열 포함).
R10~R16 이 metadata 메시지를 옮기고 새 메시지를 더하므로 **착수 시점에 다시 뽑는다:**

```bash
grep -nE "['\"][^'\"]*[가-힣][^'\"]*다[.:]?[^'\"]*['\"]" app/views/api_v1.py domain/services/vision/*.py \
  | grep -vE '"""|logger\.|^\S+:\s*#'
```

바꾸는 규칙(예):

| 지금 | 바꾼 뒤 |
|---|---|
| `인증에 실패했다.` | `인증에 실패했습니다.` |
| `metadata 가 없다.` | `metadata 가 없습니다.` |
| `요청 본문 길이(Content-Length)가 필요하다.` | `요청 본문 길이(Content-Length)가 필요합니다.` |
| `없는 경로다.` | `없는 경로입니다.` |
| `검사항목을 찾을 수 없다: {id}` | `검사항목을 찾을 수 없습니다: {id}` |
| `다른 Client 가 이미 사용한 request_id 다.` | `다른 클라이언트가 이미 사용한 request_id 입니다.` |

---

### Task 1: 메시지

- [ ] 위 명령으로 목록을 뽑아 이 문서 아래에 붙인다(건수·위치)
- [ ] `tests/test_client_api.py` 에서 `message` 를 단언하는 곳을 찾는다(`grep -n "message" tests/test_client_api.py`). 있으면 기대값을 먼저 새 문구로 바꿔 **RED** 를 확인한다
- [ ] 문자열을 바꾼다 → `python manage.py test tests --settings=configurations.test_settings`
- [ ] 커밋 `feat: 비전검사 API 오류 메시지를 ~합니다 체로 맞춘다`

### Task 2: 계약 문서

- [ ] `docs/client/SERVER_API_CONTRACT.md` 에서 옛 문구를 모두 찾는다(Task 1 목록의 각 문구로 grep. 2026-10-06 기준 `인증에 실패했다` 2 · `이미지가 없다` 1 · `Overlay 가 없다` 1 · `없는 경로다` 1 · `검사항목을 찾을 수 없다` 1 …)
- [ ] 예시 JSON 의 `message` 를 새 문구로. **"`message` 는 사람이 읽는 값이고 분기는 `code` 로 한다"** 는 문장이 계약에 있는지 확인하고, 없으면 §(오류 봉투)에 한 줄 더한다
- [ ] 변경 이력(§17)에 한 줄: 날짜 · "오류 `message` 문구를 경어체로. `code`·상태 변경 없음"
- [ ] 커밋 `docs: 계약 문서의 오류 메시지 예시를 새 문구로 맞춘다`

### Task 3: 마무리

- [ ] AGENTS.md [5] 의 "예외는 비전검사 API 메시지로 … 아직 `~다` 체다" 문장을 지운다
- [ ] 메모리 `user-facing-polite-tone` 의 `/api/v1` 예외 문장도 지운다
- [ ] 비전검사 클라이언트 담당에게 알릴 것: 계약 §17 항목(동작 변화 없음, 화면에 `message` 를 그대로 보이면 문구가 바뀜)
