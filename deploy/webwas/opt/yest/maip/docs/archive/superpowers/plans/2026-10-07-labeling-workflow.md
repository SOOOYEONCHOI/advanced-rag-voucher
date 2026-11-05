# 라벨링 워크플로우 개선·전체 흐름 테스트 · 0.1.6 반입 · 작업 대기열 삭제 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 이미지를 화면 영역에 맞춰 보이게 하고, "Client 전송 → 데이터 목록 확인·편집 → 라벨링(BBOX·Polygon) → 검수(재작업·확인) → 스냅샷 → zip 받기" 전체를 자동·수동으로 검증할 수 있게 한다. 이어서 Client 0.1.6 반입을 마무리하고 작업 대기열 화면을 지운다.

**Architecture:**
- **이미지 맞춤 표시:** `data/annotation.js` 에 "상자에 맞춤" 함수를 두고 미리보기(데이터 목록·검수)와 라벨링 캔버스가 같은 계산을 쓴다. 라벨링 확대는 "맞춤 크기 × 배율"이다.
- **좌표:** 겹침(BBOX·Polygon)은 이미 % 좌표이고, 클릭 좌표는 `getBoundingClientRect` 기준이라 표시 크기가 바뀌어도 원본 픽셀 좌표가 유지된다.
- **흐름 검증:** e2e 하나가 임시 Client 자격증명으로 실제 `/api/v1/inspections` 에 JPEG 를 보내고 화면을 눌러 zip 까지 받는다. 사람이 해 볼 수 있도록 샘플 전송 도구(`scripts/send_inspections.py`)와 점검 순서를 둔다.

**Tech Stack:** Django 5.0.4 · WeZonGrid · Playwright e2e · Pillow · requests(이미 의존성)

**Spec:** 사용자 요청(2026-10-07, 아래 "요청". P-1·P-7 은 사용자 확정, 나머지는 제안대로) · `docs/STATUS.md` §3 우선순위 · 작업 대기열 삭제 영향 조사(아래 "조사로 확인한 사실")

## Global Constraints

- 사용자 문구는 `~합니다` 체(`~해 주세요` 포함, `~하세요`·`~할까요?` 는 그대로)
- 데이터 화면 API 는 `/api/item/<view>`(DECISIONS DEC-028). `/api/v1` 응답은 바꾸지 않는다
- 테스트는 `--settings=configurations.test_settings`. e2e 는 `E2E-`·`e2e-` 데이터만 만들고 `finally` 로 지운다
- 비밀(API Key)은 소스·로그·커밋에 넣지 않는다. 도구는 환경변수로 받는다
- 하드코딩 색 금지(`tokens.css` 토큰), 새 버튼 클래스 금지
- 커밋 메시지는 한국어, main 에 직접 커밋하지 않는다

---

## 요청 (2026-10-07)

| # | 요청 |
|---|---|
| U-1 | 데이터 목록 상세·라벨링 선택 이미지·검수 상세 이미지가 **영역에 맞게 100%** 로 보인다 |
| U-2 | Client 가 보낸 이미지를 데이터 목록에서 확인·편집 → 라벨링에서 BBOX 또는 Polygon → 검수에서 재작업 또는 검수 완료 → 스냅샷 → 데이터셋 zip 받기, **전체를 테스트할 수 있게** 한다 |
| U-3 | 남은 작업 1번(Client 0.1.6 반입 마무리)과 2번(작업 대기열 **지우기**)도 포함한다 |
| U-4 | Client 전송뿐 아니라 **사용자가 데이터 목록에서 직접 올린 이미지**도 같은 흐름으로 확인한다 |

## 조사로 확인한 사실

| 사실 | 위치 | 계획에 미치는 것 |
|---|---|---|
| 미리보기 이미지는 `max-height: 500px; width: auto` 라 원본보다 커지지 않는다. 64×48 이미지는 64×48 로 보인다 | `data/preview.css` `.image-detail-coordinate-surface > img` | Task 1 |
| 라벨링 캔버스 이미지는 `max-width: min(100%, 1100px); max-height: 70vh` 이고 확대는 `transform: scale()` 이다. 작은 이미지는 작게, 확대하면 영역 밖으로 넘쳐도 스크롤 크기가 늘지 않는다 | `data/governance.css:32`, `labeling.html` `updateZoom` | Task 1 — 실제 크기(px)로 바꾼다 |
| 클릭 좌표·Polygon 시작점 판정은 `getBoundingClientRect` 기준이고 겹침은 % 좌표다 | `labeling.html` `imagePoint`·`polygonStartHit`·`renderBoxes` | 표시 크기를 바꿔도 저장 좌표가 원본 픽셀로 유지된다. e2e 좌표 검사로 지킨다 |
| **Export 가 원본 형식과 무관하게 이미지 이름을 `.png` 로 붙인다.** `zip_file.write(image.file.path, f"images/{sha}.png")` — Client 이미지(JPEG)가 "확장자 png, 내용 JPEG" 로 들어간다 | `export/base.py:13-19`, `coco.py:21`, `yolo.py:22`, `mvtec.py:40,67,96` | Task 2 — 원본 확장자를 쓴다. 형식별 단위 테스트가 지금 없다(STATUS §3-2) |
| 데이터 목록 상세에 "어디서 왔는지"가 없다. Client 이미지는 `ImageAsset.source_inspection_id` 로 검사 기록과 이어진다 | `image_list.py` `detail_payload`, `VisionInspection` | Task 3 — 상세에 수집 경로(Client ID·촬영 시각)를 보인다 |
| Client 자격증명은 화면(`/api/vision/client?action=save`)에서 만들 수 있고 응답에 API Key 가 한 번 온다. **지우는 기능은 없다.** 검사 기록이 있으면 검사항목 삭제가 막힌다(`delete_item`) | `app/views/vision/client.py:47,94`, `item_platform.py:56` | e2e 정리는 `manage.py shell` 도우미(워커 실행 도우미와 같은 방식)로 검사 기록·자격증명을 지운 뒤 검사항목을 지운다 |
| e2e `TestDataPipeline` 은 화면 업로드(PNG)·객체 검출·BBOX·COCO 만 본다. Client 전송·Polygon·이상 탐지·재작업 뒤 다시 라벨링·zip 내용은 보지 않는다 | `tests/e2e/test_write_paths.py:188` | Task 4 |
| 0.1.6 zip 은 `distribution/client/` 에 있고 해시가 맞으며 `client-packages` 가 이미 0.1.6 만 준다. `SHA256SUMS.txt`·요청서 3차 원문은 커밋되지 않았다. **0.1.5 zip 은 보관 폴더(`~/archive/vision-client/`)에도 홈 어디에도 없다**(0.1.4 만 있다) | `git status`, `find ~` | Task 6 |
| 작업 대기열은 `home.html` 하나가 `_base.html`·`data/common.js`·`layout.css`·REST 4경로·`DataApiPermissionMiddleware`·`app/views/data/`·서비스 3개(`queue`·`statistics`·`activity_query`)를 혼자 쓴다. 바깥에서 import 하는 곳이 없다. `main.css` 는 라벨링도 싣는다 | 조사 보고 | Task 7 |
| 작업 대기열 화면의 행이 "undefined · v0.1" 로 나온다(`project_name` ↔ `item_name`) | `home.html:262`, `queue.py:91` | Task 7 로 함께 사라진다 |

## 판단 (제안)

| # | 판단 | 제안 | 이유 |
|---|---|---|---|
| P-1 | "100%" 의 뜻 | **(확정)** **상자에 맞춤(contain)** — 가로·세로 중 먼저 닿는 쪽에 맞춰 비율을 지키며 키우거나 줄인다. 작은 이미지도 키운다 | 요청 그대로. 잘리지 않는다 |
| P-2 | 라벨링 확대·축소 | 100% = 맞춤 크기. 50~400%, 10% 씩이 아니라 25% 씩. 100% 를 넘으면 캔버스가 스크롤된다. 이미지를 바꾸면 100% 로 돌아간다 | 맞춤이 기본이 되면 작은 결함을 보려면 더 크게 키울 수 있어야 한다 |
| P-3 | 미리보기 상자 크기 | 데이터 목록·검수 상세 모두 높이 480px(`--preview-height` 기본값). 너비는 칸 너비 | 두 화면 모두 그리드 아래에 상세가 있어 어느 높이든 페이지가 스크롤된다 — 같은 높이로 맞춘다(실행 중 변경: 처음 제안한 검수 `calc(100vh - 380px)` 은 스크롤을 없애지 못했다) |
| P-4 | Export 이미지 이름 | `images/<sha256>.<원본 확장자>`(`.jpg`·`.png`). 주석 파일(json·txt)의 참조도 같은 이름 | 확장자와 내용이 다르면 학습 도구가 읽다 실패한다 |
| P-4a | (실행 중 발견) CSV·Classification JSON·Anomaly JSON 은 zip 에 이미지 없이 라벨 파일만 넣었다 | 세 형식도 이미지를 넣는다. Anomaly JSON 은 MVTec 폴더 구성(이미지·마스크) + `metadata.json` | 라벨 파일이 가리키는 파일이 zip 에 없으면 데이터셋으로 쓸 수 없다 |
| P-5 | 데이터 목록에 수집 경로 | 상세에 "수집" 행 — `비전검사 클라이언트 CLIENT-001 · 2026-10-07 10:00 촬영` 또는 `화면 업로드`. 그리드에 "수집" 열(클라이언트/화면) | U-2 의 "Client 가 보낸 이미지를 확인" |
| P-6 | 수동 점검 도구 | `scripts/send_inspections.py` — 결함 그림(긁힘·찍힘·정상)을 그린 JPEG 를 만들어 `/api/v1/inspections` 로 보낸다. API Key 는 `VISION_API_KEY` 환경변수로만 받는다. 점검 순서는 `docs/DEVELOPMENT.md` 에 둔다 | 사람이 화면으로 같은 흐름을 따라가 볼 수 있다. 새 문서를 만들지 않는다 |
| P-7 | 0.1.5 zip | **(확정)** 0.1.5 는 찾지 않는다 — **0.1.6 zip 이 대신한다.** 계약 §10-1 예시만 0.1.6 실제 응답으로 바꾸고 **다음 계약 전달 때 함께** 보낸다(응답 형식은 그대로라 Client 영향 없음) | `client-packages` 는 이미 0.1.6 하나를 준다 |
| P-8 | 작업 대기열 | **지운다**(화면·셸·REST·미들웨어·전용 서비스). `main.css` 는 라벨링이 쓰는 규칙만 남긴다. `.toast` 위치 규칙도 지운다 — 라벨링의 `Notify` 가 다른 MES 화면처럼 오른쪽 아래에 뜬다 | 메뉴에서 이미 내린 화면이다. API 규약이 둘(MES·`/api/v1`)로 줄고 DEC-028 이 끝난다 |
| P-9 | 순서·분기 | ① `feat/labeling-workflow`(Task 1~5) → ② `chore/client-016`(Task 6) → ③ `refactor/remove-queue`(Task 7). 단계마다 main 병합 | 요청 순서. ②는 ①과 독립이라 언제든 할 수 있다 |

---

# 단계 ① `feat/labeling-workflow`

### Task 1: 이미지를 영역에 맞춰 보인다 (데이터 목록 상세·검수 상세·라벨링)

**Files:**
- Modify: `app/static/data/annotation.js`(맞춤 함수, `createAnnotationPreview` 옵션), `app/static/data/preview.css`
- Modify: `app/templates/data/image.html`·`review.html`(미리보기 상자 높이), `labeling.html`(`updateZoom`·`zoomBy`·이미지 로드·`ResizeObserver`), `app/static/data/governance.css:30,32`
- Test: `tests/e2e/test_image_fit.py`(신규)

**Interfaces:**
- Produces: `AnnotationView.fitScale(boxWidth, boxHeight, imageWidth, imageHeight) -> number` — 상자에 맞추는 배율(비율 유지). `AnnotationView.createAnnotationPreview(image, alt, {fit: true})` — 미리보기가 부모 상자를 채운다(상자 크기가 바뀌면 다시 맞춘다)

- [x] **Step 1: e2e(RED)** — `tests/e2e/test_image_fit.py`. `E2E-` 검사항목을 만들고 64×48 PNG 1장(아주 작은 이미지)과 1600×1200 PNG 1장(큰 이미지)을 화면 업로드로 올린다. 두 이미지 모두에 대해:
  - 데이터 목록 상세: 미리보기 `<img>` 의 상자(`getBoundingClientRect`)가 `.image-detail-preview` 상자의 가로 **또는** 세로와 2px 안으로 같고, 상자 밖으로 나가지 않는다
  - 라벨링(배율 100%): `#annotationImage` 상자가 `#canvasHolder` 의 안쪽 여백을 뺀 상자에 같은 기준으로 맞는다. `+` 두 번 → 150%: 가로·세로가 1.5배이고 `#canvasHolder` 가 스크롤된다
  - 검수: 이미지를 제출 상태로 만든 뒤(`/api/item/labeling` claim·submit) 상세 미리보기가 같은 기준으로 맞는다

  지금은 64×48 이 그대로라 실패한다.

- [x] **Step 2: `annotation.js`**

```js
  // 상자에 맞추는 배율. 비율을 지키며 가로·세로 중 먼저 닿는 쪽에 맞춘다(작은 이미지는 키운다).
  function fitScale(boxWidth, boxHeight, imageWidth, imageHeight) {
    if (!boxWidth || !boxHeight || !imageWidth || !imageHeight) { return 1; }
    return Math.min(boxWidth / imageWidth, boxHeight / imageHeight);
  }

  // surface(이미지+겹침)의 크기를 px 로 정한다. 겹침은 % 좌표라 함께 따라온다.
  function fitSurface(surface, box, image) {
    var scale = fitScale(box.clientWidth, box.clientHeight, image.width, image.height);
    surface.style.width = Math.floor(image.width * scale) + "px";
    surface.style.height = Math.floor(image.height * scale) + "px";
  }
```

  `createAnnotationPreview(image, alt, options)` 에서 `options.fit` 이면 `preview` 에 `image-detail-preview-fit` 클래스를 붙이고, `ResizeObserver` 로 `preview` 크기가 바뀔 때마다 `fitSurface(surface, preview, image)` 를 부른다(처음 붙을 때 한 번 포함). `window.AnnotationView` 에 `fitScale` 을 내보낸다.

- [x] **Step 3: `preview.css`**

```css
.image-detail-preview-fit { width: 100%; height: var(--preview-height, 480px); }
.image-detail-preview-fit .image-detail-coordinate-surface { max-width: none; max-height: none; }
.image-detail-preview-fit .image-detail-coordinate-surface > img { width: 100%; height: 100%; max-width: none; max-height: none; }
```

  `image.html` 은 `--preview-height: 480px`, `review.html` 은 `--preview-height: max(360px, calc(100vh - 380px))` 를 상세 카드에 둔다. 두 화면의 `createAnnotationPreview(..., {fit: true})`.

- [x] **Step 4: 라벨링 캔버스** — `labeling.html`

```js
        // 100% = #canvasHolder 안쪽에 맞춘 크기. 확대는 그 크기에 배율을 곱한 실제 px 이다
        // (transform 이면 스크롤 영역이 늘지 않는다). 좌표는 getBoundingClientRect 기준이라 그대로 맞다.
        updateZoom() {
            $('#zoomValue').text(this.zoom + '%');
            if (!this.activeImage) { return; }
            const holder = document.getElementById('canvasHolder');
            const style = getComputedStyle(holder);
            const innerWidth = holder.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
            const innerHeight = holder.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
            const scale = AnnotationView.fitScale(innerWidth, innerHeight, this.activeImage.width, this.activeImage.height) * this.zoom / 100;
            $(this.imageElement).css({ width: Math.floor(this.activeImage.width * scale) + 'px', height: Math.floor(this.activeImage.height * scale) + 'px' });
        }

        zoomBy(delta) {
            this.zoom = this.clamp(this.zoom + delta, 50, 400);
            this.updateZoom();
        }
```

  - `applySelectedImage` 에서 `this.zoom = 100; this.updateZoom();`
  - `startWatching` 에 `ResizeObserver(#canvasHolder)` → `updateZoom()`, `destroy` 에서 해제
  - 확대 버튼은 `zoomBy(±25)`
  - 라벨링이 `annotation.js` 를 싣게 한다
  - `governance.css`: `.image-stage` 의 `max-width`·`transform-origin` 삭제, `#annotationImage` 의 `max-width`·`max-height` 삭제. `.canvas-holder` 는 `align-items: safe center; justify-content: safe center`(확대 때 왼쪽 위가 잘리지 않게)

- [x] **Step 5: GREEN** — `test_image_fit.py`, `test_write_paths.py::TestDataPipeline`(BBOX 좌표 검사 포함), `node scripts/verify_screen_js.js`, `verify_tokens.py` 통과. 1920×911 로 세 화면을 캡처해 본다.

- [x] **Step 6: 커밋** `feat: 데이터 목록·라벨링·검수 이미지를 영역에 맞춰 보인다`

### Task 2: Export zip 의 이미지 이름이 원본 형식을 따른다

**Files:**
- Modify: `domain/services/data/export/base.py`(`write_image_or_skip`), `coco.py`·`yolo.py`·`imagefolder.py`·`classification.py`·`mvtec.py`
- Test: `tests/test_export_formats.py`(신규)

**Interfaces:**
- Produces: `DatasetExporter.write_image_or_skip(zip_file, image_id, stem) -> str | None` — `stem` 은 확장자 없는 경로(`images/<sha256>`). 저장한 이름(`images/<sha256>.jpg`)을 돌려주고 파일이 없으면 None. 주석 파일은 이 반환값을 참조한다

- [x] **Step 1: 단위 테스트(RED)** — 형식 8종마다: JPEG 이미지 1장(+ 유형에 맞는 주석: OD 는 BBOX, 분류는 라벨, 이상 탐지는 이상 판정 + Polygon)을 승인 → `create_snapshot(..., format)` → `JobService.run_pending()` → zip 을 연다.
  - zip 안 이미지 이름이 `.jpg` 로 끝난다
  - 그 바이트가 `\xff\xd8` 로 시작한다
  - 주석 파일(COCO `annotations/instances.json` 의 `file_name`, MVTec `metadata.json` 의 `file_name`, 분류 CSV·JSON 의 경로)이 그 이름을 가리킨다
  - YOLO 는 `labels/<sha256>.txt` 가 있고 좌표가 0~1 사이다
  - MVTec 은 `ground_truth/<유형>/<sha256>_mask.png` 가 PNG 이고 흰 픽셀이 있다

  지금은 이름이 `.png` 라 실패한다. 이 테스트가 STATUS §3-2 의 "Export 형식별 결과" 공백을 채운다.

- [x] **Step 2: 구현** — `base.py`:

```python
    def write_image_or_skip(self, zip_file, image_id, stem):
        """원본 파일을 원본 확장자로 zip 에 넣고 그 이름을 돌려준다. 저장소에 없으면 None."""
        image = ImageAsset.objects.for_tenant(self.item.tenant).get(pk=image_id)
        if not image.file or not image.file.storage.exists(image.file.name):
            return None
        arcname = f"{stem}{Path(image.file.name).suffix.lower() or '.png'}"
        zip_file.write(image.file.path, arcname)
        return arcname
```

  각 exporter 는 `f"images/{sha}.png"` 대신 `stem=f"images/{sha}"` 를 넘기고, 돌려받은 이름을 주석 파일에 쓴다. 마스크(`_mask.png`)는 서버가 그리는 PNG 라 그대로 둔다.

- [x] **Step 3: GREEN · 커밋** `fix: Export zip 이 이미지를 원본 형식의 확장자로 담는다`

### Task 3: 데이터 목록에서 Client 가 보낸 이미지를 알아본다

**Files:**
- Modify: `domain/services/data/image_list.py`(`detail_payload`), `app/views/item/image.py`(목록 행), `app/templates/data/image.html`
- Test: `tests/test_item_api.py`(`ImageApiTest`)

- [x] **Step 1: 테스트(RED)** — Client 전송으로 들어온 이미지(`ClientApiTestCase` 방식으로 `/api/v1/inspections`)는 목록 행 `source == '클라이언트'`, 상세 `source == {'kind': 'CLIENT', 'client_id': 'CLIENT-TEST', 'captured_at': '...', 'inspection_id': '...'}`. 화면 업로드는 `source_label == '화면 업로드'`, 상세 `source.kind == 'UPLOAD'`.
- [x] **Step 2: 구현** — `source_inspection_id` 가 있으면 `VisionInspection` 을 한 번 읽어 채운다(목록은 페이지 행의 id 로 한 번에 읽는다).
  - 그리드에 "수집" 열(클라이언트/화면 업로드)을 둔다.
  - 상세에 "수집" 행을 둔다. 예: `비전검사 클라이언트 CLIENT-001 · 2026-10-07 10:00 촬영`.
- [x] **Step 3: GREEN · 커밋** `feat: 데이터 목록에 이미지가 Client 전송인지 화면 업로드인지 보인다`

### Task 4: 전체 워크플로우 e2e — Client 전송부터 zip 받기까지

**Files:**
- Create: `tests/e2e/test_client_workflow.py`
- Modify: `tests/e2e/conftest.py`(공용 도우미 `manage_shell(code)` — `run_worker_once` 와 같은 subprocess 방식)

**도우미·준비**

| 이름 | 하는 일 |
|---|---|
| `vision_client` 픽스처 | 관리자로 `/api/vision/client?action=save` 에 `E2E-WF-<시각>` 자격증명을 만들고 응답의 API Key 를 받는다. 끝나면 `manage_shell` 로 그 Client 의 검사 기록·자격증명·서비스 계정을 지운다(화면에 삭제 기능이 없다) |
| `workflow_item(task_type, labels)` | 검사항목을 만들고(`/api/item/item_admin?action=create`) 라벨 클래스를 더한다(`/api/item/item_home?action=label_create`). 끝나면 `vision_client` 정리 **뒤에** 기존 `_cleanup`(일시 중지 → 삭제 요청 → 승인)으로 지운다 |
| `send_capture(page, client, item_id, image_bytes)` | `page.request.post('/api/v1/inspections', headers={X-Client-ID, X-API-Key}, multipart={'image': {...jpeg}, 'metadata': json})` → 201 |
| `defect_jpeg(kind)` | 640×480 회색 판에 긁힘(대각선)·찍힘(원)을 그린 JPEG. `kind='normal'` 은 무늬만 |

- [x] **시나리오 1: 객체 검출 · BBOX** (`test_객체검출_전송부터_COCO_zip_까지`)

  1. 라벨 `scratch` 로 검사항목을 만들고 JPEG 3장(긁힘 2·정상 1)을 Client 로 보낸다. **데이터 목록 [업로드]로 PNG 1장(긁힘 3)을 직접 올린다**(U-4)
  2. **데이터 목록**: 그리드 4행, "수집"이 "클라이언트" 3·"화면 업로드" 1이다. 첫 행 상세의 미리보기가 맞춤 크기다. 정상 이미지를 [이미지 편집] → 오른쪽 90° 회전 → 원본 복원(저장 2번)
  3. **라벨링**: 긁힘 1을 작업 시작 → `scratch` → BBOX(긁힘 둘레) → 임시 저장 → 작업 완료. 긁힘 2·긁힘 3(화면 업로드)도 같게. 정상 이미지는 작업 시작 → 작업 완료 → "결함 없음으로 제출" 확인
  4. **검수**: 긁힘 1 은 재작업 요청(사유 `E2E 경계를 넓혀 주세요`), 나머지 셋은 검수 완료
  5. **라벨링(재작업)**: 긁힘 1 에 재작업 사유 배너가 보인다. 기존 BBOX 삭제 → 다시 그림 → 임시 저장 → 작업 완료
  6. **검수**: 긁힘 1 검수 완료. 검수 목록이 비었다
  7. **스냅샷**: 등록(COCO) → `run_worker_once()` → [조회] → 상태 "완료" → **화면의 [받기]를 눌러** `page.expect_download()` 로 zip 을 받는다
  8. **zip 검사**: `images/*.jpg` 3개(JPEG 바이트)·`images/*.png` 1개(PNG 바이트), `annotations/instances.json` 의 이미지 4·주석 3·카테고리 `scratch`. 긁힘 1 의 bbox 는 **다시 그린** 좌표다(원본 픽셀 기준, 그린 비율 ±3%)

- [x] **시나리오 2: 이상 탐지 · Polygon** (`test_이상탐지_전송부터_MVTec_zip_까지`)

  1. 이상 탐지 검사항목(라벨 `dent`)에 JPEG 1장(찍힘)을 Client 로 보내고, JPEG 1장(정상)을 데이터 목록 [업로드]로 올린다(U-4)
  2. **라벨링**: 찍힘은 `dent`(이상) → Polygon 4점 → Enter → 임시 저장 → 작업 완료. 정상은 "정상" → 작업 완료
  3. **검수**: 둘 다 검수 완료
  4. **스냅샷**: 등록(MVTec AD) → 워커 → 화면에서 받기
  5. **zip 검사**: `train/good/<sha>.jpg` 1개, `test/dent/<sha>.jpg` 1개, `ground_truth/dent/<sha>_mask.png` 의 흰 영역이 Polygon 둘레 안이다(무게중심이 그린 4점의 무게중심 ±5%)

- [x] **실행** — 개발 서버가 떠 있어야 한다. 워커는 따로 띄우지 않아도 된다(테스트가 `run_worker_once` 로 돌린다). `.venv/bin/python -m pytest tests/e2e/test_client_workflow.py -q`. 실패하면 각 단계 화면을 `tmp_path` 에 캡처해 남긴다(`page.screenshot` 를 `finally` 에서)
- [x] **커밋** `test: Client 전송부터 데이터셋 zip 까지 전체 워크플로우 e2e 를 더한다`

### Task 5: 사람이 따라 해 볼 수 있게 — 샘플 전송 도구와 점검 순서

**Files:**
- Create: `scripts/send_inspections.py`
- Modify: `docs/DEVELOPMENT.md`(검증 스크립트 표 + "라벨링 워크플로우 수동 점검" 절), `docs/FEATURES.md`(데이터 흐름 그림에 zip 받기까지)

- [x] **도구**

```
VISION_API_KEY=<발급받은 키> .venv/bin/python scripts/send_inspections.py \
    --client-id E2E-MANUAL --item-id 3 --kind scratch --count 5 [--base-url http://127.0.0.1:8123]
```

  - `--kind` 는 `scratch`·`dent`·`normal`·`mixed`, 또는 `--images <폴더>`(실제 사진)를 받는다
  - 요청마다 `request_id`(UUID)·HTTP 상태·검사 id 를 한 줄로 찍고, 키는 출력하지 않는다
  - 실패한 응답은 봉투의 `error.code`·`message` 를 그대로 보인다
  - 그림 생성 함수는 e2e `defect_jpeg` 와 같은 것을 쓴다(`scripts/` 에 두고 e2e 가 import 한다)
  - 자기 점검 `--self-check` 는 서버 없이 그림 생성과 metadata 조립만 확인한다

- [x] **DEVELOPMENT.md 수동 점검 순서**
  1. 비전검사 클라이언트 화면에서 `E2E-MANUAL` 등록 → API Key 확인
  2. 도구로 이미지 전송. 데이터 목록 [업로드]로 사진도 몇 장 직접 올린다
  3. 데이터 목록에서 확인 — "수집" 열로 클라이언트·화면 업로드가 구분된다
  4. 이미지 편집
  5. 라벨링(BBOX·Polygon)
  6. 검수(재작업 1건 포함)
  7. 스냅샷 등록 → `run_worker --once` → 받기
  8. zip 열어 확인 — 형식별로 볼 파일 표
  9. 정리 — `E2E-MANUAL` 사용 중지, 검사항목 일시 중지

- [x] **단계 ① 마무리** — 단위·검증 스크립트 10개·e2e 전체 → main 병합. 커밋 `docs: Client 전송 샘플 도구와 라벨링 워크플로우 수동 점검 순서를 더한다`

---

# 단계 ② `chore/client-016`

### Task 6: Client 0.1.6 반입 마무리 (남은 작업 1번)

**Files:** `distribution/client/SHA256SUMS.txt`, `docs/client/SERVER_REQUESTS.md`(사용자가 받아 둔 3차 원문 — 내용을 바꾸지 않는다), `docs/client/SERVER_API_CONTRACT.md` §10-1·§17, `docs/superpowers/plans/2026-10-06-client-requests-followup.md`, `docs/STATUS.md`

- [x] `sha256sum -c` 다시 확인(어제 확인함) → `SHA256SUMS.txt`·`SERVER_REQUESTS.md` 커밋(zip 은 `.gitignore` 대상이라 올라가지 않는다)
- [x] 계약 §10-1 의 `client-packages` 예시를 지금 실제 응답(0.1.6, `6cf3bacb…f7af`)으로 바꾸고 §17 에 한 줄. "다음 전달 때 함께" 로 적는다(P-7)
- [x] 후속 계획 Task 3 체크. 0.1.5 보관본은 찾지 않고 0.1.6 이 대신한다고 적는다(P-7). 남은 Task 5(Overlay 3 삭제) 때문에 계획은 그대로 둔다
- [x] STATUS 우선순위 표 갱신 → 커밋 → main 병합

---

# 단계 ③ `refactor/remove-queue`

### Task 7: 작업 대기열 화면과 그것만 쓰던 것을 지운다 (남은 작업 2번)

조사 보고의 순서를 따른다. 단계마다 단위 테스트와 `verify_permission_map.py` 가 통과해야 한다.

- [x] **Step 0** — `verify_layout_stable.py capture /tmp/geo-before`(라벨링 기준)
- [x] **Step 1: 화면·셸·REST 를 한 커밋으로**(나눌 수 없다 — `DATA_API_MENUS['activity-log']` 가 `wm_data_queue` 를 가리킨다)
  - 삭제: `data/home.html`, `data/_base.html`, `data/common.js`, `data/layout.css`, `configurations/urls_data.py`, `configurations/middleware/data_authz.py`, `app/views/data/`
  - 수정: `settings.py:58`(미들웨어), `urls.py:50-52`, `gui.py:61`(+ 주석 52-53·178-181), `seed_initial.py` `RETIRED_FROM_MENU`, `tests/e2e/test_workflow.py:20`
  - 스크립트: `verify_permission_map.py`(데이터 REST 검사 삭제), `verify_modals.py`(데이터 확인창 항목·순서 검사 블록), `verify_tokens.py:25`(`layout.css` — 없으면 실패한다), `capture_ui.py:33`, `verify_layout_stable.py:33`
- [x] **Step 2: 전용 서비스** — `queue.py`·`statistics.py`·`activity_query.py`, `ItemService.list_item_cards`(+ 남는 import), `workflow_counts`, `HomeQueueTest`
- [x] **Step 3: `main.css` 정리** — 라벨링이 쓰는 규칙만 남긴다(조사 보고 §2 의 유지·수정·삭제 목록). `.toast` 위치 규칙도 지운다(P-8). `verify_layout_stable.py compare` 로 라벨링 레이아웃이 그대로인지, 라벨링 `Notify` 가 오른쪽 아래에 뜨는지 본다
- [x] **Step 4: 남은 것** — `verify_screen_js.js` 의 `DataUI` 검사, `verify_buttons.py` 의 데이터 버튼 계열, e2e `test_crud.api()`(호출하는 곳 없음)와 `test_write_paths.py:20` import, `tokens.css`·`verify_links.py` 주석, 디스크의 `app/views/data/__pycache__`
- [x] **Step 5: 문서** — AGENTS [2](규약 둘), ARCHITECTURE(API 규약·화면층·미들웨어), DECISIONS(DEC-014·DEC-028 에 "REST 제거 완료" 주석), DEVELOPMENT, FEATURES, UI_GUIDE(데이터 셸·`DataUI`·`<dialog>` 계열 삭제), STATUS(우선순위 8 갱신, 대기열 결함 행 삭제)
- [x] **마무리** — 단위·검증 스크립트·e2e 전체 → main 병합. 커밋은 단계마다 `refactor: …`

---

## 범위 밖

- `?project=` 를 `item_id` 로 바꾸기(STATUS 보류)
- 라벨링 대기열 서버 페이징, 워커 heartbeat — 수천 장·1시간 넘는 Export 가 생길 때
- Client 자격증명 삭제 기능(화면) — e2e 는 `manage_shell` 로 정리한다. 운영에서 필요하면 따로 정한다
- 검사항목 3 Overlay 삭제 — Client 통보 대기
