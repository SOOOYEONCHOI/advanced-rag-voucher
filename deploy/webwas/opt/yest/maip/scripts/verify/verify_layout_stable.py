#!/usr/bin/env python
"""화면 요소의 바운딩 박스를 떠서 두 시점을 비교한다.

디자인 작업이 "색만 바꿨다"는 것을 눈이 아니라 수치로 증명하기 위한 것이다.
스크린샷 비교는 색이 바뀌면 전부 달라져서 레이아웃 이동을 가려낼 수 없다.

    python scripts/verify/verify_layout_stable.py capture /tmp/geo-before
    (CSS 수정)
    python scripts/verify/verify_layout_stable.py capture /tmp/geo-after
    python scripts/verify/verify_layout_stable.py compare /tmp/geo-before /tmp/geo-after

운영 의존성이 아니다. playwright 가 필요하다(capture_ui.py 와 같다).
"""
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

from demo_item import demo_item_id

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = 'http://127.0.0.1:8123'
VIEWPORT = {'width': 1920, 'height': 911}
TOLERANCE = 0.5     # 서브픽셀 반올림만 허용한다

# 로그 3화면(wm_login_log · wm_menu_log · wm_system_log)은 뺐다. 이 스크립트가
# 화면을 도는 것 자체가 로그 행을 만들어 그리드 본문 높이가 매번 자란다.
# 레이아웃이 아니라 데이터라 비교의 의미가 없다. 오류·스크린샷 검사는
# scripts/verify/capture_ui.py 가 22화면 전부에 대해 그대로 한다.

SCREENS = [
    'wm_user', 'wm_user_group', 'wm_user_group_menu', 'wm_multi_language',
    'wm_menu_language', 'wm_prop_master',
    'wm_data_item', 'wm_data_item_detail', 'wm_data_image',
    'wm_data_labeling', 'wm_data_review', 'wm_data_snapshot',
    'wm_vis_inspection', 'wm_vis_client',
    'wm_vis_overlay',
    'wm_code', 'wm_company', 'wm_depart', 'wm_unit',
]

# 요소마다 "구조상의 주소"를 만든다. class 는 상태에 따라 붙었다 떨어지므로
# 쓰지 않고 태그 + 형제 순번만으로 경로를 만든다.
COLLECT_JS = """
() => {
  const path = (el) => {
    const parts = [];
    while (el && el.nodeType === 1 && el !== document.documentElement) {
      const parent = el.parentNode;
      let idx = 1;
      if (parent) {
        for (const sib of parent.children) {
          if (sib === el) break;
          if (sib.tagName === el.tagName) idx++;
        }
      }
      parts.unshift(el.tagName.toLowerCase() + '[' + idx + ']');
      el = parent;
    }
    return parts.join('>');
  };
  const out = {};
  for (const el of document.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;   // 숨은 요소는 건너뛴다
    out[path(el)] = [
      Math.round(r.x * 100) / 100, Math.round(r.y * 100) / 100,
      Math.round(r.width * 100) / 100, Math.round(r.height * 100) / 100,
    ];
  }
  return out;
}
"""


def capture(out_dir):
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    password_file = ROOT / '.admin_pw'
    if not password_file.exists():
        print('.admin_pw 가 없다. 관리자 비밀번호를 적어 둔다(DEVELOPMENT §1.4).')
        return 2
    password = password_file.read_text(encoding='utf-8').strip()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport=VIEWPORT, locale='ko-KR')
        page = ctx.new_page()
        page.goto(BASE + '/login/', wait_until='domcontentloaded')
        page.fill('#loginId', 'admin')
        page.fill('#loginPwd', password)
        page.click('#login')
        page.wait_for_url(BASE + '/', timeout=15000)
        page.wait_for_timeout(1200)
        item_id = demo_item_id(page, BASE)

        failed = []
        for code in SCREENS:
            url = '{}/gui/{}/{}'.format(
                BASE, code, '?inspection_item={}'.format(item_id) if code.startswith('wm_data_') else '')
            # 한 화면이 느려도 나머지는 떠야 한다. 다만 조용히 넘어가면
            # compare 가 적은 화면만 보고 PASS 를 내므로 끝에서 실패시킨다.
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=25000)
                page.wait_for_timeout(2800)
                geo = page.evaluate(COLLECT_JS)
            except Exception as ex:
                failed.append(code)
                print('FAIL {:28} {}'.format(code, str(ex).splitlines()[0][:60]))
                continue
            (out / (code + '.json')).write_text(
                json.dumps(geo, sort_keys=True, indent=0), encoding='utf-8')
            print('CAP  {:28} 요소 {}개'.format(code, len(geo)))
        browser.close()

    if failed:
        print('\n뜨지 못한 화면 {}개: {}'.format(len(failed), ' '.join(failed)))
        print('FAIL')
        return 1
    print('\n화면 {}개 캡처'.format(len(SCREENS)))
    return 0


def compare(dir_a, dir_b):
    a_root, b_root = pathlib.Path(dir_a), pathlib.Path(dir_b)
    moved = 0
    checked = 0
    missing = 0
    for code in SCREENS:
        fa, fb = a_root / (code + '.json'), b_root / (code + '.json')
        if not fa.exists() or not fb.exists():
            # 건너뛰면 "본 화면이 적어서 이동이 0" 인 상태가 PASS 로 둔갑한다.
            missing += 1
            print('MISS {:28} 한쪽 캡처가 없다 — 비교 불가'.format(code))
            continue
        a = json.loads(fa.read_text(encoding='utf-8'))
        b = json.loads(fb.read_text(encoding='utf-8'))
        diffs = []
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                diffs.append((key, '요소 생성/소멸'))
                continue
            checked += 1
            for i, axis in enumerate(('x', 'y', 'w', 'h')):
                if abs(a[key][i] - b[key][i]) > TOLERANCE:
                    diffs.append((key, '{} {} → {}'.format(axis, a[key][i], b[key][i])))
        if diffs:
            moved += len(diffs)
            print('MOVE {:28} {}건'.format(code, len(diffs)))
            for key, why in diffs[:5]:
                print('       {}  {}'.format(key[-70:], why))
        else:
            print('OK   {:28} 이동 없음'.format(code))

    print('\n화면 {}개 중 {}개 비교 / 요소 {}개 대조 / 이동 {}건'.format(
        len(SCREENS), len(SCREENS) - missing, checked, moved))
    ok = moved == 0 and missing == 0
    print('PASS' if ok else 'FAIL')
    return 0 if ok else 1


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == 'capture':
        return capture(sys.argv[2])
    if len(sys.argv) >= 4 and sys.argv[1] == 'compare':
        return compare(sys.argv[2], sys.argv[3])
    print('사용법:')
    print('  python scripts/verify/verify_layout_stable.py capture  <출력폴더>')
    print('  python scripts/verify/verify_layout_stable.py compare  <폴더A> <폴더B>')
    return 2


if __name__ == '__main__':
    sys.exit(main())
