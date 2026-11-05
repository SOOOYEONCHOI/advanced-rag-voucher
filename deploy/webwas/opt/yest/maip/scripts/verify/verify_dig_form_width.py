#!/usr/bin/env python
"""디지털 전환 화면(검사양식 관리 + 수입·품질 × 검사작성·검사결과)이 1024 폭에서 가로로 넘치지 않는지 본다.

화면 기준은 1920 × 911 이지만 디지털 전환 화면은 1024 폭도 본다(사용자 결정 2026-10-16, DESIGN §1).
1024 × 768 로 셸을 열면 탭 iframe 폭은 930px 다(좌측 메뉴가 접힌다). 화면을 셸 탭으로 열고 그 안에서 잰다.

- 문서·스크롤 영역에 가로 스크롤이 생기거나, 보이는 요소가 화면 오른쪽 밖으로 나가면 FAIL
- 검사양식 관리: 수입·품질 양식마다 [조회] 미리보기 모달(`page.preview(id)`)을 열어 잰다. 양식 편집기(등록·수정)는 대상이 아니다
- 검사작성: 양식마다 새 작성 모달을 열어(`page.start(id)`) 잰다. 저장하지 않는다 — 쓰기 요청을 보내지 않는다
- 검사결과: 완료된 검사가 있으면 첫 건의 결과 모달(`page.showResult(row)`)을 잰다
- 검사작성 사진 넣기 팝업: 칸 하나를 꾸며 연다(`DigFormCapture`). 카메라가 없으면 안내 문구만 보인다. 요청을 보내지 않는다
- 4xx·5xx 응답과 JS 오류도 FAIL

서버가 떠 있어야 하고 `.admin_pw` 가 있어야 한다(DEVELOPMENT §1.4). playwright 는 capture_ui.py 와 같이 받는다.

    python scripts/verify/verify_dig_form_width.py
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = 'http://127.0.0.1:8123'
VIEWPORT = {'width': 1024, 'height': 768}
FORM_TYPES = ('incoming', 'outgoing')
FORM_EDIT = 'wm_dig_form_incoming_form'   # 검사양식 관리 — 수입·품질을 한 화면에서(domain.gui.DIG_FORM_EDIT_MENU)

# 보이는 요소 중 오른쪽 끝이 문서 폭을 넘거나, 가로 스크롤이 생긴 스크롤 영역. 앞의 5개만 돌려준다.
OVERFLOW_JS = """() => {
    const doc = document.documentElement, width = doc.clientWidth, out = [];
    if (doc.scrollWidth > width) out.push('문서 ' + doc.scrollWidth + ' > ' + width);
    const name = e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') +
        (typeof e.className === 'string' && e.className ? '.' + e.className.trim().split(/\\s+/).slice(0, 2).join('.') : '');
    for (const e of document.querySelectorAll('body *')) {
        const r = e.getBoundingClientRect();
        if (!r.width || !r.height) continue;
        const cs = getComputedStyle(e);
        if (cs.visibility === 'hidden') continue;
        if (r.right > width + 1) out.push(name(e) + ' 오른쪽 ' + Math.round(r.right));
        else if ((cs.overflowX === 'auto' || cs.overflowX === 'scroll') && e.scrollWidth > e.clientWidth + 1)
            out.push(name(e) + ' 가로 스크롤 ' + e.scrollWidth + ' > ' + e.clientWidth);
        if (out.length >= 5) break;
    }
    return out;
}"""


def open_tab(page, code):
    url = '/gui/{}/'.format(code)
    page.evaluate('([code, url]) => window.myMenu.openMenu(code, code, url, { navigateExisting: true })', [code, url])
    page.wait_for_timeout(2500)
    return next(f for f in page.frames if url in f.url)


def main():
    password_file = ROOT / '.admin_pw'
    if not password_file.exists():
        print('.admin_pw 가 없다. 관리자 비밀번호를 적어 둔다(DEVELOPMENT §1.4).')
        return 2
    password = password_file.read_text(encoding='utf-8').strip()

    failures = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, locale='ko-KR')
        errors = []
        page.on('pageerror', lambda e: errors.append('JS {}'.format(e)))
        page.on('response', lambda r: errors.append('HTTP {} {}'.format(r.status, r.url)) if r.status >= 400 else None)
        # 이 검증은 읽기만 한다. 쓰기 요청이 나가면 막고 실패로 센다.
        page.route('**/api/**', lambda route: (errors.append('쓰기 요청 ' + route.request.url), route.abort())
                   if route.request.method != 'GET' else route.continue_())

        page.goto(BASE + '/login/', wait_until='domcontentloaded')
        page.fill('#loginId', 'admin')
        page.fill('#loginPwd', password)
        page.click('#login')
        page.wait_for_url(BASE + '/', timeout=15000)
        page.wait_for_timeout(1500)

        def check(label, frame):
            nonlocal failures
            found = frame.evaluate(OVERFLOW_JS) + errors[:3]
            errors.clear()
            if found:
                failures += 1
                print('FAIL {:44} {}'.format(label, ' / '.join(found)))
            else:
                print('OK   {}'.format(label))

        def form_list(frame, form_type):
            return frame.evaluate("""(t) => fetch('/api/dig_form/dig_form?action=form_list&form_type=' + t)
                                     .then(r => r.json())""", form_type.upper())

        frame = open_tab(page, FORM_EDIT)
        check(FORM_EDIT, frame)
        for form_type in FORM_TYPES:
            for form in form_list(frame, form_type):
                frame.evaluate('(id) => page.preview(id)', form['id'])
                frame.wait_for_timeout(1500)
                check('{} {} Rev.{} 조회'.format(FORM_EDIT, form['code'], form['version']), frame)
                frame.evaluate('() => page.closePreview()')

        for form_type in FORM_TYPES:
            forms = None
            for kind in ('write', 'result'):
                code = 'wm_dig_form_{}_{}'.format(form_type, kind)
                frame = open_tab(page, code)
                check(code, frame)
                if forms is None:
                    forms = form_list(frame, form_type)
                for form in forms:
                    label = '{} {} Rev.{}'.format(code, form['code'], form['version'])
                    if kind == 'write':
                        frame.evaluate('(id) => page.start(id)', form['id'])
                        frame.wait_for_timeout(1500)
                        check(label, frame)
                        frame.evaluate('() => page.closeModal()')
                if kind == 'write':
                    frame.evaluate("""() => { window._capture = new DigFormCapture(
                        { id: 0, vision_item: { code: 'CHECK-1024', name: '1024 폭 확인', overlay_opacity: null } }, () => {});
                        window._capture.open(); }""")
                    frame.wait_for_timeout(1500)
                    check(code + ' 사진 넣기', frame)
                    frame.evaluate('() => window._capture.popup.close()')
                if kind == 'result':
                    rows = frame.evaluate("""(t) => fetch('/api/dig_form/dig_form?action=result_search&state=done&form_type=' + t)
                                             .then(r => r.json())""", form_type.upper())
                    if rows:
                        frame.evaluate('(row) => page.showResult(row)', rows[0])
                        frame.wait_for_timeout(1500)
                        check(code + ' 결과 모달', frame)
                        frame.evaluate('() => page.popup.close()')

        browser.close()

    print('\n가로 넘침·오류 {}건'.format(failures))
    print('PASS' if failures == 0 else 'FAIL')
    return 0 if failures == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
