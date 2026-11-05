#!/usr/bin/env python
"""모달 세 계열(알림·확인 / Bootstrap 단독 / PopupDraggable)이 같은 규칙을 지키는지 본다.

계열마다 구현체가 다르다(자체 PopupDraggable · Bootstrap Modal). 구현체를 통일하지 않고 **동작**을 통일했으므로,
구현체가 아니라 결과를 잰다 — 백드롭색·Esc·포커스·푸터 버튼 순서.

    python scripts/verify/verify_modals.py

운영 의존성이 아니다. playwright 가 필요하다(capture_ui.py 와 같다).
"""
import pathlib
import re
import sys

from playwright.sync_api import sync_playwright

from demo_item import demo_item_id

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = 'http://127.0.0.1:8123'
VIEWPORT = {'width': 1920, 'height': 911}

# 단일 백드롭 규칙. tokens.css 의 --modal-backdrop 과 같은 값이어야 한다.
#
# background-color 만 재면 안 된다. Bootstrap 은 .modal-backdrop 에 opacity
# 레이어를 따로 두고 그걸로 농도를 조절한다(네이티브 ::backdrop 은 opacity 가
# 1 이고 색의 알파로만 조절한다). 두 곳에 알파가 있으면 곱해지므로, 실제로
# 눈에 보이는 농도인 **실효 알파**(색의 알파 × opacity)를 잰다.
EXPECT_RGB = (36, 36, 36)
EXPECT_ALPHA = 0.45
ALPHA_TOLERANCE = 0.02

# 계열마다 여는 법이 다르다. (라벨, 화면 URL, 여는 JS, 열렸는지 보는 JS,
# 모달 루트 셀렉터, 백드롭 셀렉터, 닫는 JS)
CASES = [
    {
        'label': 'Alert (알림)',
        'url': '/gui/wm_user/',
        'open': "() => { Alert.init(); Alert.alert('제목', '본문'); }",
        'is_open': ("() => { const e = document.getElementById('commonAlertModal');"
                    " return !!e && e.classList.contains('show'); }"),
        'root': '#commonAlertModal',
        'backdrop': ("() => { const e = document.querySelector('.modal-backdrop');"
                     " if (!e) return null; const s = getComputedStyle(e);"
                     " return [s.backgroundColor, s.opacity]; }"),
        'close': "() => Alert._alertModal && Alert._alertModal.hide()",
    },
    {
        'label': 'Confirm (확인)',
        'url': '/gui/wm_user/',
        'open': "() => Alert.confirm('제목', '본문', () => {}, () => {})",
        'is_open': ("() => { const e = document.getElementById('commonConfirmModal');"
                    " return !!e && e.classList.contains('show'); }"),
        'root': '#commonConfirmModal',
        'backdrop': ("() => { const e = document.querySelector('.modal-backdrop');"
                     " if (!e) return null; const s = getComputedStyle(e);"
                     " return [s.backgroundColor, s.opacity]; }"),
        'close': "() => Alert._confirmModal && Alert._confirmModal.hide()",
    },
    {
        # 단독 Bootstrap Modal. body 에 아무 마스크 클래스도 붙지 않아
        # 벤더 기본 규칙을 그대로 타는 유일한 계열이다. 빠뜨리면 이 경로의
        # 회귀를 아무도 잡지 못한다.
        'label': 'Bootstrap 단독 (API Key)',
        'url': '/gui/wm_vis_client/',
        'open': "() => bootstrap.Modal.getOrCreateInstance(document.getElementById('apiKeyModal')).show()",
        'is_open': ("() => { const e = document.getElementById('apiKeyModal');"
                    " return !!e && e.classList.contains('show'); }"),
        'root': '#apiKeyModal',
        'backdrop': ("() => { const e = document.querySelector('.modal-backdrop');"
                     " if (!e) return null; const s = getComputedStyle(e);"
                     " return [s.backgroundColor, s.opacity]; }"),
        'close': ("() => bootstrap.Modal.getInstance("
                  "document.getElementById('apiKeyModal')).hide()"),
    },
    {
        # 비전검사 클라이언트 관리의 배포본 목록. 열 때 /api/v1/client-packages 를 받는다.
        'label': 'Bootstrap 단독 (클라이언트 배포본)',
        'url': '/gui/wm_vis_client/',
        'open': "() => document.getElementById('btnPackages').click()",
        'is_open': ("() => { const e = document.getElementById('clientPackageModal');"
                    " return !!e && e.classList.contains('show'); }"),
        'root': '#clientPackageModal',
        'backdrop': ("() => { const e = document.querySelector('.modal-backdrop');"
                     " if (!e) return null; const s = getComputedStyle(e);"
                     " return [s.backgroundColor, s.opacity]; }"),
        'close': ("() => bootstrap.Modal.getInstance("
                  "document.getElementById('clientPackageModal')).hide()"),
    },
    {
        # 사용자 등록 직후의 임시 비밀번호 창. 실제 등록 없이 창만 연다.
        'label': 'Bootstrap 단독 (임시 비밀번호)',
        'url': '/gui/wm_user/',
        'open': ("() => { document.getElementById('tempPasswordValue').value = 'sample-only';"
                 " bootstrap.Modal.getOrCreateInstance(document.getElementById('tempPasswordModal')).show(); }"),
        'is_open': ("() => { const e = document.getElementById('tempPasswordModal');"
                    " return !!e && e.classList.contains('show'); }"),
        'root': '#tempPasswordModal',
        'backdrop': ("() => { const e = document.querySelector('.modal-backdrop');"
                     " if (!e) return null; const s = getComputedStyle(e);"
                     " return [s.backgroundColor, s.opacity]; }"),
        'close': ("() => bootstrap.Modal.getInstance("
                  "document.getElementById('tempPasswordModal')).hide()"),
    },
    {
        'label': 'Bootstrap 단독 (데이터 업로드)',
        'url': '/gui/wm_data_image/?inspection_item={item}',
        'open': "() => document.getElementById('btnUpload').click()",
        'is_open': ("() => { const e = document.getElementById('uploadModal');"
                    " return !!e && e.classList.contains('show'); }"),
        'root': '#uploadModal',
        'backdrop': ("() => { const e = document.querySelector('.modal-backdrop');"
                     " if (!e) return null; const s = getComputedStyle(e);"
                     " return [s.backgroundColor, s.opacity]; }"),
        'close': ("() => bootstrap.Modal.getInstance("
                  "document.getElementById('uploadModal')).hide()"),
    },
    {
        'label': 'Bootstrap 단독 (비전검사항목 편집)',
        'url': '/gui/wm_data_item_detail/?inspection_item={item}',
        'open': "() => document.getElementById('btnEdit').click()",
        'is_open': ("() => { const e = document.getElementById('itemEditModal');"
                    " return !!e && e.classList.contains('show'); }"),
        'root': '#itemEditModal',
        'backdrop': ("() => { const e = document.querySelector('.modal-backdrop');"
                     " if (!e) return null; const s = getComputedStyle(e);"
                     " return [s.backgroundColor, s.opacity]; }"),
        'close': ("() => bootstrap.Modal.getInstance("
                  "document.getElementById('itemEditModal')).hide()"),
    },
    {
        'label': 'Bootstrap 단독 (비전검사항목 등록)',
        'url': '/gui/wm_data_item/',
        'open': "() => document.getElementById('btnNew').click()",
        'is_open': ("() => { const e = document.getElementById('itemCreateModal');"
                    " return !!e && e.classList.contains('show'); }"),
        'root': '#itemCreateModal',
        'backdrop': ("() => { const e = document.querySelector('.modal-backdrop');"
                     " if (!e) return null; const s = getComputedStyle(e);"
                     " return [s.backgroundColor, s.opacity]; }"),
        'close': ("() => bootstrap.Modal.getInstance("
                  "document.getElementById('itemCreateModal')).hide()"),
    },
    {
        # 데이터 화면의 입력 창(DECISIONS DEC-028). 배경 클릭으로 닫히지 않게 static 이다.
        'label': 'Bootstrap 단독 (스냅샷 등록)',
        'url': '/gui/wm_data_snapshot/?inspection_item={item}',
        'open': "() => document.getElementById('btnNew').click()",
        'is_open': ("() => { const e = document.getElementById('snapshotCreateModal');"
                    " return !!e && e.classList.contains('show'); }"),
        'root': '#snapshotCreateModal',
        'backdrop': ("() => { const e = document.querySelector('.modal-backdrop');"
                     " if (!e) return null; const s = getComputedStyle(e);"
                     " return [s.backgroundColor, s.opacity]; }"),
        'close': ("() => bootstrap.Modal.getInstance("
                  "document.getElementById('snapshotCreateModal')).hide()"),
    },
    {
        'label': 'PopupDraggable (컬럼 설정)',
        'url': '/gui/wm_unit/',   # 컬럼 설정 버튼이 남은 화면(메뉴에서 내린 단위정보)
        'open': "() => document.getElementById('btnGridSetting').click()",
        'is_open': "() => !!document.querySelector('.modal.show')",
        'root': '.modal.show',
        'backdrop': ("() => { const l = document.querySelectorAll('.modal-backdrop');"
                     " const e = l[l.length - 1]; if (!e) return null;"
                     " const s = getComputedStyle(e); return [s.backgroundColor, s.opacity]; }"),
        'close': "() => page.popColSetting && page.popColSetting.modal.close()",
    },
]

# 푸터의 보조→주요 순서는 Confirm 에서만 기계로 잴 수 있다. 나머지 계열은
# 버튼이 하나뿐이라 순서라는 것이 없다.
CONFIRM_ORDER_JS = """() => Array.from(
    document.querySelectorAll('#commonConfirmModal .modal-footer button,'
                            + '#commonConfirmModal .d-flex button')
).map(b => b.id)"""

# Alert 의 확인 버튼은 주요 동작이다 — 브랜드 빨강 채움이어야 한다.
BRAND = 'rgb(218, 33, 41)'


def _norm(color):
    """rgb(a) 표기를 비교 가능한 모양으로 맞춘다."""
    if not color:
        return ''
    return color.replace(' ', '')


def _effective(pair):
    """(background-color, opacity) → (rgb 3튜플, 실효 알파).

    눈에 보이는 농도는 색의 알파와 요소 opacity 의 곱이다. 둘 중 하나만
    보면 Bootstrap 계열과 네이티브 계열을 같은 잣대로 비교할 수 없다.
    """
    if not pair:
        return None, None
    color, opacity = pair
    nums = re.findall(r'[\d.]+', color or '')
    if len(nums) < 3:
        return None, None
    rgb = tuple(int(float(n)) for n in nums[:3])
    alpha = float(nums[3]) if len(nums) > 3 else 1.0
    try:
        alpha *= float(opacity)
    except (TypeError, ValueError):
        pass
    return rgb, alpha


def main():
    password_file = ROOT / '.admin_pw'
    if not password_file.exists():
        print('.admin_pw 가 없다. 관리자 비밀번호를 적어 둔다(DEVELOPMENT §1.4).')
        return 2
    password = password_file.read_text(encoding='utf-8').strip()

    violations = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport=VIEWPORT, locale='ko-KR').new_page()
        page.goto(BASE + '/login/', wait_until='domcontentloaded')
        page.fill('#loginId', 'admin')
        page.fill('#loginPwd', password)
        page.click('#login')
        page.wait_for_url(BASE + '/', timeout=15000)
        page.wait_for_timeout(1200)
        item_id = demo_item_id(page, BASE)

        current = None
        for case in CASES:
            if case['url'] != current:
                page.goto(BASE + case['url'].format(item=item_id), wait_until='domcontentloaded', timeout=25000)
                page.wait_for_timeout(2600)
                current = case['url']

            page.evaluate(case['open'])
            page.wait_for_timeout(900)
            if not page.evaluate(case['is_open']):
                violations.append((case['label'], '열리지 않았다'))
                continue

            rgb, alpha = _effective(page.evaluate(case['backdrop']))
            if rgb != EXPECT_RGB or alpha is None or abs(alpha - EXPECT_ALPHA) > ALPHA_TOLERANCE:
                violations.append((case['label'], '백드롭 rgb={} 실효알파={} (기대 {} / {})'.format(
                    rgb, None if alpha is None else round(alpha, 3), EXPECT_RGB, EXPECT_ALPHA)))

            focused = page.evaluate(
                "(sel) => { const m = document.querySelector(sel);"
                " return !!m && m.contains(document.activeElement); }", case['root'])
            if not focused:
                violations.append((case['label'], '열 때 포커스가 모달 밖에 있다'))

            page.keyboard.press('Escape')
            page.wait_for_timeout(700)
            if page.evaluate(case['is_open']):
                violations.append((case['label'], 'Esc 로 닫히지 않는다'))
                page.evaluate(case['close'])
                page.wait_for_timeout(500)

        # 푸터 순서와 주요 버튼 색은 Confirm/Alert 에서 본다.
        page.goto(BASE + '/gui/wm_user/', wait_until='domcontentloaded', timeout=25000)
        page.wait_for_timeout(2600)

        page.evaluate("() => Alert.confirm('제목', '본문', () => {}, () => {})")
        page.wait_for_timeout(800)
        order = page.evaluate(CONFIRM_ORDER_JS)
        if order[:2] != ['commonConfirmModalCancel', 'commonConfirmModalOk']:
            violations.append(('Confirm', '푸터 순서 {} (기대 취소 → 확인)'.format(order)))
        ok_bg = page.evaluate(
            "() => getComputedStyle(document.getElementById('commonConfirmModalOk')).backgroundColor")
        if _norm(ok_bg) != _norm(BRAND):
            violations.append(('Confirm', '확인 버튼 {} (기대 {})'.format(ok_bg, BRAND)))
        page.evaluate("() => Alert._confirmModal && Alert._confirmModal.hide()")
        page.wait_for_timeout(600)

        page.evaluate("() => { Alert.init(); Alert.alert('제목', '본문'); }")
        page.wait_for_timeout(800)
        alert_bg = page.evaluate(
            "() => getComputedStyle(document.getElementById('commonAlertModalOk')).backgroundColor")
        if _norm(alert_bg) != _norm(BRAND):
            violations.append(('Alert', '확인 버튼 {} (기대 {})'.format(alert_bg, BRAND)))
        icon = page.evaluate(
            "() => { const e = document.querySelector('#commonAlertModal .modal-body i');"
            " return e ? getComputedStyle(e).color : null; }")
        # 보라(#6451f3)가 남아 있으면 안 된다. 다른 색이면 설계 판단에 맡긴다.
        if _norm(icon) == _norm('rgb(100, 81, 243)'):
            violations.append(('Alert', '아이콘이 아직 보라(#6451f3)다'))

        browser.close()

    for label, why in violations:
        print('위반  {:28} {}'.format(label, why))

    print('\n모달 규칙 위반 {}건'.format(len(violations)))
    print('PASS' if not violations else 'FAIL')
    return 0 if not violations else 1


if __name__ == '__main__':
    sys.exit(main())
