"""테이블 정의서(docs/design/03_테이블_정의서_현행_v1.0.md) 생성 (2026.10.16 추가).

DB 카탈로그(컬럼·타입·제약·인덱스)는 접속한 DB에서 읽고, 테이블·컬럼 설명은 아래 사전(T, C)에서 가져온다.
스키마(Alembic 리비전)를 바꾸면 사전에 설명을 추가하고 다시 실행한다. 접속 정보는 .env의 POSTGRES_*(값은 출력하지 않음).

사용법 (저장소 루트에서)
    python adrag_backend/scripts/gen_table_definition.py .env docs/design/03_테이블_정의서_현행_v1.0.md
"""
import re
import sys
from collections import defaultdict

import psycopg
from dotenv import dotenv_values

env = dotenv_values(sys.argv[1])
OUT = sys.argv[2]

# ── 테이블 설명: (그룹, 한글명, 용도, 사용 코드, 비고) ───────────────────────────
T = {
 "tb_departments": ("사용자·권한", "부서", "부서와 부서에 허용된 대화 주제 목록. 사용자 접근 가능 주제 = 부서 허용 주제 − 개인 차단 주제", "department_repository, routes/admin_departments, collection_repository(접근 주제 계산)", "department_id는 서비스에서 채번(D001…)"),
 "tb_users": ("사용자·권한", "사용자", "로그인 계정(관리자·일반 사용자 공통). 비밀번호는 bcrypt 해시", "routes/auth, routes/admin_users, ui_settings_repository", "관리자 계정은 scripts/create_admin.py로만 생성(고정 시드 없음). 삭제보다 is_active=FALSE 권장(로그 RESTRICT 참조)"),
 "tb_login_history": ("사용자·권한", "로그인 이력", "로그인 성공·실패 감사 기록", "login_history_repository, routes/auth", "attempted_user_id는 FK 없음(없는 ID 시도도 기록)"),
 "tb_user_collection_permissions": ("사용자·권한", "사용자-대화 주제 권한", "사용자별로 직접 부여된 대화 주제(컬렉션) 접근 권한", "permissions_repository, metadata_repository, routes/collections", "admin 역할은 이 테이블을 보지 않고 전체 접근"),
 "tb_user_security_policies": ("사용자·권한", "사용자 보안 정책", "사용자별 최대 보안 등급·허용 문서 유형·추가 검색 필터", "permissions_repository, routes/admin_users(생성 시 기본 행)", "검색 필터에 반영(보안 등급 이하 문서만)"),
 "tb_collections": ("문서", "대화 주제(컬렉션)", "Qdrant 컬렉션 1개 = 대화 주제 1개. 문서 그룹 단위", "collection_repository, collection_service, routes/collections", "qdrant_name은 생성 후 변경 금지. 변경로그 D-15: 권한의 '모델' 단위 기본안"),
 "tb_documents": ("문서", "문서", "업로드된 문서 1건의 메타데이터와 처리 상태", "document_repository, ingest_service, routes/ingest, stats_repository", "삭제는 논리 삭제(deleted_at). 문서 버전 테이블은 Phase 2에서 추가 예정"),
 "tb_document_events": ("문서", "문서 이벤트 이력", "문서 처리 이벤트 기록", "document_repository.record_event ← ingest_service(삭제 시), document_repository.update_product_model(모델명 수정)", "기록하는 이벤트: delete, update(모델명 수정 전후값 snapshot, 0004). document_id FK 없음(삭제 후에도 보존)"),
 "tb_ingest_jobs": ("문서", "적재 작업", "업로드 1건 = 작업 1건. 앱 프로세스 안 asyncio 큐가 처리하고 상태를 여기에 저장", "ingest_job_repository, services/ingest_jobs(IngestJobManager), routes/ingest", "기동 시 queued/running 작업을 다시 큐에 넣음. 큐·재시도·임대 컬럼은 Phase 3에서 추가 예정"),
 "tb_document_versions": ("문서", "문서 버전", "업로드 파일 1개 = 1행. 검색·답변은 active 버전만(문서당 1개, 부분 유일 인덱스)", "ingest_record_repository(create_active_version·create_building_version·activate_version) ← routes/ingest(최신본 변경 접수)·ingest_pipeline.IndexStep, ingest_service.delete_document(retired)", "0003(Phase 2), 0005(10-19 최신본 변경): building→ready→active 한 트랜잭션 전환, 처리 중 버전 문서당 1개(uq_doc_versions_in_progress). 활성이 아니고 vectors_purged_at이 NULL인 버전의 포인트는 검색 제외(version_visibility)"),
 "tb_chunks": ("문서", "청크 원천", "Qdrant 포인트 1개 = 1행(PostgreSQL이 원천, Qdrant는 재생성 가능 색인)", "ingest_record_repository.insert_chunks ← IndexStep(excel·docling 공통)", "chunk_id = {document_id}:{version}:{source_key}#{part_no}, point_id = uuid5(chunk_id) = Qdrant ID. 문서 삭제 시 행 삭제"),
 "tb_chunk_resources": ("문서", "청크↔사진 연결", "텍스트 청크와 연결된 사진(배치) — 답변 사진 첨부(Phase 4)·검수 반영(Phase 5) 기준", "ingest_record_repository.insert_chunk_resources", "확정 리소스가 없는 연결은 기록하지 않음"),
 "tb_flow_graphs": ("문서", "흐름도", "제조공정도 시트의 노드·연결(excel_ingest XML 확정분)", "ingest_record_repository.insert_flow_graphs", "D-08 1차: 저장 + 청크 + 확인용 md. 뷰어·검수 화면은 2차"),
 "tb_spreadsheet_staging_resources": ("문서", "파서 staging 리소스", "docling 파서가 보낸 리소스의 commit 전 단계(문서 행이 생기기 전)", "spreadsheet_resource_repository(create_staging·mark_committed·delete_staging_by_parse_job)", "0003(P2-13). commit 시 tb_spreadsheet_resources로 옮김. parse_job_id는 외부 작업 ID라 FK 없음"),
 "tb_spreadsheet_resources": ("문서", "확정 리소스·사진 배치", "확정된 이미지 등 리소스 파일과 시트·셀 위치. excel_ingest 경로는 배치 1개 = 1행(역할·Step·신뢰도·검수 상태)", "spreadsheet_resource_repository, spreadsheet_resource_service, routes/spreadsheet_resources", "resource_id가 이미지 API·인용의 식별자. docling 경로는 staging 테이블에서 commit 시 옮겨 옴, excel_ingest 경로는 {document_id}-v{version}-i{순번}으로 바로 committed(0003). 문서 FK ON DELETE CASCADE"),
 "tb_spreadsheet_resource_analyses": ("문서", "리소스 분석 결과", "리소스별 OCR/VLM 분석 결과(버전별 보존)", "spreadsheet_resource_repository, routes/spreadsheet_resources(내부 API)", "(resource_id, analysis_version) 유일"),
 "tb_query_sessions": ("질의응답", "대화 세션", "사용자·대화 주제별 대화 이력", "session_repository, query_log_repository, main(만료 세션 정리)", "conversation_history에 질문·답변 목록(JSON). STT 결과도 사용자가 채팅 전송한 최종 텍스트만 일반 질문으로 저장하며 음성 입력 여부·인식 원문·수정 여부는 기록하지 않음"),
 "tb_query_logs": ("질의응답", "질의 로그", "질의 1건의 질문·답변·근거·성능·평가(👍/👎)", "query_log_repository, query_recorder, stats_repository, routes/query(피드백)", "통계 화면의 원천. user_id는 RESTRICT(로그 있는 사용자 삭제 불가). STT 변환 API 자체는 로그를 생성하지 않으며, 질문 전송 이후 일반 RAG 질의로 기록"),
 "tb_query_citations": ("질의응답", "질의-인용 문서", "답변이 인용한 문서(질의당 문서별 1행)", "query_log_repository, stats_repository(최다 참조 문서·미참조 문서)", "document_id FK 없음(문서 삭제 후에도 통계 보존)"),
 "tb_llm_models": ("모델·설정", "LLM 모델", "사용자가 고를 수 있는 LLM 목록", "model_repository, routes/models, routes/user_settings", "시드 4행(local + OpenAI 3) — OpenAI 행은 절대 규칙 7과 충돌, Phase 7에서 결정(Q-15.5)"),
 "tb_user_llm_settings": ("모델·설정", "사용자 LLM 설정", "사용자·대화 주제별 선택 모델과 API 키(암호화)", "user_llm_settings_repository, routes/user_settings", "api_key_enc는 Fernet 암호화"),
 "tb_app_settings": ("모델·설정", "런타임 설정", "관리자가 화면에서 바꾸는 검색 튜닝 값(키-값)", "app_settings_repository, core/runtime_settings, routes/admin_settings", "키 목록은 app_settings_repository.SETTING_TYPES(candidate_top_k, reranker_top_k, context_top_k, relevance_threshold, hybrid_rrf_k, bm25_k1/b, soft_boost_*, *_hint_terms, *_provider)"),
 "tb_eval_datasets": ("평가", "평가 데이터셋", "QA 생성 배치 단위(대화 주제 1개 대상)", "evaluation_repository, routes/evaluation", "collection_id RESTRICT — 데이터셋이 있으면 대화 주제 삭제 불가"),
 "tb_eval_qa_items": ("평가", "평가 QA 항목", "질문·정답·근거 청크와 검수 상태", "evaluation_repository", ""),
 "tb_eval_goldsets": ("평가", "골드셋", "데이터셋 확정 시점의 QA 스냅샷(불변)", "evaluation_repository", "(dataset_id, version) 유일"),
 "tb_eval_runs": ("평가", "평가 실행", "골드셋 1개에 대한 평가 실행 1회", "evaluation_repository, evaluation/runner/eval_runner", "기동 시 중단된 실행은 failed로 정리(main)"),
 "tb_eval_item_results": ("평가", "평가 항목 결과", "실행 × QA 항목 1건의 지표 결과", "evaluation_repository, eval_runner", "(run_id, qa_id) 유일(Phase 1.5 추가). qa_id는 스냅샷 기준이라 FK 없음"),
 "tb_eval_run_metrics": ("평가", "평가 지표 집계", "실행 완료 시 계산한 지표(대시보드 조회용)", "evaluation_repository", "PK (run_id, metric_key, segment), 재계산 시 덮어씀"),
 "tb_eval_settings": ("평가", "평가 생성 설정", "관리자별 데이터셋 생성용 OpenAI 키(암호화)", "evaluation_repository, routes/evaluation", "OpenAI backend 선택 시에만 사용"),
}
ORDER = ["사용자·권한", "문서", "질의응답", "모델·설정", "평가"]

COMMON = {
 "created_at": "생성 시각", "updated_at": "수정 시각", "created_by": "생성자 사용자 ID",
 "error_message": "오류 메시지", "status": "상태",
}
C = {
 "tb_departments": {"department_id": "부서 ID", "department_name": "부서명(유일, 사용자·컬렉션에 동기화)", "allowed_topics": "허용 대화 주제명 배열", "is_active": "사용 여부"},
 "tb_users": {"user_id": "로그인 ID", "user_pwd": "비밀번호 bcrypt 해시", "user_name": "이름", "department_name": "현재 부서명(부서 테이블과 동기화)", "department_id": "소속 부서", "blocked_topics": "개인 차단 대화 주제명 배열(부서 허용 주제 안에서만 의미)", "role": "역할 admin/user", "ui_type": "UI 연동 방식 standalone/menu_linked/layout_linked, NULL=미선택(신규 계정)", "is_active": "사용 여부(FALSE면 로그인 차단)", "pwd_changed_at": "마지막 비밀번호 변경 시각(이전에 발급된 사용자 토큰 무효), NULL=변경 이력 없음"},
 "tb_login_history": {"login_history_id": "PK", "attempted_user_id": "입력한 로그인 ID", "user_id": "확인된 사용자(없으면 NULL)", "user_role": "로그인 시 역할", "department_snapshot": "로그인 시 부서명", "success": "성공 여부", "failure_reason": "실패 사유 코드", "ip_address": "접속 IP", "user_agent": "브라우저 정보", "auth_session_id": "인증 세션 ID"},
 "tb_user_collection_permissions": {"permission_id": "PK", "user_id": "사용자", "collection_id": "허용 대화 주제"},
 "tb_user_security_policies": {"user_id": "사용자(PK)", "max_security_level": "검색 가능한 최대 보안 등급", "allowed_doc_types": "허용 문서 유형 배열([]=전체)", "metadata_filters": "Qdrant payload 추가 필터(객체)"},
 "tb_collections": {"collection_id": "PK", "display_name": "화면 표시명(생성자 안에서 유일)", "qdrant_name": "Qdrant 컬렉션 이름(전역 유일, 변경 금지)", "description": "설명", "is_active": "사용 여부(FALSE면 조회 차단, 데이터 유지)", "topic_name": "대화 주제명(부서 허용 주제와 매칭)", "department_id": "생성 부서", "department_name": "생성 부서의 현재 부서명 사본(부서명 변경 시 함께 갱신, 스냅샷 아님)"},
 "tb_documents": {"document_id": "문서 ID(UUID)", "collection_id": "소속 대화 주제", "uploaded_by": "업로더", "original_filename": "원본 파일명", "stored_filename": "저장 파일명(날짜_문서ID.확장자)", "source_path": "원본 저장 경로", "file_size": "파일 크기(byte)", "doc_type": "판별된 문서 유형", "requested_doc_type": "업로드 시 선택한 유형(auto/general/manual/law/spreadsheet)", "doc_type_source": "유형 결정 근거(file_extension/auto_detected/user_selected 등)", "title": "문서 제목", "file_format": "확장자", "security_level": "보안 등급", "parser_type": "사용 파서", "total_pages": "페이지 수", "chunk_count": "청크 수", "version_no": "현재 적용(active) 버전 번호(0003에서 의미 확정, 개정본 기능은 Phase 3)", "doc_key": "문서 키(파일명 기준, 표시·검색 보조 — 개정 판단에 쓰지 않음, D-01)", "product_model": "모델명(화면 표기, 업로드 시 파일별 입력·기본값 파일명에서 마지막 확장자 제거, 1~100자, 목록에서 수정 — 0004 백필). 엑셀 청크 머리말에 쓰임. LLM model_name·대화 주제와 별개", "active_activated_at": "현재 버전 적용 시각", "content_updated_at": "내용 갱신 시각(통계 문서 상태)", "review_due_at": "검토 기한(통계 문서 상태)", "deleted_at": "논리 삭제 시각(NULL=정상)"},
 "tb_document_events": {"event_id": "PK", "document_id": "문서 ID", "collection_id": "대화 주제", "event_type": "이벤트 유형", "event_message": "메시지", "actor_id": "수행자", "event_at": "발생 시각", "snapshot_json": "당시 문서 상태 스냅샷(선택)"},
 "tb_ingest_jobs": {"job_id": "작업 ID(UUID)", "status": "queued/running/completed/failed", "current_step": "진행 단계 queued→validate→parse→chunk→embed→index→completed(재시도는 실패 단계부터)", "request_json": "업로드 요청(file_path, filename, collection_name, parser_type, document_type, chunk_size, uploaded_by, security_level)", "result_json": "완료 결과(document_id, doc_type, chunk_count 등)", "error_code": "오류 코드(문서 유형 불일치 등)", "created_by": "요청자"},
 "tb_spreadsheet_resources": {"resource_id": "리소스 ID(이미지 식별자)", "document_id": "문서 ID(FK 없음 — staging 단계에서 문서 행보다 먼저 생김)", "parse_job_id": "파서 작업 ID", "resource_type": "리소스 종류(image 등)", "resource_path": "저장 상대 경로(RESOURCE_STORAGE_ROOT 기준)", "content_hash": "sha256 해시", "mime_type": "MIME 타입", "file_size": "크기(byte)", "sheet_id": "시트 ID", "sheet_name": "시트명", "from_cell": "시작 셀", "to_cell": "끝 셀", "linked_block_id": "연결된 표·블록 ID", "linked_record_ids": "연결된 행 ID 배열", "surrounding_range": "주변 셀 범위", "surrounding_text": "주변 텍스트(이미지 뷰어 설명)", "status": "committed→analysis_*, deleted (staging은 0003부터 별도 테이블)", "version_no": "문서 버전(excel_ingest 경로)", "role_cd": "사진 역할(step_photo·detail_view·part_photo·drawing·flowchart·decoration…)", "section_type": "시트 유형", "step_no": "연결된 작업 단계", "step_title": "단계 제목", "anchor_type": "엑셀 앵커 종류", "in_print_area": "인쇄 영역 안 여부", "overlay_json": "사진 위 표시(①② 콜아웃·Q/S 마커·글자)", "link_method": "단계 연결 방법", "link_confidence": "연결 신뢰도 0~1", "review_status": "auto/needs_review/approved/changed/unlinked(검수 UI-15)", "reviewed_by": "검수자", "reviewed_at": "검수 시각", "review_inherited_from": "재등록 시 검수 승계 원본 resource_id(예정)"},
 "tb_spreadsheet_resource_analyses": {"analysis_id": "PK", "resource_id": "리소스", "document_id": "문서", "analysis_version": "분석 버전", "method": "ocr/vlm/chart_parser", "model": "사용 모델", "model_version": "모델 버전", "prompt_version": "프롬프트 버전", "pipeline_version": "파이프라인 버전", "result_path": "결과 파일 경로", "text": "분석 텍스트", "confidence": "신뢰도"},
 "tb_query_sessions": {"session_id": "세션 ID", "user_id": "사용자", "collection_id": "대화 주제", "conversation_history": "대화 이력 배열", "expires_at": "만료 시각(만료 세션은 주기 정리)"},
 "tb_query_logs": {"log_id": "PK", "session_id": "세션", "user_id": "질문자", "collection_id": "대화 주제", "query_text": "질문", "answer_text": "답변", "context_text": "LLM에 준 청크 본문 배열", "context_meta": "청크 메타 배열", "response_time_s": "응답 시간(초)", "response_time_ms": "응답 시간(ms)", "chunks_retrieved": "검색된 청크 수", "answer_generated": "답변 생성 여부", "outcome_code": "결과 코드", "model_id": "사용 LLM", "prompt_tokens": "입력 토큰", "completion_tokens": "출력 토큰", "cost_usd": "비용(USD)", "extracted_keywords": "추출 키워드 배열(인기 키워드 통계)", "department_snapshot": "질문 당시 부서명", "collection_name_snapshot": "질문 당시 대화 주제명", "feedback": "평가 1=👍, 0=👎, NULL=미응답", "feedback_at": "평가 시각", "feedback_reasons": "평가 사유 코드 배열", "feedback_comment": "평가 의견(최대 1000자)"},
 "tb_query_citations": {"citation_id": "PK", "log_id": "질의 로그", "document_id": "인용 문서 ID", "original_filename": "인용 당시 파일명", "collection_id": "대화 주제", "collection_name_snapshot": "대화 주제명 스냅샷", "cited_at": "인용 시각"},
 "tb_llm_models": {"model_id": "모델 ID", "model_name": "표시명", "provider": "local/openai", "requires_api_key": "API 키 필요 여부", "is_enabled": "사용 여부", "sort_order": "표시 순서"},
 "tb_user_llm_settings": {"setting_id": "PK", "user_id": "사용자", "collection_id": "대화 주제", "model_id": "선택 모델", "api_key_enc": "API 키(Fernet 암호화, NULL=불필요)"},
 "tb_app_settings": {"setting_key": "설정 키", "setting_value": "값(문자열 저장, value_type으로 해석)", "value_type": "int/float/str/json", "version": "변경 버전(캐시 무효화용)", "updated_by": "수정자"},
 "tb_eval_datasets": {"dataset_id": "PK", "name": "이름", "collection_id": "대상 대화 주제", "status": "generating/review/finalized/failed", "gen_config_json": "생성 설정 스냅샷(샘플링·모델·유형 비율)", "progress_done": "생성 완료 수", "progress_total": "생성 대상 수"},
 "tb_eval_qa_items": {"qa_id": "PK", "dataset_id": "데이터셋", "question": "질문", "gold_answer": "정답", "gold_chunk_ids": "근거 청크 ID 배열", "gold_document_ids": "근거 문서 ID 배열", "gold_chunk_texts": "근거 청크 본문 배열(재적재 후 재매핑용)", "question_type": "질문 유형", "difficulty": "난이도", "self_valid_rank": "자체 검증 검색 순위(NULL=미검출)", "expected_behavior": "기대 동작(answer/not_enough_info/guardrail/permission_denied)", "tags": "태그 배열", "review_status": "검수 상태", "reviewed_by": "검수자", "reviewed_at": "검수 시각", "source_meta_json": "근거 표시 정보(섹션·페이지 등)"},
 "tb_eval_goldsets": {"goldset_id": "PK", "dataset_id": "데이터셋", "version": "골드셋 버전", "item_count": "항목 수", "items_snapshot_json": "확정 시점 QA 전체 스냅샷 배열", "note": "메모"},
 "tb_eval_runs": {"run_id": "PK", "goldset_id": "골드셋", "run_type": "retrieval/end_to_end/full", "config_json": "실행 설정(top_n·지표 버전 등)", "status": "pending/running/completed/failed/cancelled", "progress_done": "완료 항목 수", "progress_total": "전체 항목 수", "started_at": "시작 시각", "finished_at": "종료 시각"},
 "tb_eval_item_results": {"result_id": "PK", "run_id": "실행", "qa_id": "QA 항목(스냅샷 기준)", "status": "ok/error/skipped", "retrieval_json": "채널별 검색 지표", "answer_text": "생성 답변", "judge_json": "LLM 판정 결과", "similarity": "정답 대비 임베딩 유사도", "answer_correctness_v1_json": "정답성 v1", "answer_correctness_v2_json": "정답성 v2", "answer_correctness_f2_json": "정답성 F2", "answer_correctness_judge_json": "LLM Judge 정답성", "answer_correctness_json": "설정상 대표 정답성", "metric_status_json": "지표별 계산 상태", "rule_check_json": "규칙 기반 체크", "citation_json": "인용 지표", "citation_detail_json": "인용 상세(화면용)", "threshold_fallback_json": "근거 부족 대체 판정", "guardrail_json": "가드레일 판정", "latency_ms": "응답 시간(ms)", "timing_json": "노드별 처리 시간", "token_usage_json": "토큰 사용량"},
 "tb_eval_run_metrics": {"run_id": "실행", "metric_key": "지표 키(예: retrieval.rrf.recall@5)", "metric_value": "값", "metric_std": "표준편차", "evaluated_count": "평가 건수", "excluded_count": "제외 건수", "error_count": "오류 건수", "total_count": "전체 건수", "metric_version": "지표 버전", "segment": "구분(all, type:…, tag:…)"},
 "tb_document_versions": {"document_id": "문서", "version_no": "버전 번호(1부터)", "status": "building/ready/active/retired/failed", "processing_engine": "처리기 excel_ingest/docling", "file_sha256": "원본 파일 해시", "original_filename": "업로드 파일명", "stored_filename": "저장 파일명", "source_path": "원본 저장 경로", "file_size": "크기(byte)", "file_format": "확장자", "parser_type": "파서", "total_pages": "페이지(시트) 수", "chunk_count": "청크 수", "revision_label": "관리대장 개정 차수(예정)", "md_dir": "확인용 md 폴더", "summary_json": "처리 요약(시트·청크·사진 수 등)", "warnings_json": "경고 목록", "job_id": "처리 작업", "uploaded_by": "업로더", "activated_at": "적용 시각", "retired_at": "교체·삭제 시각", "vectors_purged_at": "이 버전 Qdrant 포인트 정리 시각(NULL이면 비활성 버전 검색 제외 대상, 0005)"},
 "tb_chunks": {"chunk_id": "청크 ID({document_id}:{version}:{source_key}#{part_no})", "document_id": "문서", "version_no": "버전", "collection_id": "검색 컬렉션", "point_id": "Qdrant 포인트 ID(uuid5)", "source_key": "버전 무관 위치 키(예: 09:step:6) — 개정 후 검수·평가 승계", "part_no": "분할 조각 번호(MAX_CHUNK_SIZE 초과 시)", "point_type": "text/image/drawing(현재 text만)", "content_type": "청크 종류(step·table_section·guide_note…)", "section_type": "시트 유형(sop·inspection…)", "sheet_name": "시트", "source_range": "출처 범위(행 범위 등)", "step_no": "작업 단계 번호", "chunk_text": "본문(Qdrant text와 같음)", "meta_json": "기타 메타(처리기·원천 청크 ID·개정 차수 등)"},
 "tb_chunk_resources": {"chunk_id": "청크", "resource_id": "사진(확정 리소스)", "sort_order": "표시 순서"},
 "tb_flow_graphs": {"graph_id": "PK", "document_id": "문서", "version_no": "버전", "sheet_name": "흐름도 시트", "nodes_json": "노드 배열", "edges_json": "연결 배열(XML 확정)", "unresolved_json": "미연결 선(VLM 보강·검수 대상)", "source_hash": "도형 XML 해시", "vlm_status": "VLM 판정 상태", "review_status": "auto/needs_review/md_checked"},
 "tb_spreadsheet_staging_resources": {"resource_id": "리소스 ID(파서 발급)", "document_id": "대상 문서 ID(문서 행 생성 전일 수 있음)", "parse_job_id": "파서 작업 ID", "resource_type": "리소스 종류", "resource_path": "staging 상대 경로", "content_hash": "sha256", "mime_type": "MIME", "file_size": "크기(byte)", "sheet_id": "시트 ID", "sheet_name": "시트명", "from_cell": "시작 셀", "to_cell": "끝 셀", "linked_block_id": "연결 블록", "linked_record_ids": "연결 행 ID 배열", "surrounding_range": "주변 범위", "surrounding_text": "주변 텍스트"},
 "tb_eval_settings": {"admin_id": "관리자 ID", "openai_api_key_enc": "OpenAI 키(Fernet 암호화)"},
}

conn = psycopg.connect(host=env["POSTGRES_HOST"], port=env["POSTGRES_PORT"], dbname=env["POSTGRES_DB"],
                       user=env["POSTGRES_USER"], password=env["POSTGRES_PASSWORD"])
cols = defaultdict(list)
for t, c, typ, null, default, pos in conn.execute(
    """SELECT table_name, column_name,
              CASE WHEN data_type = 'USER-DEFINED' THEN udt_name ELSE data_type END,
              is_nullable, column_default, ordinal_position
       FROM information_schema.columns WHERE table_schema='public' AND table_name LIKE 'tb\\_%'
       ORDER BY table_name, ordinal_position"""):
    cols[t].append((c, typ, null, default))
ident = {(t, c) for t, c in conn.execute(
    "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='public' AND is_identity='YES'")}
cons = defaultdict(list)
# 2026.10.16 수정 - 제약이 실제로 걸린 컬럼(conkey)을 함께 읽는다. CHECK를 텍스트 검색으로 컬럼에 붙이면
#   다른 컬럼 CHECK의 '::text' 캐스트가 `text` 컬럼에 잘못 붙는다(05 보완안 작업 중 발견).
constraint_columns: dict[tuple[str, str], set[str]] = {}
for t, name, ctype, definition, columns in conn.execute(
    """SELECT rel.relname, con.conname, con.contype, pg_get_constraintdef(con.oid),
              ARRAY(SELECT a.attname::text FROM pg_attribute a
                    WHERE a.attrelid = con.conrelid AND a.attnum = ANY(con.conkey))
       FROM pg_constraint con JOIN pg_class rel ON rel.oid = con.conrelid
       JOIN pg_namespace n ON n.oid = rel.relnamespace
       WHERE n.nspname='public' AND rel.relname LIKE 'tb\\_%' ORDER BY rel.relname, con.contype, con.conname"""):
    cons[t].append((name, ctype, definition))
    constraint_columns[(t, name)] = set(columns or [])
idx = defaultdict(list)
for t, name, definition in conn.execute(
    "SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname='public' AND tablename LIKE 'tb\\_%' ORDER BY 1,2"):
    idx[t].append((name, definition))
revision = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
server = conn.info.server_version

TYPE_SHORT = {"timestamp with time zone": "timestamptz", "double precision": "double", "character varying": "varchar"}


def col_keys(t):
    pk, fk, uq = set(), {}, set()
    for name, ctype, d in cons[t]:
        cs = [x.strip() for x in re.search(r"\(([^)]*)\)", d).group(1).split(",")] if ctype in "pfu" else []
        if ctype == "p":
            pk.update(cs)
        elif ctype == "u" and len(cs) == 1:
            uq.update(cs)
        elif ctype == "f":
            # 2026.10.16 수정 - 복합 FK((document_id, version_no) → tb_document_versions) 지원
            m = re.search(r"REFERENCES (\w+)\(([^)]*)\)(.*)", d)
            rule = "CASCADE" if "CASCADE" in m.group(3) else "SET NULL" if "SET NULL" in m.group(3) else "RESTRICT" if "RESTRICT" in m.group(3) else "NO ACTION"
            ref_cols = [x.strip() for x in m.group(2).split(",")]
            for c, ref in zip(cs, ref_cols):
                fk.setdefault(c, f"{m.group(1)}.{ref} ({rule})")
    return pk, fk, uq


def fmt_index(name, definition):
    cols_part = re.search(r"USING btree \((.*?)\)", definition).group(1)
    extra = " UNIQUE" if "UNIQUE" in definition else ""
    if " WHERE " in definition:
        extra += " WHERE " + definition.split(" WHERE ", 1)[1]
    return f"`{name}` ({cols_part}{extra})"


def checks_for(t, c):
    out = []
    for name, ctype, d in cons[t]:
        if ctype == "c" and c in constraint_columns.get((t, name), set()):
            body = d[len("CHECK "):]
            # 2026.10.16 수정 - 여러 컬럼에 걸친 CHECK는 칸에는 이름만, 전체 식은 표 아래(multi_checks)에 1회
            if len(constraint_columns.get((t, name), set())) > 1 and "ANY" not in body:
                out.append(f"`{name}`")
                continue
            m = re.search(r"ANY \(\(?ARRAY\[(.*?)\]", body)
            if m and "jsonb_typeof" not in body:
                # 'x'::text 형태와 숫자(0, 1) 모두 값 목록으로 표시
                values = [re.sub(r"::\w+(\s\w+)*$", "", v.strip()).strip("'") for v in m.group(1).split(",")]
                out.append("값: " + ", ".join(values))
            elif "jsonb_typeof" in body:
                out.append("JSON " + ("배열" if "'array'" in body else "객체"))
            else:
                out.append(_strip_outer_parens(body))
    return "; ".join(out)


def _strip_outer_parens(expr: str) -> str:
    """바깥을 완전히 감싼 괄호 쌍만 벗긴다(짝이 안 맞게 잘리지 않도록)."""
    expr = expr.strip()
    while expr.startswith("(") and expr.endswith(")"):
        depth = 0
        for i, ch in enumerate(expr):
            depth += ch == "("
            depth -= ch == ")"
            if depth == 0 and i < len(expr) - 1:
                return expr
        expr = expr[1:-1].strip()
    return expr


C["tb_query_logs"]["query_text"] = "최종 전송 질문(STT 결과 확인·수정 후 입력창에서 전송한 텍스트 포함, 인식 원문과 구분 불가)"
C["tb_query_logs"]["model_id"] = "RAG 질의에 기록된 답변용 모델 ID(ASR 모델명이 아님)"

lines = [
    "# 03. 테이블 정의서 — 현행(As-Is) v1.0",
    "",
    f"> 작성 2026-10-16 · 기준: **현재 코드(10-15 SQLite판 → Phase 1.5 PostgreSQL 전환)**, DB `rag_chatbot_dev` @ Alembic `{revision}`, PostgreSQL {server // 10000}.{server % 100}",
    "> 컬럼·타입·제약·인덱스는 DB 카탈로그에서 자동 생성했고, 설명·사용 코드는 현재 소스를 읽고 작성했다. 스키마 원본: `adrag_backend/migrations/versions/0001_baseline.py`.",
    "> 스키마가 바뀌면 `python adrag_backend/scripts/gen_table_definition.py .env docs/design/03_테이블_정의서_현행_v1.0.md`로 다시 생성한다. 이 문서보다 Alembic 리비전과 실제 DB가 우선한다(CLAUDE.md 2장 1순위).",
    "",
    "## 0. 공통 규칙",
    "",
    "| 항목 | 규칙 |",
    "|---|---|",
    "| 테이블 이름 | `tb_` 접두어 + 소문자 스네이크 |",
    "| 정수 PK | `bigint GENERATED BY DEFAULT AS IDENTITY`(이관 시 기존 ID 보존 후 시퀀스 재설정) |",
    "| 시각 | `timestamptz`, 기본값 `now()`. DB 세션 시간대 Asia/Seoul. 앱에는 `YYYY-MM-DDTHH:MM:SS+09:00` 문자열로 전달(DB 계층 변환) |",
    "| JSON | `jsonb` + 배열/객체 형태 CHECK. 앱에는 JSON 문자열로 전달 |",
    "| 0/1 플래그 | `boolean`. 앱에는 1/0으로 전달. `tb_query_logs.feedback`만 `smallint 0/1`(평가값) |",
    "| `updated_at` | 0002부터 `BEFORE UPDATE` 트리거(`fn_touch_updated_at`)가 `now()`로 갱신 — 앱이 넣은 값보다 DB 시각이 최종 |",
    "| 삭제 정책 | FK ON DELETE: RESTRICT(감사·로그 보존) / CASCADE(종속 데이터) / SET NULL(작성자 퇴사 후 데이터 유지). 문서는 논리 삭제(`deleted_at`) |",
    "| 의도적으로 FK 없음 | `tb_document_events.document_id`, `tb_query_citations.document_id`(대화 주제 삭제 시 문서가 물리 삭제되므로 이력·통계 보존, 05 보완안 P0-4), `tb_eval_item_results.qa_id`(스냅샷 기준), `tb_spreadsheet_resources.document_id`(staging이 문서 행보다 먼저), `tb_login_history.attempted_user_id` |",
    "| 표기 | PK=기본키, FK=외래키(참조, 삭제 규칙), UQ=단일 컬럼 유일, NN=NOT NULL |",
    "",
    "## 1. 테이블 목록",
    "",
    "| 그룹 | 테이블 | 한글명 | 컬럼 수 | 용도 |",
    "|---|---|---|---:|---|",
]
by_group = defaultdict(list)
for t in T:  # 정의 순서(논리 순서) 유지
    if t in cols:
        by_group[T[t][0]].append(t)
assert set(cols) == {t for g in by_group.values() for t in g}, set(cols) ^ set(T)
for g in ORDER:
    for t in by_group[g]:
        lines.append(f"| {g} | [`{t}`](#{t}) | {T[t][1]} | {len(cols[t])} | {T[t][2]} |")
lines += ["", f"총 {len(cols)}개 테이블, {sum(len(v) for v in cols.values())}개 컬럼.", ""]

lines += ["## 2. 관계 요약", "", "```"]
for g in ORDER:
    for t in by_group[g]:
        refs = sorted({v.split('.')[0] + f"({k}, {v.split('(')[1]}" for k, v in col_keys(t)[1].items()})
        if refs:
            lines.append(f"{t} → " + ", ".join(refs))
lines += ["```", ""]

n = 3
for g in ORDER:
    lines += [f"## {n}. {g}", ""]
    for t in by_group[g]:
        _, kname, purpose, code, note = T[t]
        pk, fk, uq = col_keys(t)
        lines += [f"### {t}", "", f"**{kname}** — {purpose}", "", f"- 사용 코드: {code}"]
        if note:
            lines.append(f"- 비고: {note}")
        lines += ["", "| # | 컬럼 | 타입 | NN | 기본값 | 키 | 설명 | 제약·값 |", "|---:|---|---|:---:|---|---|---|---|"]
        for i, (c, typ, null, default) in enumerate(cols[t], 1):
            keys = []
            if c in pk:
                keys.append("PK")
            if c in fk:
                keys.append("FK→" + fk[c])
            if c in uq:
                keys.append("UQ")
            d = "IDENTITY" if (t, c) in ident else (default or "")
            d = d.replace("::jsonb", "").replace("'::text", "'")
            desc = C.get(t, {}).get(c) or COMMON.get(c, "")
            lines.append(f"| {i} | `{c}` | {TYPE_SHORT.get(typ, typ)} | {'Y' if null == 'NO' else ''} | {d.replace('|', '¦')} | {'<br>'.join(keys)} | {desc} | {checks_for(t, c).replace('|', '¦')} |")
        multi = [(nm, d) for nm, ct, d in cons[t] if ct in "u" and "," in d]
        pkmulti = [(nm, d) for nm, ct, d in cons[t] if ct == "p" and "," in d]
        if multi or pkmulti:
            lines += ["", "복합 키: " + "; ".join(f"`{d}`" for _, d in pkmulti + multi)]
        multi_checks = [
            (nm, d) for nm, ct, d in cons[t]
            if ct == "c" and len(constraint_columns.get((t, nm), set())) > 1 and "ANY" not in d
        ]
        if multi_checks:
            lines += ["", "여러 컬럼 CHECK: " + "; ".join(f"`{nm}` = `{d}`" for nm, d in multi_checks)]
        other_idx = [(nm, d) for nm, d in idx[t] if not nm.endswith("_pkey") and not nm.endswith("_key")]
        if other_idx:
            lines += ["", "인덱스: " + "; ".join(fmt_index(nm, d) for nm, d in other_idx)]
        lines.append("")
    n += 1

lines += [
    f"## {n}. 현행에 없는 것 (재구현 예정)",
    "",
    "아직 없는 구조. 해당 Phase에서 Alembic 리비전으로 추가한다(상세·결정 대기 항목은 `06_미결_이슈_목록.md`).",
    "",
    "| 예정 Phase | 테이블·컬럼 |",
    "|---|---|",
    "| ~~2~~ | Phase 2(0003)에서 반영: 버전·청크·청크↔사진·흐름도·staging 분리. 해시 공유 이미지 저장소(`tb_image_assets`)는 만들지 않음(P2-5) |",
    "| 3 (작업 큐·개정본) | `tb_ingest_jobs`의 큐·재시도·임대 컬럼(`queue_cd`, `priority`, `attempts`, `locked_until`, `heartbeat_at`, `next_run_at`, `idempotency_key`, `document_id`, `version` 등) |",
    "| 4 (검색·답변·권한) | 문서 단위 권한(D-20), 대화 메시지 테이블(05 P0-3), 용어 사전(D-03), 청크·셀 출처(`context_meta` 보강) |",
    "| 4.5 (음성) | STT API 연결은 구현됨. `tb_voice_transcriptions`, `tb_query_logs.input_mode` 및 인식 원문·수정 여부 저장은 미구현(현행 테이블·컬럼 아님) |",
    "| 5·7 | `tb_model_config`(D-10), 평가 확장 |",
    "",
]
lines += [
    f"## {n + 1}. STT 실행 경로와 현행 데이터 저장 범위",
    "",
    "2026-10-20 코드 확인 기준. 상세 API·함수·파일 형식은 [STT 처리 흐름](reports/stt-process-flow.md)을 참조한다.",
    "",
    "| 처리 시점·데이터 | 현행 저장 위치·동작 |",
    "|---|---|",
    "| 브라우저 녹음 원본(WebM/MP4/Ogg 등) | 브라우저 File·Blob URL로 유지. 적용·취소·재녹음 시 정리. DB 영구 저장 없음 |",
    "| `POST /api/voice/transcriptions` | create_transcription() → VoiceAsrClient.transcribe(). 업로드 바이트를 ASR로 전달하고 JSON text 반환. DB 쓰기 없음 |",
    "| ASR 인식 원문·사용자 수정본 | 프론트 transcript 상태 및 입력창에서 관리. 별도 인식 이력·수정 비교 데이터 저장 없음 |",
    "| language, duration_ms, MIME, 파일명·크기 | STT 관련 요청 데이터이며 DB 컬럼 아님. duration_ms는 현재 백엔드 라우트에서 사용하지 않음 |",
    "| 질문에 적용 | 입력창 값 교체 및 녹음 정리. 이 동작만으로 질의 로그·대화 이력이 생성되지 않음 |",
    "| 최종 질문 전송 | /api/query/stream → RAGService → QueryRecorder.record() → log_query(). tb_query_logs.query_text에 최종 질문 기록 |",
    "| 답변·문맥·사용량·출처 | 기존 질의 기록 경로에서 tb_query_logs와 tb_query_citations 사용. ASR 결과·사용량 기록이 아님 |",
    "| 대화 이력 | RAGService._save_stream_history()가 유효한 세션·컬렉션에 질문·답변을 tb_query_sessions.conversation_history로 저장 |",
    "| 음성 입력 여부·인식 수정 여부 | 현행 요청·스키마에 저장 경로 없음. 저장된 질문만으로 음성/키보드 입력을 구분할 수 없음 |",
    "| ASR URL·모델·인증·timeout | Settings의 VOICE_ASR_* 환경 설정 사용. tb_llm_models·tb_user_llm_settings의 답변 모델 선택과 별개 |",
    "",
    "현재 conversation_history의 스트리밍 저장 항목은 사용자 {role, content}, 답변 {role, content, citations, images}이며, 음성 파일·인식 원문·ASR 모델을 포함하지 않는다. images는 답변 관련 이미지이며 녹음 파일이 아니다.",
    "",
    "tb_voice_transcriptions와 tb_query_logs.input_mode는 향후 설계 항목으로만 유지한다. 현재 구현에 없는 컬럼의 타입·FK·기본값을 확정된 스키마처럼 추가하지 않는다. STT 연결만으로 새 마이그레이션이 필요한 것은 아니다.",
    "",
    "확인 근거: app/routes/voice.py, clients/voice_asr_client.py, routes/query.py, services/query_recorder.py, services/rag_service.py, repositories/query_log_repository.py, migrations/versions/0001~0005 및 프론트 useVoiceRecorder.js·useChatView.js·ChatView.vue. 실제 운영 DB 적용 상태는 이번 설명 갱신에서 검증하지 않았다.",
    "",
]
open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
print("ok", len(cols), "tables")
