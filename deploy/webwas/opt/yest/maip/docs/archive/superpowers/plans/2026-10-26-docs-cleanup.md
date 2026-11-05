# 마크다운 문서 정리 계획

**목표:** 현행 마크다운 문서에서 코드와 맞지 않는 사실을 정정하고, 중요도가 낮은데 긴 내용을 줄인다.

## 범위

| 구분 | 문서 | 할 일 |
|---|---|---|
| 정리 | AGENTS, README, DESIGN, docs/ 현행 9개, distribution/README, domain/_sql/i18n/README | 사실 정정 + 요약·중복 정리 |
| 계약 정본(서버 관리) | docs/client/SERVER_API_CONTRACT, docs/Wezard/maip-api | 사실 정정만. 고치면 변경 이력에 남긴다 |
| 받은 문서 | docs/client/SERVER_REQUESTS, docs/Wezard/wezard-api | 고치지 않는다. 다른 곳은 보고만 |
| 두 쪽 합의 | docs/Wezard/integration-protocol | 고치지 않는다. 다른 곳은 보고만 |
| 제외 | docs/archive, docs/prd, vendor LICENCE | — |

## 결정 (사용자 2026-10-26)

- DECISIONS.md 는 모든 행을 두고 문장만 줄인다(archive 로 옮기지 않는다)
- 계약 문서는 사실만 정정한다(요약하지 않는다)
- 사실 확인은 서브에이전트 5개가 문서 묶음을 나눠 병렬로 한다. 판정은 컨트롤러가 코드 줄로 다시 확인한다

## 단계

1. **사실 확인(읽기만)** — 경로·명령·설정 키·`.env`·API 경로·오류 코드·테이블·RLS 목록·메뉴 수·테스트·스크립트 옵션·버전을 코드와 대조한다.
   묶음: ① 계약·Wezard·SERVER_REQUESTS ② ARCHITECTURE·DATA_MODEL·SOURCE_CONTROL ③ FEATURES·DESIGN
   ④ DEVELOPMENT·DEPLOYMENT·README·distribution/README·i18n/README ⑤ DECISIONS·STATUS·AGENTS·docs/README
   → 확인: 판정마다 근거 코드 줄. 없으면 "확인 불가"
2. **문서 간 충돌·중복 지도** — 충돌하면 DECISIONS 가 정본. 중복은 정본 한 곳 + 나머지는 한 줄과 링크
3. **요약 범위 표** — 과정 서술·끝난 일 상세·반복 설명을 줄인다. 규칙·금지·절차 명령·운영 근거는 줄이지 않는다
   → 확인: 1~3 결과를 사용자에게 보여 승인받은 뒤 고친다
4. **적용** — 문서별 커밋, 사실 정정과 요약을 커밋으로 나눈다. 절 번호는 유지한다(코드 → 문서 참조 52곳, 문서 간 56곳). 바꾸면 참조를 모두 고친다
5. **검증** — `verify_links`·`verify_naming`·`verify_korean_only`, 절 참조 전수 검사, 줄 수 전후 비교, 처음 보는 리뷰어 검토
