# 챗봇 화면 API 연결표

기본 경로 `/api`. 인증이 필요한 요청에는 `Authorization: Bearer <token>`을 보낸다.
`collection_name` 요청 값은 주제 목록의 `qdrant_name`을 사용한다.
아래 값은 가상 예시이며, `Citation`과 `Image`의 전체 형태는 문서 끝에 정의했다.

## 화면 영역별 엔드포인트

| 화면 영역 | 연결 API / 응답 데이터 |
|---|---|
| ① 대화 주제 | GET `/api/query/collections` |
| ② 헤더·모델·새 대화 | GET `/api/models`, GET `/api/chat/models`, GET `/api/health`, GET·POST `/api/user/llm-settings`, POST `/api/query/reset` |
| ③ 이전 대화 | GET `/api/query/history` |
| ④ 질문 입력 | POST `/api/query/stream`, POST `/api/voice/transcriptions` |
| ⑤ 답변·사진 배지 | stream의 `token`, `citations`, `images` |
| ⑥ 관련 이미지 | stream의 `images` |
| ⑦ 참고 문서·피드백 | stream의 `citations`, `meta`; PATCH `/api/query/{log_id}/feedback` |
| ⑧ 출처 패널 | stream의 `citations`; GET `/api/documents/{document_id}/spreadsheet-resources` |
| ⑨ 이미지 뷰어 | GET `/api/spreadsheet-resources/{resource_id}` |
| ⑩ 답변 듣기 | 미구현 |

## API별 Response

### GET /api/query/collections

```json
{
  "collections": [{"collection_name": "예시 주제", "qdrant_name": "example_topic"}],
  "user_id": "example_user"
}
```

### GET /api/models

```json
{
  "models": [{
    "model_id": "local", "model_name": "예시 모델", "provider": "local",
    "requires_api_key": false, "is_enabled": true, "sort_order": 0
  }]
}
```

### GET /api/chat/models

```json
{"model": "<LLM 모델명>", "embedding_model": "<임베딩 모델명>"}
```

### GET /api/health

```json
{"status": "healthy", "database": "connected", "vector_store": "connected"}
```

### GET /api/user/llm-settings?collection_name=example_topic

```json
{"setting": {"collection_name": "example_topic", "model_id": "local", "has_api_key": false}}
```

미저장 시 `{"setting":null}`.

### POST /api/user/llm-settings

요청: `{"collection_name":"example_topic","model_id":"local"}`

```json
{"collection_name": "example_topic", "model_id": "local", "has_api_key": false}
```

### POST /api/query/reset

요청: `{"collection_name":"example_topic"}`

```json
{"success": true, "collection_name": "example_topic"}
```

### GET /api/query/history?collection_name=example_topic

```json
{
  "collection_name": "example_topic",
  "history": [
    {"role": "user", "content": "예시 질문"},
    {
      "role": "assistant", "content": "예시 답변[1][IMG:abc123]",
      "citations": [], "images": [], "log_id": 123, "feedback": null
    }
  ]
}
```

`citations`는 `Citation[]`, `images`는 `Image[]`. 이전 이력에서는 필드가 없을 수 있어 빈 배열로 처리한다. `feedback`은 `like` / `dislike` / null. 대응 로그가 없으면 `log_id`가 없을 수 있다.

### POST /api/query/stream

요청:

```json
{"query": "예시 질문", "collection_name": "example_topic", "llm_provider": "local"}
```

응답: `text/event-stream`. 각 이벤트는 `data: {JSON}` + 빈 줄이다.

```text
data: {"type":"progress","stage":"searching"}

data: {"type":"progress","stage":"generating"}

data: {"type":"token","content":"예시 답변[1][IMG:abc123]"}

data: {"type":"citations","data":[]}

data: {"type":"images","data":[]}

data: {"type":"meta","log_id":123}

data: {"type":"done"}

```

`citations.data`는 `Citation[]`, `images.data`는 `Image[]`. `token`은 여러 번 수신한다. 사진이 없으면 `images` 이벤트를 보내지 않을 수 있다.

스트림 내부 오류:

```json
{"type": "error", "message": "<안내 문구>"}
```

### PATCH /api/query/{log_id}/feedback

요청: `{"feedback":"like"}` / `{"feedback":"dislike"}` / `{"feedback":null}`

```json
{"log_id": 123, "feedback": "like"}
```

### GET /api/documents/{document_id}/spreadsheet-resources

```json
{
  "document_id": "example-doc", "total": 1,
  "resources": [{
    "resource_id": "example-doc-v1-i0001", "document_id": "example-doc",
    "resource_type": "image", "content_hash": "<해시>", "mime_type": "image/png", "file_size": 10000,
    "sheet_id": null, "sheet_name": "예시 시트", "from_cell": "C10", "to_cell": "C12",
    "linked_block_id": null, "linked_record_ids": [], "surrounding_range": "A8:H14",
    "surrounding_text": "예시 설명", "status": "committed", "created_at": "2026-10-21T09:00:00+09:00",
    "download_url": "/api/spreadsheet-resources/example-doc-v1-i0001",
    "title": "예시 작업 사진", "role": "step_photo", "step_no": 1, "step_title": "예시 단계",
    "version_no": 1, "in_print_area": true, "review_status": "auto", "displayable": true
  }]
}
```

연결된 이미지 = 인용의 `resource_ids`에 포함되면서 `displayable === true`인 항목. `total`은 필터 전 개수다.

### GET /api/spreadsheet-resources/{resource_id}

성공 시 **JSON이 아닌 이미지 바이너리** (`Content-Type: image/png` 등).
인증 헤더를 붙여 blob으로 받은 뒤 `URL.createObjectURL`로 표시한다.

### POST /api/voice/transcriptions

요청: multipart `audio` 파일 필수, `language` 선택.

```json
{"text": "예시 인식 문장", "language": "ko"}
```

`language` 미전송 시 null. 성공 형태는 코드 계약이며 이번 실제 음성 인식 성공 호출은 미검증이다.

## 공용 응답 객체

### Citation — stream / history의 citations 항목

```json
{
  "citation_id": 1, "chunk_id": "example-chunk", "document_id": "example-doc",
  "original_filename": "예시.xlsx", "title": "예시.xlsx", "document_type": "spreadsheet",
  "section_name": "예시 단계", "header_path": [], "page_number": null,
  "chunk_text": "예시 근거", "display_markdown": "예시 근거 마크다운", "highlight_text": "예시 강조 문장",
  "sheet_name": "예시 시트", "source_range": null,
  "resource_ids": ["example-doc-v1-i0001"], "score": 0.8, "referenced_in_answer": true
}
```

매뉴얼은 조건에 따라 `manual_display_mapped`, `display_filename`, `display_page_number`가 추가된다.

### Image — stream / history의 images 항목

```json
{
  "ref": "abc123", "resource_id": "example-doc-v1-i0001", "document_id": "example-doc",
  "title": "예시 작업 사진", "role": "step_photo", "sheet_name": "예시 시트",
  "from_cell": "C10", "to_cell": "C12", "step_no": 1, "step_title": "예시 단계",
  "surrounding_text": "예시 설명", "original_filename": "예시.xlsx", "context_no": 1, "cited": true
}
```

`ref`는 본문의 `[IMG:ref]`와 연결한다. 사진 번호는 배열 순서+1이다. 문서 위치는 `document_id` + `context_no == citation_id`로 연결한다. `cited:false`는 본문 인용 없이 자동 첨부한 이미지다.

### 공통 오류

```json
{"detail": "<안내 문구>"}
```

요청 검증 오류(422):

```json
{"detail": [{"type": "missing", "loc": ["body", "query"], "msg": "Field required", "input": {}}]}
```

이미지: 401 인증 없음 / 403 권한 없음 / 404 없음. 질의 스트림 권한 없음은 HTTP 403 JSON 응답이다.

현재 백엔드 이슈: 권한 회수 후에도 기존 대화 이력이 반환된다. 프론트 처리와 별도로 백엔드 수정이 필요하다.
