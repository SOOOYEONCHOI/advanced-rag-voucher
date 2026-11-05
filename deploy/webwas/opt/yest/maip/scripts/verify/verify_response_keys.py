#!/usr/bin/env python
"""데이터 관리 템플릿이 폐기된 응답 키 `project` 를 읽는 곳을 찾는다.

검사항목 응답 키는 `item` 으로 통일했다. 서버는 `item` 만 내보내므로
`response.project` / `data.project` 는 항상 undefined 이고, 화면이 조용히 빈다.
문법상 유효해서 verify_screen_js.js 로는 잡히지 않는다.

    python scripts/verify/verify_response_keys.py
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / 'app' / 'templates' / 'data'

# response.project / data.project / detail.project / payload.project
PATTERN = re.compile(r'\b(?:response|data|detail|payload|result)\.project\b')


def main():
    hits = []
    for path in sorted(TEMPLATES.rglob('*.html')):
        for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if PATTERN.search(line):
                hits.append((path.relative_to(ROOT), lineno, line.strip()))

    for rel, lineno, text in hits:
        print('KEY  {}:{}  {}'.format(rel, lineno, text[:90]))

    print('\n데이터 템플릿 폐기 키(project) {}건'.format(len(hits)))
    print('PASS' if not hits else 'FAIL')
    return 0 if not hits else 1


if __name__ == '__main__':
    sys.exit(main())
