#!/usr/bin/env python
"""버튼의 형태가 역할을 말하는지 본다.

버튼 규칙은 역할을 색상이 아니라 **형태**로 나눈다 — 주요는 빨강 채움,
되돌릴 수 없는 동작은 빨강 외곽선, 보조는 중립 외곽선. 클래스 이름으로
역할을 알 수 있으므로, 클래스마다 기대 형태를 적어 두고 실제 렌더링과 맞춘다.

    python scripts/verify/verify_buttons.py

치수(패딩·높이·테두리 굵기)는 재지 않는다.
레이아웃 불변은 scripts/verify/verify_layout_stable.py 가 따로 본다.
"""
import pathlib
import re
import sys

from playwright.sync_api import sync_playwright

from demo_item import demo_item_id

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = 'http://127.0.0.1:8123'
VIEWPORT = {'width': 1920, 'height': 911}

TRANSPARENT = (0, 0, 0, 0.0)
BRAND = (218, 33, 41)
WHITE = (255, 255, 255)
INK2 = (46, 46, 49)
LINE = (216, 216, 216)

# 계층별 기대 형태. outlined 는 "테두리가 형태의 일부라 없으면 안 된다".
# 채움 계층(주요)은 테두리 굵기가 0 이어도 된다 — 굵기는 치수라
# 재지 않고, 굵기가 0 이면 borderTopColor 는 글자색이 돌아와 색을 잴 수 없다.
TIERS = {
    '주요':   {'bg': BRAND,       'color': WHITE, 'border': BRAND, 'outlined': False},
    '보조':   {'bg': TRANSPARENT, 'color': INK2,  'border': LINE,  'outlined': True},
    '위험':   {'bg': TRANSPARENT, 'color': BRAND, 'border': BRAND, 'outlined': True},
}
# 목록 머리(.upper-wezongrid) 오른쪽 위의 보조 버튼은 흰 바탕이다 — 회색 화면 바탕 위에서 버튼으로 보이게 한다
LIST_HEADER_TIERS = {'보조': dict(TIERS['보조'], bg=WHITE)}

# 클래스 → 계층. 여기 없는 클래스는 동작 버튼이 아니므로 보지 않는다
# (아이콘·텍스트 링크·토글·상태 표시). 근거는 계획의 "4계층에 넣지 않는 것".
CLASS_TIER = {
    'btn-band': '주요', 'btn-search': '주요',
    'btn-input': '보조', 'btn-outline-light': '보조',
    'btn-dell': '위험',
}

# 맨 텍스트 버튼(배경도 테두리도 없는 동작 버튼)을 허용하는 클래스.
# 이동(링크)과 아이콘은 맨 텍스트여도 된다.
BARE_OK = {'icon-button', 'btn-icon', 'btn-white', 'btn-close',
           'btn-newpadge', 'tool-button', 'wzg-pager-btn', 'wzg-page-btn',
           'btn-check', 'btn-group'}

SCREENS = [
    'wm_user', 'wm_user_group', 'wm_user_group_menu', 'wm_multi_language',
    'wm_menu_language', 'wm_prop_master',
    'wm_data_item', 'wm_data_item_detail', 'wm_data_image', 'wm_data_snapshot',
    'wm_vis_inspection', 'wm_vis_client',
    'wm_vis_overlay',
    'wm_code', 'wm_company', 'wm_depart', 'wm_unit',
    'wm_product_bom', 'wm_interface_log', 'wm_receipt', 'wm_product_form',
    'wm_dig_form_judge_code',
]

COLLECT_JS = """() => Array.from(document.querySelectorAll('button, a.btn'))
    .filter(b => b.offsetHeight > 0 && !b.disabled)
    .map(b => {
        const s = getComputedStyle(b);
        return {
            cls: (b.className || '').toString(),
            text: (b.textContent || '').trim().slice(0, 14),
            bg: s.backgroundColor,
            color: s.color,
            border: s.borderTopColor,
            bw: s.borderTopWidth,
            header: !!b.closest('.upper-wezongrid'),
        };
    })"""


def _rgba(value):
    nums = re.findall(r'[\d.]+', value or '')
    if len(nums) < 3:
        return None
    rgb = tuple(int(float(n)) for n in nums[:3])
    alpha = float(nums[3]) if len(nums) > 3 else 1.0
    return rgb + (alpha,)


def _same(actual, expected):
    """기대값이 4튜플(투명)이면 알파까지, 3튜플이면 rgb 만 본다."""
    got = _rgba(actual)
    if got is None:
        return False
    if len(expected) == 4:
        return got[3] == expected[3]
    return got[:3] == expected


def _is_bare(item):
    """배경도 테두리도 보이지 않는 버튼."""
    bg = _rgba(item['bg'])
    border = _rgba(item['border'])
    bg_invisible = bg is not None and bg[3] == 0.0
    border_invisible = (border is not None and border[3] == 0.0) or item['bw'] == '0px'
    return bg_invisible and border_invisible


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

        for code in SCREENS:
            url = '{}/gui/{}/{}'.format(
                BASE, code, '?inspection_item={}'.format(item_id) if code.startswith('wm_data_') else '')
            page.goto(url, wait_until='domcontentloaded', timeout=25000)
            page.wait_for_timeout(2500)

            for item in page.evaluate(COLLECT_JS):
                classes = set(item['cls'].split())

                tier = None
                for cls in classes:
                    if cls in CLASS_TIER:
                        tier = CLASS_TIER[cls]
                        break

                if tier:
                    want = LIST_HEADER_TIERS.get(tier, TIERS[tier]) if item['header'] else TIERS[tier]
                    has_border = item['bw'] != '0px'
                    if want['outlined'] and not has_border:
                        violations.append((code, item['text'],
                                           '{} 테두리가 없다 — 외곽선 계층이다'.format(tier)))
                    for key, label in (('bg', '배경'), ('color', '글자'), ('border', '테두리')):
                        if key == 'border' and not has_border:
                            continue
                        if not _same(item[key], want[key]):
                            violations.append((code, item['text'], '{} {} {} (기대 {})'.format(
                                tier, label, item[key], want[key])))
                    continue

                # 등급이 없는 버튼 중 맨 텍스트인 것은 허용 목록에 있어야 한다.
                if _is_bare(item) and not (classes & BARE_OK):
                    violations.append((code, item['text'],
                                       '맨 텍스트 버튼 (클래스: {})'.format(item['cls'][:40])))

        browser.close()

    for code, text, why in violations:
        print('위반  {:22} {:14} {}'.format(code, text, why))

    print('\n버튼 규칙 위반 {}건'.format(len(violations)))
    print('PASS' if not violations else 'FAIL')
    return 0 if not violations else 1


if __name__ == '__main__':
    sys.exit(main())
