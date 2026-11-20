# CLAUDE CODE 작업지시서 — Phase 6 개정: DWG 도면 처리 1단계 (파싱·저장·검수)

| 항목 | 내용 |
|---|---|
| 문서 버전 | v1.0 |
| 작성일 | 2026-11-09 |
| 대체 범위 | `CLAUDE_CODE_작업지시서_v3.1.md` **6장(Phase 6 — DXF 도면 기본 모듈)을 이 문서로 대체**한다. 다른 장은 그대로 따른다 |
| 설계 근거 | `docs/design/DWG_도면파싱_설계_v0.3.md` (요구사항 ID FR-…, NFR-…, 오류 코드 `E_`/`W_`는 이 문서 기준) |
| 화면 기준 | `docs/design/mockups/admin_UI-12_문서관리_도면처리_목업_20261109_v0.5.html` ([목업 미리보기] ①~⑦ 시나리오) |
| 참고 | DXF 기술검토 v0.1(`dxf_ingest` PoC), DB 구조 변경안 v0.1, 화면·API ID 목록(MOD-14), 변경로그 D-01·D-16·D-19~D-24 |
| 2단계 | `docs/design/도면처리_2단계_백로그.md` — **이번 Phase에서 구현하지 않는다** |

---

## 0. 요약

관리자가 UI-12에서 DWG·DXF를 올리면 **변환 → 보정 → 파싱 → 추출 → 청크 생성·저장 → 렌더**까지 자동으로 처리하고, 관리자가 [처리 결과]에서 추출 값을 검수할 수 있게 한다. **검색(임베딩·Qdrant 색인)에는 쓰지 않는다.** 청크는 `tb_chunks`에 임베딩 없이 저장해 두고, 2단계에서 저장된 청크만 임베딩·색인한다.

설계는 실제 저장소 코드를 보지 않고 만들었다. 그래서 **6-0(조사·계획 보고)을 먼저 하고 멈춘다.** 설계와 저장소가 다르면 저장소(CLAUDE.md 문서 우선순위 1)를 따르고, 다른 점을 보고한다.

## 1. 범위

| 구분 | 내용 |
|---|---|
| 한다 | `.dwg`·`.dxf` 업로드 접수, 형식 판별, 중복 확인, DWG→DXF 변환(별도 프로세스), DXF 보정, ezdxf 로드, 표제란·블록·BOM·개정이력·주기·치수·공차 요약·풍선·도면 간 연결 추출, 렌더·크롭, 도면 IR 저장, 청크 생성·저장(임베딩 없음), 청크 재생성(`rechunk`), 확인용 md, 처리 결과·검수 API와 UI-12 화면 |
| 하지 않는다 (2단계) | 임베딩, Qdrant 색인, [검색 적용] 동작, 검색 엔진(MOD-08) 필터 변경, 답변 출처(MOD-09)·UI-03·UI-05 변경, 재처리 시 색인 교체 |
| 하지 않는다 (2차) | 치수↔형상 연결·뷰 캡션(VLM, G-14), 추출값 편집 화면, PDF·스캔 도면, 3D 모델, PLM(Windchill) 연동 |

[검색 적용] 버튼은 화면에 **비활성 + "2단계" 표시**로만 둔다(목업 v0.5와 같게).

## 2. 전달 자료와 위치

| 자료 | 위치 | 저장소 커밋 |
|---|---|---|
| 이 작업지시서 | `docs/design/CLAUDE_CODE_작업지시서_Phase6_도면1단계.md` | 사용자가 넣음 |
| 설계 문서 v0.3 | `docs/design/DWG_도면파싱_설계_v0.3.md` | 사용자가 넣음 |
| 2단계 백로그 | `docs/design/도면처리_2단계_백로그.md` | 사용자가 넣음 |
| 화면 목업 v0.5 | `docs/design/mockups/admin_UI-12_문서관리_도면처리_목업_20261109_v0.5.html` | 사용자가 넣음. **읽기 전용**(절대 규칙 9) |
| PoC 참고 코드 | `docs/design/ref/drawing_poc/` (`sanitize_libredwg_dxf.py`, `render_filter.py`, `README.md`) | 사용자가 넣음. 샘플 데이터 없음 |
| 샘플 DWG 3종 | `{DRAWING_SAMPLE_DIR}/` (예: 저장소 밖 `~/neocon_local_samples/drawing/`) | **커밋 금지** |
| 정답 표 초안 | `{DRAWING_SAMPLE_DIR}/golden/*.json` | **커밋 금지** |

- 샘플 DWG와 정답 표는 실제 사내 도면과 그 추출값이다. 절대 규칙 3에 따라 **저장소·코드·테스트 데이터·보고서에 복사하지 않는다.** 테스트는 환경변수 `DRAWING_SAMPLE_DIR`가 있을 때만 실행하고 없으면 `skip`한다. 보고서에는 수치(통과 수·정답률·소요 시간)만 쓰고 품번·품명·작성자 같은 값은 쓰지 않는다.
- 목업 HTML에는 샘플 도면 렌더 이미지가 들어 있다. 챗봇 목업과 같이 **읽기만 하고** 이미지·데이터를 화면 코드나 테스트로 옮기지 않는다.
- 단위 테스트용 도면은 PoC처럼 **합성 DXF**를 코드로 만들어 쓴다(`tests/` 안에서 생성). 샘플 양식 특성(표제란 값이 라벨 아래, BOM이 `SW_TABLEANNOTATION` 블록 안, 헤더 2~3줄)을 합성 샘플로 재현한다.

## 3. 이번 Phase 추가 규칙

CLAUDE.md 절대 규칙 1~9는 그대로 지킨다. 이번 Phase는 아래를 더한다.

1. **임베딩·색인 호출 0.** 도면 작업은 `DRAWING_INDEX_ENABLED`가 false(기본)이면 임베딩 서버·Qdrant를 호출하지 않는다. 테스트로 확인한다.
2. **기본값은 꺼짐.** `DRAWING_PARSE_MODE` 기본 `off`. `off`이면 지금처럼 `.dwg`는 `415 UNSUPPORTED_FORMAT`, `.dxf`는 기존 동작(변경로그 D-16)을 유지한다.
3. **LibreDWG는 별도 프로세스로만 호출**한다(`subprocess`, 타임아웃·메모리 제한). 라이브러리 링크·Python 바인딩 사용 금지(GPLv3). ODA File Converter도 같은 어댑터 인터페이스 뒤에 둔다.
4. **새 의존성은 먼저 보고**한다: ezdxf 1.4.x(MIT, Python), LibreDWG 0.13.3(GPLv3, CLI, 소스 빌드), 한글 글꼴(Noto Sans CJK 또는 나눔고딕), matplotlib(이미 있으면 생략). 설치 방법(이미지 빌드 단계·내부 미러)을 계획에 쓴다.
5. **DB는 추가만**(D-19). 신규 칼럼·테이블은 Alembic revision 하나(`0007_drawing` 가칭)로 묶고 upgrade·downgrade를 쓴다.
6. **`excel_ingest`·docling-parser 수정 금지**(절대 규칙 5). 공통 모듈(파일 라우터·적재 워커·이미지 저장)을 고쳐야 하면 영향 범위를 계획에 쓴다.

## 4. 결정 대기 항목과 처리 방법

| 항목 | 상태 | 이번 Phase 처리 |
|---|---|---|
| D-25 후보: DWG 파싱·저장(1단계)을 1차로 당김 (v3.1 6장·MOD-14는 "DWG 변환 2차") | 승인 대기 | 이 지시서는 승인을 전제로 한다. 승인 전에는 `DRAWING_PARSE_MODE=off` 기본값 덕분에 운영 동작이 바뀌지 않는다 |
| D-26 후보: `tb_documents.search_enabled`, `tb_drawing_links` 신규 | 승인 대기 | 마이그레이션은 **작성하고 로컬에서만 적용**. 운영 반영 절차서에는 "D-26 승인 후 실행"으로 표시 |
| Q-1 LibreDWG·ODA 라이선스 검토 | 진행 중 | 개발·테스트는 LibreDWG로 진행. 운영 배포 여부는 결정 전까지 보류(NFR-08) |
| Q-3 REVISION `F.5`·`A.2` 의미 | 확인 중 | 원문(`revision`)과 분리값(`rev_major`, `rev_iter`)을 함께 저장. 분리 실패 시 원문만 |
| D-19~D-24 (DB 구조 변경안) | 승인 대기 | 기존 Phase 진행 상황을 따른다. 테이블이 아직 없으면(예: `tb_chunks`, `tb_document_versions`) 6-0에서 보고하고 진행 방법을 제안 |

결정이 필요한 새 항목이 나오면 추측해서 구현하지 말고 `TODO(결정필요: …)`로 남기고 보고서 질문 목록에 쓴다.

## 5. 할 일

각 단계가 끝나면 완료 기준을 테스트로 확인하고 다음으로 간다. 6-0만은 **보고 후 멈춘다.**

### 6-0. 조사·구현 계획 보고 (코드 수정 없음)

1. 다음을 저장소에서 확인한다: 파일 라우터(MOD-01) 위치와 분기 방식, 적재 워커·작업 테이블 실제 이름(`tb_ingest_job` vs `tb_ingest_jobs`)과 단계 칼럼, `dxf_ingest` PoC 존재 여부·위치, 이미지 저장 경로 설정(`RESOURCE_STORAGE_ROOT`)과 `tb_image_assets`·`tb_spreadsheet_resources` 상태, `tb_chunks`·`tb_document_versions` 존재 여부, 문서 유형 값 목록(`drawing` 허용 여부), UI-12 프런트 컴포넌트 구조(업로드 카드·처리 현황·문서 목록·문서 상세).
2. 설계 v0.3과 다른 점을 표로 정리한다(설계 / 저장소 / 제안).
3. 6-1~6-7의 구현 계획과 **수정·추가할 파일 목록**, 새 의존성 설치 계획, 마이그레이션 초안 목록을 보고한다.

**완료 기준**: `docs/design/reports/phase-6-plan.md` 작성 후 멈춤. 사용자 승인 후 6-1 시작.

### 6-1. 형식 판별·변환·보정·로드 (FR-02, 04~07)

- 모듈 위치 `ingest/drawing/`(MOD-14). 구성은 설계 4장 표를 따른다: `detect.py`, `convert/base.py`·`libredwg.py`·`oda.py`, `sanitize.py`, `reader.py`, `normalize.py`.
- `detect`: 확장자 + 매직바이트(`AC1012`~`AC1032` 허용, 그 밖은 `E_UNSUPPORTED_FORMAT`).
- `convert`: `convert(src, out_dir, timeout) -> ConvertResult(dxf_path, tool, version, elapsed_ms, exit_code, warnings)`. 실패 시 `DWG_CONVERTER_FALLBACK` 1회. 결과 DXF는 버전 폴더의 `derived/`에 보관해 재시도 시 재변환하지 않는다(NFR-04).
- `sanitize`: LibreDWG 출력에서 **값이 `0`인 소프트/하드 포인터(350·360)를 가리키는 사전 항목(코드 3 + 350/360)** 을 제거한다. 보정 건수를 `W_SANITIZED`(info)로 남긴다. 참고: `docs/design/ref/drawing_poc/sanitize_libredwg_dxf.py`. 보정 전 파일도 보관.
- `reader`: `ezdxf.readfile` → 실패 시 `ezdxf.recover.readfile` → 실패 시 `E_DXF_LOAD`.
- `normalize`: `$EXTMIN/$EXTMAX`와 축척으로 용지 크기(A0~A4)와 정규화 좌표(0~1) 변환을 만든다. 모델공간이 비면 레이아웃 사용.
- 인코딩: R2004 이하는 `$DWGCODEPAGE`(cp949), 한글 깨짐률 1% 초과 시 `W_ENCODING`.

**완료 기준**
- 샘플 3종: 변환 성공, 보정 후 `readfile` 성공(각 4건 보정), 한글 문자 깨짐 0, 용지 A3 판별. Taylor 변환 1 s 이내(참고 실측 0.35 s).
- 실패 케이스: 확장자만 바꾼 텍스트, 0바이트, 앞 50%만 남긴 DWG, 변환기 강제 종료(타임아웃) → 각각 `E_UNSUPPORTED_FORMAT`·`E_CONVERT_FAILED`·`E_CONVERT_TIMEOUT`.

### 6-2. 표제란·블록 전개·표 복원 (FR-08~10)

- 표제란 우선순위: ① 양식 템플릿(정규화 영역, `templates/*.yaml`) → ② ATTRIB 태그 사전 → ③ 라벨 인접. **라벨 인접은 "같은 줄 오른쪽"과 "바로 아래 칸" 둘 다** 본다(샘플 양식은 값이 라벨 아래).
- 샘플 양식 템플릿 이름 `yest_a3_v1`(가칭). 3종 모두 필드 위치가 정규화 좌표 소수점 4자리까지 같았다. 템플릿 라벨 일치율 50% 미만이면 `W_TEMPLATE_MISMATCH` 후 ②·③.
- 블록 전개: INSERT 삽입점·배율·회전 적용. `SW_TABLEANNOTATION_*`·`SW_NOTE_*` 안의 문자를 추출. 치수 블록(`*D…`, `_D_*`)은 치수에만 사용.
- 표: 헤더 별칭 사전(`PART_NAMBER`처럼 원본 오타도 별칭으로 등록, `PTC_WM_PART_NAME`, `Q'TY` 등) → **표의 가로·세로 선(LINE)으로 행·열 경계** → 셀 안 여러 줄 문자 합치기 → 헤더 위/아래 자동 판별(BOM은 헤더 위, 개정이력은 헤더 아래).
- 필수 3필드(품번·품명·개정) 중 하나라도 없으면 버전 `ready` + `W_TITLE_MISSING`.

**완료 기준**: 정답 표 대비 표제란 필수 3필드 3종 100%, 전체 14필드 95% 이상. Taylor BOM 8행×9열 행 누락 0·셀 정답 98% 이상, 개정이력 3행 정답, 벨트 도면의 빈 개정 표는 0행.

### 6-3. 주기·치수·공차·고정 문구·풍선·연결 (FR-11~15, 19)

- 주기: `Notes`/`주기` 아래 번호 항목 분리, 일반공차 규격(KS B ISO 2768-m/K) 추출, 규격 메모(`<… 규격 : …>` 형태 줄과 이어지는 줄) 수집.
- 치수: `<>`→측정값, 블록 문자의 접두·접미(`4-Ø … THRU`) 결합, 괄호 = 참고치수, 공차 분류(PoC 규칙 재사용).
- 공차 요약: `specified_tolerance_count`, `gdt_count`, `general_tolerance_only`.
- 고정 문구 제외: 템플릿에 정의된 일반공차표·`Confidential` 문구는 기타 문자 청크에서 뺀다. `Confidential`은 메타(`confidential: true`)로 저장.
- 풍선(S): `SW_NOTE` 블록 중 원 + 번호 1개 → 풍선, 가장 가까운 LEADER 끝점 = 지시 위치, BOM 항번 매칭, 미매칭은 `W_BOM_NO_BALLOON`/`W_BALLOON_NO_BOM`(warn). 개정 구름 표시(`D` 등 문자 1개 + 삼각형)는 풍선에서 제외.
- 도면 간 연결(S): BOM 품번 = 다른 도면 품번이면 `tb_drawing_links`에 저장. 하위 도면이 나중에 올라와도 품번으로 역방향 연결.

**완료 기준**: S2803265 주기 6항목·규격 메모 5줄, S2803463 치수 10개(`4-Ø3.8 THRU`, 참고치수 `(2.62)` 포함) 정답, 3종 `general_tolerance_only=true`, Taylor 풍선 6개 연결 + BOM 5·8번 `W_BOM_NO_BALLOON` 2건, 기타 문자 청크에 일반공차표 값 0건.

### 6-4. 렌더·크롭 (FR-16~17)

- ezdxf `addons.drawing` + matplotlib. 렌더 범위는 `$EXTMIN/$EXTMAX`로 고정한다.
- 범위 5% 밖으로 나가는 엔티티와 경계 경로 계산에 실패하는 HATCH는 **건너뛰고 `W_RENDER_SKIPPED`(warn, 건수)**. 참고: `docs/design/ref/drawing_poc/render_filter.py`. (Taylor는 변환 과정에서 손상된 HATCH 34개 때문에 그대로 그리면 범위가 40배로 커지고, 일부는 B-spline knot 오류로 렌더러가 멈춘다.)
- 글꼴 매핑 설정(`DRAWING_FONT_MAP`): GOTHIC·MALGUN 등 → 서버 한글 글꼴. 대체 시 `W_FONT_FALLBACK`(info).
- 출력: 전체 PNG(긴 변 4,000 px) + 표제란·BOM·개정이력·주기 영역 크롭. 이미지 3종(원본·미리보기·썸네일)은 기존 이미지 저장 규칙(`tb_image_assets`, sha256)을 따른다. 역할 `role_cd`: `drawing`(전체), `drawing_crop`(영역, `location_json.region` = `title_block|bom|revision|notes`).
- 렌더는 저장을 막지 않는다. 렌더 실패 시 `W_RENDER_FAILED`로 남기고 버전 상태는 바꾸지 않는다(NFR-05).

**완료 기준**: 3종 전체 이미지 정상(사람 확인, 보고서에 "확인함"만 기록), 한글 □ 0, Taylor 렌더 60 s 이내(참고 실측 24 s), 도면당 크롭 2~4개.

### 6-5. IR·청크 저장·재생성·md·파이프라인 (FR-18, 20~21, 28~30)

- 도면 IR `drawing_ir/1.0`(설계 6장 예시 구조)을 `derived/drawing_ir.json`에 저장하고 `tb_document_versions.ir_path`에 경로 기록. IR에 변환기·ezdxf·템플릿·`chunker_version` 기록(NFR-06).
- 청크 content_type 7종(설계 FR-18), 접두 `[도면 {품번} {품명} Rev.{개정} > {섹션}]`. **임베딩 없이 `tb_chunks`에 저장**(`embedding_model`·`embedded_at` NULL, `point_id`는 기존 규칙대로 계산만).
- `meta_json` 키 계약(2단계가 그대로 씀, 이름 바꾸지 말 것):

| 키 | 예 | 비고 |
|---|---|---|
| `doc_type` | `drawing` | |
| `part_no` / `drawing_no` | 표제란 품번 | 같은 값 |
| `rev`, `rev_major`, `rev_iter` | `F.5`, `F`, `5` | Q-3 |
| `drawing_kind` | `assembly` / `part` | BOM 유무로 판정 |
| `sheet_size`, `scale` | `A3`, `1:12` | |
| `content_type`, `section_label` | `drawing_bom_item`, `부품표 > 6` | |
| `item_no` | `6` | BOM 행 청크만 |
| `citation_label` | `{품번} Rev {개정} · 부품표 6번` | FR-29, 2단계 출처 카드 |
| `image_roles` | `["bom"]` | 연결 이미지 역할(`tb_chunk_resources`와 일치) |
| `chunker_version`, `ir_schema` | `1`, `drawing_ir/1.0` | FR-28 |
| `confidential` | `true` | FR-19 |

- `token_count` 기록. `DRAWING_CHUNK_MAX_TOKENS` 초과 시 BOM 전체 청크를 행 묶음으로 나눔(FR-30).
- `rechunk`: 저장된 IR만으로 청크를 다시 만드는 함수 + 관리 명령(CLI). DWG 변환·파싱을 다시 하지 않는다(FR-28).
- doc_key = 표제란 품번(없으면 파일명). 같은 품번이 이미 있으면 업로드 결과에 "같은 품번 문서 있음"을 표시하고 관리자가 [기존 문서의 최신본으로 등록]/[새 문서로 등록]/[취소]를 고른다(D-01, 목업 ⑥). 자동으로 교체하지 않는다.
- 확인용 md `{MD_SAVE_DIR}/drawing/{doc_key}/{job_id}/`(MOD-12 규칙, 최근 5회).
- 작업 단계 코드 `current_step`: `detect → convert → sanitize → load → extract → chunk_store → render → done`. 진행률은 단계 기준.
- 마이그레이션 `0007_drawing`(가칭): `tb_documents.search_enabled boolean NOT NULL DEFAULT false` + **기존 행은 true로 채움**(기존 문서 동작 유지), `tb_drawing_links`(parent_document_id, parent_part_no, child_part_no, child_document_id NULL, bom_item_no, qty, created_at). 필요하면 `tb_chunks`에 `token_count`·`chunker_version`이 없을 때만 추가. 문서 유형 CHECK에 `drawing` 추가(넓히기만).

**완료 기준**: Taylor 청크 13개(개요 1·개정 1·BOM 1·BOM 행 8·치수 1·기타 1, 실제 개수가 다르면 근거 보고), 벨트 도면 각 5개 내외. 모든 청크에 `citation_label`·`token_count` 존재. Qdrant 포인트 증가 0, 임베딩 호출 0. `rechunk` 실행 시 변환기 호출 0이고 같은 IR이면 같은 청크. `alembic downgrade`로 원복 확인.

### 6-6. API·화면 (FR-01, 03, 20, 22~23 / API-02·03·04·09 / UI-12)

API는 설계 8.1 표의 1단계 행을 따른다. 엔드포인트 접두사·버전은 Phase 0 규칙에 맞춘다.

- API-02: `.dwg`·`.dxf` 접수, `document_type=drawing`, 파일당 `DRAWING_MAX_UPLOAD_MB`(기본 100). 중복 sha256은 새 작업 없이 기존 문서 반환.
- API-03: 단계 코드·진행률·오류 코드.
- API-09: 처리 결과(표제란 필드·표·풍선 연결·주기·치수·경고(level 포함)·이미지 ID·청크 목록·검수 상태). 검수 `POST …/versions/{v}/review`(취소 `DELETE`), `ready` 버전은 누락 필드 값 `{fields}`를 받아 확정.
- API-04: 같은 품번 교체 후보 제시.

UI-12(목업 v0.5 기준, 배치·문구·상태 흐름을 따른다):
1. 업로드 카드: 허용 확장자에 `.dwg`·`.dxf`, 도면만 선택 시 문서 유형 "도면" 자동 지정 + 파서 "도면 처리기" 고정·비활성 + 안내(D-16의 엑셀 처리와 같은 방식). 문서·도면 혼합 선택 시 파일별 판별.
2. 처리 현황: 파일별 6단계 표시(형식 판별·DWG→DXF 변환·DXF 보정·항목 추출·청크 저장·렌더·크롭), 표시 이름은 표제란 품명으로 자동 입력, 실패 시 오류 코드·해결 안내·[재시도], 같은 품번 감지 시 선택 상자(⑥).
3. 문서 목록: "도면" 배지, 파일명 위 품번·Rev·유형, 경고 칩(`warn` 수만), "검색 미적용"·"미검수/검수 완료" 표시, 유형 필터(전체/문서/도면), [처리 결과] 버튼, [검색 적용] 비활성 + "2단계".
4. 처리 결과 대화상자: 탭 요약(렌더 썸네일 전체·표제란·부품표·개정이력 + 표제란 필드 + 공차 구성 + 도면 연결) · 부품표(풍선·하위 도면 상태, 원본 영역 보기) · 개정이력 · 주기·치수 · **경고·정보(`2+2`처럼 나눠 표시)** · 처리 정보(단계·소요 시간·저장된 청크 목록·md 경로). 하단 [다시 처리]·[검색 적용(2단계, 비활성)]·[검수 완료]/[검수 취소]·[닫기]. `ready` 버전은 누락 필드 입력 + [확인 후 확정](⑤).
5. 관리 API·화면은 관리자만(작업자 토큰 403). 도면 이미지도 권한 판단 함수 하나를 거친다(절대 규칙 8).

**완료 기준**: 목업 ①~⑦ 흐름이 실제 화면에서 재현됨(스크린샷은 합성 도면으로 찍어 보고서에 첨부), 작업자 계정 403, 검수 표시가 `tb_document_events`(review)에 남음.

### 6-7. 테스트·보고 (FR-31은 S)

- 단위 테스트(합성 DXF): 매직 판별, 보정 규칙(보정 전 로드 실패 → 보정 후 성공), 변환 타임아웃·대체 변환기(가짜 변환기 스크립트로), 템플릿 매칭, 라벨 아래 값, 여러 줄 셀 합치기, 헤더 방향, 치수 접두 결합, 일반공차표 제외, 범위 밖 엔티티 렌더 제외, `DRAWING_INDEX_ENABLED=false`일 때 임베딩·Qdrant 호출 0, `rechunk` 재현성. 기존 PoC 테스트 17개는 ezdxf 교체 후에도 통과.
- 샘플 테스트(`DRAWING_SAMPLE_DIR` 있을 때만): 정답 표 대비 정답률 계산 스크립트, 6-1~6-5 완료 기준 수치 산출.
- (S) FR-31 테스트 컬렉션 CLI: 개발 환경에서만, 운영 컬렉션 이름이면 거부.

## 6. 설정값

| 이름 | 기본값 | 설명 |
|---|---|---|
| `DRAWING_PARSE_MODE` | `off` | `off`/`backend`. off면 기존 동작 |
| `DRAWING_INDEX_ENABLED` | `false` | 1단계는 항상 false. true여도 이번 Phase에서는 동작 없음(2단계 연결 지점만) |
| `DWG_CONVERTER` | `libredwg` | `libredwg`/`oda` |
| `DWG_CONVERTER_FALLBACK` | `none` | `oda`/`none` |
| `DWG_CONVERT_TIMEOUT_SEC` | `120` | |
| `DWG_CONVERT_MAX_MEM_MB` | `2048` | NFR-02 |
| `LIBREDWG_BIN` / `ODA_CONVERTER_BIN` | (경로) | 실행 파일 위치 |
| `DRAWING_MAX_UPLOAD_MB` | `100` | |
| `DRAWING_TEMPLATE_DIR` | `ingest/drawing/templates` | 양식 템플릿·키워드 사전 YAML |
| `DRAWING_FONT_MAP` | (YAML 경로) | CAD 글꼴 → 서버 글꼴 |
| `DRAWING_RENDER_MAX_PX` | `4000` | 전체 이미지 긴 변 |
| `DRAWING_CHUNK_MAX_TOKENS` | (임베딩 모델 한도의 80%) | FR-30 |
| `DRAWING_SAMPLE_DIR` | (없음) | 테스트 전용. 저장소 밖 경로 |

`.env.example`에는 이름과 비밀 아닌 기본값만 쓴다.

## 7. Phase 전체 완료 기준

- [ ] 6-0 계획 승인 후 진행, 6-1~6-6 완료 기준 모두 충족(수치는 보고서에)
- [ ] 샘플 3종: 표제란 필수 3필드 100%, BOM 행 누락 0, 한글 깨짐 0, 렌더 정상
- [ ] 도면 처리 중 임베딩 호출 0, Qdrant 포인트 증가 0
- [ ] `DRAWING_PARSE_MODE=off`에서 기존 엑셀·PDF 업로드 회귀 테스트 통과
- [ ] 마이그레이션 upgrade·downgrade 로컬 확인, 기존 268개 칼럼 보존 스크립트 통과(DB 변경안 7장)
- [ ] 샘플 도면·정답 표·추출값이 저장소·보고서에 들어가지 않음(`svn status`로 확인)

## 8. 보고서

`docs/design/reports/phase-6.md`에 CLAUDE.md 4장 항목(변경 파일 / 요약 / 관련 ID / 완료 기준 충족 근거 / 마이그레이션 / 되돌리는 방법 / 남은 이슈)을 쓰고 멈춘다. 추가로:

- **설계와 다르게 구현한 점**과 이유
- **2단계 준비 상태**: `meta_json` 키 계약 충족 여부, `rechunk` 동작, 남은 연결 지점
- **요구사항 정의서·기능 목록에 반영할 것**: MOD-14 비고("DWG 변환은 2차" → 1단계 1차), API-02·03·04·09 설명, UI-12 설명(도면 업로드·처리 결과·검수), 변경로그 D-25·D-26 후보
- 질문 목록(결정 필요)

## 부록 A. 샘플 실측값 (2026-11-04, LibreDWG 0.13.3 + ezdxf 1.4)

값의 근거는 설계 문서 2장. 품번·품명 등 원본 값은 정답 표(`{DRAWING_SAMPLE_DIR}/golden/`)에만 있다.

| 항목 | 조립도(Taylor) | 벨트 가공품 A | 벨트 가공품 B |
|---|---|---|---|
| 형식 | R2000(AC1015), cp949, SolidWorks | 같음 | 같음 |
| DWG → DXF | 3.4 MB → 14.9 MB | 129 KB → 458 KB | 158 KB → 569 KB |
| 변환 / 로드 / 렌더 | 0.35 s / 2.5 s / 24 s | 0.01 s / 0.06 s / 0.8 s | 0.02 s / 0.07 s / 1.3 s |
| 모델공간 엔티티 | 52,404 | 1,243 | 1,498 |
| 보정 건수 | 4 | 4 | 4 |
| 표 | 개정 3행 + BOM 8행 | 개정(빈 표) | 개정(빈 표) |
| 렌더 제외 HATCH | 34 | 0 | 0 |

## 부록 B. 이 문서가 바꾸는 v3.1 6장 내용

| v3.1 6장 | 이 문서 |
|---|---|
| `.dwg`는 "1차 미지원" + 415 | `DRAWING_PARSE_MODE=backend`일 때 변환 후 처리 |
| 추출 범위 G-1~5, G-9, G-13 | G-1~G-13(풍선·연결은 S) |
| 청크 → 기존 적재 파이프라인(임베딩·색인) | 청크 저장까지만, 색인은 2단계 |
| 완료 기준: 검증 질의 5개 Top-5 | 2단계로 이동. 1단계는 정답 표 기준 추출 정확도 |
| 합성 샘플 2종 결과 = 기술검토 7장 | 유지(PoC 테스트 17개 통과) + 실제 샘플 3종 기준 추가 |
