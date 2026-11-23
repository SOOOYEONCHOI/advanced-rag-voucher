from __future__ import annotations

import copy
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.styles import Font


BLUE = "0070C0"


@dataclass
class Column:
    values: list[Any]
    styles: list[Any] | None = None


@dataclass
class Table:
    name: str
    logical: str
    area: str
    introduced: str
    description: str
    pk: str
    requirements: str
    columns: list[Column] = field(default_factory=list)
    metadata: list[list[Any]] = field(default_factory=list)
    start_row: int = 0


def copy_style(source, target) -> None:
    target._style = copy.copy(source._style)
    target.number_format = source.number_format
    target.alignment = copy.copy(source.alignment)
    target.protection = copy.copy(source.protection)


def row_style(sheet, row: int, max_col: int) -> tuple[list[Any], float | None]:
    return ([copy.copy(sheet.cell(row, col)._style) for col in range(1, max_col + 1)], sheet.row_dimensions[row].height)


def apply_row_style(sheet, row: int, snapshot: tuple[list[Any], float | None]) -> None:
    styles, height = snapshot
    for col, style in enumerate(styles, 1):
        sheet.cell(row, col)._style = copy.copy(style)
    if height is not None:
        sheet.row_dimensions[row].height = height


def set_blue(cell) -> None:
    cell.font = Font(
        name=cell.font.name,
        size=cell.font.sz,
        bold=cell.font.bold,
        italic=cell.font.italic,
        vertAlign=cell.font.vertAlign,
        underline=cell.font.underline,
        strike=cell.font.strike,
        color=BLUE,
    )


def parse_tables(sheet) -> list[Table]:
    header_rows = [row for row in range(1, sheet.max_row + 1) if sheet.cell(row, 1).value == "테이블명"]
    tables: list[Table] = []
    for index, start in enumerate(header_rows):
        end = header_rows[index + 1] - 1 if index + 1 < len(header_rows) else sheet.max_row
        title = str(sheet.cell(start, 3).value)
        name, logical = title.split("  (", 1)
        logical = logical[:-1] if logical.endswith(")") else logical
        introduced = str(sheet.cell(start, 10).value or "").replace("도입 Alembic ", "")
        requirements = str(sheet.cell(start + 1, 10).value or "").replace("요구사항: ", "")
        table = Table(
            name=name,
            logical=logical,
            area=str(sheet.cell(start, 9).value or ""),
            introduced=introduced,
            description=str(sheet.cell(start + 1, 3).value or ""),
            pk=str(sheet.cell(start + 1, 9).value or ""),
            requirements=requirements,
        )
        row = start + 3
        while row <= end and isinstance(sheet.cell(row, 1).value, int):
            values = [sheet.cell(row, col).value for col in range(1, 11)]
            styles = [copy.copy(sheet.cell(row, col)._style) for col in range(1, 11)]
            table.columns.append(Column(values, styles))
            row += 1
        while row <= end:
            if sheet.cell(row, 1).value is not None:
                table.metadata.append([sheet.cell(row, 1).value, sheet.cell(row, 3).value])
            row += 1
        tables.append(table)
    return tables


def col(name, logical, data_type, pk=None, fk=None, null="Y", default=None, description="") -> Column:
    return Column([None, name, logical, data_type, None, pk, fk, null, default, description])


def metadata_set(table: Table, label: str, value: str) -> None:
    for item in table.metadata:
        if item[0] == label:
            item[1] = value
            return
    table.metadata.append([label, value])


def get_table(tables: list[Table], name: str) -> Table:
    return next(table for table in tables if table.name == name)


def update_tables(tables: list[Table]) -> None:
    documents = get_table(tables, "tb_documents")
    documents.columns.extend([
        col("activation_revision", "적용 순번", "BIGINT", null="N", default="1", description="문서별 버전 적용 순번(1 이상, 복원·교체 때 증가)"),
        col("pending_job_id", "진행 중 변경 작업 ID", "TEXT", fk="tb_ingest_jobs.job_id (SET NULL)", description="최신본 변경·복원 공통 점유 작업(NULL=진행 중 작업 없음)"),
    ])
    documents.description = "업로드된 문서 1건의 현재 메타데이터·적용 버전과 처리 상태"
    metadata_set(documents, "CHECK", "6건 — 「CHECK 제약」 시트")
    metadata_set(documents, "사용 코드", "document_repository, ingest_record_repository, document_version_restore, ingest_service, routes/ingest, stats_repository")
    metadata_set(documents, "비고", "삭제는 논리 삭제. activation_revision은 적용 이력의 낙관적 동시성 기준, pending_job_id는 최신본 변경·복원 공통 점유 표식")

    versions = get_table(tables, "tb_document_versions")
    versions.columns.extend([
        col("embedding_profile_id", "임베딩 프로필 ID", "BIGINT", fk="tb_embedding_profiles.embedding_profile_id (NO ACTION)", description="이 버전을 색인한 임베딩 프로필"),
        col("vector_storage_state", "벡터 보관 상태", "TEXT", null="N", default="'unknown'", description="벡터 보관 상태 · 값: unknown, available, missing, archived"),
        col("vector_manifest_json", "벡터 매니페스트", "JSONB", description="Qdrant 포인트 식별·검증용 매니페스트 객체"),
        col("document_snapshot_json", "문서 메타 스냅샷", "JSONB", description="해당 버전 적용 시점의 문서 메타데이터 객체"),
        col("restore_verified_at", "복원 검증 시각", "TIMESTAMPTZ", description="복원 가능성·벡터 상태를 마지막으로 검증한 시각"),
    ])
    versions.description = "업로드 파일 1개 = 1행. active 버전 검색과 과거 버전 복원에 필요한 파일·벡터·문서 스냅샷 보존"
    metadata_set(versions, "CHECK", "10건 — 「CHECK 제약」 시트")
    metadata_set(versions, "사용 코드", "ingest_record_repository, document_version_restore, embedding_profile, routes/ingest, ingest_pipeline.IndexStep, version_visibility")
    metadata_set(versions, "비고", "0006: 임베딩 프로필·벡터 상태/매니페스트·문서 스냅샷을 기록. 복원은 현재 프로필과 일치하고 vector_storage_state='available'인 버전만 허용")
    versions.introduced = "0003 (신규) · 0005·0006 보강"

    jobs = get_table(tables, "tb_ingest_jobs")
    jobs.columns.extend([
        col("operation_type", "작업 유형", "TEXT", null="N", default="'ingest'", description="작업 유형 · 값: ingest, restore"),
        col("document_id", "대상 문서 ID", "TEXT", description="최신본 변경·복원 대상 문서 ID(FK 없음)"),
        col("idempotency_key", "멱등 키", "TEXT", description="요청자·작업 유형별 중복 접수 방지 키"),
        col("request_fingerprint", "요청 지문", "TEXT", description="같은 멱등 키의 요청 내용 일치 검증용 지문"),
    ])
    jobs.description = "업로드·최신본 변경·이전 버전 복원 작업의 상태와 요청/결과 저장"
    metadata_set(jobs, "인덱스", "idx_ingest_jobs_active_created / idx_ingest_jobs_created_by / idx_ingest_jobs_document (document_id WHERE document_id IS NOT NULL) / uq_ingest_jobs_idempotency (created_by, operation_type, idempotency_key WHERE idempotency_key IS NOT NULL) UNIQUE")
    metadata_set(jobs, "CHECK", "5건 — 「CHECK 제약」 시트")
    metadata_set(jobs, "사용 코드", "ingest_job_repository, services/ingest_jobs, document_version_restore, routes/ingest")
    metadata_set(jobs, "비고", "operation_type='restore' 작업은 validate→snapshot→activate→completed 단계 사용. idempotency_key와 request_fingerprint로 안전한 재요청 처리")

    events = get_table(tables, "tb_document_events")
    event_col = next(column for column in events.columns if column.values[1] == "event_type")
    event_col.values[9] = "이벤트 유형 · 값: upload, parse, embed, delete, reindex, fail, update, restore"
    metadata_set(events, "사용 코드", "document_repository.record_event, document_repository.update_product_model, document_version_restore")
    metadata_set(events, "비고", "기록 이벤트: delete, update, restore 등. document_id FK 없음(문서 삭제 후에도 이력 보존)")

    logs = get_table(tables, "tb_query_logs")
    logs.columns.extend([
        col("feedback_reasons", "피드백 사유 코드 배열", "JSONB", description="평가별 선택 사유 코드 배열(최대 10개, 평가 변경·취소 시 함께 갱신)"),
        col("feedback_comment", "피드백 자유 의견", "TEXT", description="피드백 자유 의견(최대 1000자)"),
    ])
    logs.description = "질의 1건의 질문·답변·근거·성능과 평가(👍/👎, 사유·의견)"
    metadata_set(logs, "CHECK", "8건 — 「CHECK 제약」 시트")
    metadata_set(logs, "사용 코드", "query_log_repository, query_recorder, stats_repository, routes/query, routes/admin_stats")
    metadata_set(logs, "비고", "feedback_reasons 허용 코드는 routes/query.py FEEDBACK_REASONS에서 평가별 검증. feedback_comment는 1000자 이하")

    embedding = Table(
        "tb_embedding_profiles", "임베딩 프로필", "B. 대화 주제·문서·적재", "0006 (신규)",
        "임베딩 모델·차원·dense/sparse 구성의 정규화된 정의와 해시. 같은 프로필의 버전만 복원 허용",
        "embedding_profile_id", "R1-5, SC-06",
        [
            col("embedding_profile_id", "임베딩 프로필 ID", "BIGINT", pk="PK", null="N", default="IDENTITY", description="PK"),
            col("profile_hash", "프로필 해시", "TEXT", null="N", description="정규화된 definition_json의 SHA-256 해시(유일)"),
            col("definition_json", "프로필 정의", "JSONB", null="N", description="provider·model·dimension·dense/sparse 설정 객체"),
            col("is_supported", "현재 지원 여부", "BOOLEAN", null="N", default="false", description="현재 코드가 복원에 사용할 수 있는 프로필 여부"),
            col("created_at", "생성 시각", "TIMESTAMPTZ", null="N", default="now()", description="생성 시각"),
        ],
        [["유니크", "tb_embedding_profiles_profile_hash_key (profile_hash)"],
         ["CHECK", "1건 — 「CHECK 제약」 시트"],
         ["사용 코드", "services/embedding_profile, ingest_pipeline, document_version_restore, routes/ingest"],
         ["비고", "현재 설정의 프로필을 적재 시 생성/활성화하고 복원 요청 시 대상 버전 프로필과 비교"]],
    )
    activations = Table(
        "tb_document_version_activations", "문서 버전 적용 이력", "B. 대화 주제·문서·적재", "0006 (신규) · 0007 FK 보강",
        "업로드·최신본 변경·이전 버전 복원으로 실제 적용된 버전의 불변 이력",
        "activation_id", "R1-5, SC-06, D-22",
        [
            col("activation_id", "적용 이력 ID", "BIGINT", pk="PK", null="N", default="IDENTITY", description="PK"),
            col("document_id", "문서 ID", "TEXT", fk="tb_documents.document_id (CASCADE)", null="N", description="적용 대상 문서"),
            col("from_version_no", "이전 버전 번호", "INTEGER", description="적용 전 버전(NULL=최초 적용)"),
            col("to_version_no", "적용 버전 번호", "INTEGER", null="N", description="적용된 버전 번호(1 이상)"),
            col("activation_revision", "적용 순번", "BIGINT", null="N", description="문서별 단조 증가 적용 순번(1 이상)"),
            col("operation_type", "적용 유형", "TEXT", null="N", description="적용 유형 · 값: upload, replace, restore, baseline"),
            col("actor_id", "수행자 ID", "TEXT", fk="tb_users.user_id (SET NULL)", description="적용 수행자"),
            col("job_id", "작업 ID", "TEXT", fk="tb_ingest_jobs.job_id (SET NULL)", description="적용을 수행한 작업(유일)"),
            col("activated_at", "적용 시각", "TIMESTAMPTZ", null="N", default="now()", description="적용 시각"),
        ],
        [["유니크", "tb_document_version_activations_document_id_activation_revision_key (document_id, activation_revision) / tb_document_version_activations_job_id_key (job_id)"],
         ["인덱스", "idx_doc_activations_document (document_id, activation_id DESC)"],
         ["CHECK", "3건 — 「CHECK 제약」 시트"],
         ["사용 코드", "ingest_record_repository.record_activation·activation_history, ingest_pipeline, document_version_restore, routes/ingest"],
         ["비고", "0006 기존 문서에 baseline 이력 생성. 0007에서 document_id FK를 ON DELETE CASCADE로 보강"]],
    )
    insert_at = next(i for i, table in enumerate(tables) if table.name == "tb_ingest_jobs")
    tables[insert_at:insert_at] = [embedding, activations]

    for table in tables:
        for number, column in enumerate(table.columns, 1):
            column.values[0] = number


def render_table_definition(sheet, tables: list[Table]) -> None:
    templates = {
        "table": row_style(sheet, 4, 10), "desc": row_style(sheet, 5, 10),
        "header": row_style(sheet, 6, 10), "body": row_style(sheet, 7, 10),
        "meta": row_style(sheet, 13, 10), "blank": row_style(sheet, 19, 10),
    }
    for merged in list(sheet.merged_cells.ranges):
        if merged.min_row >= 4:
            sheet.unmerge_cells(str(merged))
    sheet.delete_rows(4, sheet.max_row - 3)
    sheet["A2"] = "PK = 노란색 · 붉은 글자 = 0003 추가 · 보라 글자 = 0005 추가 · 파란 글자 = 0006~0008 추가 · NULL 허용 = Y · 값 목록은 CHECK 제약"
    row = 4
    for table in tables:
        table.start_row = row
        apply_row_style(sheet, row, templates["table"])
        sheet.cell(row, 1, "테이블명"); sheet.cell(row, 3, f"{table.name}  ({table.logical})")
        sheet.cell(row, 8, "영역"); sheet.cell(row, 9, table.area); sheet.cell(row, 10, f"도입 Alembic {table.introduced}")
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
        sheet.merge_cells(start_row=row, start_column=3, end_row=row, end_column=7)
        row += 1
        apply_row_style(sheet, row, templates["desc"])
        sheet.cell(row, 1, "설명"); sheet.cell(row, 3, table.description); sheet.cell(row, 8, "PK")
        sheet.cell(row, 9, table.pk); sheet.cell(row, 10, f"요구사항: {table.requirements}")
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
        sheet.merge_cells(start_row=row, start_column=3, end_row=row, end_column=7)
        row += 1
        apply_row_style(sheet, row, templates["header"])
        for c, value in enumerate(["No", "컬럼명(물리)", "컬럼명(논리)", "데이터 타입", "길이", "PK", "FK 참조", "NULL", "기본값", "설명"], 1):
            sheet.cell(row, c, value)
        row += 1
        for column in table.columns:
            apply_row_style(sheet, row, templates["body"])
            if column.styles:
                for c, style in enumerate(column.styles, 1):
                    sheet.cell(row, c)._style = copy.copy(style)
            for c, value in enumerate(column.values, 1):
                sheet.cell(row, c, value)
            if column.styles is None:
                set_blue(sheet.cell(row, 2))
            row += 1
        for label, value in table.metadata:
            apply_row_style(sheet, row, templates["meta"])
            sheet.cell(row, 1, label); sheet.cell(row, 3, value)
            sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
            sheet.merge_cells(start_row=row, start_column=3, end_row=row, end_column=10)
            row += 1
        for _ in range(2):
            apply_row_style(sheet, row, templates["blank"])
            row += 1
    sheet.freeze_panes = "A4"


def render_table_list(sheet, tables: list[Table]) -> None:
    header = row_style(sheet, 4, 9)
    body = row_style(sheet, 5, 9)
    sheet.delete_rows(4, sheet.max_row - 3)
    sheet["A2"] = "테이블명을 누르면 테이블 정의서의 해당 위치로 이동 · 붉은색=0003 · 보라색=0005 · 파란색=0006~0008 추가"
    apply_row_style(sheet, 4, header)
    for c, value in enumerate(["No", "주제 영역", "테이블명(물리)", "테이블명(논리)", "설명", "컬럼 수", "PK", "관련 요구사항", "도입"], 1):
        sheet.cell(4, c, value)
    for index, table in enumerate(tables, 1):
        row = index + 4
        apply_row_style(sheet, row, body)
        values = [index, table.area, table.name, table.logical, table.description, len(table.columns), table.pk, table.requirements, table.introduced]
        for c, value in enumerate(values, 1):
            sheet.cell(row, c, value)
        sheet.cell(row, 3).hyperlink = f"#'테이블 정의서'!A{table.start_row}"
        sheet.cell(row, 3).style = "Hyperlink"
        if "0006" in table.introduced:
            set_blue(sheet.cell(row, 3))
    sheet.freeze_panes = "A5"


def render_column_list(sheet, tables: list[Table]) -> None:
    header = row_style(sheet, 4, 11)
    body = row_style(sheet, 5, 11)
    sheet.delete_rows(4, sheet.max_row - 3)
    apply_row_style(sheet, 4, header)
    headings = ["테이블명(물리)", "테이블명(논리)", "순번", "컬럼명(물리)", "컬럼명(논리)", "데이터 타입", "PK", "FK 참조", "NULL", "기본값", "설명"]
    for c, value in enumerate(headings, 1):
        sheet.cell(4, c, value)
    row = 5
    for table in tables:
        for column in table.columns:
            apply_row_style(sheet, row, body)
            v = column.values
            values = [table.name, table.logical, v[0], v[1], v[2], v[3], "Y" if v[5] == "PK" else None, v[6], v[7], v[8], v[9]]
            for c, value in enumerate(values, 1):
                sheet.cell(row, c, value)
            if column.styles is None:
                set_blue(sheet.cell(row, 4))
            row += 1
    sheet.auto_filter.ref = f"A4:K{row - 1}"
    sheet.freeze_panes = "A5"


def read_tabular(sheet, width: int) -> list[list[Any]]:
    rows = []
    for row in range(5, sheet.max_row + 1):
        if isinstance(sheet.cell(row, 1).value, int):
            rows.append([sheet.cell(row, col).value for col in range(2, width + 1)])
    return rows


def render_tabular(sheet, rows: list[list[Any]], width: int) -> None:
    header = row_style(sheet, 4, width)
    body = row_style(sheet, 5, width)
    sheet.delete_rows(4, sheet.max_row - 3)
    apply_row_style(sheet, 4, header)
    # Header values are restored by callers.
    for index, values in enumerate(rows, 1):
        row = index + 4
        apply_row_style(sheet, row, body)
        sheet.cell(row, 1, index)
        for col_index, value in enumerate(values, 2):
            sheet.cell(row, col_index, value)
    sheet.auto_filter.ref = f"A4:{openpyxl.utils.get_column_letter(width)}{len(rows) + 4}"
    sheet.freeze_panes = "A5"


def update_relations(workbook, tables: list[Table]) -> None:
    sheet = workbook["관계 정의"]
    rows = read_tabular(sheet, 8)
    logical = {table.name: table.logical for table in tables}
    additions = [
        ["tb_documents", "pending_job_id", "tb_ingest_jobs", "job_id", "1 : N", "SET NULL", "tb_documents_pending_job_id_fkey"],
        ["tb_document_versions", "embedding_profile_id", "tb_embedding_profiles", "embedding_profile_id", "1 : N", "NO ACTION", "tb_document_versions_embedding_profile_id_fkey"],
        ["tb_document_version_activations", "document_id", "tb_documents", "document_id", "1 : N", "CASCADE", "tb_document_version_activations_document_id_fkey"],
        ["tb_document_version_activations", "actor_id", "tb_users", "user_id", "1 : N", "SET NULL", "tb_document_version_activations_actor_id_fkey"],
        ["tb_document_version_activations", "job_id", "tb_ingest_jobs", "job_id", "1 : 0..1", "SET NULL", "tb_document_version_activations_job_id_fkey"],
    ]
    for child, child_col, parent, parent_col, relation, delete, constraint in additions:
        rows.append([f"{child} ({logical[child]})", child_col, f"{parent} ({logical[parent]})", parent_col, relation, delete, constraint])
    order = {table.name: i for i, table in enumerate(tables)}
    rows.sort(key=lambda item: (order[str(item[0]).split(" (")[0]], str(item[1])))
    headings = ["No", "자식 테이블", "자식 컬럼", "부모 테이블", "부모 컬럼", "관계", "삭제 규칙", "제약명"]
    render_tabular(sheet, rows, 8)
    for c, value in enumerate(headings, 1): sheet.cell(4, c, value)
    note_row = len(rows) + 6
    sheet.cell(note_row, 2, "의도적으로 FK 없음: tb_ingest_jobs.document_id, tb_document_events.document_id, tb_query_citations.document_id, tb_eval_item_results.qa_id, tb_spreadsheet_staging_resources.document_id·parse_job_id, tb_login_history.attempted_user_id, tb_app_settings.updated_by")


def update_indexes(workbook, tables: list[Table]) -> None:
    sheet = workbook["인덱스 정의"]
    rows = read_tabular(sheet, 6)
    rows.extend([
        ["tb_embedding_profiles", "tb_embedding_profiles_profile_hash_key", "profile_hash", "Y", "UNIQUE 제약 · 0006"],
        ["tb_document_version_activations", "idx_doc_activations_document", "document_id, activation_id DESC", "N", "0006"],
        ["tb_document_version_activations", "tb_document_version_activations_document_id_activation_revision_key", "document_id, activation_revision", "Y", "UNIQUE 제약 · 0006"],
        ["tb_document_version_activations", "tb_document_version_activations_job_id_key", "job_id", "Y", "UNIQUE 제약 · 0006"],
        ["tb_ingest_jobs", "idx_ingest_jobs_document", "document_id", "N", "WHERE document_id IS NOT NULL · 0006"],
        ["tb_ingest_jobs", "uq_ingest_jobs_idempotency", "created_by, operation_type, idempotency_key", "Y", "WHERE idempotency_key IS NOT NULL · 0006"],
    ])
    order = {table.name: i for i, table in enumerate(tables)}
    rows.sort(key=lambda item: (order[str(item[0])], str(item[1])))
    render_tabular(sheet, rows, 6)
    for c, value in enumerate(["No", "테이블명", "인덱스명", "컬럼", "유니크", "비고"], 1): sheet.cell(4, c, value)


def update_checks(workbook, tables: list[Table]) -> None:
    sheet = workbook["CHECK 제약"]
    rows = read_tabular(sheet, 6)
    for item in rows:
        if item[0] == "tb_ingest_jobs" and item[1] == "current_step":
            item[4] = "queued, validate, parse, chunk, embed, index, completed, snapshot, activate"
        if item[0] == "tb_document_events" and item[1] == "event_type":
            item[4] = "upload, parse, embed, delete, reindex, fail, update, restore"
    rows.extend([
        ["tb_documents", "activation_revision", "tb_documents_activation_revision_check", "범위·조건", "(activation_revision >= 1)"],
        ["tb_embedding_profiles", "definition_json", "ck_tb_embedding_profiles_definition_object", "JSON 형태", "(jsonb_typeof(definition_json) = 'object')"],
        ["tb_document_versions", "vector_storage_state", "tb_document_versions_vector_storage_state_check", "값 목록", "unknown, available, missing, archived"],
        ["tb_document_versions", "vector_manifest_json", "tb_document_versions_vector_manifest_json_check", "JSON 형태", "((vector_manifest_json IS NULL) OR (jsonb_typeof(vector_manifest_json) = 'object'))"],
        ["tb_document_versions", "document_snapshot_json", "tb_document_versions_document_snapshot_json_check", "JSON 형태", "((document_snapshot_json IS NULL) OR (jsonb_typeof(document_snapshot_json) = 'object'))"],
        ["tb_document_version_activations", "to_version_no", "tb_document_version_activations_to_version_no_check", "범위·조건", "(to_version_no >= 1)"],
        ["tb_document_version_activations", "activation_revision", "tb_document_version_activations_activation_revision_check", "범위·조건", "(activation_revision >= 1)"],
        ["tb_document_version_activations", "operation_type", "tb_document_version_activations_operation_type_check", "값 목록", "upload, replace, restore, baseline"],
        ["tb_ingest_jobs", "operation_type", "tb_ingest_jobs_operation_type_check", "값 목록", "ingest, restore"],
        ["tb_query_logs", "feedback_reasons", "tb_query_logs_feedback_reasons_check", "JSON 형태", "(jsonb_typeof(feedback_reasons) = 'array')"],
        ["tb_query_logs", "feedback_comment", "tb_query_logs_feedback_comment_check", "범위·조건", "(char_length(feedback_comment) <= 1000)"],
    ])
    order = {table.name: i for i, table in enumerate(tables)}
    rows.sort(key=lambda item: (order[str(item[0])], str(item[1]), str(item[2])))
    render_tabular(sheet, rows, 6)
    for c, value in enumerate(["No", "테이블명", "컬럼", "제약명", "구분", "허용값 / 조건"], 1): sheet.cell(4, c, value)


def update_overview(workbook) -> None:
    sheet = workbook["개요"]
    sheet["A1"] = "테이블 정의서 — 지능형 작업표준 안내 AI(RAG)"
    sheet["A2"] = "[AX바우처] 지능형 작업표준 절차 AI(RAG) · v0.7 · 2026-11-12 · 대상 DBMS: PostgreSQL 16 · 기준: 현재 코드(Alembic head = 0008_query_feedback_detail)"
    sheet["B6"] = "실제 스키마 기준. v0.6(0005)에서 현재 Alembic 0006~0008과 복원·피드백 구현 코드를 반영. 컬럼·타입·NULL·기본값·PK/FK·CHECK·인덱스는 마이그레이션 기준이며 실제 운영 DB 적용 상태보다 Alembic 리비전·DB 카탈로그가 우선"
    sheet["B7"] = "31개 (주제 영역 6개) · 컬럼 385개 · FK 48개 · CHECK 89개 · 인덱스 117개(PK 31개 포함). 0006 신규 2개 테이블·복원 메타데이터, 0007 FK CASCADE, 0008 피드백 상세 반영"
    sheet["B12"] = "문서는 논리 삭제 후 관련 청크·리소스를 정리. 대화 주제 삭제 시 문서 물리 삭제 → 버전·청크·리소스·적용 이력 CASCADE. 이벤트·인용·평가 결과는 일부러 FK 없음"
    sheet["B13"] = "v0.7은 Alembic 0001~0008과 현재 저장소 코드를 정적 대조하여 작성. 운영 PostgreSQL 카탈로그 재조회는 하지 않음. 산출물 구조·행 수·참조 무결성은 openpyxl 재열기로 검증"
    sheet["B14"] = "ERD 시트 이미지는 v0.5 키 컬럼 중심 그림으로 0006 신규 테이블·컬럼은 미반영. 최신 관계는 「관계 정의」 시트를 기준으로 사용"
    sheet["A16"] = "v0.7 변경"
    sheet["B16"] = "0006 이전 버전 복원(임베딩 프로필·적용 이력·벡터/스냅샷·멱등 작업), 0007 적용 이력 문서 FK CASCADE, 0008 피드백 사유·의견 반영. 상세는 「v0.7 변경 내역」 시트"
    sheet["A17"] = "이전 이력"
    sheet["B17"] = "v0.6: 0004·0005·STT 범위 / v0.5: 실제 스키마 전면 재작성 / v0.2~v0.4: 목표 설계 변경 — 각 변경 내역 시트·이전 파일 참조"
    erd = workbook["ERD"]
    erd["A1"] = "ERD (키 컬럼 중심 · v0.5 이미지)"
    erd["A2"] = "이미지는 0006 신규 tb_embedding_profiles·tb_document_version_activations 및 후속 컬럼 미반영 — 최신 관계는 관계 정의 시트 참조"


def create_change_log(workbook) -> None:
    source = workbook["v0.6 변경 내역"]
    sheet = workbook.copy_worksheet(source)
    sheet.title = "v0.7 변경 내역"
    workbook._sheets.remove(sheet)
    workbook._sheets.insert(workbook.sheetnames.index("v0.6 변경 내역"), sheet)
    prototypes = {
        "title": row_style(sheet, 1, 5), "subtitle": row_style(sheet, 2, 5),
        "section": row_style(sheet, 4, 5), "header": row_style(sheet, 5, 5),
        "data": row_style(sheet, 6, 5), "blank": row_style(sheet, 3, 5),
    }
    for merged in list(sheet.merged_cells.ranges): sheet.unmerge_cells(str(merged))
    sheet.delete_rows(1, sheet.max_row)
    records = [
        [1, "기준 변경", "문서 전체", "Alembic head 0005 → 0008. 테이블 29→31, 컬럼 358→385, FK 43→48, CHECK 78→89, 인덱스 109→117(PK 포함)", "0006~0008"],
        [2, "신규 테이블", "tb_embedding_profiles", "임베딩 모델·차원·dense/sparse 설정 정의와 SHA-256 해시. 같은 프로필 버전만 복원 허용", "0006, embedding_profile.py"],
        [3, "신규 테이블", "tb_document_version_activations", "upload·replace·restore·baseline 적용 이력, 문서별 적용 순번 UNIQUE, 작업 UNIQUE", "0006·0007"],
        [4, "컬럼 추가", "tb_documents", "activation_revision, pending_job_id — 적용 순번과 최신본 변경·복원 공통 점유 작업", "0006"],
        [5, "컬럼 추가", "tb_document_versions", "embedding_profile_id, vector_storage_state, vector_manifest_json, document_snapshot_json, restore_verified_at", "0006"],
        [6, "컬럼·인덱스", "tb_ingest_jobs", "operation_type, document_id, idempotency_key, request_fingerprint 및 문서/멱등 인덱스. 복원 단계 snapshot·activate 허용", "0006"],
        [7, "값 추가", "tb_document_events.event_type", "restore 추가", "0006"],
        [8, "FK 보강", "tb_document_version_activations.document_id", "문서 물리 삭제 시 적용 이력도 정리되도록 ON DELETE CASCADE", "0007"],
        [9, "컬럼 추가", "tb_query_logs", "feedback_reasons JSONB 배열, feedback_comment TEXT(최대 1000자)", "0008"],
        [10, "코드 반영", "복원·피드백 경로", "복원 접수/검증/활성화, 임베딩 프로필 비교, 피드백 사유 코드 검증과 관리자 통계 조회 설명 갱신", "현재 app 코드"],
    ]
    row = 1
    apply_row_style(sheet, row, prototypes["title"]); sheet.cell(row, 1, "v0.7 변경 내역 (2026-11-12)"); sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    row += 1
    apply_row_style(sheet, row, prototypes["subtitle"]); sheet.cell(row, 1, "기준: 현재 코드·Alembic 0001~0008 (head 0008_query_feedback_detail). 운영 DB 카탈로그 재조회는 하지 않음"); sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    row += 2
    apply_row_style(sheet, row, prototypes["section"]); sheet.cell(row, 1, "A. 변경 요약"); sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    row += 1
    apply_row_style(sheet, row, prototypes["header"])
    for c, value in enumerate(["No", "구분", "대상", "변경 내용", "근거"], 1): sheet.cell(row, c, value)
    for record in records:
        row += 1; apply_row_style(sheet, row, prototypes["data"])
        for c, value in enumerate(record, 1): sheet.cell(row, c, value)
    row += 2
    apply_row_style(sheet, row, prototypes["section"]); sheet.cell(row, 1, "B. 현행 동작·주의사항"); sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    row += 1
    apply_row_style(sheet, row, prototypes["header"])
    for c, value in enumerate(["No", "영역", "현행 동작", "정의서 반영", "근거"], 1): sheet.cell(row, c, value)
    notes = [
        [1, "복원 가능 조건", "벡터 available·문서 스냅샷 존재·현재 임베딩 프로필 일치·다른 변경 작업 없음", "버전·프로필·작업 컬럼/제약", "document_version_restore.py"],
        [2, "동시성·멱등", "activation_revision 비교와 pending_job_id 점유, 요청자+작업유형+멱등 키 부분 UNIQUE", "문서·작업·적용 이력", "0006, ingest_job_repository.py"],
        [3, "적용 이력", "신규 업로드·교체·복원 성공 시 이력 기록. 기존 문서는 baseline 이력 백필", "신규 적용 이력 테이블", "0006, ingest_pipeline.py"],
        [4, "벡터 상태", "적재 완료 시 available, 정리·실패 시 missing. 복원 검증 시 매니페스트와 상태 사용", "문서 버전 5개 컬럼", "ingest_record_repository.py"],
        [5, "피드백 상세", "평가별 허용 사유 코드 검증, 의견 1000자. 평가 변경·취소 시 상세도 함께 덮어씀", "질의 로그 2개 컬럼", "routes/query.py, query_log_repository.py"],
    ]
    for note in notes:
        row += 1; apply_row_style(sheet, row, prototypes["data"])
        for c, value in enumerate(note, 1): sheet.cell(row, c, value)
    sheet.freeze_panes = "A5"


def validate(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
    workbook = openpyxl.load_workbook(path, data_only=False)
    assert "v0.7 변경 내역" in workbook.sheetnames
    assert workbook["개요"]["A2"].value.find("v0.7") >= 0
    table_rows = [row for row in workbook["테이블 목록"].iter_rows(min_row=5, values_only=True) if row[0] is not None]
    column_rows = [row for row in workbook["컬럼 목록"].iter_rows(min_row=5, values_only=True) if row[0] is not None]
    relation_rows = [row for row in workbook["관계 정의"].iter_rows(min_row=5, values_only=True) if isinstance(row[0], int)]
    index_rows = [row for row in workbook["인덱스 정의"].iter_rows(min_row=5, values_only=True) if isinstance(row[0], int)]
    check_rows = [row for row in workbook["CHECK 제약"].iter_rows(min_row=5, values_only=True) if isinstance(row[0], int)]
    assert len(table_rows) == 31, len(table_rows)
    assert len(column_rows) == 385, len(column_rows)
    assert len(relation_rows) == 48, len(relation_rows)
    assert len(index_rows) == 86, len(index_rows)
    assert len(check_rows) == 89, len(check_rows)
    assert any(row[2] == "tb_embedding_profiles" for row in table_rows)
    assert any(row[2] == "tb_document_version_activations" for row in table_rows)
    assert any(row[3] == "feedback_reasons" for row in column_rows)


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("[AX바우처]_지능형 작업표준 절차 AI_테이블 정의서_v0.6.xlsx")
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else source.with_name(source.name.replace("v0.6", "v0.7"))
    workbook = openpyxl.load_workbook(source)
    tables = parse_tables(workbook["테이블 정의서"])
    update_tables(tables)
    render_table_definition(workbook["테이블 정의서"], tables)
    render_table_list(workbook["테이블 목록"], tables)
    render_column_list(workbook["컬럼 목록"], tables)
    update_relations(workbook, tables)
    update_indexes(workbook, tables)
    update_checks(workbook, tables)
    update_overview(workbook)
    create_change_log(workbook)
    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    workbook.save(target)
    validate(target)
    print(target.resolve())


if __name__ == "__main__":
    main()
