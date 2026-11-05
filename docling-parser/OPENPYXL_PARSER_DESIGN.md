# OpenPyXL 기반 Excel 파서 상세 설계

## 1. 목적과 범위

현재 `docling-parser`는 PDF, Word, PowerPoint, Excel 및 이미지 문서를 Docling으로 변환한다. Excel 문서는 Docling 변환 품질이 충분하지 않으므로 OOXML Excel 형식만 `openpyxl` 기반 전용 파서로 분기한다.

이 설계는 다음을 전제로 한다.

- 대상 확장자: `.xlsx`, `.xlsm`, `.xltx`, `.xltm`
- `.xls`, `.xlsb`, `.ods`는 제외한다.
- 기존 `/api/parse` 비동기 API 및 `pages[]` 응답 계약을 유지한다.
- Excel의 페이지는 워크시트로 정의한다.
- 원본 파일은 읽기만 하고 수정하거나 저장하지 않는다.
- 매크로, 외부 링크, Power Query 및 피벗 테이블을 실행하거나 갱신하지 않는다.
- 화면을 완전히 재현하는 것이 아니라 RAG 검색에 적합한 Markdown을 생성한다.

## 2. 목표 아키텍처

현재 흐름은 다음과 같다.

```text
POST /api/parse
  → DocumentParser.parse()
      → Docling DocumentConverter
          → Markdown 변환
```

변경 후에는 확장자에 따라 파서를 분기한다.

```text
POST /api/parse
  → DocumentParser.parse()
      ├─ Excel 확장자
      │    → OpenpyxlExcelParser.parse()
      │         → 시트 탐색
      │         → 실제 데이터 영역 계산
      │         → 병합 셀 및 값 정규화
      │         → 표 영역 분리
      │         → Markdown 생성
      └─ 기타 확장자
           → 기존 Docling 처리
```

권장 파일 구조는 다음과 같다.

```text
docling-parser/
├─ app/
│  └─ services/
│     ├─ parser.py
│     └─ excel_parser.py
├─ tests/
│  ├─ fixtures/excel/
│  └─ test_excel_parser.py
└─ requirements.txt
```

초기에는 `excel_parser.py` 한 파일로 시작한다. 실제 구현이 커질 때만 모델이나 Markdown renderer를 분리한다.

## 3. 외부 응답 계약

기존 백엔드와의 호환성을 위해 다음 구조를 유지한다.

```json
{
  "format": "md",
  "pages": [
    {
      "page_no": 1,
      "sheet_name": "요구사항정의",
      "sheet_index": 1,
      "markdown": "# Sheet: 요구사항정의\n\n| ID | 요구사항명 |\n| --- | --- |",
      "metadata": {
        "sheet_state": "visible",
        "source_range": "A1:H250",
        "table_count": 2,
        "truncated": false,
        "warnings": []
      }
    }
  ],
  "num_pages": 1,
  "metadata": {
    "file_path": "/app/data/uploads/document.xlsx",
    "num_pages": 1,
    "is_scanned": false,
    "parser": "openpyxl",
    "source_type": "spreadsheet"
  }
}
```

필드의 의미는 다음과 같다.

| 필드 | Excel에서의 의미 |
|---|---|
| `page_no` | 1부터 시작하는 출력 시트 순번 |
| `sheet_name` | 원본 워크시트명 |
| `sheet_index` | 원본 워크북의 시트 순번 |
| `markdown` | 해당 시트의 Markdown |
| `num_pages` | 출력에 포함된 시트 수 |
| `is_scanned` | 항상 `false` |
| `parser` | `openpyxl` |

기존 소비자는 `page_no`와 `markdown`만 사용하므로 페이지 수준 추가 필드는 하위 호환성을 해치지 않는다.

## 4. 내부 데이터 모델

파싱 결과를 즉시 문자열로 연결하지 않고 최소한의 중간 모델을 사용한다.

```python
@dataclass
class SheetBlock:
    min_row: int
    max_row: int
    min_col: int
    max_col: int
    rows: list[list[str]]
    header_row_count: int = 0


@dataclass
class ParsedSheet:
    index: int
    name: str
    state: str
    source_range: str | None
    blocks: list[SheetBlock]
    warnings: list[dict[str, Any]]
    truncated: bool = False
```

셀 단위 좌표, 수식, 링크 등이 JSON 출력에 필요해지는 경우에만 별도 `ExcelCell` 모델을 추가한다.

## 5. 단계별 구현 계획

### Phase 1. Excel 라우팅 분리

#### 구현 사항

`DocumentParser.parse()`가 확장자를 확인한 후 Excel 문서는 Docling에 전달하지 않는다.

```python
EXCEL_EXTENSIONS = {
    ".xlsx",
    ".xlsm",
    ".xltx",
    ".xltm",
}
```

개념적인 라우팅은 다음과 같다.

```python
async def parse(self, file_path: str, output_format: str = "md"):
    ext = Path(file_path).suffix.lower()

    if ext in EXCEL_EXTENSIONS:
        async with self._excel_semaphore:
            return await asyncio.to_thread(
                self.excel_parser.parse,
                file_path,
                output_format,
            )

    return await self._parse_with_docling(file_path, output_format)
```

Excel 파싱은 동기 파일 I/O와 CPU 작업을 포함하므로 `asyncio.to_thread()`로 실행한다. 기존 GPU semaphore는 Docling에만 적용하고 Excel에는 별도 semaphore를 둔다. 초기 동시 처리 수는 `2`로 시작하고 메모리 측정 후 조정한다.

#### 의존성

```text
openpyxl==3.1.5
defusedxml==0.7.1
```

배포 환경에서 검증한 patch 버전으로 고정한다.

#### 검증 항목

- Excel 입력 시 Docling converter가 호출되지 않는다.
- PDF, DOCX, PPTX의 기존 동작이 유지된다.
- 지원하지 않는 `.xls`는 400 응답을 반환한다.
- 기존 API 응답 구조가 유지된다.

#### 완료 기준

- 네 가지 Excel 확장자가 `OpenpyxlExcelParser`로 진입한다.
- 비 Excel 문서 동작에는 변경이 없다.

### Phase 2. 기본 시트 및 셀 추출

#### 워크북 로딩

수식 결과와 수식 문자열을 모두 얻기 위해 두 워크북을 연다.

```python
value_workbook = openpyxl.load_workbook(
    filename=file_path,
    read_only=False,
    data_only=True,
    keep_links=False,
)

formula_workbook = openpyxl.load_workbook(
    filename=file_path,
    read_only=False,
    data_only=False,
    keep_links=False,
)
```

`openpyxl`은 수식을 계산하지 않는다. `data_only=True`는 Excel이 마지막으로 저장한 cached value를 읽는다. 두 워크북은 반드시 `finally`에서 닫는다.

#### 시트 처리 정책

- worksheet만 처리하고 chart sheet는 제외한다.
- `sheet_state == "visible"`인 시트를 기본 처리한다.
- hidden/veryHidden 시트는 제외하되 문서 metadata에 기록한다.
- 완전히 빈 시트는 결과에서 제외한다.
- 원본 시트 순서를 유지한다.

#### 셀 값 선택 정책

```text
1. data_only=True 워크북의 cached value
2. cached value가 없고 원본 셀이 수식이면 수식 문자열
3. 일반 원본 값
4. 모두 없으면 빈 값
```

수식 결과가 재계산된 값이 아니라 마지막 저장 시점의 값임을 metadata로 표현한다.

```json
{
  "formula_policy": "cached_value_then_formula",
  "formula_recalculated": false
}
```

#### 검증 항목

- 여러 시트의 순서가 보존된다.
- 빈 시트와 숨김 시트가 제외된다.
- 문자열, 숫자, Boolean 값을 추출한다.
- cached value가 있으면 결과값을 사용한다.
- cached value가 없으면 수식 문자열을 보존한다.
- 성공과 실패 양쪽에서 workbook을 닫는다.

#### 완료 기준

- 기본 셀 값이 누락되지 않고 시트별 텍스트가 생성된다.
- 수식 셀이 이유 없이 빈 문자열로 사라지지 않는다.

### Phase 3. 실제 데이터 범위 계산

`max_row`, `max_column`은 서식만 적용된 셀 때문에 과도하게 커질 수 있으므로 최종 데이터 경계로 그대로 사용하지 않는다.

#### 유효 셀 정의

다음 중 하나를 만족하면 유효 셀로 본다.

- 값이 `None`이 아니다.
- 수식이 존재한다.
- 값이 있는 병합 영역의 좌상단 셀이다.

공백 문자열은 값이 없는 것으로 처리한다.

```python
def has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True
```

유효 셀을 기준으로 `min_row`, `max_row`, `min_col`, `max_col`을 계산하고 A1 notation을 metadata에 기록한다.

```text
A3:H250
```

#### 자원 제한

초기 기본값은 다음과 같이 둔다.

```text
최대 시트 수: 100
시트당 최대 검사 행: 100,000
시트당 최대 검사 열: 500
시트당 최대 검사 셀: 2,000,000
```

한도 초과 시 전체 문서를 조용히 자르지 않는다. 추출 가능한 범위까지 처리하고 `truncated=true`와 warning을 반환한다.

#### 검증 항목

- 아래쪽에 서식만 적용된 대형 시트
- 중간이 비어 있는 sparse sheet
- 값은 없고 수식만 있는 셀
- 병합 제목만 있는 시트
- 최대 셀 제한을 초과한 시트

#### 완료 기준

- 서식 때문에 생성된 거대한 빈 영역을 출력하지 않는다.
- 실제 데이터 좌표와 truncation 여부가 metadata에 기록된다.

### Phase 4. 셀 표시값 정규화

#### 문자열

- `CRLF`, `CR`을 `LF`로 통일한다.
- 앞뒤 공백을 제거한다.
- 표 내부 줄바꿈은 `<br>`로 변환한다.
- `\`와 `|`를 Markdown 규칙에 맞게 escape한다.

#### 숫자

- 정수로 표현 가능한 float의 `.0`을 제거한다.
- 일반 실수의 정밀도를 임의로 과도하게 낮추지 않는다.
- 퍼센트 number format은 백분율로 출력한다.
- 첫 구현에서는 Excel 표시 형식 전체를 재현하지 않고 일반 숫자와 퍼센트만 지원한다.

#### 날짜와 시간

```text
date     → YYYY-MM-DD
datetime → YYYY-MM-DD HH:mm:ss
time     → HH:mm:ss
```

timezone이 없는 Excel datetime에 임의 timezone을 붙이지 않는다.

#### 오류 셀

`#N/A`, `#VALUE!`, `#REF!`, `#DIV/0!` 등의 오류 값을 그대로 보존한다.

#### 하이퍼링크

셀 값과 hyperlink가 있으면 Markdown link로 생성한다.

```markdown
[OpenAI](https://openai.com)
```

외부 URL에 접근하지 않고 문자열만 보존한다.

#### 길이 제한

셀 하나의 최대 출력 길이는 우선 10,000자로 제한한다. 초과 시 `[truncated]`를 표시하고 시트 warning에 셀 좌표를 기록한다.

#### 완료 기준

- 셀 값 때문에 Markdown table 문법이 깨지지 않는다.
- 날짜와 퍼센트의 의미가 보존된다.
- 잘린 값은 사용자에게 명확히 표시된다.

### Phase 5. 병합 셀 처리

병합 셀 값은 좌상단 셀에만 존재하므로 Markdown 생성 과정에서 논리값을 전파한다. worksheet 자체는 수정하지 않는다.

#### 기본 정책

- 병합 영역의 좌상단 값을 범위 내 모든 셀의 논리값으로 사용한다.
- 빈 병합 셀은 빈 값으로 유지한다.
- 병합 범위와 anchor 좌표를 내부적으로 보존한다.
- 헤더 영역에서는 후속 단계에서 상위·하위 헤더를 결합한다.

예를 들어 `B2:D2`가 `2026년`으로 병합되어 있으면 세 열 모두 `2026년`이라는 상위 헤더 문맥을 갖도록 한다.

#### 검증 항목

- 가로 병합
- 세로 병합
- 가로·세로 병합 혼합
- 실제 데이터 경계에 걸친 병합
- 좌상단 값이 비어 있는 병합

#### 완료 기준

- 병합된 제목 및 분류 텍스트가 사라지지 않는다.
- 병합 영역 때문에 표의 열 정렬이 어긋나지 않는다.

### Phase 6. 표 블록 분리

복잡한 표 탐지 알고리즘을 처음부터 구현하지 않고 실제 fixture를 기준으로 확장한다.

#### 6.1 빈 행 기준 세로 분리

실제 데이터 범위 내에서 완전히 빈 행을 block 경계로 사용한다. 연속 빈 행은 하나의 경계로 처리한다.

```text
값이 있는 행
값이 있는 행
빈 행          ← block 경계
값이 있는 행
```

1행 1열처럼 작은 block도 제목이나 설명일 수 있으므로 버리지 않는다.

#### 6.2 블록별 좌우 빈 열 제거

각 block마다 값이 존재하는 최소·최대 열을 다시 계산한다.

#### 6.3 가로 다중 표 분리

실제 문서에서 가로 다중 표 사례가 확인되면 추가한다. 기본적으로 모든 행에서 연속 두 열 이상 비어 있을 때 가로 경계로 간주한다.

#### 6.4 정식 Excel Table 우선 처리

`sheet.tables`에 정식 Excel Table이 있으면 해당 범위를 우선 block으로 채택한다. Table 영역 밖의 데이터도 일반 block 탐색으로 처리하여 누락하지 않는다.

#### 검증 항목

- 단일 표
- 제목과 표 사이에 빈 행이 있는 문서
- 세로 및 가로 다중 표
- 설명 문단과 표가 혼합된 문서
- 표 내부에 의도적인 빈 행이 있는 문서
- 정식 Excel Table 객체

#### 완료 기준

- 서로 다른 표가 하나의 거대한 표로 합쳐지는 사례가 감소한다.
- 모든 유효 셀이 어느 block엔가 포함된다.

### Phase 7. 헤더 판정 및 Markdown 생성

#### 헤더 판정

헤더 후보의 기본 조건은 다음과 같다.

- block이 두 행 이상이다.
- 첫 행의 비어 있지 않은 셀 비율이 충분하다.
- 첫 행이 대부분 문자열이다.
- 아래 행에는 숫자나 날짜 등 다른 타입이 존재한다.
- 굵기, 배경색, 정렬 및 병합 여부는 보조 신호로만 사용한다.

확신이 없으면 첫 행을 헤더로 간주하지 않는다. 첫 데이터 행이 잘못된 헤더 처리로 사라져서는 안 된다.

#### 다단 헤더

상단 2~3행이 헤더이고 병합 셀이 있으면 열별 상위·하위 값을 결합한다.

```text
2026년 | 2026년
1분기  | 2분기
```

출력:

```markdown
| 2026년 / 1분기 | 2026년 / 2분기 |
| --- | --- |
```

같은 텍스트가 연속되면 중복을 제거한다.

#### Markdown 구조

```markdown
# Sheet: 요구사항정의

## Table 1

| 요구사항 ID | 구분 | 요구사항명 | 내용 |
| --- | --- | --- | --- |
| SFR-001 | 기능 | 문서 파싱 | ... |
```

좌표 범위는 기본적으로 본문이 아닌 metadata에 기록한다. 한 행 또는 한 열짜리 설명 영역은 억지로 표로 만들지 않고 일반 텍스트 section으로 출력한다.

#### 완료 기준

- 첫 데이터 행이 누락되지 않는다.
- 다단 헤더의 상위 의미가 최종 열 이름에 포함된다.
- 모든 block이 유효한 Markdown을 생성한다.

### Phase 8. 대형 표 분할

시트 하나는 하나의 `pages[]` 항목으로 유지하되 내부 Markdown table은 다음 기준으로 나눈다.

```text
한 table part당 최대 100행
또는 최대 30,000자
먼저 도달한 조건 적용
```

각 part에 헤더를 반복한다.

```markdown
## Table 1 — Part 1

| ID | 제목 | 상태 |
| --- | --- | --- |

## Table 1 — Part 2

| ID | 제목 | 상태 |
| --- | --- | --- |
```

#### 완료 기준

- 대형 표도 유효한 Markdown을 생성한다.
- 각 part에 헤더가 존재한다.
- 원본 행이 누락되거나 중복되지 않는다.

### Phase 9. JSON 출력

Excel JSON은 Docling 문서 스키마를 모방하지 않고 독립적인 명시적 구조를 사용한다.

```json
{
  "format": "json",
  "content": {
    "schema_name": "OpenpyxlWorkbook",
    "version": "1.0",
    "sheets": [
      {
        "sheet_index": 1,
        "sheet_name": "요구사항정의",
        "sheet_state": "visible",
        "source_range": "A1:H250",
        "blocks": [
          {
            "block_index": 1,
            "type": "table",
            "source_range": "A3:H57",
            "headers": ["요구사항 ID", "구분", "요구사항명"],
            "rows": [
              ["SFR-001", "기능", "문서 파싱"]
            ]
          }
        ]
      }
    ]
  },
  "metadata": {
    "file_path": "...",
    "num_pages": 1,
    "parser": "openpyxl",
    "is_scanned": false
  }
}
```

JSON에는 시트, block, 헤더, 셀 표시값, 필요한 수식 및 warning만 포함한다. font, border, fill 등 전체 스타일 정보는 결과 크기에 비해 RAG 활용도가 낮으므로 제외한다.

## 6. 클래스 인터페이스

권장 최소 인터페이스는 다음과 같다.

```python
class OpenpyxlExcelParser:
    SUPPORTED_EXTENSIONS = {
        ".xlsx",
        ".xlsm",
        ".xltx",
        ".xltm",
    }

    def parse(
        self,
        file_path: str,
        output_format: str = "md",
    ) -> dict[str, Any]:
        ...
```

내부 메서드는 테스트 가능한 책임 단위로만 분리한다.

```python
def _load_workbooks(self, file_path): ...
def _parse_sheet(self, value_sheet, formula_sheet, sheet_index): ...
def _find_used_range(self, value_sheet, formula_sheet): ...
def _build_merged_cell_map(self, sheet): ...
def _split_blocks(self, sheet_data): ...
def _normalize_cell_value(self, value_cell, formula_cell): ...
def _render_sheet_markdown(self, parsed_sheet): ...
def _build_json_result(self, parsed_sheets, file_path): ...
```

날짜, 숫자, 문자열 처리 등을 처음부터 별도 클래스로 만들지 않는다.

## 7. 초기 설정값

첫 버전에서는 환경변수 대신 모듈 상수로 관리한다.

```python
MAX_SHEETS = 100
MAX_ROWS_PER_SHEET = 100_000
MAX_COLUMNS_PER_SHEET = 500
MAX_CELLS_PER_SHEET = 2_000_000
MAX_CELL_TEXT_LENGTH = 10_000
MAX_MARKDOWN_TABLE_ROWS = 100
MAX_MARKDOWN_TABLE_CHARS = 30_000
INCLUDE_HIDDEN_SHEETS = False
EMPTY_COLUMNS_FOR_BLOCK_SPLIT = 2
```

운영 중 실제 변경 요구가 확인된 설정만 환경변수로 승격한다.

## 8. 오류 및 warning 정책

### 전체 작업 실패

다음 상황은 job을 `failed` 처리한다.

- 손상되어 열 수 없는 workbook
- 암호화된 workbook
- 확장자와 실제 파일 형식 불일치
- openpyxl 파싱 예외
- 지원하지 않는 Excel 형식
- 모든 시트를 처리할 수 없는 치명적 오류

API 오류에는 내부 stack trace나 전체 서버 경로를 노출하지 않고 상세 원인은 서버 로그에 기록한다.

### 부분 성공

다음은 결과를 반환하면서 warning을 기록한다.

- 숨김 시트 제외
- 빈 시트 제외
- 최대 행, 열 또는 셀 제한 도달
- 셀 텍스트 잘림
- cached value가 없어 수식 문자열 사용
- 지원하지 않는 표시 형식
- 이미지 또는 차트가 존재하지만 추출하지 않음

```json
{
  "code": "FORMULA_CACHE_MISSING",
  "sheet": "계산",
  "cell": "D15",
  "message": "Formula text was used because no cached result exists."
}
```

warning은 유형별 최대 개수를 제한하고 전체 발생 횟수는 별도 count로 기록한다.

## 9. 차트, 이미지 및 피벗 처리

초기 구현에서는 셀 데이터 추출을 우선한다.

- 차트는 렌더링하지 않는다.
- 차트 제목, 유형 및 원본 참조 범위는 후속 단계에서 선택적으로 추출한다.
- 이미지 OCR은 수행하지 않는다.
- 이미지 존재 여부와 anchor 위치는 후속 metadata로 추가할 수 있다.
- 피벗 결과가 셀에 저장되어 있으면 일반 셀 값으로 읽는다.
- 피벗 테이블 자체를 재계산하지 않는다.
- 외부 데이터 연결과 Power Query를 갱신하지 않는다.
- VBA 매크로를 실행하지 않는다.

이 기능들은 기본 셀 및 표 추출 품질이 검증된 후 별도 요구사항으로 진행한다.

## 10. 보안 및 자원 제한

`.xlsx`는 ZIP 기반 OOXML이므로 일반 파일 크기 외에 압축 컨테이너 검증이 필요하다.

### 업로드 단계

- 원본 파일 크기 제한
- ZIP magic number 확인
- ZIP entry 개수 제한
- 전체 비압축 크기 제한
- 단일 entry 크기 제한
- 비정상 압축률 제한
- 암호화된 ZIP entry 거절
- 확장자와 실제 container 형식 확인

초기 검토값은 다음과 같다.

```text
업로드 파일: 100MB
ZIP entry: 10,000개
전체 비압축 크기: 1GB
단일 entry: 200MB
최대 압축률: 100배
```

실제 운영 문서의 크기 분포를 확인한 후 확정한다.

### 처리 단계

- 매크로 실행 금지
- 외부 링크 접근 금지
- workbook 저장 금지
- 처리 timeout 적용
- Excel 동시 처리 개수 제한
- 셀, 행, 열 및 결과 문자열 크기 제한
- warning 개수 제한

`defusedxml`은 XML 공격 방어를 위해 사용하지만 ZIP bomb 검증은 별도 구현해야 한다.

## 11. 백엔드 연계 변경

현재 `adrag_backend/app/parsers/loaders/docling_loader.py`는 PPTX 외 형식의 Markdown heading을 제거한다.

현재 개념:

```python
PRESERVE_HEADERS_FOR = {"pptx"}
```

권장 변경:

```python
PRESERVE_HEADERS_FOR = {
    "pptx",
    "xlsx",
    "xlsm",
    "xltx",
    "xltm",
}
```

이를 적용하지 않으면 `# Sheet`와 `## Table` 문맥이 제거된다.

또한 현재 구성에는 지원 확장자 불일치가 있다.

```text
docling-parser API: .xlsx .xlsm .xltx .xltm
adrag_backend DoclingApiLoader: xlsx만 명시
```

네 확장자를 모두 지원하려면 백엔드와 프론트엔드의 업로드 허용 확장자도 동일하게 맞춘다.

## 12. 테스트 계획

### 단위 테스트

라우팅:

```text
test_xlsx_uses_openpyxl_parser
test_xlsm_uses_openpyxl_parser
test_pdf_still_uses_docling
test_unsupported_xls_is_rejected
```

셀 값:

```text
test_extracts_string_number_boolean
test_preserves_formula_cached_value
test_falls_back_to_formula_text
test_formats_date_and_datetime
test_formats_percentage
test_escapes_markdown_characters
test_preserves_hyperlink
```

시트:

```text
test_preserves_sheet_order
test_excludes_hidden_sheet
test_excludes_empty_sheet
test_uses_sheet_name_as_heading
```

범위와 병합:

```text
test_trims_formatting_only_rows
test_detects_sparse_used_range
test_propagates_horizontal_merged_header
test_propagates_vertical_merged_value
test_combines_multi_row_headers
```

표 분리:

```text
test_splits_blocks_on_empty_rows
test_trims_empty_columns_per_block
test_splits_side_by_side_tables
test_preserves_text_block
```

크기 제한:

```text
test_splits_large_table
test_repeats_header_for_each_part
test_truncates_oversized_cell
test_reports_sheet_limit_warning
```

### 통합 테스트

FastAPI endpoint를 통해 전체 흐름을 검증한다.

```text
POST /api/parse
→ job polling
→ GET /api/job/{id}/result
→ pages[] Markdown 검증
→ 임시 업로드 파일 삭제 검증
```

### Fixture 목록

```text
simple_table.xlsx
multiple_sheets.xlsx
merged_headers.xlsx
multiple_tables.xlsx
formulas_cached.xlsx
formulas_without_cache.xlsx
hidden_sheets.xlsx
dates_and_formats.xlsx
hyperlinks.xlsx
large_sparse_sheet.xlsx
chart_and_image.xlsx
macro_workbook.xlsm
template.xltx
```

수식 cached value는 openpyxl만으로 생성하기 어려우므로 해당 fixture는 Excel 또는 LibreOffice에서 계산 후 저장한 정적 파일을 사용한다.

## 13. 품질 검증 기준

### 필수 기준

- 원본 유효 텍스트 셀 보존율 99% 이상
- 시트 누락 0건
- 원본 데이터 행 누락 0건
- 병합 헤더 텍스트 누락 0건
- Markdown 문법 파손 0건
- 일반 10MB workbook의 처리 시간 목표 충족
- 최대 메모리 사용량 측정 및 허용 범위 충족
- 기존 비 Excel parser 테스트 전부 통과

### RAG 품질 기준

동일한 문서를 기존 Docling과 신규 openpyxl 경로로 각각 수집하고 다음을 비교한다.

- Recall@k
- Hit Rate@k
- 정답 행을 포함한 chunk의 검색 순위
- 표 헤더와 데이터 행이 같은 chunk에 존재하는 비율
- 생성 token 수
- 파싱 시간

평가 질문은 ID 조회, 특정 행의 상태, 분기별 수치, 특정 시트의 담당 부서 및 병합 헤더 아래 값처럼 표 구조가 필요한 항목을 포함한다.

## 14. 실행 순서 요약

### 1차: 동작 가능한 최소 버전

1. `openpyxl`, `defusedxml` 의존성 추가
2. `excel_parser.py` 생성
3. Excel 확장자 라우팅
4. visible 시트별 기본 값 추출
5. 시트별 Markdown 생성
6. 기존 `pages[]` 응답 유지
7. 라우팅 및 API 테스트

성공 기준: Docling을 호출하지 않고 단순 XLSX를 시트별 Markdown으로 반환한다.

### 2차: 데이터 정확도

1. 실제 데이터 범위 계산
2. 수식 cached value 및 fallback 처리
3. 날짜, 퍼센트, 하이퍼링크 정규화
4. Markdown escape
5. 빈 시트와 숨김 시트 처리
6. 자원 제한과 warning 추가

성공 기준: 값 누락과 불필요한 빈 영역 없이 안정적인 Markdown을 생성한다.

### 3차: 표 구조 품질

1. 병합 셀 논리값 전파
2. 빈 행 기준 block 분리
3. block별 좌우 빈 열 제거
4. 헤더 판정
5. 다단 헤더 결합
6. 텍스트 block과 table block 구분

성공 기준: 복잡한 업무 Excel에서도 제목, 헤더 및 표 경계가 검색 가능한 형태로 보존된다.

### 4차: 대용량 및 운영 안정화

1. 대형 표 분할
2. 셀, 행, 열 및 ZIP 제한
3. Excel 전용 동시 처리 제한
4. 처리 시간과 메모리 측정
5. warning 및 관측 정보 추가
6. 악성 파일과 손상 파일 테스트

성공 기준: 대용량 또는 비정상 파일이 전체 파서 서비스를 고갈시키지 않는다.

### 5차: 백엔드 및 검색 품질 연계

1. Excel 시트 및 table Markdown heading 보존
2. `.xlsm`, `.xltx`, `.xltm` 허용 목록 정합화
3. 시트명과 셀 범위 metadata 전달
4. Docling 대비 RAG 검색 평가
5. 실제 문서에 맞춰 병합 및 표 분리 휴리스틱 조정

성공 기준: 신규 파서가 기존 Docling보다 Excel 질의 검색 정확도와 처리 성능에서 우수하다.

## 15. 구현 원칙

- Phase 1에서 복잡한 표 추론을 한꺼번에 구현하지 않는다.
- 먼저 API 호환성과 셀 값 보존을 검증한다.
- 실제 실패 fixture가 생긴 경우에만 병합 헤더 및 다중 표 휴리스틱을 확장한다.
- 모든 변경 라인은 Excel 파서 분기와 직접 관련되어야 한다.
- 기존 Docling의 PDF, Word, PowerPoint 및 이미지 동작은 변경하지 않는다.
- 부분 추출과 데이터 잘림을 조용히 숨기지 않고 metadata와 warning으로 노출한다.
