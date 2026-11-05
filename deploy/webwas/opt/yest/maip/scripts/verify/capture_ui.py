#!/usr/bin/env python
"""전체 화면을 캡처한다. 디자인 작업의 회귀 비교용.

운영 의존성이 아니다. 쓰기 전에 받는다:

    .venv/bin/pip install playwright
    .venv/bin/python -m playwright install chromium

서버가 떠 있어야 하고 seed_demo 가 돌아 있어야 한다.

    python scripts/verify/capture_ui.py /tmp/ui-before
    python scripts/verify/capture_ui.py /tmp/ui-after

4xx·5xx 응답과 JS 오류를 함께 세고, 하나라도 있으면 FAIL 로 끝난다.
모달은 화면마다 여는 방법이 달라(네이티브 <dialog> · 자체 modal.open() ·
Bootstrap) 여기 넣지 않는다. 모달 단일화 뒤에 더한다.
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

from demo_item import demo_item_id

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = 'http://127.0.0.1:8123'
VIEWPORT = {'width': 1920, 'height': 911}   # 최소 사양

SCREENS = [
    ('01-system', 'wm_user'), ('01-system', 'wm_user_group'),
    ('01-system', 'wm_user_group_menu'), ('01-system', 'wm_multi_language'),
    ('01-system', 'wm_menu_language'), ('01-system', 'wm_prop_master'),
    ('01-system', 'wm_login_log'), ('01-system', 'wm_menu_log'),
    ('01-system', 'wm_system_log'),
    ('02-data', 'wm_data_item'), ('02-data', 'wm_data_item_detail'),
    ('02-data', 'wm_data_image'),
    ('02-data', 'wm_data_labeling'), ('02-data', 'wm_data_review'),
    ('02-data', 'wm_data_snapshot'),
    ('03-vision', 'wm_vis_inspection'), ('03-vision', 'wm_vis_client'),
    ('03-vision', 'wm_vis_overlay'),
    ('04-basic', 'wm_code'), ('04-basic', 'wm_company'),
    ('04-basic', 'wm_depart'), ('04-basic', 'wm_unit'),
]


def main():
    if len(sys.argv) < 2:
        print('사용법: python scripts/verify/capture_ui.py <출력폴더>')
        return 2
    out = pathlib.Path(sys.argv[1])
    password_file = ROOT / '.admin_pw'
    if not password_file.exists():
        print('.admin_pw 가 없다. 관리자 비밀번호를 적어 둔다(DEVELOPMENT §1.4).')
        return 2
    password = password_file.read_text(encoding='utf-8').strip()

    failures = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport=VIEWPORT, locale='ko-KR')
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append('JS {}'.format(e)))
        page.on('console',
                lambda m: errors.append('CONSOLE {}'.format(m.text))
                if m.type == 'error' else None)
        page.on('response',
                lambda r: errors.append('HTTP {} {}'.format(r.status, r.url))
                if r.status >= 400 else None)

        page.goto(BASE + '/login/', wait_until='domcontentloaded')
        page.fill('#loginId', 'admin')
        page.fill('#loginPwd', password)
        page.click('#login')
        page.wait_for_url(BASE + '/', timeout=15000)
        page.wait_for_timeout(1200)
        item_id = demo_item_id(page, BASE)

        for group, code in SCREENS:
            errors.clear()
            url = '{}/gui/{}/{}'.format(
                BASE, code, '?inspection_item={}'.format(item_id) if code.startswith('wm_data_') else '')
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=25000)
                page.wait_for_timeout(2800)
            except Exception as ex:
                print('FAIL {:28} {}'.format(code, str(ex).splitlines()[0][:60]))
                failures += 1
                continue
            (out / group).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out / group / (code + '.png')))
            if errors:
                failures += 1
                print('ERR  {:28} {}'.format(code, errors[0][:80]))
            else:
                print('OK   {}'.format(code))

        browser.close()

    print('\n화면 {}개 / 오류 {}건'.format(len(SCREENS), failures))
    print('PASS' if failures == 0 else 'FAIL')
    return 0 if failures == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
