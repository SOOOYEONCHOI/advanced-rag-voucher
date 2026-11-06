# 답변 사진 출처 기준 전환 보고서 (2026-11-06)

> 관련 ID: R4-3, R4-4, UI-03(답변 사진), UI-05(출처 패널), Phase 4-A, 변경로그 D-23
> 방향 문서: `../답변사진_출처기준_전환_개발방향_v1.0.md` · 원인 분석: `../관련이미지_연결이미지_개수차이_분석_v1.0.md`

## 1. 요약

- 설정 `ANSWER_IMAGE_SOURCE=citation`이면 답변 하단 [관련 이미지]를 **답변이 `[n]`으로 인용한 출처 청크의 `resource_ids` 사진**에서 고른다. 같은 그림 1장, LLM이 `[IMG:ref]`로 인용한 사진을 맨 앞으로, 최대 4장 + 전체 장수.
- 하단에 없는 사진의 `[IMG:ref]` 태그는 답변에서 지운다 → 본문 배지 번호 = 하단 번호, 하단 사진 ⊆ 출처 카드 사진.
- 행 범위 대체 조회·자동 첨부는 이 모드에서 쓰지 않는다. 기본값 `llm`은 기존 동작 그대로.
- 화면: 전체 장수가 더 많으면 "관련 이미지 4 / 전체 N" + [전체 N장 보기](출처 패널, 첫 사진의 출처 카드 선택). 사진 위치에 출처 번호 `[n]` 표시.
- 출처 패널 [연결된 이미지]: `resource_ids` 순서로 정렬, 같은 그림 1장(설정과 무관).

## 2. 변경 파일

| 구분 | 파일 | 내용 |
|---|---|---|
| 백엔드 | `app/core/config.py` | `answer_image_source: Literal["llm","citation"] = "llm"` |
| | `app/graphs/images.py` | `collect_citation_images`·`keep_image_tags` 추가, `_make_ref`·`_image_entry` 분리(ref 규칙 공용), `_lookup_resources(allow_row_fallback)`, 후보에 내부 키 `image_key`, 공개 필드 `citation_id` |
| | `app/graphs/nodes/format_citations.py` | `citation` 모드 분기, 두 모드 모두 `answer_images_total` |
| | `app/graphs/state.py` | `answer_images_total` |
| | `app/models/data_models.py` | `QueryResponse.images_total` |
| | `app/services/rag_service.py` | 비스트림 응답·이력 `images_total`, SSE `images` 이벤트 `total` |
| | `tests/test_answer_images.py` | 출처 기준 테스트 3개 추가, 이력 테스트에 `images_total` 반영 |
| | `.env.example` | `ANSWER_IMAGE_SOURCE`, `RAG_MAX_IMAGES` 이름·설명 |
| 프런트 | `src/components/ChatImageGallery.vue` | `total` props, "표시 / 전체" 장수, [전체 N장 보기], 출처 번호 표시 |
| | `src/components/CitationPanel.vue` | `linkedImages` 순서 정렬·같은 그림 1장 |
| | `src/composables/useChatView.js` | `imagesTotal`(SSE·비스트림·이력, 없으면 표시 장수) |
| | `src/views/ChatView.vue` | 갤러리에 `total`·`open-sources` 연결, `openImageSources` |
| 문서 | `01_결정사항_변경로그.md` | D-23 |

모든 수정 지점에 `2026.11.06(sooyeon.choi) 추가/수정 - 설명` 주석. `excel_ingest`·docling-parser·목업·요구사항 엑셀은 변경 없음.

## 3. 확인 결과

| 항목 | 결과 |
|---|---|
| `tests/test_answer_images.py` (컨테이너, langgraph 포함) | **14 passed** (기존 11 + 신규 3) |
| 관련 테스트 5개 파일(answer_images·citation_mapping·excel_ingest_pipeline_sample·spreadsheet_pipeline_integration·rag_stream) | 31 passed / 9 skipped / **1 failed** — `test_rag_stream.py::test_query_stream_converts_graph_tokens_to_sse`, 원인 `SimpleNamespace`에 `sqlite_db_path` 없음(rag_service.py 기존 코드, 기존 실패 목록과 같음) |
| 프런트 빌드(`vite build`, 임시 폴더 출력) | 성공(기존 번들 크기 경고만) |
| 전체 테스트(약 67분) | **실행하지 않음** |
| 개발 환경 실측(질의 로그·이력 저장 막고 컨테이너에서 실행, 질문 6개 × 두 모드) | "REACT FAN 조립 순서 알려줘": `citation` 모드 하단 1장(출처 [2] 사진, LLM 인용 없음) / 같은 질문 `llm` 모드는 그 실행에서 출처 0건이라 사진 없음. 모든 경우 **하단 사진 ⊆ 출처 카드 사진** 충족. 사진이 많은 표 청크(Recheck Sheet 등, 최대 21장) 문서는 이 컬렉션 검색에 잡히지 않아 **상한·같은 그림 합침은 실데이터로 못 봤고 단위 테스트로만 확인** |

신규 테스트가 확인하는 것: 출처 순 → `resource_ids` 순, 같은 그림 1장(출처 간 포함), 표시 불가 형식 제외, 상한·전체 장수, LLM 인용 사진 맨 앞·후보 ref 재사용(같은 그림의 다른 배치여도), 행 범위 대체 조회 안 함, DB 오류 시 빈 목록, 인용 안 된 컨텍스트 청크 사진·후보 밖 태그 제거, LLM 인용 없어도 사진 표시, 근거 없음·`[n]` 인용 없음이면 사진 없음, `llm` 모드 `total` = 표시 장수, 응답에 내부 키 `image_key` 안 나감.

## 4. 켜는 방법·마이그레이션·되돌리기

- 켜기: 백엔드 환경변수 `ANSWER_IMAGE_SOURCE=citation` 후 백엔드 재기동. 개발 `.env`는 바꾸지 않았다(사용자가 설정).
- 마이그레이션: 없음(이력 JSON에 필드만 추가). 이전 이력은 `images_total`이 없어 화면이 표시 장수로 대체.
- 되돌리기: `ANSWER_IMAGE_SOURCE=llm`(기본). 출처 패널 정렬·합침은 `CitationPanel.vue` `linkedImages` 수정만 원복.

## 5. 남은 이슈

- 실데이터 확인 부족: 사진이 많은 Step 청크가 걸리는 질문으로 화면에서 "4 / 전체 N"·[전체 N장 보기]를 확인해야 한다(사진 많은 문서를 대화 주제에 올린 뒤).
- 출처 패널은 여전히 문서 사진 전체를 받아 거른다(분석 S-2, E안 — 이번 범위 밖).
- 출처 카드에 "하단에 나온 사진" 배지는 이번 범위 제외(Q-5).
- 운영 반영 여부(`citation` 기본 전환)는 개발 확인 후 결정.

## 6. 요구사항 정의서·기능 목록에 반영할 것

- R4-3: "[관련 이미지]는 답변이 인용한 출처의 연결 사진 중 최대 4장(같은 그림 1장), 전체는 출처 패널에서 본다".
- UI-05: "연결된 이미지는 출처 청크 연결 순서, 같은 그림 1장".
