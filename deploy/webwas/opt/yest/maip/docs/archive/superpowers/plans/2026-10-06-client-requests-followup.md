# 클라이언트 요청서(2차) 후속 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 요청서 2차분(R10~R18)과 "참고 — Client 0.1.6" 에서 서버에 남은 일을 닫는다. 특히 0.1.6 이 **봉투 없는 4xx 를 재시도하지 않고 "서버 응답 오류"로 멈추므로**, `/api/v1` 의 모든 오류를 봉투로 낸다는 계약 §2-1 을 실제로 지킨다.

**Architecture:** 코드 변경은 `app/views/api_v1.py`·`configurations/urls.py` 두 파일이다. 나머지는 실측과 계약 문서 갱신, 배포물 반입 절차다.

**Spec:** `docs/client/SERVER_REQUESTS.md`(2026-10-06 2차), `docs/client/SERVER_API_CONTRACT.md`

## Global Constraints

- `/api/v1` 응답을 바꾸면 `SERVER_API_CONTRACT.md` 를 함께 고친다(§15 처리 결과·§17 변경 이력). 바꾼 뒤 클라이언트 담당에게 다시 전달한다
- 라우트는 `urls.py` 의 `api/v1/<path:rest>` catch-all **앞**에 둔다
- 테스트는 `--settings=configurations.test_settings`. 실서버 실측은 `E2E-` 임시 자격증명을 만들고 끝나면 지운다
- 사용자 문구는 `~합니다` 체

## 진행 (2026-10-06)

- Task 1·2·4 **완료** — 405·루트 404 봉투(커밋 "fix: /api/v1 의 405 와 루트 404 도…"), 413·409 실측, 계약 §2-1·§11-1·§15·§17(4차)
- Task 3 **완료(2026-10-07)** — 0.1.6 반입. 운영 서버 `DISTRIBUTION_ROOT` 반입은 DEPLOYMENT §8-1 절차로 운영 서버를 세울 때 한다. Task 5 — 검사항목 3 Overlay 는 검사항목 3 을 지워(2026-10-12) 없어졌고, §16 질문 1~4·Heatmap·`components.gpu` 는 STATUS §3-1·§3-4 가 추적한다. 2026-10-13 `docs/archive/superpowers/plans/` 로 옮겼다

---

## 요청서 2차 확인 결과 (2026-10-06)

| # | 요청 | 상태 | 회신 위치 |
|---|---|---|---|
| R10 | 0.1.4 zip 내리기 | **완료**(클라이언트 확인). 0.1.5 게시, `SHA256SUMS.txt` 커밋 | 계약 §15 2차·§10-1 |
| R11 | 판정 필드 형식 유지 | **수락**, bbox `{x1,y1,x2,y2}` 로 경계 고정 | §6-3 |
| R12 | `RECEIVED` 의미 | **A안** — 추론은 POST 안에서, 서버 타임아웃 20초 | §6-5 |
| R13 | §16 질문 답 | 5·6·7 종결. **1~4 는 운영 서버를 세울 때** | §16 |
| R14 | Overlay 실측 데이터 | **완료**(클라이언트 확인) | §5·§9 |
| R15 | 새 자격증명 | 확인 | §3-2 |
| R16 | 길이 초과 500 | **수정 완료** — 422 `METADATA_INVALID`. R16-2 답(기록 없음, 파일 1쌍 정리) | §6-1·§6-6 |
| R17 | 실측 데이터 정리 | **완료** — 기록 5건·검사항목 5 Overlay 삭제. **검사항목 3 Overlay 는 클라이언트 통보 대기** | §9·§15 |
| R18 | 계약 보완 | **완료** — §10-1 0.1.5, 숨긴 Overlay 표시 | §5·§9·§10-1 |
| 참고 | Client 0.1.6 동작 변화 | **서버 조치 필요** — 아래 Task 1 | — |
| 실측 공백 | 413·409 를 클라이언트가 확인하지 못함 | 서버가 실측해 회신 — Task 2 | — |

## 실측으로 찾은 것 (2026-10-06, 실서버)

| 요청 | 응답 | 계약 |
|---|---|---|
| `GET /api/v1/inspections` · `POST /api/v1/catalog` · `DELETE /api/v1/overlays/3` · `PUT /api/v1/health` · `POST /api/v1/client-packages` · `OPTIONS` | **405, 본문 없음, `text/html`** | ✗ §2-1 "모든 오류가 봉투" |
| `GET /api/v1` · `GET /api/v1/` | **404 DEBUG HTML**(URL 패턴 목록이 보인다) | ✗ §2-1 |
| `GET /api/v1/overlays/abc` · `by-request/`(빈 값) | 404 `NOT_FOUND` 봉투 | ✓ |
| `Content-Length` 40 MiB 선언 | 413 `IMAGE_TOO_LARGE` 봉투 | ✓ (§2-3) |

---

## 판단 (제안)

| # | 판단 | 제안 | 이유 |
|---|---|---|---|
| P-1 | 허용하지 않는 메서드의 응답 | **405 `METHOD_NOT_ALLOWED`, `retryable: false`, `Allow` 헤더 유지** | 계약 §11-1 공통 코드에 한 줄 추가. 같은 요청은 다시 보내도 같다 |
| P-2 | `/api/v1`·`/api/v1/` 루트 | **404 `NOT_FOUND` 봉투**(다른 미지 경로와 같다) | 새 엔드포인트를 만들지 않는다 |
| P-3 | 0.1.6 을 올릴 때 0.1.5 | **목록에서 내린다**(zip 은 저장소 밖에 보관). `client-packages` 에는 최신 하나만 둔다 | 0.1.4 때와 같은 방식. LGPL 3년 보관 대상은 `licenses/sources` 쪽이다 |

---

### Task 1: `/api/v1` 의 모든 오류를 봉투로 (P-1·P-2)

**Files:** Modify `app/views/api_v1.py`(`ClientApiView`·`V1NotFoundView`), `configurations/urls.py` · Test `tests/test_client_api.py` `EnvelopeTest`

- [x] **RED** — `EnvelopeTest` 에 추가

```python
    def test_허용하지_않는_메서드도_봉투다(self):
        for method, path in (('get', '/api/v1/inspections'), ('delete', '/api/v1/overlays/1'),
                             ('options', '/api/v1/catalog')):
            response = getattr(self.http, method)(path, **self._headers())
            self.assertEqual(response.status_code, 405, (method, path))
            self.assertEqual(response.json()['error']['code'], 'METHOD_NOT_ALLOWED', (method, path))
            self.assertIs(response.json()['error']['retryable'], False)
            self.assertIn('Allow', response)

    def test_v1_루트도_404_봉투다(self):
        for path in ('/api/v1', '/api/v1/'):
            response = self.http.get(path)
            self.assertEqual(response.status_code, 404, path)
            self.assertEqual(response.json()['error']['code'], 'NOT_FOUND', path)
```

`POST /api/v1/catalog` 는 본문이 있어 411·413 선검사와 인증을 먼저 지난다 — 인증된 요청으로 405 봉투인지도 한 줄 본다.

- [x] **GREEN** — `ClientApiView` 에 `http_method_not_allowed` 를 덮어 `error('METHOD_NOT_ALLOWED', '허용하지 않는 메서드입니다.', 405)` 에 `Allow` 헤더를 붙인다(`self._allowed_methods()`). `urls.py` 에 `path('api/v1', V1NotFoundView.as_view())`·`path('api/v1/', ...)` 를 catch-all 옆에 둔다
- [x] 전체 단위 테스트 → 실서버 재실측(위 표의 ✗ 행이 모두 봉투)
- [x] 커밋 `fix: /api/v1 의 405 와 루트 404 도 오류 봉투로 답한다`

### Task 2: 클라이언트가 확인하지 못한 413·409 를 서버가 실측

**Files:** 없음(실측) → Task 4 에서 계약에 기록

- [x] 413 — 이미 확인(위 표). 실제로 33 MiB 를 넘는 본문을 보내 같은지도 한 번 본다(인증보다 먼저인지)
- [x] 409 — 임시 자격증명 `E2E-A`·`E2E-B` 를 만들고, A 가 쓴 `request_id` 로 B 가 보낸다 → 409 `REQUEST_ID_CONFLICT` 봉투. 만든 검사·이미지·파일·자격증명은 지운다

### Task 3: Client 0.1.6 반입 절차 (0.1.6 이 도착하면, P-3)

- [x] 받은 zip 과 해시를 대조한다(`sha256sum`) — 2026-10-07 `sha256sum -c` 성공
- [x] `distribution/client/` 에 0.1.6 zip 을 두고 0.1.5 zip 은 `~/archive/vision-client/` 로 옮긴다 — **0.1.5 zip 은 보관 폴더에도 홈 어디에도 없었다**(0.1.4 만 있다). 사용자 결정(2026-10-07)으로 찾지 않고 0.1.6 이 대신한다
- [x] `SHA256SUMS.txt` 를 0.1.6 한 줄로 바꿔 커밋한다
- [x] `GET /api/v1/client-packages` 로 확인 → 계약 §10-1 예시를 그 응답으로 바꾼다(R18-1 "0.1.6 을 올리면 다시 맞춘다") — 다음 계약 전달에 포함
- [ ] 운영 서버가 있다면 `DISTRIBUTION_ROOT` 에도 같은 절차(docs/DEPLOYMENT.md 배포물 반입)

### Task 4: 계약 문서 회신

- [x] §2-1 — "405 도 봉투다" 한 줄. §11-1 공통 표에 `405 METHOD_NOT_ALLOWED false`
- [x] §15 2차 회신 아래 "참고 — Client 0.1.6" 수령: 봉투 유지 약속, Task 1 로 405·루트 404 를 봉투로 바꿨다는 것, 413·409 실측 결과(Task 2)
- [x] §17 변경 이력
- [x] 클라이언트 담당에게 다시 전달(사용자)

### Task 5: 대기 항목 (조건이 오면)

| 항목 | 조건 | 할 일 |
|---|---|---|
| 검사항목 3 Overlay | 클라이언트가 현장 PC 시험 완료를 알림(R17-1) | Overlay 관리 [수정]에서 "표시" 해제 → §9 "지금 등록된 Overlay" 문장 갱신(DEC-C14 — 클라이언트에는 없는 것과 같다. 화면에 [삭제]는 없다, 2026-10-07 사용자 결정) |
| §16 질문 1~4 | 운영 서버를 세우는 시점 | docs/STATUS.md §3-1 |
| R11·R12 이행 | GPU 추론을 연결할 때 | docs/STATUS.md §3-4(20초 타임아웃·`components.gpu`·`heatmap_url`) |

## 범위 밖

- 요청서(`SERVER_REQUESTS.md`)의 클라이언트 원문 수정 — 클라이언트 소유다. 서버는 맨 위 "서버 처리 현황"만 갱신한다
