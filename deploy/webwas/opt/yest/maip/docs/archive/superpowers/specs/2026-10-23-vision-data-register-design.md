# 비전 데이터 등록 화면 설계

날짜: 2026-10-23. 사용자 승인: 2026-10-23(권장안 전부 + 상세 영역 [이미지 편집]·[삭제]).

## 목적

검사항목별 비전 데이터를 웹에서 카메라나 파일로 바로 등록한다. 지금은 양식 "사진 넣기"나 비전검사항목 홈 › 데이터 목록 탭을
거쳐야 한다. 대시보드에서 최근 등록 현황을 보고 이 화면으로 넘어간다.

## 결정

| # | 항목 | 결정 |
|---|---|---|
| 1 | 메뉴 | "비전 데이터 관리" 폴더의 **첫 메뉴** `wm_data_register` "비전 데이터 등록". 그 아래 분류 › 비전검사항목 트리는 그대로다 |
| 2 | 권한 | 그 메뉴 R = 목록·상세, W = 등록·편집·삭제. 데이터 목록 W 는 요구하지 않는다. 검수 완료 이미지 삭제는 지금처럼 검수 작업 W 도 있어야 한다 |
| 3 | 등록 대상 | 사용 중(ACTIVE) 비전검사항목. 치수 측정 항목은 뺀다 |
| 4 | 같은 사진 | 파일은 같은 내용을 거절, 카메라는 허용(사진 넣기와 같다) |
| 5 | 등록 경로·등록자 | 이미지에 `channel`(클라이언트·파일 업로드·카메라 촬영·양식 사진 넣기)과 `uploaded_by` 를 더한다. 마이그레이션 `0021`. 기존 행은 Client 수신이면 클라이언트, 아니면 파일 업로드. 등록자는 비운다 |
| 6 | 대시보드 | 요약 카드 "최근 7일 비전 데이터 등록": 합계·경로별 수·항목별 상위 5개. 카드 → 등록 화면, 항목 줄 → 그 항목으로 거른 등록 화면. 새 메뉴 R 이 없으면 카드를 감춘다 |
| 7 | 상세 영역 | 보기 + 오른쪽 위 [이미지 편집]·[삭제]. 편집·삭제 규칙은 데이터 목록과 같다(라벨링 전만 편집, 작업 중·스냅샷 포함은 막음) |

## 화면 (`data/register.html`)

- 조회: 비전검사항목(전체/하나), 등록 경로, 등록일 기간(기본 최근 7일), 파일명. [조회]
- 목록 머리 오른쪽 [데이터 등록](W). 목록: 썸네일·비전검사항목·등록 경로·파일명·진행 단계·등록자·등록일시. 서버 페이징 50건, 등록일 최신순
- 상세(목록 아래): 왼쪽 원본(확대·이동, `ImageZoom`), 오른쪽 표 — 비전검사항목(코드·이름)·등록 경로(클라이언트면 Client·촬영 시각)·등록자·등록일시·원본 파일명·크기(해상도·용량)·진행 단계. 머리 오른쪽 [이미지 편집]·[삭제](W, 막히면 비활성 + 이유 툴팁)
- [데이터 등록] 모달: 비전검사항목 선택(대상 항목만, "분류 › 이름" 묶음) → 등록 유형 [카메라]/[파일]
  - 카메라: 공용 카메라 촬영(Overlay = 그 항목 Overlay 가 표시 중이면 설정 불투명도). HTTPS·localhost 가 아니면 기기 카메라 앱(Overlay 없음)
  - 파일: 여러 장(20장씩 나눠 보냄), 결과(올림 n·거절 목록)를 알린다
  - 등록 뒤 목록을 다시 읽고 첫 행을 고른다
- 주소 `?inspection_item=<id>` 로 열면 그 항목으로 거른다(대시보드에서 연다)

## API

`/api/item/register` (`app/views/item/register.py`, `gui.py` 매핑 `wm_data_register`)

| action | 메서드 | 입력 | 결과 |
|---|---|---|---|
| list | GET | item_id?, channel?, date_from, date_to, q, page, page_size | rows(id·thumbnail_url·item_code·item_name·channel_label·original_name·workflow_status_label·uploaded_by·created_at) |
| detail | GET | image_id | `ImageListService.detail_payload` + item·channel·uploaded_by·source |
| items | GET | — | 등록 대상 항목(id·code·name·category·overlay_url·overlay_opacity) |
| upload | POST | item_id, kind(FILE/CAMERA), files | uploaded·rejected |
| preprocess | POST | image_id, Q={"operations": [...]} | image |
| delete | POST | image_id | success |

`/api/vision/dashboard` (`app/views/vision/dashboard.py`, 매핑 `wm_dashboard`) — action `summary`: `{"register": null | {days, total, by_channel[], by_item[]}}`. `register` 는 요청자가 `wm_data_register` R 일 때만 준다.

## 공용 부품

- `data/camera_capture.html` — 카메라 영상 + Overlay + [촬영]/[다시 찍기]/[사용] + HTTP 대체. 양식 사진 넣기(`dig_form_capture.html`)와 등록 화면이 같이 쓴다
- `data/preprocess_modal.html` — 이미지 편집 모달과 JS. 데이터 목록과 등록 화면이 같이 쓴다

## 하지 않는 것

라벨링·검수는 이 화면에서 하지 않는다. 대시보드의 다른 카드는 예시 값 그대로다. 등록 화면에서 여러 장 일괄 삭제는 없다.
