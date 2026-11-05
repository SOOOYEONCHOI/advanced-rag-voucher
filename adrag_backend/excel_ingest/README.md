# excel_ingest — 엑셀 파서 + 파싱 결과 md 출력

설계 문서 「NEOCON_RAG_엑셀적재_요구사항_및_세부설계.md」의 B-1~B-6, C-1~C-3, D-1 판정, D-2(XML 부분), F-1 구현체.

## 구성
| 파일 | 역할 |
|---|---|
| `ooxml.py` | drawing XML 직접 파싱: 그룹 내부·AlternateContent 포함 도형/이미지/연결선, 그룹 내부 실제 위치 환산, 폼 컨트롤, 인쇄영역 |
| `sheet.py` | 셀 그리드(병합·수식 캐시·숨김), 섹션 분할, 헤더 라벨링, 시트 유형 분류, 번호 표(SOP Step/공정단계) 인식 |
| `parser.py` | 공통 IR 생성, 이미지 역할·Step 연결·확대도 보정, 안내문-섹션 연결, 흐름 그래프, 관리대장 개정 메타, VLM 판정, 청크 생성 |
| `export_md.py` | 확인용 md 출력 (instance 하위, 임시폴더 → 원자적 교체, 최근 N회 보관) |
| `cli.py` | 명령행 실행 |

## 실행
```bash
pip install openpyxl lxml
python -m excel_ingest.cli 파일.xlsx --instance-dir <backend>/instance --doc-key NEOCON_C2_제조관리 --model "NEOCON C2"
```

## 출력
```
<backend>/instance/parsed_results/<doc_key>/
  LATEST                       최신 실행 ID
  <run_id>/                    run_id = job_id 권장(동시 업로드 시 충돌 없음)
    00_summary.md              시트별 집계, 이미지 역할·VLM 판정, 검수 필요 목록, 경고
    sheets/NN_시트명.md          시트별 상세
    chunks.md                  벡터DB 적재 청크 미리보기
    ir.json                    공통 IR + 청크
    images/                    추출 이미지(sha256 앞 16자리 파일명)
```

## 백엔드 워커 연동 예
```python
from excel_ingest.parser import parse_workbook
from excel_ingest.export_md import export_markdown

res = parse_workbook(local_path, doc_key=doc_key, model="NEOCON C2")
if settings.PARSE_DEBUG_EXPORT:                      # 개발·검증 환경에서만 켬
    export_markdown(res, instance_dir=app.instance_path,   # Flask면 app.instance_path
                    run_id=str(job_id), source_name=original_filename, keep_last=5)
# 이후 res.ir → Object Storage(ir/{job_id}.json), res.chunks → 임베딩·Vector DB, res.assets → images/
```

## 알려진 한계
- 흐름도: XML로 확정 가능한 연결만 포함. 모선·분기선(끝점 미연결)과 OK/NG 라벨은 VLM 보강 + 검수 필요.
- 흐름도 노드의 공정단계 매핑은 행 위치 기준이라 도형이 표 행과 어긋난 구간(제조공정도 3~8단계)은 부정확할 수 있음.
- 이미지 연결 신뢰도 0.7 미만은 `needs_review`로 표시(검수 UI 대상).
- VLM은 판정(`vlm_status`)만 하고 실제 호출은 하지 않음.
