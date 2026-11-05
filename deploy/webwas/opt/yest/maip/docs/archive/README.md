# 보관함 — 구축 과정 기록

> **여기는 현행 사실이 아니다.** 지금 제품이 무엇이고 어떻게 동작하는지는
> [docs/README.md](../README.md) 의 문서를 본다. 여기 문서는 **쓴 날의 원문 그대로**이며
> 고치지 않는다. 그래서 안의 링크·파일 경로·건수는 지금과 다를 수 있다.

제조AI플랫폼은 MES(Backbone)를 복제하고 데이터 관리·비전 검사 기능을 이식해 만들었다
(2026-09-30 ~ 10-06). 그 과정의 분석·계획·결정·작업 기록이다.

| 문서 | 무엇 |
|---|---|
| `01_CURRENT_STATE_ANALYSIS.md` | 원본 저장소 3개의 현황 분석 |
| `02_FEATURE_MAPPING.md` | 원본 기능 → 통합 기능 매핑 |
| `03_CONFLICT_ANALYSIS.md` | 패키지명·app label·테이블 충돌 분석 |
| `04_TARGET_ARCHITECTURE.md` | 통합 목표 구조(설계 당시) |
| `05_DATABASE_MIGRATION_PLAN.md` | DB 이관 계획 |
| `06_API_COMPATIBILITY_PLAN.md` | API 호환 계획. §2 는 GPU 추론 서버 계약 초안 |
| `07_IMPLEMENTATION_PLAN.md` | Phase 별 구현 계획 |
| `09_UI_DESIGN_SYSTEM.md` | 디자인 통일 계획과 Phase 기록 |
| `IMPLEMENTATION_STATUS.md` | 날짜별 작업 기록과 그때의 남은 일 |
| `SCREEN_MAPPING.md` | 원본 화면 → 통합 화면 이관표 |
| `USER_DECISIONS.md` | 결정 원문(§2 분석 포함). **지금 유효한 결정은 [DECISIONS.md](../DECISIONS.md)** 에 같은 ID 로 있다 |
| `superpowers/` | 실행을 마친 구현 계획·설계 |

코드 주석의 `USER_DECISIONS §1.6 O-8`·`§1.65 DEC-C2` 같은 표기는 위 `USER_DECISIONS.md` 의
절 번호다. 같은 ID 가 [DECISIONS.md](../DECISIONS.md) 에 있다.
