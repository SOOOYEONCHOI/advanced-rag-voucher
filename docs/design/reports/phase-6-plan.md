# Phase 6 계획 — DWG 도면 1단계: 업로드·기본 파싱 (6-0 조사·구현 계획 보고)

> 작성 2026-11-11 · 브랜치 `refactor-1`(작업 폴더, 커밋 안 함) · **코드 수정 없음. 승인 후 6-1 시작**
> 근거: `docs/design/drawing/DWG_도면파싱_설계_v0.3.md`(FR·NFR·오류 코드), `CLAUDE_CODE_작업지시서_Phase6_도면1단계.md`
> 관련 ID: R8-1, SC-12, MOD-14, MOD-01, WRK-01, API-02·03·09, UI-12

## 0. 사용자 결정 (2026-11-11)

| # | 결정 | 이 계획에 준 영향 |
|---|---|---|
| U-1 | **지금은 파싱만 한다.** 도면 메타데이터를 잘 저장하는 것이 목표 | 임베딩·Qdrant·검색 변경 없음 |
| U-2 | **최종 단계 목표**: 질의할 때 관련 도면을 찾아 챗봇 답변에서 도면을 바로 볼 수 있게 한다 | 파싱 결과의 중심을 "메타데이터 + 렌더 이미지"로 둔다. 치수 세부·풍선·도면 간 연결은 빼거나 미룬다 |
| U-3 | VLM 해석은 파싱 이후, 부족한 부분이 보일 때 붙인다 | 이번 Phase는 VLM 호출 0. 다만 렌더 이미지를 VLM 입력에 바로 쓸 수 있게 저장한다 |
| U-4 | DrawX(마키나락스) 참고 → 조건(재질·사양) 검색에 쓸 메타데이터를 미리 정리 | 표제란 필드를 `meta` 키 계약으로 고정(5장) |

## 1. 저장소 조사 결과 (6-0 항목 1)

| 항목 | 실제 코드 | 비고 |
|---|---|---|
| 파일 라우터(MOD-01) | `app/ingest/file_router.py` `resolve_parse_route()` → `ROUTE_DOCLING`/`ROUTE_EXCEL_INGEST` | 도면 경로를 같은 방식으로 추가 |
| 업로드 검사 | `routes/ingest.py` `_validate_upload_options()`·`SUPPORTED_EXTENSIONS`, 저장 `_store_upload_tmp()` | `.dwg`는 지금 400(`지원하지 않는 파일 형식`) |
| 작업 큐 | `tb_ingest_jobs` + 앱 프로세스 안 asyncio 큐(`services/ingest_jobs.py`) | 설계의 `tb_ingest_job`(단수)은 틀림 |
| 파이프라인 | `services/ingest_pipeline.py` `ParseStep → ChunkStep → EmbedStep → IndexStep`, 단계별 체크포인트·재시도 | 문서 행·버전·청크·리소스·적용 이력이 **IndexStep 한 트랜잭션**에 묶여 있다 |
| 엑셀 분기 | `ChunkStep._run_excel_ingest()`가 `parse_result`를 만들고 뒤 단계는 공용 | 도면은 뒤 단계(임베딩·색인)를 타면 안 된다 |
| 청크 표 | `tb_chunks` = **"Qdrant 포인트 1개 = 1행"**. 복원·삭제 검증이 `version_point_ids()`로 Qdrant와 대조 | **설계 v0.3의 "임베딩 없이 tb_chunks 저장"은 이 규칙을 깬다** → 이번 Phase는 `tb_chunks`에 쓰지 않는다 |
| `point_type` | CHECK에 `'drawing'` 이미 있음 | 최종 단계에서 사용 |
| 버전 상태 | `building/ready/active/retired/failed`. `ready` = "새 버전 색인 완료·전환 대기"(`ingest_pipeline.py` IndexStep) | 설계의 `ready` = "경고 대기"와 뜻이 충돌 → 도면에 `ready`를 쓰지 않는다 |
| 이미지 저장 | `tb_spreadsheet_resources`(+`role_cd`), `SpreadsheetResourceService`, `RESOURCE_STORAGE_ROOT`(기본 `instance/xl_res`), 청크 연결 `tb_chunk_resources` | 설계의 `tb_image_assets`는 없음. `resource_labels.py`에 `drawing`="도면" 라벨 있음 |
| VLM 결과 표 | `tb_spreadsheet_resource_analyses`(method `ocr/vlm/chart_parser`, model·prompt_version·text·confidence) | VLM 단계에서 마이그레이션 없이 사용 가능 |
| 문서 유형 | `RequestedDocumentType` = auto/law/manual/general/spreadsheet. `tb_documents.doc_type`에 CHECK 없음 | `drawing` 추가는 코드 enum만 |
| 마이그레이션 | 0001~0008 사용 중 | 설계의 `0007_drawing`은 번호 충돌. **이번 Phase는 마이그레이션 없음**(3장) |
| `dxf_ingest` PoC | 저장소에 없음. `docs/design/drawing/`에 참고 코드 2개(`sanitize_libredwg_dxf.py`, `render_filter.py`)만 있음 | 작업지시서의 `docs/design/ref/drawing_poc/` 경로도 실제와 다름 |
| 의존성 | ezdxf·matplotlib·LibreDWG 없음. 한글 글꼴(`fonts-noto-cjk`, `fonts-nanum`)·numpy·Pillow·pyyaml은 있음. 베이스 `python:3.12-slim` | 4장 |
| 프런트 UI-12 | `views/AdminView.vue`(2,232줄) 한 파일에 업로드 카드·처리 현황·문서 목록·최신본 변경. `acceptedExtensions`는 `/api/ingest/options` 응답으로 정함 | 처리 결과는 새 컴포넌트로 분리 |
| 화면 목업 | `mockups/admin_UI-12_문서관리_도면처리_목업_20261109_v0.5.html` | 읽기 전용(절대 규칙 9) |

## 2. 설계 v0.3과 다르게 하는 점 (6-0 항목 2)

| 설계 v0.3 | 저장소·결정 | 제안 |
|---|---|---|
| 청크를 임베딩 없이 `tb_chunks`에 저장(FR-18, 28~30) | `tb_chunks` = Qdrant 포인트 규칙 | **도면 IR(`drawing_ir.json`)을 원천 데이터로 둔다.** 청크는 최종 단계에서 IR로 만들어 기존 Embed·Index 단계에 넣는다. `rechunk`·`token_count`·`chunker_version` 칼럼은 필요 없다 |
| `tb_documents.search_enabled` + `tb_drawing_links` 신규(0007) | 파싱만 하는 동안에는 Qdrant 포인트가 0이라 검색에 나오지 않는다 | **이번 Phase 마이그레이션 없음.** 검색 적용 표시는 최종 단계에서 정한다(Q-2) |
| 표제란 누락 → 버전 `ready` | `ready`는 다른 뜻 | 버전은 `active`, 누락은 `W_TITLE_MISSING`(warn)과 `summary_json.drawing.needs_review=true`로 표시 |
| 이미지 `tb_image_assets` | 없음 | `tb_spreadsheet_resources`, `role_cd`=`drawing`(전체)·`drawing_crop`(영역) |
| 풍선↔BOM(FR-14), 도면 간 연결(FR-15), 치수 세부·공차 요약(FR-12~13), ODA 변환기 | U-2(메타데이터 + 도면 보기) | **이번 Phase에서 뺀다.** 치수 글자는 원문만 IR에 모아 둔다. 다른 항목은 6장 남은 이슈 |
| 같은 품번 감지 → 교체 선택 상자(목업 ⑥) | D-01(시스템이 같은 문서를 추측하지 않음, 개정은 [최신본 변경]) | 같은 품번이 이미 있으면 **안내 경고만** 띄우고(`W_DUPLICATE_PART_NO`) 자동 교체·선택 상자는 만들지 않는다 |
| 검수 완료 기록 `tb_document_events`(review) | 표는 있음 | 그대로 쓴다(API-09 검수) |

## 3. 처리 흐름 (이번 Phase)

```
API-02 업로드(.dwg·.dxf, DRAWING_PARSE_MODE=backend)
  → 형식 판별(확장자 + 매직 AC1012~AC1032 / DXF 헤더)  실패 400 E_UNSUPPORTED_FORMAT
  → tb_ingest_jobs 등록(operation=upload, 문서 유형 drawing)
WRK-01 도면 파이프라인: ParseStep(기존, 원본 저장·sha256)
  → DrawingParseStep: convert → sanitize → load → normalize → extract → IR 저장 → 확인용 md
  → DrawingRenderStep: 전체 PNG + 표제란·BOM·개정 크롭 (실패해도 경고만)
  → DrawingStoreStep: 한 트랜잭션으로 문서 행(doc_key=품번) + 버전 active(chunk_count 0)
                     + 이미지 리소스 + 적용 이력. tb_chunks·Qdrant·임베딩 호출 없음
```

- 기존 `IngestPipeline.steps`는 건드리지 않고, 도면용 `DrawingIngestPipeline.steps = (ParseStep(), DrawingParseStep(), DrawingRenderStep(), DrawingStoreStep())`을 따로 둔다. 작업 관리자는 요청의 처리기(`drawing_ingest`)를 보고 파이프라인을 고른다. 체크포인트·재시도·보상(리소스 파일 삭제)은 같은 방식이다.
- 버전 봉인(`seal_version`)은 하지 않는다. `vector_storage_state`는 기본값 그대로 두고 **도면 버전은 이전 버전 복원 대상에서 뺀다**(복원할 벡터가 없음). 6-5에서 복원·삭제·목록 경로가 포인트 0개 문서를 정상 처리하는지 테스트로 확인한다.

## 4. 새 의존성·설치 계획 (6-0 항목 3, 작업지시서 3장 규칙 4)

| 의존성 | 라이선스 | 설치 | 비고 |
|---|---|---|---|
| ezdxf 1.4.x | MIT | `requirements.txt`에 버전 고정. 운영(폐쇄망)은 기존 wheel 반입 방식 | 순수 Python(선택적 C 가속은 쓰지 않음) |
| matplotlib 3.x | PSF 계열 | 같음 | 렌더 전용 |
| LibreDWG 0.13.3 `dwg2dxf` | **GPLv3** | Dockerfile builder 단계에서 릴리스 tarball 소스 빌드(`--disable-bindings --disable-docs`), 실행 파일만 런타임 이미지에 복사. **별도 프로세스로만 호출** | 운영 반입은 라이선스 검토(Q-1) 후. 개발은 dev 이미지·WSL에서 |
| 한글 글꼴 | OFL | 이미 있음(`fonts-noto-cjk`, `fonts-nanum`) | 글꼴 매핑 YAML만 추가 |

## 5. 구현 계획과 파일 목록

### 6-1. 판별·변환·보정·로드 (FR-02, 04~07)
| 파일 | 내용 |
|---|---|
| `app/ingest/drawing/__init__.py` (신규) | 모듈(MOD-14) |
| `app/ingest/drawing/detect.py` (신규) | 확장자 + 매직바이트 판별, `DrawingFileRejected` |
| `app/ingest/drawing/convert.py` (신규) | 변환기 인터페이스 + LibreDWG 구현(subprocess, 타임아웃, 작업별 임시 폴더). ODA는 인터페이스 자리만 |
| `app/ingest/drawing/sanitize.py` (신규) | 핸들 0을 가리키는 사전 항목 제거(참고 코드 규칙 이식), 보정 건수 `W_SANITIZED`(info) |
| `app/ingest/drawing/reader.py` (신규) | `ezdxf.readfile` → `recover` → `E_DXF_LOAD`, 코드페이지·한글 깨짐률 `W_ENCODING` |
| `app/ingest/drawing/normalize.py` (신규) | `$EXTMIN/$EXTMAX`·축척 → 용지 크기(A0~A4)·정규화 좌표 |

### 6-2. 추출 (FR-08~11, 19) — 메타데이터 중심
| 파일 | 내용 |
|---|---|
| `app/ingest/drawing/textcodes.py` (신규) | MTEXT 서식·`%%`·`\U+`·`\M+` → 평문 |
| `app/ingest/drawing/blocks.py` (신규) | INSERT 전개(삽입점·배율·회전), `SW_TABLEANNOTATION_*`·`SW_NOTE_*` 문자 수집 |
| `app/ingest/drawing/title_block.py` (신규) | ① 템플릿(정규화 영역) → ② ATTRIB → ③ 라벨 인접(오른쪽·**아래**). 템플릿 일치율 50% 미만 `W_TEMPLATE_MISMATCH` |
| `app/ingest/drawing/tables.py` (신규) | 헤더 별칭 사전, 표 선으로 행·열 경계, 여러 줄 셀 합치기, 헤더 위/아래 판별 → BOM·개정이력 |
| `app/ingest/drawing/notes.py` (신규) | 주기 번호 항목, 일반공차 규격, 규격 메모, 기타 글자(일반공차표·`Confidential` 고정 문구 제외) |
| `app/ingest/drawing/templates/yest_a3_v1.yaml`, `aliases.yaml`, `fonts.yaml` (신규) | 양식·헤더 별칭·글꼴 매핑(NFR-10). 샘플 값은 넣지 않고 좌표 영역·라벨만 |

**메타데이터 키 계약**(IR `title_block.fields` → 최종 단계 payload·조건 필터에 그대로 사용, 이름 바꾸지 않음):
`doc_type=drawing`, `part_no`(=`drawing_no`), `part_name`, `rev`·`rev_major`·`rev_iter`(Q-3), `drawing_kind`(BOM 있으면 assembly), `sheet_size`, `scale`, `units`, `date`, `material`, `material_group`, `part_spec`, `after_treatment`, `drawn`·`checked`·`approved`, `bom_part_nos`(BOM 품번 목록), `confidential`.

### 6-3. 렌더·크롭 (FR-16~17)
| 파일 | 내용 |
|---|---|
| `app/ingest/drawing/render.py` (신규) | ezdxf `addons.drawing` + matplotlib, 범위 고정, 범위 5% 밖·경계 오류 HATCH 건너뛰기 `W_RENDER_SKIPPED`, 글꼴 대체 `W_FONT_FALLBACK`, 전체 PNG(긴 변 `DRAWING_RENDER_MAX_PX`) + 표제란·BOM·개정 크롭. 렌더 시간 제한(`DRAWING_RENDER_TIMEOUT_SEC`) |
| `app/ingest/drawing/images.py` (신규) | 렌더 결과 → `tb_spreadsheet_resources` 행 계획(엑셀 `excel_images.py`의 배치·저장 방식 재사용, 원본·미리보기·썸네일) |

### 6-4. IR·md·파이프라인 (FR-20~21)
| 파일 | 내용 |
|---|---|
| `app/ingest/drawing/ir.py` (신규) | `drawing_ir/1.0` 생성·저장(`{원본 저장소}/{document_id}/v{n}/derived/drawing_ir.json`), 변환기·ezdxf·템플릿 버전 기록(NFR-06) |
| `app/ingest/drawing/export_md.py` (신규) | 확인용 md `{MD_SAVE_DIR}/drawing/{doc_key}/{job_id}/`, 최근 5회 |
| `app/ingest/drawing/runner.py` (신규) | 6-1~6-3을 묶어 실행·단계 결과·경고(level 포함) 반환 |
| `app/services/drawing_pipeline.py` (신규) | `DrawingConvertStep`·`DrawingExtractStep`·`DrawingRenderStep`·`DrawingStoreStep`·`DrawingIngestPipeline`. 단계 코드 `parse → drawing_convert → drawing_extract → drawing_render → drawing_store` (2026-11-12 화면 단계 칸과 1:1로 나눔, `도면업로드_화면설계_현행기준_v1.0.md` 3.2) |
| `app/services/ingest_pipeline.py` (수정) | 도면 요청이면 `DrawingIngestPipeline`으로 넘기는 분기 1곳. 기존 단계 클래스는 수정하지 않음 |
| `app/services/ingest_jobs.py` (수정, 필요할 때만) | 단계 이름·진행률 표시 매핑에 도면 단계 추가 |
| `app/ingest/file_router.py` (수정) | `ROUTE_DRAWING_INGEST`, `DRAWING_PARSE_MODE` 분기. 엑셀 분기는 그대로 |
| `app/parsers/document_types.py` (수정) | `DRAWING = "drawing"`, 도면 확장자 호환성 |
| `app/core/config.py`, `.env.example` (수정) | 설정값(아래) |

### 6-5. API (API-02·03·09)
| 파일 | 내용 |
|---|---|
| `app/routes/ingest.py` (수정) | `_validate_upload_options()`에 도면 분기(엑셀 분기와 같은 형태), `/options`에 `drawing_ingest_extensions`, 도면 크기 상한 `DRAWING_MAX_UPLOAD_MB` |
| `app/routes/drawings.py` (신규) | API-09: `GET /api/ingest/documents/{id}/versions/{v}/drawing-result`(IR 요약·표·경고·이미지 ID·검수 상태), `POST/DELETE …/drawing-review`(검수 완료·취소 → `tb_document_events`). 보기 = 문서 열람 범위(`utils/security.document_scope` 한 곳), 검수 = `can_edit`(본인 업로드) 또는 관리자 — 2026-11-12 현행 화면(일반 사용자도 업로드) 기준으로 "관리자 전용"에서 바꿈 |
| `app/routes/ingest.py` (추가 수정) | `/options`에 `drawing_max_upload_mb`, 작업 결과 `result.drawing` 요약·`error_code`, 문서 목록 `DocumentItem.drawing`, 새 버전 등록의 도면↔문서 형식 불일치 400 |
| `app/models/ingest_models.py` (수정) | 응답 스키마(`DocumentItem.drawing` 선택 필드 등) |
| `app/services/document_version_restore.py` (수정, 최소) | 도면 문서 이력 응답 `restore_supported=false`·`restore_block_reason`, 복원 요청은 거부(벡터 없음) |

### 6-6. 화면 (UI-12) — **2026-11-12 현행 화면 기준으로 갱신**

상세는 `docs/design/drawing/도면업로드_화면설계_현행기준_v1.0.md`(영역별 설계·API·완료 기준·질문). 목업 v0.5는 11-09 이전 화면 위에 그려져 배치가 다르므로 문구·상태 흐름만 참고한다.

| 파일 | 내용 |
|---|---|
| `src/composables/useDocumentUpload.js` (수정) | 도면 확장자·크기 옵션, 전용 처리기 판정 일반화, 처리기별 단계 칸, `needs_review` 상태 |
| `src/composables/useAdminDocuments.js` (수정) | 유형 칩 `도면 N`, 오류 코드 문구, 처리 결과 열기 |
| `src/composables/useDrawingResult.js` (신규) | 처리 결과 조회·검수 |
| `src/components/DrawingResultDialog.vue` (신규) | 요약·부품표·개정이력·주기·경고·정보·처리 정보 탭, [검수 완료]/[검수 취소], [검색 적용] 비활성 |
| `src/views/AdminView.vue` (수정) | 업로드 안내·문서 유형/파서 비활성, 처리 현황 도면 행, 목록 3줄째 품번·Rev·상태 칩, [처리 결과] 버튼 |
| `src/utils/textFormat.js`, `src/api/adminApi.js` (수정) | `도면`·`도면 처리기` 라벨, API 호출 |

목업 ⑥(같은 품번 선택 상자)은 D-01에 따라 안내 문구로, ⑤(누락 필드 입력)는 확인 창 후 검수 완료로 바꾼다. 버전 이력 창(`DocumentVersionHistoryDialog.vue`)은 서버 응답만 바꾸고 화면 코드는 그대로 둔다.

### 6-7. 테스트
- `tests/drawing/` (신규): 합성 DXF를 코드로 생성(값이 라벨 아래, `SW_TABLEANNOTATION` 블록, 2~3줄 헤더). 매직 판별·보정 전후 로드·변환 타임아웃(가짜 변환기)·템플릿·라벨 아래 값·셀 합치기·헤더 방향·고정 문구 제외·범위 밖 렌더 제외·**임베딩·Qdrant 호출 0**·`DRAWING_PARSE_MODE=off` 회귀(.dwg 400 유지).
- 샘플 테스트는 `DRAWING_SAMPLE_DIR`가 있을 때만 실행(저장소 밖 샘플·정답 표, 보고서에는 수치만).

## 6. 설정값 (기본값은 기존 동작 유지)

| 이름 | 기본 | 설명 |
|---|---|---|
| `DRAWING_PARSE_MODE` | `off` | `off`/`backend`. off면 `.dwg` 400 유지 |
| `DWG_CONVERTER` | `libredwg` | 지금은 libredwg만 |
| `LIBREDWG_BIN` | `dwg2dxf` | 실행 파일 경로 |
| `DWG_CONVERT_TIMEOUT_SEC` | `120` | |
| `DRAWING_MAX_UPLOAD_MB` | `100` | |
| `DRAWING_TEMPLATE_DIR` | `app/ingest/drawing/templates` | 양식·별칭·글꼴 YAML |
| `DRAWING_RENDER_MAX_PX` | `4000` | |
| `DRAWING_RENDER_TIMEOUT_SEC` | `90` | 렌더 멈춤 방지 |
| `DRAWING_MD_KEEP_LAST` | `5` | |

## 7. 일정 (1인 추정)

| 단계 | 추정 |
|---|---|
| 6-1 판별·변환·보정·로드 + Dockerfile(dev) LibreDWG 빌드 | 1.5일 |
| 6-2 표제란·블록·표·주기 | 2.5일 |
| 6-3 렌더·크롭 | 1일 |
| 6-4 IR·md·파이프라인·저장 | 1.5일 |
| 6-5 API | 0.5일 |
| 6-6 화면(현행 화면 기준: 처리기별 단계 칸·유형 칩·목록 상태 칩 포함) | 2일 |
| 6-7 테스트·보고 | 1일 |
| **합계** | **약 10일** (설계 v0.3 12.5일에서 풍선·연결·치수 세부·청크 저장 제외, 11-12 화면 갱신으로 +0.5일) |

## 8. 최종 단계(검색·답변 도면 표시)로 넘기는 것

- IR + 메타데이터 키 계약(5장 6-2) → 도면당 청크 소수(개요·부품표·개정·주기) 생성 → 기존 Embed·Index 단계 → payload에 메타데이터와 `resource_ids`(전체 렌더·크롭)를 넣는다. 기존 답변 사진(D-23, 출처 청크의 연결 사진)이 그대로 도면을 보여 준다.
- 품번처럼 코드가 들어간 질의는 검색 토큰 정책 v2(Kiwi, `search-tuning-1.md`)가 이미 처리한다.
- 조건 필터(재질·사양·도면 종류)는 `build_metadata_filter`에 키를 더한다.

## 9. 질문 (결정 필요)

| # | 질문 | 제안 |
|---|---|---|
| Q-1 | LibreDWG(GPLv3)를 운영 이미지에 넣어도 되는지(법무·고객 확인) | 별도 프로세스 호출로 개발 진행, 운영 반입은 확인 후 |
| Q-2 | 검색 적용 표시를 `tb_documents` 칼럼으로 둘지 다른 방식으로 둘지 | 최종 단계 계획 때 결정(이번 Phase 마이그레이션 없음) |
| Q-3 | REVISION `F.5`의 의미(개정.반복?) | 원문과 분리값 함께 저장 |
| Q-4 | 다른 표제란 양식 도면 2~3장 추가 수집 가능 여부 | 템플릿이 하나뿐이면 다른 양식에서는 라벨 인접 방식만 동작 |
| Q-5 | 도면 문서를 넣을 대화 주제(collection) | 엑셀과 같은 대화 주제에 넣고 권한도 같게 |
| Q-6 | 같은 품번 도면이 이미 있을 때 안내만 할지(D-01), 목업 ⑥처럼 선택 상자를 둘지 | 안내만(D-01 유지) |
| Q-7 | 샘플 DWG 3종의 로컬 경로(`DRAWING_SAMPLE_DIR`) | 저장소 밖 경로를 알려 주시면 샘플 테스트에 사용 |

## 10. 요구사항 정의서·기능 목록에 반영할 것

- MOD-14 비고: "DWG 변환 2차" → "DWG 파싱(1단계) 1차, 검색 적용은 최종 단계"
- 변경로그 후보 D-25: DWG 파싱을 1차로 당김, 결과 중심을 메타데이터 + 도면 보기로(U-1·U-2)
- API-02(도면 접수)·API-09(도면 처리 결과·검수)·UI-12(도면 업로드·처리 결과) 설명
