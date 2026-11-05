# 전체 메뉴 정리 · 대시보드(데모) · AI 모델 매핑 화면 정리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 좌측 메뉴를 업무 흐름 기준으로 다시 묶고 이름을 맞추며, 맨 위에 대시보드(데모)를 두어 로그인 첫 화면으로 열고, AI 모델 매핑 화면을 비전검사항목 관리로 합친다.

**Architecture:** 모델 변경 없음. 메뉴는 `seed_initial` `MENU_TREE`·`gui.py` 이름, 첫 화면은 `main_menu` 기본값, 맨 위 단독 메뉴는 `menus.py` 가 폴더를 잎 링크로 바꿔 내려주고 `left_menu_class.html` 이 1단계 링크로 그린다. 모델 매핑 로직은 `domain/services/vision/model_mapping.py` 로 옮기고 화면·API 를 지운다.

**Tech Stack:** Django 5.2 템플릿 · jQuery · Bootstrap 5 · WeZonGrid · Playwright e2e

**Spec:** 사용자 결정 2026-10-21(대화 — M1·M2·M8, N1–N4 추천안, N5 수정안, 첫 화면 = 대시보드)

## Global Constraints

- 메뉴 코드는 바꾸지 않는다(권한·즐겨찾기 유지). 공유 개발 DB 의 `seed_initial` 은 담당자가 돌린다
- 화면 제목 = 메뉴 이름, 문구 `~합니다` 체, 색은 토큰, 사용자 값은 `.text()`
- 테스트 `--settings=configurations.test_settings`, 고친 범위만. e2e 는 작업 공간 서버(8124)

## 목표 메뉴

```text
대시보드                     wm_dashboard (1단계 단독 메뉴, 아이콘, 로그인 첫 화면 — 데모)
검사 작업     수입검사 작성 · 수입검사 결과 · 작업지시 관리 · 품질검사 작성 · 품질검사 결과 · 비전 검사 결과
비전 데이터   (분류 트리 › 비전검사항목 → 내부 탭)
검사 관리     검사양식 관리 · 비전검사항목 관리 · Overlay 관리 · 수입검사 품목 지정 · 판정 코드 관리 · 클라이언트 관리
품목·입고     품목·BOM 조회 · 입고 내역 · 인터페이스 이력
시스템 관리   사용자 · 사용자 그룹 · 메뉴 권한 · 메뉴명 설정 · 로그인 로그 · 메뉴 로그 · 시스템 로그
```

---

### Task 1: 메뉴 구조·이름

**Files:** `domain/management/commands/seed_initial.py`(MENU_TREE), `domain/gui.py`(이름, `DIG_FORM_SCREENS` → "수입검사 작성" 꼴), 화면 제목이 고정 글자인 템플릿(`vision/inspection.html`·`system/usergroup.html`·`usergroup_menu.html`·`login_log.html`·`menu_log.html`·`system_log.html`), `system/form_edit.html` openWrite 제목, 주석. Test: `tests/test_dig_form.py`(SeedInitialDigFormTest·gui), `tests/test_menu_tree.py`, e2e `test_menu.py`·`test_dig_form.py`·`test_inspection_jobs.py`·`test_workflow.py`

- [ ] 시드 뒤 폴더·메뉴 이름·순서가 "목표 메뉴"와 같다는 단위 테스트(RED)
- [ ] MENU_TREE·gui 이름·dig_form 이름 규칙 구현(GREEN)
- [ ] 커밋 `feat: 좌측 메뉴를 업무 흐름 기준으로 다시 묶고 이름·띄어쓰기를 맞춘다`

### Task 2: 대시보드(데모)·첫 화면

**Files:** `domain/gui.py`(`wm_dashboard` → `vision/dashboard.html`), `app/templates/vision/dashboard.html`(새, 예시 값만·API 없음), `seed_initial`(폴더 "대시보드" `uil-chart-line` + 잎 하나), `app/views/system/menus.py`(`TOP_LEVEL_MENU_CODES` 폴더 → `leaf`), `app/templates/app/left_menu_class.html`(leaf 면 1단계 링크), `app/views/__init__.py`(`main_menu` 기본 `wm_dashboard`), `seed_demo`(작업자 그룹 R). Test: `tests/test_menu_tree.py`, `tests/test_login.py`, e2e `test_menu.py`

- [ ] 메뉴 트리가 대시보드를 폴더 없는 1단계 링크로 주고, 기본 첫 화면이 대시보드라는 테스트(RED)
- [ ] 구현(GREEN), 접힌 사이드바·활성 표시 스크린샷 확인
- [ ] 커밋 `feat: 메뉴 맨 위에 대시보드(데모)를 두고 로그인 첫 화면으로 연다`

### Task 3: AI 모델 매핑 화면 정리 · 매핑 열

**Files:** 새 `domain/services/vision/model_mapping.py`(`WEZARD_TASK`·`deployed_models`·`save_mapping`·`active_model_name`), 지움 `app/views/vision/model_mapping.py`·`app/templates/vision/model_mapping.html`, `domain/gui.py`(화면·API 매핑), `app/views/item/item_admin.py`(import), `domain/services/data/category.py`(비전검사항목 행 `model_name`), `app/templates/data/item_list.html`(열 "매핑": 중분류 = 양식, 비전검사항목 = AI 모델), 검증 스크립트 SCREENS. Test: `tests/test_vision_model_mapping.py`(서비스로), `tests/test_item_api.py`(patch 대상), `tests/test_inspection_category.py`, e2e `test_xss.py`·`test_detail_form.py`·`test_grid_common.py`·`test_write_paths.py`·`test_workflow.py`

- [ ] 트리 행에 `model_name` 이 있고 옛 API 가 없다는 테스트(RED)
- [ ] 구현(GREEN)
- [ ] 커밋 `feat: AI 모델 매핑 화면을 지우고 비전검사항목 관리 목록의 매핑 열에 양식·AI 모델을 보인다`

### Task 4: 문서

FEATURES(메뉴 트리·화면 표·§2.1 권한)·DESIGN(화면 목록)·DECISIONS(새 결정, 뒤집힌 2026-10-07 첫 탭 결정 정리)·STATUS·DEVELOPMENT(검증 스크립트 화면 수)·ARCHITECTURE·DEPLOYMENT·README 의 옛 이름

### Task 5: 검증

단위(고친 범위) → 정적 검사 → 8124 e2e(고친 화면) → 모달·버튼·1024 폭·레이아웃 비교 → 전체 단위는 승인 뒤
