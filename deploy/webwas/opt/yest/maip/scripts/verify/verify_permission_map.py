#!/usr/bin/env python
"""API 경로와 권한 매핑을 양방향 대조한다.

**MES 동적 dispatch** — `app/views/<task>/<view>.py` ↔ `taskview_menu_code_map()`.
데이터 화면 API(`app/views/item/`)도 여기다(DECISIONS DEC-028). page 경로 매핑의 메뉴 코드도 본다.

`API_AUTHZ_MODE=enforce` 에서는 매핑이 없는 경로가 즉시 403이다. 화면을 추가할
때 매핑 등록을 빠뜨렸는지 여기서 먼저 잡는다.

사용: python scripts/verify/verify_permission_map.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'configurations.settings')

import django  # noqa: E402

django.setup()

from domain.gui import GUIConfiguration, PAGE_PERMISSION_MAP  # noqa: E402

VIEWS_ROOT = Path(__file__).resolve().parents[2] / 'app' / 'views'

# 같은 패키지 안이지만 동적 dispatch 대상이 아닌 모듈.
NOT_DISPATCHED_VIEWS = {
    'files/media',  # URLConf 직결 Private* View. 자체적으로 인가를 건다
}


def discover_task_views():
    found = set()
    for task_dir in sorted(p for p in VIEWS_ROOT.iterdir()
                           if p.is_dir() and p.name != '__pycache__'):
        for view in sorted(task_dir.glob('*.py')):
            key = f'{task_dir.name}/{view.stem}'
            if view.stem != '__init__' and key not in NOT_DISPATCHED_VIEWS:
                found.add(key)
    return found


def check_dispatch_map(gui_codes):
    mapping = GUIConfiguration.taskview_menu_code_map()
    on_disk = discover_task_views()
    mapped = set(mapping)

    missing = sorted(on_disk - mapped)
    orphan = sorted(mapped - on_disk)
    bad = sorted((key, code) for key, codes in mapping.items() for code in codes
                 if code not in gui_codes)

    report('MES dispatch — MISSING (뷰는 있는데 매핑 없음)', missing)
    report('MES dispatch — ORPHAN (매핑은 있는데 뷰 없음)', orphan)
    report('MES dispatch — BAD MENU CODE', [f'{k} -> {c}' for k, c in bad])
    print(f'  뷰 {len(on_disk)}개 / 매핑 {len(mapped)}개')
    return len(missing) + len(orphan) + len(bad)


def check_page_map(gui_codes):
    bad = sorted(f'{k} -> {c}' for k, codes in PAGE_PERMISSION_MAP.items() for c in codes
                 if c not in gui_codes)
    report('page 경로 — BAD MENU CODE', bad)
    return len(bad)


def report(label, items):
    print(f'\n[{label}] {len(items)}건')
    for item in items:
        print('  -', item)


def main():
    GUIConfiguration.__static_init__()
    gui_codes = set(GUIConfiguration.menu_init())

    failed = check_dispatch_map(gui_codes)
    failed += check_page_map(gui_codes)

    print(f'\n화면 {len(gui_codes)}개')
    print('PASS' if failed == 0 else f'FAIL ({failed}건)')
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
