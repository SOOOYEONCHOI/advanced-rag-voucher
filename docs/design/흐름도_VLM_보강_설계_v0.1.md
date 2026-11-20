# 흐름도 VLM 보강 설계 v0.1 — 제조공정도(Gemma-4-12B-it)

> 작성 2026-11-16 · 상태: **설계안(승인 전, 구현 없음)**
> 관련 ID: R3-4(공정 흐름도 인식), R3-5(연결 검수), D-08(흐름도 범위), SC(공정 순서 질문)
> 기준 코드: `excel_ingest/parser.py`(`_flow_graph`, `build_chunks`), `app/services/ingest_pipeline.py`, `app/ingest/records.py`(`flow_graph_rows`), `app/services/sheet_preview_service.py`

**요약:** VLM에 "흐름도를 읽고 설명하라"고 맡기지 않는다. XML 파싱과 도형 좌표 계산으로 연결선을 최대한 확정하고, 그래도 연결 대상을 모르는 선과 OK/NG 분기만 Gemma에게 묻는다. 답은 미리 준 노드 ID 안에서만 고르게 한다. 이렇게 하면 정확하고, 결과를 검증하기 쉽고, 다음 등록 때 재사용할 수 있다.

## 0. 시작 전에 확인할 것

- **범위:** 변경로그 D-08에서 "분기·병렬 자동 해석"은 **2차 항목**이다. 사용자 요청으로 진행하되, 1차로 앞당기는 결정을 변경로그에 새 항목(D-xx)으로 남긴다(결정 필요 1번).
- **기존 파서는 그대로 둔다:** 절대 규칙 5에 따라 `excel_ingest/`는 수정하지 않는다. 새 모듈 `app/ingest/flowchart/`에서 `ParseResult`를 받아 보강한다. `excel_ingest.ooxml`은 가져다 쓰기(import)만 한다.
- **Gemma 서버(GPU 3번, 8111, `vllm@vlm-gemma`):** 현재 테스트용이라 부팅 시 자동으로 켜지지 않는다. VLM이 꺼져 있거나 응답이 없어도 적재는 실패하지 않게 한다. 이때는 지금처럼 XML 결과만으로 청크를 만든다.
- 모델은 사내 GPU 자체 서빙이며 외부 API 호출이 없다(절대 규칙 7 충족).

## 1. 샘플 파일 실제 파싱 결과 (현재 `parse_workbook` 기준, 2026-11-16)

| 항목 | 값 |
|---|---|
| 시트 분류 | `flowchart` (도형끼리 이은 연결선 28개) |
| 노드 | 46개 (사각형 33, 둥근 사각형 7, **판단(마름모) 5**, 준비 1) |
| XML로 확정된 연결 | 28개 |
| **연결 대상을 모르는 선** | **20개** (끝점만 없음 10, 양 끝 없음 9, 시작점만 없음 1) |
| 연결 없는 노드 | 12개 |
| OK/NG 라벨 도형 | 8개 (어느 선에 붙는지는 정해지지 않음) |
| 공정단계 표 | 13행 (열: 공정단계·주요 작업·사용 Tool·작업 가이드·검사 항목) |
| 사진 | **0개**. 흐름도가 그림이 아니라 엑셀 도형이므로 VLM에 넣을 이미지를 따로 렌더링해야 한다 |
| 인쇄영역 | 없음 |

- 핵심 문제는 판단 노드 5개, OK/NG 라벨 8개, 연결 대상 없는 선 20개다.
- 양 끝이 없는 선 9개는 대부분 선끼리 이어지는 모선(분기선)으로 보인다.
- 노드→공정단계 매핑이 행 위치 기준이라 3~8단계 구간은 어긋날 수 있다(`excel_ingest/README.md`).

## 2. 전체 흐름

```
[L0] parse_workbook (기존 그대로)  → flow_graph: 노드·XML 연결·미연결 선·OK/NG 라벨
        │
[L1] 좌표 보강 (결정적 계산, 비용 없음)
        │   연결선 실제 끝점 좌표 → 가까운 노드에 붙임 / 선-선 교차 → 모선 병합 / OK/NG → 가장 가까운 선
        │   노드 → 공정단계 매핑을 도형 영역과 겹치는 행 기준으로 다시 계산
        ▼
[L2] VLM 필요 여부 판정 ── 필요 없음 ──► [L6]
        │ 필요
[L3] 렌더링: 임시 사본에 노드 ID 표시 → LibreOffice로 PDF → PNG
[L4] Gemma-4-12B-it 호출: 이미지 + 노드 목록 + 남은 미해결 항목 → 정해진 형식의 JSON
[L5] 병합·검증: ID 검사, XML 연결은 덮어쓰지 않음, 그래프 규칙 검사, 신뢰도 표시
        ▼
[L6] 텍스트로 변환 → 청크 (전체 흐름 1개 + 판단 노드별 분기 청크 + 공정단계 청크에 이전·다음 줄)
[L7] tb_flow_graphs 저장 (연결마다 출처 표시) + 확인용 md(mermaid)
```

**연결 지점:** `app/services/ingest_pipeline.py` 엑셀 단계에서 `run_excel_ingest()` 직후, `excel_chunks_to_documents()`·`flow_graph_rows()`를 부르기 전에 `enrich_flowcharts(output.result, source_path, settings)`를 한 번 부른다. 이 함수는 `result.ir["sections"][i]["flow_graph"]`와 `result.chunks`의 흐름도 청크(`flow_overview`)를 바꿔 넣는다.

## 3. L1 좌표 보강 (VLM 전에 최대한 줄이기)

현재 `Connector.rng`에는 셀 범위만 들어 있어 선 끝점의 정확한 위치를 모른다. 도면 XML을 다시 읽어 실제 좌표(EMU 단위)를 계산한다.

1. **선 끝점:** `xfrm`의 위치(off)·크기(ext)·뒤집기(flipH/flipV)·회전(rot)과 그룹 좌표 변환(`_group_positions`)을 적용해 시작점·끝점을 구한다. 꺾인 연결선(bentConnector)도 끝점은 bbox의 대각 꼭짓점이므로 같은 방식으로 계산한다.
2. **노드에 붙이기:** 끝점이 노드 영역에서 허용 오차(`FLOWCHART_SNAP_TOL_EMU`, 기본값 약 0.1행 높이) 안에 있으면 그 노드에 연결한다. 출처는 `source="geom"`이다.
3. **모선 병합:** 끝점이 다른 선의 선분 위에 있으면 하나의 그룹으로 묶는다(합집합 찾기). 그룹 안에서 화살표 머리가 붙은 쪽을 도착 노드로 보고, 나머지 노드에서 도착 노드로 가는 연결을 만든다. 방향이 애매하면 해결하지 않고 남긴다.
4. **OK/NG 라벨:** 판단 노드에서 나가는 선 가운데 라벨 도형 중심과 가장 가까운 선분에 라벨을 붙인다. 거리가 기준값을 넘으면 붙이지 않고 남긴다.
5. **공정단계 매핑:** 노드 영역의 세로 범위와 겹치는 비율이 가장 큰 공정단계 행으로 정한다(3~8단계 어긋남 대응).

이 단계에서 남는 것이 VLM 대상이다. 샘플에서 20개 중 몇 개가 남는지는 구현 후 실제 수치로 보고한다.

## 4. L2 VLM 호출 기준

| 순서 | 조건 | 처리 | `vlm_status` |
|---|---|---|---|
| 1 | `FLOWCHART_VLM_ENABLED=false` (기본값) | 호출 안 함 | `skipped:disabled` |
| 2 | 시트 유형이 `flowchart`가 아님 | 호출 안 함. SOP 시트의 연결선(FAN Module 17개 등)은 사진에 붙은 지시선이라 대상 아님 | (없음) |
| 3 | 도면 내용(`source_hash`)·프롬프트 버전·모델이 같은 이전 결과가 있음 | 재사용. 검수가 끝난 결과면 검수 상태도 유지(R3-5 "다시 등록해도 유지") | `cached` |
| 4 | L1 이후 미해결 선 0개, 연결 없는 노드 0개, 판단 노드마다 나가는 선 2개 이상 + OK/NG 모두 붙음 | 호출 안 함 | `skipped:xml_complete` |
| 5 | 4번 조건 가운데 하나라도 남음 | **호출** | `done` / `partial` |
| 6 | 노드가 `FLOWCHART_VLM_MAX_NODES`(예: 80)를 넘음 | 공정단계 행 기준으로 겹치게 나눠 여러 번 호출 | `done` / `partial` |
| 7 | 렌더링 실패·시간 초과·JSON 형식 오류(1회 재시도 후) | XML·좌표 결과로 계속 적재 | `failed:<원인>` |

## 5. L3 렌더링

- **노드 ID 표시:** 원본은 건드리지 않는다. 임시 사본의 도형 텍스트 앞에 `[N12]`처럼 짧은 ID를 붙여 렌더링한다. VLM이 화면 속 위치를 노드 ID로 정확히 짚게 하는 핵심 장치다(문구로 찾아 맞추면 같은 문구가 반복될 때 틀어진다). 사본과 렌더링 결과는 작업 임시 폴더에만 두고 끝나면 지운다.
- **렌더러:** `sheet_preview_service._render_sheet_preview()`(LibreOffice UNO 워커, 운영 중)를 재사용한다. 범위는 모든 노드 영역을 합친 셀 범위에 여백을 더한 것이다.
- **PDF → PNG:** 이미 설치된 `pypdfium2`(pdfplumber 의존 패키지)를 쓴다. 새 패키지는 필요 없다. 해상도 `FLOWCHART_RENDER_DPI=200`, 긴 변이 `FLOWCHART_RENDER_MAX_PX=2048`을 넘으면 줄이거나 나눈다.

## 6. L4 Gemma 호출

vLLM의 OpenAI 호환 `/v1/chat/completions`에 base64 이미지를 넣어 보낸다. `temperature=0`, 답 형식은 `response_format`의 json_schema로 강제한다.

**모델 설정:** 변경로그에 VLM 용도가 Qwen3-VL-8B(시범)로 남아 있으므로 모델 이름을 코드에 박지 않는다. `tb_model_config`의 VLM 용도 활성 모델을 쓰고, 없으면 `VLM_API_URL`·`VLM_MODEL_NAME` 환경변수를 쓴다. 기존 `app/clients/openai_client.py`를 재사용한다.

**프롬프트에 넣는 것:**
1. 노드 목록: `N12 | 판단 | "<도형 문구>"`
2. 이미 확정된 연결: 참고용이며 바꾸지 말라고 명시
3. 물어볼 것: 연결 대상이 없는 선의 대략적 위치, 나가는 선이 부족한 판단 노드, 아직 붙지 않은 OK/NG 라벨

**답 형식(JSON):**
```json
{"edges": [{"from": "N12", "to": "N15", "label": "OK|NG|null",
            "confidence": "high|medium|low", "evidence": "짧은 근거"}],
 "unknown": ["N30"]}
```

**지켜야 할 규칙:** 목록에 없는 ID는 쓰지 않는다. 확신이 없으면 `unknown`에 넣는다. 노드 문구를 새로 만들어 쓰지 않는다.

## 7. L5 병합·검증

- **ID 검사:** 목록에 없는 ID, 자기 자신으로 가는 연결, 중복 연결은 버린다.
- **XML 연결은 그대로:** VLM이 XML로 확정된 연결과 반대되는 답을 하면 덮어쓰지 않고 `conflicts`에 기록한다.
- **그래프 규칙:**
  - 시작 노드에서 모든 노드에 도달할 수 있는지
  - 판단 노드마다 OK·NG가 각각 하나인지
  - 순환은 NG 재작업처럼 판단 노드에서 시작하는 것만 허용
  - 규칙을 어긴 연결은 `confidence=low`로 표시
- **연결 출처:** `xml` / `geom` / `vlm`으로 나누고, VLM에서 온 연결은 모두 `verified=false`다.
- **신뢰도 높이기(선택):** `FLOWCHART_VLM_VOTES=2`로 두 번 물어 일치한 연결만 `confidence=high`로 둔다.
- **검수 상태:** VLM 연결이 하나라도 있으면 `review_status=needs_review`. 관리자가 md로 확인하면 `md_checked`(기존 값 그대로).

## 8. L6 청크 (Qdrant에 들어가는 텍스트)

| 청크 | 내용 예 | 용도 |
|---|---|---|
| `flow_overview` (기존 것을 교체) | `[모델 > 제조공정도 > 공정 흐름]` + 주 흐름 순서, 판단 지점 요약, "※ 일부 연결 VLM 보강·검수 전" | "전체 공정 순서" 질문 |
| `flow_branch` (신규, 판단 노드마다 1개) | `<판단 노드>(3단계): OK → <다음 노드> / NG → <재작업 노드> → <판단 노드>` | "NG 나면 어디로?" 질문 |
| `flow_stage` (기존 청크에 줄 추가) | `이전 공정: … / 다음 공정: …` | 단계별 질문 |

- `source_key`는 `NN:flow_branch:N12` 형태로 정해 버전이 바뀌어도 같은 키가 유지되게 한다.
- 낮은 신뢰도 연결은 문장에 "(확인 필요)"를 붙인다. 검수 전 VLM 연결을 답변에 쓸지는 결정 필요 2번.

## 9. 저장·설정·테스트

**저장:**
- `tb_flow_graphs.edges_json`에 연결별 출처·신뢰도·라벨을 넣고, `vlm_status`는 4절 상태값을 쓴다. **마이그레이션 없이 가능하다.**
- 캐시 판단용 정보(모델·프롬프트 버전·소요 시간)는 `vlm_meta_json` 컬럼을 Alembic으로 추가할지 따로 정한다(결정 필요 5번).
- 확인용 md: `excel_ingest`의 md를 고칠 수 없으므로 같은 폴더에 `flow_<시트>.md`(mermaid, VLM 연결은 점선)를 따로 쓴다.

**설정값** (모두 `app/core/config.py`, 기본값은 기존 동작 유지):

| 이름 | 기본값 | 설명 |
|---|---|---|
| `FLOWCHART_VLM_ENABLED` | `false` | VLM 보강 켜기 |
| `FLOWCHART_SNAP_TOL_EMU` | 약 0.1행 높이 | L1 노드 붙이기 허용 오차 |
| `FLOWCHART_RENDER_DPI` | `200` | 렌더링 해상도 |
| `FLOWCHART_RENDER_MAX_PX` | `2048` | 이미지 긴 변 최대 |
| `FLOWCHART_VLM_MAX_NODES` | `80` | 넘으면 나눠 호출 |
| `FLOWCHART_VLM_TIMEOUT` | `120` | 호출 시간 제한(초) |
| `FLOWCHART_VLM_VOTES` | `1` | 반복 호출 횟수 |
| `FLOWCHART_PROMPT_VERSION` | `0.1` | 캐시 키에 포함 |

L1 좌표 보강은 VLM과 별도로 켜고 끌 수 있게 `FLOWCHART_GEOM_ENABLED`(기본 `false`)를 둔다.

**새 파일:**
- `app/ingest/flowchart/__init__.py` — `enrich_flowcharts()` 진입점
- `app/ingest/flowchart/geometry.py` — L1
- `app/ingest/flowchart/decide.py` — L2
- `app/ingest/flowchart/render.py` — L3
- `app/ingest/flowchart/vlm.py` — L4
- `app/ingest/flowchart/merge.py` — L5
- `app/ingest/flowchart/chunks.py` — L6
- `tests/test_flowchart_*.py`

**테스트:**
- 좌표 붙이기·모선 병합·라벨 붙이기는 합성 도형 데이터로 단위 테스트
- VLM은 응답을 흉내 내는 가짜 서버로 검증(ID 밖 응답, 깨진 JSON, 시간 초과)
- 샘플 파일 테스트는 기존처럼 `NEOCON_SAMPLE_XLSX`가 없으면 건너뜀

**정확도 평가:** 사용자가 제조공정도 정답 연결 목록을 손으로 한 번 만들면, 단계별(XML만 → +좌표 보강 → +VLM) 정확도·재현율을 수치로 보고한다.

**구현 순서:** L1 좌표 보강부터 시작한다. VLM 없이도 효과가 있고, VLM에 넘길 양이 실제로 몇 개인지 먼저 확인할 수 있다.

## 10. 결정이 필요한 것

1. **D-08 범위 변경:** 분기 자동 해석을 1차로 앞당기는 것으로 변경로그에 기록할지.
2. **검수 전 VLM 연결을 답변에 쓸지:** (a) "확인 필요" 표시를 붙여 사용 (b) 검수가 끝날 때까지 XML·좌표 연결만 사용.
3. **운영 Gemma 상시 기동:** 8111을 자동 시작으로 바꿀지, 적재 시 VLM이 없으면 건너뛰는 상태로 둘지.
4. **실행 방식:** 적재 작업 안에서 바로 호출(시간 초과 시 건너뜀, 구현 단순 — **추천**) 또는 적재 후 별도 보강 작업으로 흐름도 청크만 다시 임베딩.
5. **`vlm_meta_json` 컬럼:** Alembic으로 추가할지, 작업 요약(`tb_ingest_job`)에만 남길지.

## 11. 요구사항 정의서·기능 목록에 반영할 것

- R3-4 비고: "XML + 좌표 보강 + VLM 선별 보강(미해결 연결·OK/NG 분기만)" 추가
- 1차/2차 구분표(`00_요구사항_기준_1차_v0.7.md` 이미지·흐름도 행): 결정 1번에 따라 "흐름도 분기 자동 해석" 위치 조정
