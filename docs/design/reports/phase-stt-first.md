# STT 선행 연결 — 2026-10-16

사용자 요청에 따라 Phase 3보다 먼저 진행. R5-1 / F-4-05 / SC-02 / UI-07. 현재 프런트엔드의 녹음 완료·미리듣기 단계를 유지한다.

## 변경

- `adrag_frontend/src/api/voiceApi.js`: 기존 인증 클라이언트로 `POST /api/voice/transcriptions` 호출, 취소 신호·35초 제한.
- `adrag_frontend/src/composables/useVoiceRecorder.js`: 명시적 텍스트 변환, 결과·오류 상태, 닫기·재녹음·주제 변경·화면 이탈 시 요청 취소 및 늦은 결과 무시.
- `adrag_frontend/src/views/ChatView.vue`: 기존 미리듣기 유지 → [텍스트 변환] → 결과 확인·수정 → [질문에 적용]. 질문 입력창으로 옮긴 후 기존 전송 버튼으로 전송하며 자동 전송 없음.
- `adrag_backend/app/core/config.py`, `main.py`: 기존 ASR 클라이언트의 누락 설정 및 라우터 등록 복구.
- `adrag_frontend/tests/voiceTranscription.test.mjs`, `adrag_backend/tests/test_voice_routes.py`, `tests/conftest.py`: STT 검증 및 수집 복구.

## 설정·데이터

백엔드 `VOICE_ASR_API_URL`에 사내 Qwen3-ASR 서버 주소를 지정하고 재시작한다. 미설정 시 STT는 503으로 비활성화되며 녹음·미리듣기는 유지한다. 외부 AI API 호출이나 운영 서버 접속은 하지 않았다.

선택 설정: `VOICE_ASR_API_KEY`(미지정 시 `VLLM_API_KEY`), `VOICE_ASR_MODEL_NAME`(기본 Qwen/Qwen3-ASR-1.7B), `VOICE_ASR_TIMEOUT`(기본 30초), `VOICE_MAX_UPLOAD_BYTES`(기본 10MB).

DB 마이그레이션 없음. 오디오를 서버 파일로 저장하지 않는 기존 API를 사용한다. 적용·닫기·재녹음 시 브라우저 파일과 객체 URL을 해제한다.

## 검증

- `npm run build`: 통과(번들 크기 경고 있음).
- `node --test tests/voiceTranscription.test.mjs`: 1 passed. 미리듣기 유지, 결과 공백 정리, API 실패 후 녹음 유지, 취소 신호 전달, 늦은 결과 무시 검증. 컴포넌트 밖 composable 호출에 따른 Vue lifecycle 경고 있음.
- `python -m pytest tests/test_voice_routes.py tests/test_voice_asr_client.py -q`: 9 passed. 정상 호출, 인증, 형식, 빈 파일, 비활성화, 서버 실패, ASR multipart 계약 검증.
- 실제 마이크·사내 ASR 서버를 통한 음성 인식 및 브라우저 시각 검증은 미실시.

## 남은 범위·되돌리기

이번 작업은 STT 선행 연결이며 Phase 4.5 전체 완료는 아니다. 용어 사전 보정, `tb_voice_transcriptions` 저장, `input_mode`·수정 여부 기록, [바로 질문], 1초 미만 서버 검증·504 구분, TTS는 후속 작업이다. Phase 3는 진행하지 않았다.

STT만 끄려면 `VOICE_ASR_API_URL`을 비우고 백엔드를 재시작한다. UI를 이전으로 복원하려면 위 프런트엔드 변경을 되돌린다. 데이터 복구 작업은 필요 없다.

## 요구사항 정의서·기능 목록에 반영할 것

UI-07 흐름에 녹음 완료 후 미리듣기와 명시적 [텍스트 변환] 단계를 반영한다(사용자 지정). 선행 연결 범위와 후속 Phase 4.5 범위를 구분한다.
