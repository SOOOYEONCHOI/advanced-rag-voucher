# 비전 데이터 등록 화면 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "비전 데이터 관리" 첫 메뉴로 비전 데이터 등록 화면(목록·상세·편집·삭제·카메라/파일 등록)을 두고, 대시보드에 최근 7일 등록 요약 카드를 붙인다.

**Architecture:** 이미지에 등록 경로(`channel`)·등록자(`uploaded_by`)를 더하고(마이그레이션 0021, 담당자 적용), 모든 업로드 경로가 이를 채운다. 새 화면은 자기 API `/api/item/register` 하나만 부르고, 카메라 촬영·이미지 편집은 기존 화면에서 떼어 낸 공용 부품을 쓴다. 대시보드는 자기 API `/api/vision/dashboard` 가 메뉴 권한만큼 카드를 내려준다.

**Tech Stack:** Django 5.2, PostgreSQL(RLS), Django Template + jQuery + Bootstrap 5 + WeZonGrid, Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-10-23-vision-data-register-design.md`

## Global Constraints

- 사용자 문구는 `~합니다` 체. 값은 `.text()` 로 넣는다(`.html()` 로 이어 붙이지 않는다)
- 동기 Ajax 금지 — 조회 `AjaxUtil.getAsyncData`, 변경 `postAsyncData`/`postFileAsyncData`
- 새 API 는 `/api/item/<view>` 에 두고 `READ_ACTIONS` 에 조회 action 만. `domain/gui.py` 매핑 필수(`verify_permission_map`)
- 파일은 권한 확인 View 로만 낸다(`/media/image/<id>/`, `/media/image/<id>/thumbnail/`, `/media/overlay/<item_id>/`)
- 마이그레이션은 Django 로만. 모델·마이그레이션은 `migration/<이름>` 브랜치로 따로 push 하고 담당자가 적용한다. 공유 DB 에 `migrate` 를 돌리지 않는다
- 기존 e2e 가 쓰는 id·클래스(`#preprocess*`, `.capture-*`, `DigFormCapture`)는 그대로 둔다
- 테스트: `--settings=configurations.test_settings`. e2e 는 `E2E-` 데이터만 만들고 지운다
- 커밋: Conventional Commits, 한국어, AI 표시 없음

## File Structure

| 파일 | 할 일 |
|---|---|
| `domain/models/data.py` | `ImageAsset.Channel`, `channel`, `uploaded_by` |
| `domain/migrations/0021_image_channel.py` | 칼럼 2개 + 기존 Client 수신 행을 `CLIENT` 로 |
| `domain/services/data/image.py` | `upload_images(..., channel=...)` 가 `channel`·`uploaded_by` 저장 |
| `domain/services/vision/inspection.py`, `domain/services/dig_form_image.py` | 경로별 channel 지정 |
| `app/views/item/image.py` | 수집 열·상세가 `channel` 로 |
| `app/templates/data/camera_capture.html` (새) | 공용 `CameraCapture` |
| `app/templates/dig_form/dig_form_capture.html` | `DigFormCapture` 를 `CameraCapture` 위 얇은 껍데기로 |
| `app/templates/data/preprocess_modal.html` (새) | 편집 모달 + 공용 `PreprocessEditor` |
| `app/templates/data/image.html` | 모달·편집 JS 를 공용 부품으로 |
| `app/views/item/register.py` (새) | `/api/item/register` |
| `app/templates/data/register.html` (새) | 비전 데이터 등록 화면 |
| `domain/gui.py`, `domain/management/commands/seed_initial.py` | 메뉴 `wm_data_register` |
| `app/views/vision/dashboard.py` (새), `app/templates/vision/dashboard.html` | 요약 카드 |
| `tests/test_item_api.py`, `tests/test_data_services.py`, `tests/test_menu_tree.py`, `tests/test_dashboard_api.py`(새) | 단위 |
| `tests/e2e/test_data_register.py`(새), `tests/e2e/test_menu.py` | e2e |
| `docs/FEATURES.md`, `docs/DATA_MODEL.md`, `docs/DECISIONS.md`, `docs/STATUS.md` | 문서 |

---

### Task 1: 이미지 등록 경로·등록자 칼럼 (마이그레이션 브랜치)

**Files:**
- Modify: `domain/models/data.py` (`ImageAsset`, 361행 근처)
- Create: `domain/migrations/0021_image_channel.py`
- Test: `tests/test_data_services.py`

**Interfaces:**
- Produces: `ImageAsset.Channel.{CLIENT,FILE,CAMERA,FORM}`, `ImageAsset.channel`(str), `ImageAsset.uploaded_by`(User|None, `related_name='uploaded_images'`)

- [ ] **Step 1: 브랜치** — `git switch -c migration/image-channel main`
- [ ] **Step 2: 실패하는 테스트** (`tests/test_data_services.py` 끝)

```python
class ImageChannelFieldTest(DataServiceTestCase):
    def test_등록_경로_기본값은_파일_업로드이고_등록자는_비어_있다(self):
        with tenant_atomic(self.tenant):
            image = make_asset(self.item)          # 기존 헬퍼가 없으면 ImageService.upload_images 로 한 장
        self.assertEqual((image.channel, image.uploaded_by_id), (ImageAsset.Channel.FILE, None))
        self.assertEqual(image.get_channel_display(), '파일 업로드')
```

`make_asset` 이 없으면 `ImageService.upload_images(self.item, [make_image()])['uploaded'][0]['id']` 로 만든 뒤 `ImageAsset.objects.for_tenant(self.tenant).get(pk=...)` 로 읽는다.

- [ ] **Step 3: 실행 → FAIL** — `python manage.py test tests.test_data_services.ImageChannelFieldTest --settings=configurations.test_settings` (AttributeError: channel)
- [ ] **Step 4: 모델**

```python
    class Channel(models.TextChoices):
        CLIENT = 'CLIENT', '클라이언트'
        FILE = 'FILE', '파일 업로드'
        CAMERA = 'CAMERA', '카메라 촬영'
        FORM = 'FORM', '양식 사진 넣기'

    # 어떻게·누가 들였는지(사용자 결정 2026-10-23). 옛 행은 Client 수신이면 CLIENT, 아니면 FILE, 등록자는 비어 있다
    channel = models.CharField('등록 경로', max_length=16, choices=Channel.choices, default=Channel.FILE, db_default=Channel.FILE)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='등록자', related_name='uploaded_images',
                                    null=True, blank=True, on_delete=models.SET_NULL)
```

- [ ] **Step 5: 마이그레이션** — `python manage.py makemigrations domain -n image_channel --settings=configurations.test_settings` 뒤 데이터 단계를 더한다(0018 과 같은 방식 — FORCE RLS 라 조직마다 `app.tenant_id` 를 건다)

```python
def client_rows(apps, schema_editor):
    """Client 수신으로 들어온 옛 이미지를 CLIENT 로. vision_data_image 는 FORCE RLS — 조직마다 app.tenant_id 를 건다"""
    Tenant = apps.get_model('domain', 'Tenant')
    Image = apps.get_model('domain', 'ImageAsset')
    for tenant_id in Tenant.objects.values_list('id', flat=True):
        if schema_editor.connection.vendor == 'postgresql':
            schema_editor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_id)])
        Image.objects.filter(tenant_id=tenant_id, source_inspection_id__isnull=False).update(channel='CLIENT')
```

`operations` 끝에 `migrations.RunPython(client_rows, migrations.RunPython.noop)`.

- [ ] **Step 6: 실행 → PASS**, `python manage.py makemigrations --check --dry-run --settings=configurations.test_settings` 로 남은 변경이 없는지 본다
- [ ] **Step 7: 커밋** — `git add domain/models/data.py domain/migrations/0021_image_channel.py tests/test_data_services.py` → `feat: 이미지에 등록 경로·등록자 칼럼을 더한다(0021)`
- [ ] **Step 8: push 는 사용자 확인 뒤** — `migration/image-channel` 을 push 하고 담당자에게 적용을 요청한다(공유 DB `migrate` 는 담당자 몫). 기능 브랜치는 `git switch -c feat/vision-data-register-impl migration/image-channel` 로 이 위에서 시작한다

---

### Task 2: 업로드 경로마다 channel·uploaded_by 채우기, 데이터 목록 "수집" 표시

**Files:**
- Modify: `domain/services/data/image.py:76-124`, `domain/services/vision/inspection.py:141`, `domain/services/dig_form_image.py:226`, `app/views/item/image.py:55,82-90`
- Test: `tests/test_data_services.py`, `tests/test_item_api.py` (`ImageApiTest`), `tests/test_dig_form.py`(capture 테스트)

**Interfaces:**
- Consumes: Task 1 `ImageAsset.Channel`
- Produces: `ImageService.upload_images(item, files, actor=None, requires_labeling=True, requires_labeling_flags=None, allow_duplicate=False, source_inspection_id=None, channel=None)` — `channel` 이 None 이면 `source_inspection_id` 가 있으면 CLIENT, 아니면 FILE. `uploaded_by` 는 `actor` 가 로그인 사용자일 때만

- [ ] **Step 1: 실패하는 테스트**

```python
class UploadChannelTest(DataServiceTestCase):
    def test_경로와_등록자를_남긴다(self):
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image('f.png')], actor=self.worker)
            ImageService.upload_images(self.item, [make_image('c.png', color=(1, 2, 3))], actor=self.worker,
                                       channel=ImageAsset.Channel.CAMERA)
            rows = dict(ImageAsset.objects.for_tenant(self.tenant).values_list('original_name', 'channel'))
            who = set(ImageAsset.objects.for_tenant(self.tenant).values_list('uploaded_by_id', flat=True))
        self.assertEqual(rows, {'f.png': 'FILE', 'c.png': 'CAMERA'})
        self.assertEqual(who, {self.worker.id})
```

`tests/test_item_api.py` `ImageApiTest` 에: 업로드 뒤 목록 `source` 가 `'파일 업로드'`, 상세 `source.kind` 가 `'FILE'`.
`tests/test_dig_form.py` capture 테스트(이미 있는 `action=capture` 테스트)에: 만든 이미지 `channel == 'FORM'`, `uploaded_by == 작성자`.
Client 수신 테스트(`tests/test_client_api.py` 의 검사 전송 성공 테스트)에: `channel == 'CLIENT'`.

- [ ] **Step 2: 실행 → FAIL**
- [ ] **Step 3: 구현**
  - `upload_images` 시그니처에 `channel=None`. 시작에서 `channel = channel or (ImageAsset.Channel.CLIENT if source_inspection_id else ImageAsset.Channel.FILE)`, `uploader = actor if getattr(actor, 'is_authenticated', False) else None`. `ImageAsset.objects.create(..., channel=channel, uploaded_by=uploader)`
  - `dig_form_image.capture_image`: `channel=ImageAsset.Channel.FORM`
  - `vision/inspection.py`: 이미 `source_inspection_id` 를 넘기므로 기본값으로 CLIENT 가 된다(바꾸지 않는다)
  - `app/views/item/image.py`: 목록 `'source': image.get_channel_display()`. `_source` 는 `{'kind': image.channel, 'label': image.get_channel_display(), ...}` 이고 CLIENT 일 때만 Client 정보를 더한다
  - `data/image.html` `renderDetail`: `sourceText` 를 `source.kind === 'CLIENT' ? (기존 Client 문구) : source.label`
- [ ] **Step 4: 실행 → PASS** — `python manage.py test tests.test_data_services tests.test_item_api tests.test_dig_form tests.test_client_api --settings=configurations.test_settings`
- [ ] **Step 5: 커밋** — `feat: 업로드 경로마다 이미지 등록 경로·등록자를 남기고 데이터 목록 수집 열이 네 경로를 보인다`

---

### Task 3: 공용 카메라 촬영 부품 `CameraCapture`

**Files:**
- Create: `app/templates/data/camera_capture.html`
- Modify: `app/templates/dig_form/dig_form_capture.html` (1-197행의 `DigFormCapture` 와 스타일)
- Modify: `app/templates/dig_form/dig_form_write.html:75` (include 앞에 공용 부품 include)
- Test: `tests/e2e/test_dig_form.py`(사진 넣기 410-460행, 바꾸지 않고 그대로 통과해야 한다), `scripts/verify/verify_dig_form_width.py`

**Interfaces:**
- Produces (전역 JS):

```javascript
// options: { popupTitle, title, overlayUrl|null, overlayOpacity|null, filePrefix, upload(file, done) }
// upload 는 서버에 보내고 done(errorMessage|null) 을 부른다 — null 이면 팝업을 닫는다
class CameraCapture { constructor(options); open(); }
```

- [ ] **Step 1: `data/camera_capture.html` 만들기** — `dig_form_capture.html` 1-197행을 옮기며 다음만 바꾼다
  - 스타일 클래스 `dig-form-capture-stage`/`dig-form-capture-overlay` → `camera-capture-stage`/`camera-capture-overlay`. 상수 `CAPTURE_TYPES`·`CAPTURE_CAMERA_ERRORS` 는 그대로
  - 생성자 `constructor(options)` — `this.options = options`. `open()` 의 제목은 `options.title`, 팝업 제목은 `options.popupTitle`, Overlay 는 `options.overlayOpacity != null && options.overlayUrl` 일 때 `src = options.overlayUrl`, 불투명도 `options.overlayOpacity`
  - [사용] 파일 이름 `options.filePrefix + '-' + Date.now() + '.jpg'`
  - `upload(file)` 은 형식 검사 뒤 버튼을 잠그고 `this.options.upload(file, function (error) { 버튼 풀기; if (error) _this.message(error); else _this.popup.close(); })`
  - 나머지(start/stop/shoot/retake/showShot/message, HTTP 대체)는 그대로
- [ ] **Step 2: `DigFormCapture` 를 껍데기로**

```javascript
    // 사진 넣기 — 비전검사항목이 연결된 이미지 칸(서버 dig_form.capture). 촬영 화면은 공용 CameraCapture(data/camera_capture.html)
    class DigFormCapture {
        constructor(cell, fnUse) { this.cell = cell; this.fnUse = fnUse; }
        open() {
            const cell = this.cell, fnUse = this.fnUse, v = cell.vision_item;
            new CameraCapture({
                popupTitle: '사진 넣기', title: v.code + ' · ' + v.name, filePrefix: 'dig-form',
                overlayUrl: '/media/dig-form-overlay/' + cell.id + '/', overlayOpacity: v.overlay_opacity,
                upload: function (file, done) {
                    const fd = new FormData();
                    fd.append('item_id', cell.id);
                    fd.append('uploadfile', file);
                    AjaxUtil.postFileAsyncData('/api/dig_form/dig_form?action=capture', fd, function (res) {
                        if (!res || !res.success) { done((res && res.message) || '사진을 넣지 못했습니다. 다시 시도해 주세요.'); return; }
                        fnUse(res.asset_id);
                        done(null);
                    }, function (req, status, error) { done(''); AjaxUtil.failureCallback(req, status, error); });
                }
            }).open();
        }
    }
```

`done('')` 는 메시지 없이 버튼만 푼다(실패 알림은 `failureCallback` 이 띄운다) — `CameraCapture.upload` 는 `error === null` 일 때만 닫는다. `DigFormRigResult` 는 그대로 둔다.
- [ ] **Step 3: include** — `dig_form_write.html` 에서 `{% include 'dig_form/dig_form_capture.html' %}` 바로 앞에 `{% include 'data/camera_capture.html' %}`. `DigFormCapture` 를 쓰는 다른 템플릿이 있으면(`grep -rn "dig_form_capture.html" app/templates`) 같이 더한다
- [ ] **Step 4: 검증** — `node scripts/verify/verify_screen_js.js`, `python scripts/verify/verify_dig_form_width.py`(사진 넣기 팝업 OK 줄), `python -m pytest tests/e2e/test_dig_form.py -q -k "사진 or capture"`
- [ ] **Step 5: 커밋** — `refactor: 사진 넣기의 카메라 촬영을 공용 CameraCapture 로 떼어 낸다`

---

### Task 4: 공용 이미지 편집 부품 `PreprocessEditor`

**Files:**
- Create: `app/templates/data/preprocess_modal.html`
- Modify: `app/templates/data/image.html:102-147`(모달), `:170-172,212,214,430-565`(편집 JS)
- Test: `tests/e2e/test_data_screens.py:140-155`, `tests/e2e/test_write_paths.py:345-355`, `tests/e2e/test_client_workflow.py:185-192` (그대로 통과)

**Interfaces:**
- Produces:

```javascript
// options: { save(operations, onSaved) } — 서버에 연산 목록 전체를 보내고 onSaved(편집된 이미지 detail) 를 부른다
class PreprocessEditor { constructor(options); open(image); }   // image: detail 응답(url·width·height·preprocess·id)
```

- [ ] **Step 1: `data/preprocess_modal.html`** — `image.html` 102-147행 모달 마크업(id 그대로) + `<script>` 안에 `PreprocessEditor`. 메서드는 `image.html` 의 `bindPreprocess`·`showPreprocess`(→`open(image)`)·`renderPreprocess`·`fitPreprocess`·`setPreprocessMode`·`imagePoint`·`addPreprocessPoint`·`drawPreprocessOverlay`·`applyPreprocessShape`·`syncPreprocessSize`·`savePreprocess` 를 그대로 옮기고 상태(`image`·`ops`·`mode`·`points`)를 클래스가 갖는다. 생성자에서 bind 한 번. `savePreprocess(operations)` 만 바뀐다:

```javascript
        savePreprocess(operations) {
            const _this = this;
            this.options.save(operations, function (image) {
                _this.image = image;
                _this.ops = image.preprocess || [];
                _this.setMode(null);
                _this.render();
            });
        }
```

- [ ] **Step 2: `image.html` 이 부품을 쓰게** — 모달 마크업을 지우고 `{% include 'data/preprocess_modal.html' %}` (모달 자리, `{% endblock %}` 앞). `init()` 의 `preprocessOps/Mode/Points` 를 지우고

```javascript
            this.editor = new PreprocessEditor({ save: function (operations, onSaved) {
                AjaxUtil.postAsyncData(API + '?action=preprocess',
                    { item_id: ITEM_ID, image_id: _this.image.id, Q: JSON.stringify({ operations: operations }) }, function (res) {
                        _this.image = res.image;
                        _this.renderDetail(res.image);
                        _this.grid.refreshRemote('preprocess');
                        onSaved(res.image);
                    });
            } });
            $('#btnPreprocess').on('click', function () { _this.editor.open(_this.image); });
```

`bindPreprocess()` 호출과 430-565행 편집 메서드를 지운다.
- [ ] **Step 3: 검증** — `node scripts/verify/verify_screen_js.js`, `python scripts/verify/verify_modals.py`, `python -m pytest tests/e2e/test_data_screens.py tests/e2e/test_write_paths.py -q -k "preprocess or 편집"`
- [ ] **Step 4: 커밋** — `refactor: 데이터 목록의 이미지 편집 창을 공용 PreprocessEditor 로 떼어 낸다`

---

### Task 5: 메뉴 `wm_data_register` 와 API `/api/item/register`

**Files:**
- Create: `app/views/item/register.py`
- Modify: `domain/gui.py`(menu_init 71-77행 근처, taskview_menu_code_map 185-191행 근처), `domain/management/commands/seed_initial.py`(비전 데이터 관리 폴더 첫 줄)
- Test: `tests/test_item_api.py`(새 `RegisterApiTest`), `tests/test_menu_tree.py:44-63`

**Interfaces:**
- Consumes: Task 2 `upload_images(..., channel=)`
- Produces: `/api/item/register` actions `list`·`detail`·`items`(GET), `upload`·`preprocess`·`delete`(POST). 응답 키는 spec 의 API 표

- [ ] **Step 1: 실패하는 테스트**

```python
class RegisterApiTest(ItemApiTestCase):
    """비전 데이터 등록(`wm_data_register`) — 모든 항목의 최근 데이터, 카메라·파일 등록, 편집·삭제."""

    menus = {'wm_data_register': 'RW'}

    def _get(self, user, action, **params):
        return self.http(user).get('/api/item/register', {'action': action, **params}, **AJAX)

    def _post(self, user, action, **data):
        return self.http(user).post(f'/api/item/register?action={action}', data, **AJAX)

    def test_파일과_카메라로_등록하고_목록에서_경로와_등록자를_본다(self):
        r = self._post(self.manager, 'upload', item_id=self.item.id, kind='FILE', files=[make_image('f.png')])
        self.assertEqual(len(r.json()['uploaded']), 1, r.content.decode()[:200])
        self._post(self.manager, 'upload', item_id=self.item.id, kind='CAMERA', files=[make_image('f.png')])  # 카메라는 같은 사진도 받는다
        again = self._post(self.manager, 'upload', item_id=self.item.id, kind='FILE', files=[make_image('f.png')])
        self.assertEqual(len(again.json()['rejected']), 1)                                                   # 파일은 거절
        rows = self._get(self.manager, 'list').json()['rows']
        self.assertEqual([(r['channel_label'], r['item_code'], r['uploaded_by']) for r in rows],
                         [('카메라 촬영', 'API', 'item-manager'), ('파일 업로드', 'API', 'item-manager')])
        self.assertEqual(self._get(self.manager, 'list', channel='CAMERA').json()['totalRows'], 1)

    def test_R_이면_보기만_하고_W_가_없으면_등록이_403(self):
        UserGroupMenu.objects.filter(MenuCode='wm_data_register', UserGroup__Code='worker').update(AuthCode='R')
        self.assertEqual(self._get(self.worker, 'list').status_code, 200)
        r = self._post(self.worker, 'upload', item_id=self.item.id, kind='FILE', files=[make_image()])
        self.assertEqual(r.status_code, 403)

    def test_치수_측정_중지_항목은_대상이_아니다(self):
        with tenant_atomic(self.tenant):
            InspectionItem.objects.create(tenant=self.tenant, code='DIM', name='치수', task_type=InspectionItem.TaskType.MEASUREMENT)
            InspectionItem.objects.create(tenant=self.tenant, code='OFF', name='중지', task_type=InspectionItem.TaskType.OBJECT_DETECTION,
                                          status=InspectionItem.Status.PAUSED)
        codes = [i['code'] for i in self._get(self.manager, 'items').json()['items']]
        self.assertEqual(codes, ['API'])
        with tenant_atomic(self.tenant):
            dim = InspectionItem.objects.get(code='DIM')
        r = self._post(self.manager, 'upload', item_id=dim.id, kind='FILE', files=[make_image()])
        self.assertEqual(r.status_code, 400)

    def test_상세_편집_삭제(self):
        self._post(self.manager, 'upload', item_id=self.item.id, kind='FILE', files=[make_image()])
        image_id = self._get(self.manager, 'list').json()['rows'][0]['id']
        detail = self._get(self.manager, 'detail', image_id=image_id).json()
        self.assertEqual((detail['item']['code'], detail['channel_label'], detail['can_preprocess']), ('API', '파일 업로드', True))
        r = self._post(self.manager, 'preprocess', image_id=image_id, Q=json.dumps({'operations': [{'op': 'rotate', 'degrees': 90}]}))
        self.assertEqual(r.status_code, 200, r.content.decode()[:200])
        self.assertEqual((r.json()['image']['width'], r.json()['image']['height']), (48, 64))
        self.assertEqual(self._post(self.manager, 'delete', image_id=image_id).status_code, 200)
        self.assertEqual(self._get(self.manager, 'list').json()['totalRows'], 0)

    def test_검수_완료_삭제는_검수_작업_W_도_있어야_한다(self):
        self.approve_one()
        image_id = self._get(self.manager, 'list').json()['rows'][0]['id']
        self.assertEqual(self._post(self.manager, 'delete', image_id=image_id).status_code, 403)
```

`tests/test_menu_tree.py` 기대값: `('비전 데이터 관리', 'uil-database', [('wm_data_register', '비전 데이터 등록'), ('wm_data_item_detail', ...` 로 첫 줄 추가.

- [ ] **Step 2: 실행 → FAIL** — `python manage.py test tests.test_item_api.RegisterApiTest tests.test_menu_tree --settings=configurations.test_settings`
- [ ] **Step 3: 메뉴·매핑**
  - `gui.py` menu_init: `gui_dc['wm_data_register'] = cls.gui_item('비전 데이터 등록', 'data/register.html')` (비전검사항목 관리 줄 아래). `ITEM_CHILD_MENUS` 에 넣지 않는다
  - `gui.py` map: `m['item/register'] = ['wm_data_register']`
  - `seed_initial.MENU_TREE` 비전 데이터 관리 첫 줄: `# 검사항목을 골라 카메라·파일로 등록하고 최근 데이터를 본다(사용자 결정 2026-10-23). 트리의 분류 노드보다 위에 보인다` + `('wm_data_register', '비전 데이터 등록'),`
- [ ] **Step 4: `app/views/item/register.py`**

```python
"""비전 데이터 등록 화면(`wm_data_register`) — `/api/item/register`.

모든 비전검사항목의 최근 데이터를 보고, 항목을 골라 카메라·파일로 등록하고, 한 장을 편집·삭제한다(사용자 결정 2026-10-23).
권한은 이 메뉴의 R(조회)·W(등록·편집·삭제)뿐이다 — 검수 완료 삭제만 검수 작업 W 도 본다(ImageService.delete_image).

| action     | 메서드 | 입력 |
|------------|--------|------|
| list       | GET    | item_id?, channel?, q, date_from, date_to, page, page_size |
| detail     | GET    | image_id |
| items      | GET    | — 등록 대상(사용 중·치수 측정 아님)과 Overlay |
| upload     | POST   | item_id, kind(FILE·CAMERA), files |
| preprocess | POST   | image_id, Q={"operations": [...]} |
| delete     | POST   | image_id |
"""
from datetime import date

from django.http import Http404
from django.urls import reverse

from app.views.item import ItemApiError, paged, param
from domain.models.data import ImageAsset, InspectionItem
from domain.models.vision import VisionInspection, VisionOverlay
from domain.services.account import user_display_name
from domain.services.data.image import ImageService
from domain.services.data.image_list import ImageListService
from domain.services.data.preprocess import ImagePreprocessService, PreprocessLocked
from domain.services.data.workflow import workflow_status, workflow_status_label

READ_ACTIONS = frozenset({'list', 'detail', 'items'})
KINDS = {'FILE': ImageAsset.Channel.FILE, 'CAMERA': ImageAsset.Channel.CAMERA}


def register(context):
    """api/item/register"""
    handler = {'list': _list, 'detail': _detail, 'items': _items, 'upload': _upload,
               'preprocess': _preprocess, 'delete': _delete}.get(context.gparam.get('action', 'list'))
    if handler is None:
        raise ItemApiError('지원하지 않는 기능입니다.')
    return handler(context)


def _images(context):
    return (ImageAsset.objects.for_tenant(context.request.tenant)
            .select_related('dataset__item', 'uploaded_by__userprofile'))


def _image(context):
    try:
        return _images(context).get(pk=int(param(context, 'image_id')))
    except (ImageAsset.DoesNotExist, TypeError, ValueError) as exc:
        raise Http404('데이터를 찾을 수 없습니다.') from exc


def _list(context):
    g = context.gparam
    images = _images(context)
    if g.get('item_id'):
        images = images.filter(dataset__item_id=g['item_id'])
    if g.get('channel') in ImageAsset.Channel.values:
        images = images.filter(channel=g['channel'])
    if (g.get('q') or '').strip():
        images = images.filter(original_name__icontains=g['q'].strip())
    if g.get('date_from'):
        images = images.filter(created_at__date__gte=date.fromisoformat(g['date_from']))
    if g.get('date_to'):
        images = images.filter(created_at__date__lte=date.fromisoformat(g['date_to']))
    return paged(images.order_by('-created_at', '-id'), g, lambda image: {
        'id': image.id, 'thumbnail_url': reverse('private-image-thumbnail', args=[image.id]),
        'item_code': image.dataset.item.code, 'item_name': image.dataset.item.name,
        'channel_label': image.get_channel_display(), 'original_name': image.original_name,
        'workflow_status_label': workflow_status_label(workflow_status(image)),
        'uploaded_by': user_display_name(image.uploaded_by) if image.uploaded_by else '-',
        'created_at': image.created_at.strftime('%Y-%m-%d %H:%M'),
    }, default_size=50)


def _detail(context):
    image = _image(context)
    payload = ImageListService.detail_payload(image, context.request.user)
    item = image.dataset.item
    payload.update({
        'item': {'id': item.id, 'code': item.code, 'name': item.name},
        'channel': image.channel, 'channel_label': image.get_channel_display(),
        'uploaded_by': user_display_name(image.uploaded_by) if image.uploaded_by else '-',
        'created_at': image.created_at.strftime('%Y-%m-%d %H:%M'), 'file_size': image.file_size,
    })
    if image.source_inspection_id:
        inspection = VisionInspection.objects.select_related('client').filter(pk=image.source_inspection_id).first()
        payload['client'] = {'client_id': inspection.client.client_id if inspection else '',
                             'captured_at': inspection.capture_timestamp.strftime('%Y-%m-%d %H:%M')
                             if inspection and inspection.capture_timestamp else ''}
    return payload


def _targets(tenant):
    return (InspectionItem.objects.for_tenant(tenant).filter(status=InspectionItem.Status.ACTIVE)
            .exclude(task_type=InspectionItem.TaskType.MEASUREMENT).select_related('category__parent'))


def _items(context):
    overlays = {o.item_id: o for o in VisionOverlay.objects.filter(visible=True).exclude(image='')}
    rows = []
    for item in _targets(context.request.tenant).order_by('category__parent__sort_order', 'category__sort_order',
                                                          'display_order', 'code'):
        overlay = overlays.get(item.id)
        category = item.category
        rows.append({'id': item.id, 'code': item.code, 'name': item.name,
                     'category': ' › '.join(c.name for c in (category.parent, category) if c) if category else '미분류',
                     'overlay_url': f'/media/overlay/{item.id}/' if overlay else '',
                     'overlay_opacity': overlay.opacity if overlay else None})
    return {'items': rows}


def _upload(context):
    try:
        item = _targets(context.request.tenant).get(pk=int(param(context, 'item_id')))
    except (InspectionItem.DoesNotExist, TypeError, ValueError) as exc:
        raise ItemApiError('등록할 수 있는 비전검사항목이 아닙니다. 사용 중인 항목을 골라 주세요.') from exc
    kind = KINDS.get(param(context, 'kind'))
    if kind is None:
        raise ItemApiError('등록 유형을 골라 주세요.')
    files = context.request.FILES.getlist('files')
    if not files:
        raise ItemApiError('등록할 이미지를 골라 주세요.')
    result = ImageService.upload_images(item=item, files=files, actor=context.request.user, channel=kind,
                                        allow_duplicate=kind == ImageAsset.Channel.CAMERA)
    return {'success': True, 'message': f"{len(result['uploaded'])}개를 등록했습니다.",
            'uploaded': result['uploaded'], 'rejected': result['rejected']}


def _preprocess(context):
    image = _image(context)
    body = context.posparam.get('Q')
    if not isinstance(body, dict):
        raise ItemApiError('편집 내용을 확인해 주세요.')
    try:
        edited = ImagePreprocessService.apply(image, body.get('operations'), actor=context.request.user)
    except (PreprocessLocked, ValueError) as exc:
        raise ItemApiError(str(exc)) from exc
    return {'success': True, 'message': '이미지를 편집했습니다.',
            'image': ImageListService.detail_payload(edited, context.request.user)}


def _delete(context):
    image = _image(context)
    try:
        ImageService.delete_image(image, context.request.user)
    except ValueError as exc:
        raise ItemApiError(str(exc)) from exc
    return {'success': True, 'message': '데이터를 삭제했습니다.'}
```

`VisionOverlay` 는 조직 칼럼이 없는 표(`TimestampMixin`)이고 항목 id 로만 맞춘다. `paged(queryset, gparam, serialize, default_size=20)` 다. `delete_image` 의 `PermissionDenied` 는 dispatch 가 403 으로 바꾼다(`test_검수_완료…` 가 확인) — 위 코드의 `PermissionDenied` import 는 쓰지 않으므로 넣지 않는다.
- [ ] **Step 5: 실행 → PASS**, `python scripts/verify/verify_permission_map.py`, `python scripts/verify/verify_menu.py`(서버 DB 기준이면 공유 DB 적용 뒤 — 실행 못 하면 보고에 적는다)
- [ ] **Step 6: 커밋** — `feat: 비전 데이터 등록 메뉴와 API(목록·상세·대상 항목·등록·편집·삭제)를 둔다`

---

### Task 6: 비전 데이터 등록 화면 `data/register.html`

**Files:**
- Create: `app/templates/data/register.html`
- Test: `tests/e2e/test_data_register.py`(새)

**Interfaces:**
- Consumes: Task 3 `CameraCapture`, Task 4 `PreprocessEditor`, Task 5 API

- [ ] **Step 1: e2e 테스트(실패)**

```python
"""비전 데이터 등록 화면 — 파일 등록 → 목록·상세 → 편집 → 삭제. 자기 항목(E2E-REG)만 만들고 지운다."""
import pytest

from tests.e2e.conftest import login, manage_shell
from tests.e2e.test_write_paths import confirm_ok

MAKE = ("from domain.tenancy import tenant_atomic, current_tenant\n"
        "from domain.models.data import InspectionItem\n"
        "t = current_tenant()\n"
        "with tenant_atomic(t):\n"
        "    InspectionItem.objects.get_or_create(code='E2E-REG', defaults={'tenant': t, 'name': 'E2E 등록', 'task_type': 'OBJECT_DETECTION'})")
CLEAN = ("from domain.tenancy import tenant_atomic\n"
         "from domain.models.data import InspectionItem\n"
         "from domain.services.data.item_platform import ItemPlatformService\n"
         "with tenant_atomic():\n"
         "    ids = list(InspectionItem.objects.filter(code='E2E-REG').values_list('id', flat=True))\n"
         "for item_id in ids: ItemPlatformService.delete_item(item_id)")


@pytest.fixture
def e2e_item():
    manage_shell(MAKE)
    yield
    manage_shell(CLEAN)


def test_파일로_등록하고_상세에서_편집하고_삭제한다(page, base_url, admin_password, e2e_item, tmp_path):
    from PIL import Image
    png = tmp_path / 'e2e-reg.png'
    Image.new('RGB', (64, 48), (10, 120, 30)).save(png)
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_data_register/', wait_until='networkidle')
    page.click('#btnRegister')
    page.select_option('#registerItem', label='E2E-REG · E2E 등록')
    page.check('#registerKindFile')
    page.set_input_files('#registerFiles', str(png))
    with page.expect_response(lambda r: 'action=upload' in r.url):
        page.click('#registerSubmit')
    page.wait_for_selector('#detailTable td:has-text("E2E-REG")')
    assert page.locator('#detailTable').get_by_text('파일 업로드', exact=True).count() == 1
    page.click('#btnPreprocess')
    page.wait_for_selector('#preprocessModal.show')
    with page.expect_response(lambda r: 'action=preprocess' in r.url):
        page.click('#preprocessRotateRight')
    page.locator('#preprocessModal [data-bs-dismiss="modal"]').last.click()
    page.click('#btnDelete')
    with page.expect_response(lambda r: 'action=delete' in r.url):
        confirm_ok(page)
    assert not page.console_errors, page.console_errors
```

정리는 다른 e2e 와 같은 `ItemPlatformService.delete_item`, 확인창은 `test_write_paths.confirm_ok` 다.
- [ ] **Step 2: 실행 → FAIL**(404) — `python -m pytest tests/e2e/test_data_register.py -q`
- [ ] **Step 3: 템플릿** — `vision/inspection.html` 의 조회 카드·목록·상세 틀을 따른다
  - 조회 카드: `#cboItem`(전체 + `items`), `#cboChannel`(전체·클라이언트·파일 업로드·카메라 촬영·양식 사진 넣기), `#dateFrom`·`#dateTo`(기본 오늘-6 ~ 오늘), `#q`, `#btnSearch`. 주소 `?inspection_item=` 이 있으면 `#cboItem` 을 그 값으로
  - 목록 머리: 왼쪽 "등록 목록", 오른쪽 `#btnRegister` "데이터 등록"(`btn btn-input y_write_auth`)
  - 그리드 `#main-grid`: 썸네일(`data/image.html:186-189` 렌더러) · `item_code`+`item_name` · `channel_label` · `original_name` · `workflow_status_label` · `uploaded_by` · `created_at`. 서버 페이징 50, `rowHeight: 48`, `AjaxUtil.gridRemoteSource('/api/item/register', ...)`
  - 상세 카드: 머리 `#detailTitle` 왼쪽, 오른쪽 `#btnPreprocess`·`#btnDelete`(`y_write_auth d-none`, 막히면 disabled + `title`=이유). 본문 `row g-2` → `col-lg-5` `div.detail-image-box.image-zoom-viewport#imageBox > img#detailImage + p#imageEmpty` (`ImageZoom.attach`), `col-lg-7` `table#detailTable` 행: 비전검사항목(코드 · 이름) / 등록 경로(CLIENT 면 `client_id · captured_at 촬영` 덧붙임) / 등록자 / 등록일시 / 파일명 / 크기(`width × height px · n KB`) / 진행 단계(`stage_steps` 를 `data/image.html:250-252` 처럼)
  - 등록 모달 `#registerModal`(Bootstrap, `verify_modals` 규칙): `#registerItem`(select, `optgroup label=category`, option text `code · name`), 등록 유형 라디오 `#registerKindCamera`·`#registerKindFile`, 파일 `#registerFiles`(multiple, accept png/jpeg, 파일 유형일 때만 보임), `#registerMessage`, 푸터 [닫기]·`#registerSubmit`("등록"). 카메라 유형에서 [등록]은 모달을 닫고 `new CameraCapture({ popupTitle: '비전 데이터 등록', title, overlayUrl, overlayOpacity, filePrefix: 'register', upload: (file, done) => post(kind=CAMERA) })` 를 연다. 파일은 20개씩 나눠 보내고(`data/image.html` startUpload 의 나눔만) 결과를 `#registerMessage` 에 "n개를 등록했습니다 · 거절 m개(사유)" 로
  - 등록·편집·삭제 뒤 `AjaxUtil.gridResearch`, 등록 뒤 첫 행 상세를 연다
  - `{% include 'data/camera_capture.html' %}`·`{% include 'data/preprocess_modal.html' %}`, `<script src="{% static 'assets/js/image_zoom.js' %}">`
- [ ] **Step 4: 실행 → PASS**, `node scripts/verify/verify_screen_js.js`, `python scripts/verify/verify_modals.py`, `python scripts/verify/verify_buttons.py`, `python scripts/verify/verify_tokens.py`
- [ ] **Step 5: 커밋** — `feat: 비전 데이터 등록 화면 — 최근 데이터 목록·상세(편집·삭제)·카메라/파일 등록`

---

### Task 7: 대시보드 "최근 7일 비전 데이터 등록" 카드

**Files:**
- Create: `app/views/vision/dashboard.py`, `tests/test_dashboard_api.py`
- Modify: `domain/gui.py`(map `m['vision/dashboard'] = ['wm_dashboard']`), `app/templates/vision/dashboard.html`
- Test: `tests/e2e/test_data_register.py`(카드 클릭)

**Interfaces:**
- Produces: `GET /api/vision/dashboard?action=summary` → `{"register": null | {"days": 7, "total": int, "by_channel": [{"label", "count"}], "by_item": [{"id", "code", "name", "count"}]}}` (`by_item` 상위 5)

- [ ] **Step 1: 실패하는 테스트**

```python
"""대시보드 자기 API — 메뉴 권한만큼 카드를 내려준다(대시보드 템플릿 주석의 원칙)."""
from django.test import override_settings

from domain.models.user import UserGroupMenu
from domain.services.data.image import ImageService
from domain.tenancy import tenant_atomic
from tests.test_data_services import make_image
from tests.test_item_api import AJAX, ItemApiTestCase


@override_settings(API_AUTHZ_MODE='enforce')
class DashboardSummaryTest(ItemApiTestCase):
    menus = {'wm_dashboard': 'RW', 'wm_data_register': 'R'}

    def test_등록_메뉴_R_이면_최근_7일_등록_요약을_준다(self):
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image('a.png'), make_image('b.png', color=(1, 1, 1))], actor=self.manager)
        body = self.http(self.manager).get('/api/vision/dashboard', {'action': 'summary'}, **AJAX).json()
        self.assertEqual((body['register']['days'], body['register']['total']), (7, 2))
        self.assertEqual(body['register']['by_channel'], [{'label': '파일 업로드', 'count': 2}])
        self.assertEqual([(i['code'], i['count']) for i in body['register']['by_item']], [('API', 2)])

    def test_등록_메뉴_권한이_없으면_카드가_없다(self):
        UserGroupMenu.objects.filter(MenuCode='wm_data_register').delete()
        body = self.http(self.worker).get('/api/vision/dashboard', {'action': 'summary'}, **AJAX).json()
        self.assertIsNone(body['register'])
```

- [ ] **Step 2: 실행 → FAIL** — `python manage.py test tests.test_dashboard_api --settings=configurations.test_settings`
- [ ] **Step 3: API**

```python
"""대시보드(`wm_dashboard`) 자기 API — 요청자의 메뉴 권한만큼 카드 값을 준다(다른 메뉴 API 를 부르면 그 권한이 없는 그룹에서 403).

지금은 비전 데이터 등록 요약 하나다(사용자 결정 2026-10-23). 나머지 카드는 아직 예시 값이다.
"""
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from domain.models.data import ImageAsset
from domain.services.account import AccountService
from domain.tenancy import current_tenant, tenant_atomic

REGISTER_MENU = 'wm_data_register'
DAYS = 7


def dashboard(context):
    """api/vision/dashboard"""
    if context.gparam.get('action', 'summary') != 'summary':
        return {'success': False, 'message': '지원하지 않는 기능입니다.'}
    return {'register': _register(context.request.user)}


def _register(user):
    if 'R' not in (AccountService.check_user_auth(user, REGISTER_MENU) or ''):
        return None
    since = timezone.localdate() - timedelta(days=DAYS - 1)
    tenant = current_tenant()
    with tenant_atomic(tenant):
        images = ImageAsset.objects.for_tenant(tenant).filter(created_at__date__gte=since)
        labels = dict(ImageAsset.Channel.choices)
        by_channel = [{'label': labels[r['channel']], 'count': r['n']}
                      for r in images.values('channel').annotate(n=Count('id')).order_by('-n', 'channel')]
        by_item = [{'id': r['dataset__item_id'], 'code': r['dataset__item__code'], 'name': r['dataset__item__name'], 'count': r['n']}
                   for r in images.values('dataset__item_id', 'dataset__item__code', 'dataset__item__name')
                   .annotate(n=Count('id')).order_by('-n', 'dataset__item__code')[:5]]
        return {'days': DAYS, 'total': images.count(), 'by_channel': by_channel, 'by_item': by_item}
```

`check_user_auth` 의 반환(문자열 'RW'·'R'·None)을 `domain/services/account.py:148` 에서 확인하고 맞춘다.
- [ ] **Step 4: 카드** — `#summaryCards` 맨 앞에 `<div class="col-12 col-lg d-none" id="registerCard">` (카드 `dashboard-stat`, `role="button"`): `.stat-label` "최근 7일 비전 데이터 등록", `.stat-value#registerTotal`, `.stat-note#registerChannels`(경로별 "파일 업로드 n · 카메라 촬영 n"), `ul#registerItems`(항목별 상위 5, 줄마다 `code · name n장`). 화면 설명 문구를 "비전 데이터 등록 카드만 실제 값이고 나머지는 예시입니다."로. JS:

```javascript
        loadSummary() {
            AjaxUtil.getAsyncData('/api/vision/dashboard', { action: 'summary' }, function (res) {
                const r = res && res.register;
                if (!r) { return; }
                $('#registerTotal').text(r.total.toLocaleString() + '장');
                $('#registerChannels').text(r.by_channel.map(function (c) { return c.label + ' ' + c.count; }).join(' · ') || '등록 없음');
                $('#registerItems').empty().append(r.by_item.map(function (i) {
                    return $('<li>').attr('data-item-id', i.id).text(i.code + ' · ' + i.name + ' ' + i.count + '장');
                }));
                $('#registerCard').removeClass('d-none');
            });
        }

        // 카드 → 비전 데이터 등록 탭, 항목 줄 → 그 항목으로 거른 탭. 좌측 메뉴에 없으면(권한 없음) 열지 않는다
        openRegister(itemId) {
            const shell = window.parent !== window && window.parent.myMenu;
            if (!shell) { return; }
            const $link = shell.$leftSideNavi.find('.menu-leaf-link[data-mid="wm_data_register"]');
            if (!$link.length) { return; }
            const url = '/gui/wm_data_register/' + (itemId ? '?inspection_item=' + itemId : '');
            const frame = window.parent.document.getElementById('mnb_iframe_wm_data_register');
            shell.openMenu('wm_data_register', shell.leafTitle($link), url);
            if (frame && frame.contentWindow.page && itemId) { frame.contentWindow.page.filterItem(itemId); }
        }
```

카드 클릭 `openRegister(null)`, 항목 줄 클릭은 `e.stopPropagation()` 뒤 `openRegister(id)`. 등록 화면 `Page` 에 `filterItem(itemId)`(`#cboItem` 값 → 조회)를 둔다(Task 6 템플릿에 더한다).
- [ ] **Step 5: e2e** — `tests/e2e/test_data_register.py` 에: 셸에서 대시보드 → `#registerCard` 보임 → 클릭 → `.mnb-tab-panel.active[data-mid="wm_data_register"]`
- [ ] **Step 6: 실행 → PASS** — 단위 + `python -m pytest tests/e2e/test_data_register.py -q`, `verify_permission_map`, `verify_screen_js`
- [ ] **Step 7: 커밋** — `feat: 대시보드에 최근 7일 비전 데이터 등록 요약 카드를 붙이고 등록 화면으로 잇는다`

---

### Task 8: 문서·메뉴 e2e·마무리

**Files:**
- Modify: `docs/FEATURES.md`(§1 트리 첫 줄, §4.2 업로드 경로 4개, §5 끝에 새 절 "5.7 비전 데이터 등록"(앞 절 번호는 그대로), §10 카드), `docs/DATA_MODEL.md`(이미지 칼럼·마이그레이션 0021 행), `docs/DECISIONS.md`(사용자 결정 2026-10-23 행), `docs/STATUS.md`(지금 되는 것), `tests/e2e/test_menu.py`(비전 데이터 관리 첫 메뉴)
- Move: 구현이 끝나면 이 계획·설계를 `docs/archive/superpowers/` 로

- [ ] **Step 1: 문서** — 위 절들을 지금 동작대로. DECISIONS 행: 메뉴·권한(메뉴 R/W)·대상(사용 중, 치수 측정 제외)·중복(파일 거절·카메라 허용)·channel/uploaded_by·대시보드 카드(7일, 권한 없으면 감춤)·상세 편집/삭제 규칙
- [ ] **Step 2: `test_menu.py`** — 비전 데이터 관리 폴더 첫 항목이 "비전 데이터 등록"이고 그 아래 분류 노드가 이어지는지
- [ ] **Step 3: 검증** — 단위(`tests.test_item_api tests.test_data_services tests.test_dig_form tests.test_client_api tests.test_menu_tree tests.test_dashboard_api`), e2e(`test_data_register.py`·`test_menu.py`·`test_dig_form.py -k 사진`·`test_data_screens.py -k 편집`), `verify_links`·`verify_naming`·`verify_korean_only`·`verify_permission_map`·`verify_modals`·`verify_buttons`·`verify_dig_form_width`. 공용 JS·레이아웃이 아니므로 전체 e2e 는 묻고 돌린다
- [ ] **Step 4: 커밋** — `docs: 비전 데이터 등록 화면·등록 경로·대시보드 카드를 문서에 적는다`

## 실행 순서와 막히는 지점

1. Task 1 → `migration/image-channel` push(사용자 확인) → **담당자가 공유 DB 에 `migrate`** 해야 Task 2 이후 e2e 가 돈다(단위 테스트는 SQLite 라 먼저 돈다)
2. Task 2~7 은 기능 브랜치에서 차례로. Task 3·4 는 서로 독립
3. 메뉴(`wm_data_register`)는 공유 DB 에 `seed_initial` 을 다시 돌려야 보인다(담당자 지시 때만). 그 전에는 e2e 가 `/gui/wm_data_register/` 를 직접 연다(admin 은 superuser 라 열린다)
