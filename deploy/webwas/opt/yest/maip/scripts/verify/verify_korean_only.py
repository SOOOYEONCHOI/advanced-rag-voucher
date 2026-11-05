#!/usr/bin/env python
"""사용자에게 언어 변경 수단이 노출되지 않았는지 본다.

다국어는 내부 기능으로 남기고 화면에는 한국어만 내보내기로 했다(사용자 결정,
2026-10-02). 표·모델·API·관리자 화면은 그대로 두고 **고르는 수단**만 없앴다.
이 검사는 그 결정이 되돌아오지 않았는지 지킨다.

    python scripts/verify/verify_korean_only.py

서버가 필요 없다 — 템플릿을 읽어서 본다. 관리자 전용 화면(다국어 설정·
메뉴명 설정·라벨 편집 팝업)은 내부 기능이라 보지 않는다.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / 'app' / 'templates'

# 관리자 전용 i18n 화면. 내부 기능으로 남기기로 했으므로 검사하지 않는다.
INTERNAL = {
    'system/multi_language.html',
    'system/menu_language.html',
    'page/popup/label.html',
    'page/account/language.html',   # UI 링크가 없다. 되살릴 때를 위해 남겼다
}

# 언어를 고르게 하는 흔적. 하나라도 사용자 화면에 있으면 결정이 깨진 것이다.
MARKERS = [
    (re.compile(r'data-lang-code'),      '언어 선택 항목(data-lang-code)'),
    (re.compile(r'top-language-item'),   '상단바 언어 항목(top-language-item)'),
    (re.compile(r'images/flags/'),       '국기 이미지'),
    (re.compile(r'\blang_list\b'),       '언어 목록(lang_list)'),
    (re.compile(r'#lang_select'),        '언어 선택 버튼(lang_select)'),
]


def main():
    hits = []
    for path in sorted(TEMPLATES.rglob('*.html')):
        rel = path.relative_to(TEMPLATES).as_posix()
        if rel in INTERNAL:
            continue
        for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            for pattern, why in MARKERS:
                if pattern.search(line):
                    hits.append((rel, lineno, why))

    for rel, lineno, why in hits:
        print('노출  {}:{}  {}'.format(rel, lineno, why))

    print('\n사용자 화면의 언어 변경 수단 {}건'.format(len(hits)))
    print('PASS' if not hits else 'FAIL')
    return 0 if not hits else 1


if __name__ == '__main__':
    sys.exit(main())
