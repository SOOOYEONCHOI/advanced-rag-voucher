# 챗봇 API 검증 및 프론트엔드 전달서 (2026-10-21)

대상: `07_챗봇_목업_연동판_20261019.html`, `07_프런트_연동_명세_챗봇.md`.
관련 ID: R4-3, F-4-03·F-4-04, SC-01·SC-03, UI-02~05, ANS-01~04, VOC-01~03.

## 1. 검증 범위와 결론

로컬 `rag-backend-dev`의 실제 HTTP API와 개발 DB·Qdrant·사내 자체 서빙 모델을 사용했다. 운영 서버에는 접속하지 않았다. 임시 사용자를 생성하여 기존 사용자 대화와 모델 설정은 변경하지 않았다. 테스트 후 임시 사용자와 질의 로그·이력을 정리했다. 인증 토큰은 개발 서버의 기존 서명 함수를 사용해 메모리에서 발급했으며 로그인 API 자체는 이번 검증 범위에 포함하지 않았다.

사진 답변 SSE → 인용 → 문서별 사진 목록 → 이미지 파일 → 이력 복원 경로가 동작했다. 모델 설정 조회/저장, 일반 JSON 질의, 좋아요/싫어요/취소, 새 대화 초기화도 실제 호출했다. 사진 개수와 인용은 LLM 실행마다 달라질 수 있다.

**해결 필요: 권한 회수 뒤에도 `GET /api/query/history`가 기존 대화를 반환한다.** 이미지 목록과 이미지 파일은 403으로 차단되지만, 저장된 답변·인용·사진 메타데이터는 이력에서 조회된다. `query.py:get_chat_history`가 현재 접근 권한으로 이력을 재검증하지 않는다. 기능 구현 완료나 권한 보안 검증 전체 통과로 판단하면 안 된다. 이번 요청은 검증·문서화이므로 제품 코드는 수정하지 않았다.

자동 테스트 결과:

- 실제 HTTP 및 데이터 연결 검사: **52건 중 51건 통과 / 1건 실패**. 실패는 권한 회수 후 이력 비노출 검사다. 최종 스트림은 8.26초, 사진 2장·인용 2건이었고 각 인용에서 표시 가능한 연결 이미지 1장·4장을 확인했다.
- 백엔드 사진·리소스·인용: **40 passed / 4 skipped**. 4건은 기존 코드에 명시된 구 설계 테스트 제외이며 통과로 계산하지 않았다.
- 프론트 이미지 렌더·blob 캐시: **6 passed / 0 failed**.
- 최종 HTTP 검사별 상태·개수·소요 시간: 함께 제공하는 `chat-api-verification-20261021.json`의 `results` 참조. 문자열을 치환한 실제 응답 형태는 `response_shapes` 참조.

별도 JSON의 배열은 구조 확인을 위해 첫 항목만 남겼다(스트림 이벤트 목록 제외). 따라서 history에는 첫 사용자 메시지만 보이며 실제 답변 객체 예시는 이 문서 4-9절을 참조한다. `total`과 축약 배열 길이가 다를 수 있다. 응답별 문자열 치환값은 실제 조회 키로 사용할 수 없다.

다음은 미검증 또는 제한 사항이다.

- 실제 브라우저 화면의 패널 열기, 키보드 이동, 새 탭, 레이아웃과 CORS 동작은 이번 API 검증 범위 밖이다. 프론트 자동 테스트는 별도로 실행했다.
- 실제 음성 인식 성공, 413/502/503 응답은 이번에 호출하지 않았다. 음성 API는 401/400/415만 실제 확인했고 성공 JSON은 코드 계약으로 기재했다.
- PDF 매뉴얼의 표시 페이지 매핑, 과거 버전·삭제 이미지 전체 조합, 다른 사용자의 실제 로그 피드백 차단, 만료 토큰은 별도 E2E 미검증이다. 없는 로그는 404를 확인했다.
- 이미지 권한 없음은 현 코드에서 **403**이다. 향후 404 변경 예정과 구분해야 한다.
- `/api/health`의 DB·벡터 상태 문자열은 코드에서 고정 반환한다. 이 API 200만으로 의존 서비스 정상 여부까지 보장하지 않는다.

## 2. 화면 영역과 API 연결

| 목업 영역 | API / 데이터 | 실제 확인 |
|---|---|---|
| ① 대화 주제 | GET `/api/query/collections` | 인증/익명 조회 |
| ② 모델·상태·새 대화 | GET `/api/models`, `/api/chat/models`, `/api/health`; GET/POST `/api/user/llm-settings`; POST `/api/query/reset` | 정상 호출 |
| ③ 이전 대화 | GET `/api/query/history` | 사진 복원·초기화 정상, 권한 회수 후 노출 결함 |
| ④ 텍스트 질문 | POST `/api/query/stream` | SSE 완료, 잘못된 요청 422, 권한 없음 403 |
| ④ 음성 질문 | POST `/api/voice/transcriptions` | 401/400/415 확인, 성공 인식 미검증 |
| ⑤ 본문·사진 배지 / ⑥ 관련 이미지 | SSE `token`, `citations`, `images` | 사진·인용 연결 확인 |
| ⑦ 참고 문서·피드백 | SSE `citations`, `meta`; PATCH `/api/query/{log_id}/feedback` | like/dislike/null 및 오류 확인 |
| ⑧ 출처 패널 | SSE `citations`; GET `/api/documents/{document_id}/spreadsheet-resources` | 연결 ID·표시 가능 필터 확인 |
| ⑨ 이미지 뷰어 | GET `/api/spreadsheet-resources/{resource_id}` | 이미지 바이너리 다운로드·401/403/404 확인 |
| ⑩ 답변 듣기 | 예정 POST `/api/voice/speech` | 현 라우터에 구현 없음. 응답 JSON 정의 불가 |

## 3. 요청 공통 규칙

- 기본 경로 `/api`. 인증 API에는 `Authorization: Bearer <token>`을 보낸다.
- `collection_name` 요청 값은 화면 표시명 대신 **qdrant_name**이다. URL 경로/쿼리는 인코딩한다.
- `/api/query/*`는 토큰이 없으면 익명으로 처리한다. 다른 모든 API가 무조건 401인 것은 아니다. `/api/models`, `/api/chat/models`, `/api/health`는 무인증 200을 실제 확인했다.
- 사진·문서 리소스·사용자 모델 설정·음성 API는 인증이 필요하다.
- 아래 JSON은 프론트 전달용 구조 예시다. 원본 문서 내용·파일명·내부 주소·토큰은 포함하지 않았으며, 예시 ID와 본문은 가상 값이다. 선택/nullable 필드는 데이터에 따라 생략되거나 null이다. 실제 익명화 응답 형태는 별도 JSON 파일을 기준으로 본다.

## 4. API별 Response JSON

### 4-1. GET /api/query/collections — ①

```json
{
  "collections": [{"collection_name": "예시 작업 주제", "qdrant_name": "example_topic"}],
  "user_id": "example_user"
}
```

접근 가능한 주제가 없으면 `collections: []`. 익명일 때 `user_id: "anonymous"`. 관리자라도 질의 주제 목록은 현재 부서 기반 접근 목록의 영향을 받으므로 이미지 API의 관리자 허용과 동일하다고 가정하면 안 된다.

### 4-2. GET /api/models — ②

```json
{
  "models": [{
    "model_id": "local", "model_name": "예시 로컬 모델", "provider": "local",
    "requires_api_key": false, "is_enabled": true, "sort_order": 0
  }]
}
```

목록에 외부 제공자 모델이 있더라도 이번 연동은 `provider: "local"`만 사용한다.

### 4-3. GET /api/chat/models — ②

```json
{"model": "<서버 LLM 모델명>", "embedding_model": "<서버 임베딩 모델명>"}
```

서버 설정값을 반환한다. 실제 모델 서버에 해당 모델이 로드됐는지를 이 API가 조회하지는 않는다.

### 4-4. GET /api/health — ②

```json
{"status": "healthy", "database": "connected", "vector_store": "connected"}
```

고정 상태 문자열이라는 제한은 1절 참조.

### 4-5. GET /api/user/llm-settings?collection_name=example_topic — ②

```json
{"setting": {"collection_name": "example_topic", "model_id": "local", "has_api_key": false}}
```

미저장 또는 미등록 주제일 때:

```json
{"setting": null}
```

### 4-6. POST /api/user/llm-settings — ②

요청: `{"collection_name":"example_topic","model_id":"local"}`

```json
{"collection_name": "example_topic", "model_id": "local", "has_api_key": false}
```

GET과 다르게 `setting` 래퍼가 없다. API 키 원문은 응답하지 않는다.

### 4-7. POST /api/query/stream — ④~⑨

요청:

```json
{"query": "작업 방법을 사진과 함께 알려줘", "collection_name": "example_topic", "llm_provider": "local"}
```

HTTP 200의 Content-Type은 `text/event-stream`. 단일 JSON 배열 응답이 아니다. 아래와 같이 `data:` 한 줄과 빈 줄로 이벤트를 구분하며, 토큰은 여러 번 올 수 있다.

```text
data: {"type":"progress","stage":"searching"}

data: {"type":"progress","stage":"generating"}

data: {"type":"token","content":"예시 작업을 진행합니다[1][IMG:abc123]."}

data: {"type":"citations","data":[{"citation_id":1,"document_id":"example-doc","resource_ids":["example-doc-v1-i0001"]}]}

data: {"type":"images","data":[{"ref":"abc123","resource_id":"example-doc-v1-i0001","document_id":"example-doc","context_no":1,"cited":true}]}

data: {"type":"meta","log_id":123}

data: {"type":"done"}

```

위 citations/images 항목은 이벤트 흐름을 보여주기 위한 축약이며 전체 필드는 5절 참조. `images`가 없으면 빈 배열로 처리한다. `meta.log_id`는 피드백 키다. `done` 전까지 네트워크 청크 경계가 이벤트 경계와 같다고 가정하면 안 된다.

스트림 내부 오류(코드 계약, 이번 정상 실행에서 미발생):

```json
{"type": "error", "message": "<사용자 안내 문구>"}
```

HTTP 403은 SSE가 아닌 `{"detail":"..."}` JSON이다. HTTP 상태와 Content-Type을 먼저 확인한다.

### 4-8. POST /api/query/ — 비스트리밍 보조 API

요청은 스트림과 동일하다.

```json
{
  "query": "예시 질문", "answer": "예시 답변[1][IMG:abc123].",
  "chunks": [{
    "chunk_id": "example-chunk", "document_id": "example-doc", "document_name": "예시.xlsx",
    "text": "예시 검색 청크", "score": 0.8, "section_name": null, "page_number": null
  }],
  "citations": [{
    "citation_id": "1", "document_id": "example-doc", "original_filename": "예시.xlsx",
    "chunk_text": "예시 근거", "chunk_id": null, "section_name": "예시 단계", "header_path": [],
    "page_number": null, "response_segment": null, "title": "예시.xlsx", "document_type": "spreadsheet",
    "score": 0.8, "referenced_in_answer": true, "collection_id": null,
    "sheet_name": "예시 시트", "source_range": null, "display_markdown": "예시 근거",
    "resource_ids": ["example-doc-v1-i0001"]
  }],
  "processing_time_ms": 10000.0, "log_id": 123,
  "images": [{
    "ref": "abc123", "resource_id": "example-doc-v1-i0001", "document_id": "example-doc",
    "title": "예시 작업 사진", "role": "step_photo", "sheet_name": "예시 시트",
    "from_cell": "C10", "to_cell": "C12", "step_no": 1, "step_title": "예시 단계",
    "surrounding_text": "예시 설명", "original_filename": "예시.xlsx", "context_no": 1, "cited": true
  }]
}
```

**스트림과 차이**: `citation_id`는 문자열이다. 현재 변환 코드가 `highlight_text` 및 매뉴얼 표시 매핑 필드를 전달하지 않으며, `chunk_id`도 채우지 않아 null이 된다. 스트리밍과 동일한 출처 강조/매핑 필드를 보장하지 않는다. 이번 실제 응답에서 `highlight_text` 누락과 `chunk_id: null`을 확인했다.

### 4-9. GET /api/query/history?collection_name=example_topic — ③

```json
{
  "history": [
    {"role": "user", "content": "예시 질문"},
    {
      "role": "assistant", "content": "예시 답변[1][IMG:abc123].",
      "citations": [{"citation_id": 1, "document_id": "example-doc", "resource_ids": ["example-doc-v1-i0001"]}],
      "images": [{"ref": "abc123", "resource_id": "example-doc-v1-i0001", "document_id": "example-doc", "context_no": 1, "cited": true}],
      "log_id": 123, "feedback": null
    }
  ],
  "collection_name": "example_topic"
}
```

citations/images는 5절 전체 객체의 축약 예시다. 예전 이력에는 필드가 없을 수 있으므로 `citations ?? []`, `images ?? []`로 처리한다. `feedback`은 `like`/`dislike`/null이다. 대응 로그가 없는 이력에서는 `log_id`/`feedback`이 없을 수 있다.

권한 회수 후에도 같은 응답이 반환될 수 있는 결함은 1절 참조. 프론트에서 이미지만 숨기는 것으로 보안 문제가 해결되지는 않는다.

### 4-10. POST /api/query/reset — ②

요청: `{"collection_name":"example_topic"}`

```json
{"success": true, "collection_name": "example_topic"}
```

검증에서는 새로 만든 대화의 초기화 뒤 `history: []`를 확인했다. 기존 세션이 없을 때의 success 값은 별도 검증하지 않았다.

### 4-11. PATCH /api/query/{log_id}/feedback — ⑦

요청: `{"feedback":"like"}`, `{"feedback":"dislike"}`, `{"feedback":null}`.

```json
{"log_id": 123, "feedback": "like"}
```

취소 시 `feedback: null`. 없는 로그는 404, 허용되지 않는 feedback 문자열은 422를 확인했다.

### 4-12. GET /api/documents/{document_id}/spreadsheet-resources — ⑧

```json
{
  "document_id": "example-doc", "total": 1,
  "resources": [{
    "resource_id": "example-doc-v1-i0001", "document_id": "example-doc", "resource_type": "image",
    "content_hash": "<콘텐츠 해시>", "mime_type": "image/png", "file_size": 10000,
    "sheet_id": null, "sheet_name": "예시 시트", "from_cell": "C10", "to_cell": "C12",
    "linked_block_id": null, "linked_record_ids": [], "surrounding_range": "A8:H14",
    "surrounding_text": "예시 설명", "status": "committed", "created_at": "2026-10-21T09:00:00+09:00",
    "download_url": "/api/spreadsheet-resources/example-doc-v1-i0001", "title": "예시 작업 사진",
    "role": "step_photo", "step_no": 1, "step_title": "예시 단계", "version_no": 1,
    "in_print_area": true, "review_status": "auto", "displayable": true
  }]
}
```

`total`은 필터 전 문서 전체 목록 수이며 “연결된 이미지 N장”이 아니다. 실제 목록에 `form_header`/`displayable:false` 항목도 있었다. 인용의 `document_id`별로 목록을 받아 **resource_ids에 포함 AND displayable===true**로 고른 결과의 길이를 N으로 쓴다. 다른 문서의 목록에서 ID를 찾으면 안 된다. 이전 버전이 섞일 수 있으므로 버전 최댓값만으로 거르지 말고 인용의 resource_ids를 사용한다.

### 4-13. GET /api/spreadsheet-resources/{resource_id} — ⑤·⑥·⑧·⑨

**성공 응답은 JSON이 아닌 이미지 바이너리**다. 실제 다운로드에서 HTTP 200, `Content-Type: image/png`와 비어 있지 않은 파일을 확인했다. 이미지 원본을 전달 문서에 저장하지 않았다.

```text
HTTP/1.1 200 OK
Content-Type: image/png
Content-Disposition: attachment; filename="...png"

<image bytes>
```

인증 헤더를 붙여 blob으로 받아 `URL.createObjectURL`로 사용한다. resource_id별 캐시를 ⑤·⑥·⑧·⑨에서 공유하고 해제할 때 revoke한다. `size=thumb|preview` 옵션은 없다. 직접 img src URL로 인증 헤더를 전달할 수 없으므로 blob 경로를 사용한다.

오류 응답은 JSON이다:

```json
{"detail": "Resource not found"}
```

401 인증 없음, 403 `Resource access denied`, 404 리소스 없음. 예시 헤더의 정확한 파일명 인코딩은 파일명에 따라 달라진다.

### 4-14. POST /api/voice/transcriptions — ④

multipart `audio` 필수, `language` 선택. **아래 성공 응답은 코드 계약이며 실제 STT 성공 호출 결과가 아니다.**

```json
{"text": "예시 인식 문장", "language": "ko"}
```

language를 보내지 않으면 null이다. 이 필드는 인식기가 감지한 언어가 아니라 요청한 language를 그대로 반환한다. `raw_text`/`corrections`는 없다. 실제 확인: 무인증 401, 빈 audio/wav 400, text/plain 415. 413/502/503은 코드상 존재하며 미호출이다.

## 5. 스트림·이력의 공용 객체

### Citation

```json
{
  "citation_id": 1, "chunk_id": "example-chunk", "document_id": "example-doc",
  "original_filename": "예시.xlsx", "section_name": "예시 단계", "header_path": [],
  "page_number": null, "chunk_text": "예시 근거 미리보기", "score": 0.8,
  "referenced_in_answer": true, "title": "예시.xlsx", "document_type": "spreadsheet",
  "sheet_name": "예시 시트", "source_range": null, "display_markdown": "예시 근거 마크다운",
  "resource_ids": ["example-doc-v1-i0001"], "highlight_text": "예시 강조 문장"
}
```

`source_range`는 null일 수 있다. 매뉴얼의 경우 조건에 따라 `manual_display_mapped: true`, `display_filename`, `display_page_number`가 추가된다(이번 실제 엑셀 검증에서는 미관측). 비스트리밍과 비교할 때 `String(citation_id)`로 정규화한다.

### Image

```json
{
  "ref": "abc123", "resource_id": "example-doc-v1-i0001", "document_id": "example-doc",
  "title": "예시 작업 사진", "role": "step_photo", "sheet_name": "예시 시트",
  "from_cell": "C10", "to_cell": "C12", "step_no": 1, "step_title": "예시 단계",
  "surrounding_text": "예시 주변 설명", "original_filename": "예시.xlsx", "context_no": 1, "cited": true
}
```

사진 번호는 배열 순서+1이며 resource_id나 context_no가 아니다. `context_no`는 인용 번호다. [문서 위치]는 document_id와 citation_id를 함께 비교한다. `cited:false`는 자동 첨부 이미지이므로 본문 태그가 없어도 관련 이미지 카드에 표시한다. 답변당 최대 4장이다.

## 6. 오류 공통 JSON

일반 HTTP 오류:

```json
{"detail": "<사용자 안내 문구>"}
```

요청 검증 오류 422(누락된 query를 보냈을 때의 형태):

```json
{"detail": [{"type": "missing", "loc": ["body", "query"], "msg": "Field required", "input": {}}]}
```

`detail`은 문자열 또는 배열이다. 422를 문자열 detail과 같은 방식으로 직접 출력하지 말고 사용자 메시지로 변환한다.

## 7. 재실행과 변경 파일

```text
wsl docker exec rag-backend-dev python scripts/verify_chat_mockup_api.py
wsl docker exec rag-backend-dev python -m pytest -q tests/test_answer_images.py tests/test_spreadsheet_resource_service.py tests/test_citation_mapping.py --basetemp=/tmp/chat-api-check-20261021
cd adrag_frontend
node --test tests/answerImages.test.mjs
```

HTTP 검증 스크립트는 `_dev`로 끝나는 DB만 허용하고 임시 사용자 데이터를 생성·삭제한다. 기존 부서의 접근 주제가 설정되고 사진이 적재된 개발 환경이 필요하다. 질문 과정에서 사내 자체 서빙 모델을 호출한다. 테스트 실패 결과도 JSON에 남기므로 프로세스 종료 코드만으로 통과 여부를 판단하지 않는다.

변경: 검증 스크립트, 이 전달서, 익명화 결과 JSON만 추가. 제품 코드·목업·DB 스키마 변경 없음, 마이그레이션 없음. 되돌리기는 추가한 검증 산출물을 제거하면 된다. 권한 이력 결함과 비스트리밍 필드 차이는 후속 수정 대상으로 남겼다.
