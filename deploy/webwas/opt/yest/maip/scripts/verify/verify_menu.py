#!/usr/bin/env python
"""`gui.py` 화면 정의와 DB `menu_item.MenuCode` 를 양방향 대조한다.

- DB에만 있는 MenuCode: 메뉴를 눌러도 화면이 없다(404).
- gui.py에만 있는 gui_code: 메뉴에 노출되지 않아 접근 경로가 없다.

사용: python scripts/verify/verify_menu.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'configurations.settings')

import django  # noqa: E402

django.setup()

from domain.gui import GUIConfiguration  # noqa: E402
from domain.management.commands.seed_initial import RETIRED_FROM_MENU  # noqa: E402
from domain.models.system import MenuItem  # noqa: E402

# 메뉴에 등록하지 않는 내부 화면.
# RETIRED_FROM_MENU 는 메뉴에서 내렸지만 화면 정의는 남긴 것들이다(시드 참고).
NOT_IN_MENU = {
    'wm_noauth_default',      # 권한 없는 사용자의 기본 진입 화면
} | set(RETIRED_FROM_MENU)


def main():
    GUIConfiguration.__static_init__()
    gui_codes = set(GUIConfiguration.menu_init()) - NOT_IN_MENU
    menu_codes = set(MenuItem.objects.values_list('MenuCode', flat=True))

    only_db = sorted(menu_codes - gui_codes)
    only_gui = sorted(gui_codes - menu_codes)

    print(f'\n[DB에만 있음 (화면 없는 메뉴)] {len(only_db)}건')
    for code in only_db:
        print('  -', code)
    print(f'\n[gui.py에만 있음 (메뉴 미등록 화면)] {len(only_gui)}건')
    for code in only_gui:
        print('  -', code)

    print(f'\n화면 {len(gui_codes)}개 / 메뉴 {len(menu_codes)}개')
    failed = len(only_db) + len(only_gui)
    print('PASS' if failed == 0 else f'FAIL ({failed}건)')
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
