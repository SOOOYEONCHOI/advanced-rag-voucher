"""화면에 들어가는 사용자·Client 값은 글자로 보인다(HTML 로 해석되지 않는다).

배포 전 점검(2026-10-07) #3: 공통 알림·확인창·토스트와 검사 이력·AI 모델 선택지가 값을 이어 붙여
`.html()` 로 넣어, 파일명·라벨 이름·Client 메타데이터(camera 등)로 스크립트가 실행됐다.
서버 데이터는 바꾸지 않는다 — 응답을 `page.route` 로 바꿔 넣는다.
"""
import json

from tests.e2e.conftest import login
from tests.e2e.test_write_paths import open_gui

PAYLOAD = '<img src=x onerror=window.__xss=1>'
RAN = '() => window.__xss === 1'


def fulfill(route, body):
    route.fulfill(status=200, content_type='application/json', body=json.dumps(body))


def test_알림_확인창_토스트는_메시지를_글자로_보인다(page, base_url, admin_password):
    login(page, base_url, 'admin', admin_password)
    open_gui(page, base_url, 'wm_vis_client')
    page.evaluate("p => Alert.confirm('', p + '\\n둘째 줄', function () {})", PAYLOAD)
    page.wait_for_selector('#commonConfirmModal.show')
    body = page.locator('#commonConfirmModalBody')
    assert PAYLOAD in body.inner_text()
    assert body.locator('br').count() == 1          # 줄바꿈은 그대로 줄바꿈이다
    page.evaluate("p => Notify.success(p)", PAYLOAD)
    page.wait_for_timeout(500)
    assert not page.evaluate(RAN)


def test_검사_이력의_콤보와_상세는_값을_글자로_보인다(page, base_url, admin_password):
    login(page, base_url, 'admin', admin_password)
    page.route('**/api/vision/inspection?action=filters*', lambda route: fulfill(route, {
        'items': [{'id': 1, 'code': 'X', 'name': PAYLOAD}], 'clients': [{'id': 1, 'client_id': PAYLOAD}]}))
    page.route('**/api/vision/inspection?action=detail*', lambda route: fulfill(route, {
        'id': 'e2e', 'request_id': 'e2e', 'item_code': 'X', 'item_name': PAYLOAD, 'client_id': PAYLOAD,
        'client_version': PAYLOAD, 'status_label': PAYLOAD, 'model': PAYLOAD, 'abnormal': None,
        'anomaly_score': None, 'threshold': None, 'inference_ms': None, 'capture_timestamp': '',
        'camera': PAYLOAD, 'error_message': PAYLOAD, 'image_id': None}))
    try:
        open_gui(page, base_url, 'wm_vis_inspection')
        assert PAYLOAD in page.locator('#cboItem option').nth(1).inner_text()
        assert page.locator('#cboClient option').nth(1).inner_text() == PAYLOAD
        page.evaluate("() => page.showDetail('e2e')")
        page.wait_for_timeout(500)
        assert PAYLOAD in page.inner_text('#inspDetail')
        assert not page.evaluate(RAN)
    finally:
        page.unroute('**/api/vision/inspection?action=filters*')
        page.unroute('**/api/vision/inspection?action=detail*')


def test_AI_모델_선택지는_모델_이름을_글자로_보인다(page, base_url, admin_password):
    """비전검사항목 관리 상세의 AI 모델 칸(모델 매핑 화면을 합쳤다, 사용자 결정 2026-10-21). 저장하지 않는다."""
    from tests.e2e.test_crud import select_item
    login(page, base_url, 'admin', admin_password)
    page.route('**/api/item/item_admin?action=models*', lambda route: fulfill(route, {
        'models': [{'name': PAYLOAD, 'version': 1, 'dataset_external_ref': None, 'recommended': False}], 'message': PAYLOAD}))
    try:
        open_gui(page, base_url, 'wm_data_item')
        select_item(page, '냉각팬 패널 단면(객체탐지)')
        page.click('#btnEdit')
        page.wait_for_timeout(600)
        # 지금 매핑한 모델이 배포 목록에 없으면 그 이름이 '(배포 없음)'으로 먼저 붙는다 — 순서가 아니라 글자로 찾는다
        assert PAYLOAD + ' (최신 v1)' in page.locator('#model_name option').all_inner_texts()
        assert page.inner_text('#modelHelp') == PAYLOAD
        assert not page.evaluate(RAN)
        page.click('#btnCancel')
    finally:
        page.unroute('**/api/item/item_admin?action=models*')
