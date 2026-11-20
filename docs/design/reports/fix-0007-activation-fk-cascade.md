# 대화 주제 삭제 실패 수정 — 0007 적용 이력 FK CASCADE (2026-11-06)

> 관련 ID: UI-12(문서 관리·이전 버전 복원), 변경로그 D-22, 마이그레이션 0006 후속
> 발견: 2026-11-06 운영 재배포(`chatbot-20261106-1519`, 0005 → 0006) 직후 대화 주제 삭제 시 오류

## 1. 증상·원인

- 대화 주제 삭제 → `ForeignKeyViolation: … violates foreign key constraint "tb_document_version_activations_document_id_fkey"`.
- 0006이 만든 `tb_document_version_activations.document_id`가 `tb_documents`를 **ON DELETE CASCADE 없이** 참조한다(0003의 문서 하위 테이블은 모두 CASCADE).
- 0006 업그레이드가 삭제되지 않은 문서마다 `baseline` 이력 1행을 넣으므로, 문서가 있는 대화 주제는 모두
  `collection_service.delete_collection`의 `DELETE FROM tb_documents WHERE collection_id = ?`에서 실패한다
  (`_cleanup_missing_qdrant_collection`도 같은 문장).
- 삭제 순서가 Qdrant → DB라서, 실패한 주제는 **벡터는 지워지고 DB 메타데이터만 남은 상태**가 된다. 0007 적용 후 다시 삭제하면
  "Qdrant에 없는 컬렉션 정리" 경로로 DB까지 정리된다.

## 2. 변경 파일

| 파일 | 내용 |
|---|---|
| `adrag_backend/migrations/versions/0007_activation_fk_cascade.py` | 신규. FK를 `ON DELETE CASCADE`로 다시 만듦. downgrade는 CASCADE 없는 원래 FK. 데이터 변경 없음 |
| `adrag_backend/tests/test_database_migrations.py` | `HEAD` = 0007, 물리 삭제 CASCADE 테스트에 적용 이력 행 추가·대화 주제 삭제 문장(`collection_id`)으로 검증 |

## 3. 완료 기준 근거

- 수정 전: `test_document_physical_delete_cascades_phase2_rows`가 운영과 같은 `ForeignKeyViolation`으로 실패(재현).
- 수정 후: 위 테스트 통과, 왕복(upgrade → base → head) 테스트 통과. 전체 결과는 아래 4절.

## 4. 테스트 결과

- `pytest -q -m "not e2e and not voice"` 전체: 501 passed / 12 failed / 17 skipped / 수집 오류 3.
  - 실패·오류는 이번 변경과 무관하다(FK·적용 이력 관련 메시지 0건). 실패 파일만 따로 돌리면 대부분 통과(실행 순서에 따른 stub 오염),
    단독에서도 실패하는 것은 `test_unified_auth_routes`(로그인 응답에 `ui_type` 필드 추가로 기대값 불일치) 1건.
  - 수집 오류 3건(`test_stats_api`, `test_voice_*`)은 기존과 같다(음성은 `--noconftest`로 따로 실행).
- 묶음: `chatbot-20261106-1628.tar.gz`(0007 포함, 런타임 이미지 `chatbot-backend-runtime:8e9be33989fa` 그대로, 프런트 `index-CUi_zBN_.js`).

## 5. 마이그레이션·배포·되돌리기

- 마이그레이션: 있음(`0007_activation_fk_cascade`, 제약만 변경, 운영 데이터 그대로).
- 배포: 묶음 `deploy.sh`가 `alembic upgrade head`로 적용 → `sudo systemctl restart chatbot`.
- 되돌리기: `alembic downgrade 0006_document_version_restore`(제약만 원복) 후 이전 묶음 `SKIP_MIGRATE=1 ./deploy.sh …`.

## 6. 남은 이슈

- 운영에서 삭제가 실패한 대화 주제(collection_id 2, 6)는 0007 반영 후 화면에서 다시 삭제해야 한다.
